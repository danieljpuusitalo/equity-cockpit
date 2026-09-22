# Publish the rendered dashboard to Vercel, behind the password gate.
#
#   .\run.ps1 deploy          build nothing, publish out\dashboard.html as it is
#   .\run.ps1 deploy -Fresh   re-price and re-render first, then publish
#
# Most of this file is refusals, and that is the point. The artefact being
# uploaded is the entire book in one HTML file: every ISIN, account, unit count
# and euro amount. The repo can be public because the book lives in gitignored
# files; a deployment has no such structure to lean on, so it leans on
# deploy\middleware.ts, and this script will not put the book anywhere that
# middleware is not demonstrably in front of.
#
# The verification runs AFTER the upload, not instead of it, and it asks the
# live URL what an anonymous stranger gets. A pre-flight check can only confirm
# intent; only the deployed thing can confirm behaviour.

param([switch] $Fresh)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$deployDir = Join-Path $here "deploy"
$rendered = Join-Path $here "out\dashboard.html"
$target = Join-Path $deployDir "public\index.html"

function Fail($message) {
  Write-Host "  REFUSED  $message" -ForegroundColor Red
  exit 1
}

# Every call to the Vercel CLI goes through here.
#
# PowerShell 5.1 turns anything a native exe writes to stderr into an
# ErrorRecord, and with ErrorActionPreference = Stop that throws even when the
# exe exits 0. The Vercel CLI writes a plugin hint line to stderr on every
# single invocation, so the strict preference this script wants for its own
# logic has to be relaxed for exactly the duration of the call. The function
# scope does that: the assignment is local and Stop is back in force on return.
function Invoke-Vercel {
  param([string[]] $Arguments)
  $ErrorActionPreference = "Continue"
  $text = & node $script:vc @Arguments 2>&1 | Out-String
  return [pscustomobject]@{ Text = $text; Code = $LASTEXITCODE }
}

Write-Host "Equity cockpit - deploy"

if ($Fresh) {
  Write-Host "  re-rendering first"
  & (Join-Path $here "run.ps1") refresh
  if ($LASTEXITCODE -ne 0) { Fail "refresh failed with exit $LASTEXITCODE - not publishing a stale or partial render" }
}

# --- guard 1: is there something to publish, and is it actually current ---
if (-not (Test-Path $rendered)) { Fail "no out\dashboard.html. Run `.\run.ps1 refresh` first." }
$age = (New-TimeSpan -Start (Get-Item $rendered).LastWriteTime -End (Get-Date)).TotalHours
Write-Host ("  render   {0:N0} KB, {1:N1}h old" -f ((Get-Item $rendered).Length / 1KB), $age)
if ($age -gt 24) {
  Write-Host "  WARNING  that render is over a day old. Use -Fresh to re-price." -ForegroundColor Yellow
}

# --- guard 2: is the gate still shaped like a gate ---
# Cheap structural checks, not a substitute for the live test below. They exist
# to catch the edit that narrows the matcher or deletes the fail-closed branch
# BEFORE the book is uploaded, rather than after.
$mw = Join-Path $deployDir "middleware.ts"
if (-not (Test-Path $mw)) { Fail "deploy\middleware.ts is missing - there is no gate" }
$mwText = Get-Content $mw -Raw
if ($mwText -notmatch "matcher:\s*'/:path\*'") { Fail "middleware matcher is not '/:path*' - it no longer covers every path" }
if ($mwText -notmatch "if \(!expected\) return challenge") { Fail "middleware no longer fails closed when COCKPIT_PASSWORD is unset" }
if ($mwText -notmatch "sameDigest") { Fail "middleware no longer compares digests" }
Write-Host "  gate     matcher covers /:path*, fails closed, compares digests"

# --- guard 3: does the deployment actually have a password ---
$script:vc = Join-Path $env:APPDATA "npm\node_modules\vercel\dist\vc.js"
if (-not (Test-Path $script:vc)) { Fail "vercel CLI not found at $script:vc" }
Push-Location $deployDir
try {
  $envList = (Invoke-Vercel @("env", "ls", "production")).Text
} finally { Pop-Location }
if ($envList -notmatch "COCKPIT_PASSWORD") {
  Fail "COCKPIT_PASSWORD is not set on Vercel production. The middleware would fail closed and the deployment would be unusable - but more to the point, set the password before uploading the book, not after."
}
Write-Host "  secret   COCKPIT_PASSWORD present on Vercel production"

# --- copy and publish ---
New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
Copy-Item $rendered $target -Force
Set-Content -Path (Join-Path $deployDir "public\robots.txt") -Value "User-agent: *`nDisallow: /" -Encoding utf8 -NoNewline
Write-Host ("  staged   deploy\public\index.html ({0:N0} KB)" -f ((Get-Item $target).Length / 1KB))

Push-Location $deployDir
try {
  $result = Invoke-Vercel @("deploy", "--prod", "--yes")
  $out = $result.Text
  $code = $result.Code
} finally { Pop-Location }
if ($code -ne 0) {
  Write-Host ($out.Trim())
  Fail "vercel deploy exited $code"
}

$url = ([regex]::Matches($out, "https://[a-z0-9\-]+\.vercel\.app") | Select-Object -Last 1).Value
if (-not $url) { Fail "could not find a deployment URL in the vercel output - verify by hand with tools\gate_check.py" }

# --- the check that matters: ask the live URL what a stranger gets ---
Write-Host ""
Write-Host "  verifying $url"
& (Join-Path $here "run.ps1") gate-check $url
$gate = $LASTEXITCODE

Write-Host ""
switch ($gate) {
  0 {
    Write-Host "  deployed, and the cockpit's own gate was proven against the live URL:"
    Write-Host "    $url"
    exit 0
  }
  3 {
    # Protected, but by Vercel's SSO rather than by this project's middleware.
    # Say which. "Deployed and verified" would be true of the deployment and
    # false of the gate, and that is the sentence this repo keeps writing.
    Write-Host "  deployed: $url" -ForegroundColor Yellow
    Write-Host "  NOT PROVEN: Vercel Deployment Protection is answering first, so" -ForegroundColor Yellow
    Write-Host "  the password gate never ran. The book is not reachable, but the" -ForegroundColor Yellow
    Write-Host "  only thing standing in front of it right now is a Vercel login." -ForegroundColor Yellow
    exit 3
  }
  default {
    Write-Host "  THE BOOK MAY BE READABLE. Take it down:" -ForegroundColor Red
    Write-Host "    cd deploy; node `"$script:vc`" remove equity-cockpit --yes" -ForegroundColor Red
    exit 1
  }
}
