# Equity cockpit - the entry point Windows Task Scheduler calls.
#
# This file exists for one reason: this machine has several Pythons and only
# one of them has yfinance. Calling bare `python` works at the terminal and
# fails silently at 07:30 every morning. So the interpreter is pinned, and if
# the pinned one ever stops working we find another rather than dying quietly.
#
#   .\run.ps1              full run
#   .\run.ps1 refresh      re-price and re-render only (intraday, every 30 min)
#   .\run.ps1 selftest     offline wiring checks
#   .\run.ps1 doctor       what is stale or drifting
#   .\run.ps1 deploy       publish to Vercel behind the password gate
#   .\run.ps1 gate-check <url>   ask a deployment what a stranger gets
#
# `deploy` and `gate-check` are shell work, not cockpit subcommands, so they are
# intercepted below rather than forwarded to cockpit.py.
#
# Exit code is the cockpit's own, so Task Scheduler's "Last Run Result" is
# meaningful instead of always 0.

param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $CockpitArgs)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $here "state"
$log = Join-Path $logDir "run.log"

if (-not $CockpitArgs -or $CockpitArgs.Count -eq 0) { $CockpitArgs = @("run") }

# Intercepted before the interpreter hunt: `deploy` is PowerShell and node, not
# Python, and forwarding it to cockpit.py would only produce an argparse error.
if ($CockpitArgs[0] -eq "deploy") {
  & (Join-Path $here "deploy.ps1") @($CockpitArgs | Select-Object -Skip 1)
  exit $LASTEXITCODE
}

# Known-good first, then the usual suspects. The run is only as good as the
# interpreter that has yfinance, so we test for that rather than trusting a path.
$candidates = @(
  "$env:LOCALAPPDATA\Programs\Python\Python312-arm64\python.exe",
  "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
  "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
  "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
)
$onPath = (Get-Command python.exe -ErrorAction SilentlyContinue)
if ($onPath) { $candidates += $onPath.Source }

$python = $null
foreach ($c in $candidates) {
  if (-not (Test-Path $c)) { continue }
  & $c -c "import yfinance" *> $null
  if ($LASTEXITCODE -eq 0) { $python = $c; break }
}

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
if (-not $python) {
  $msg = "$stamp  FATAL  no Python on this machine can import yfinance. Tried: $($candidates -join '; ')"
  Add-Content -Path $log -Value $msg -Encoding utf8
  Write-Error $msg
  exit 3
}

Add-Content -Path $log -Value "$stamp  using $python  args: $($CockpitArgs -join ' ')" -Encoding utf8

# gate-check is Python but not cockpit.py: it talks to a live deployment and is
# the one thing here that must stay runnable when everything else is broken.
if ($CockpitArgs[0] -eq "gate-check") {
  & $python (Join-Path $here "tools\gate_check.py") @($CockpitArgs | Select-Object -Skip 1)
  exit $LASTEXITCODE
}

# Capture, then print and log separately. Tee-Object on PowerShell 5.1 takes no
# -Encoding and writes UTF-16 into what is otherwise a UTF-8 file, which leaves
# the log full of null bytes and unreadable by anything else.
$output = & $python (Join-Path $here "cockpit.py") @CockpitArgs 2>&1
$code = $LASTEXITCODE
$output | ForEach-Object { Write-Host $_ }
if ($output) { Add-Content -Path $log -Value ($output | Out-String).TrimEnd() -Encoding utf8 }

if ($code -ne 0) {
  Add-Content -Path $log -Value "$stamp  exit $code" -Encoding utf8
}

# Keep the log from growing forever - last 2000 lines is plenty of history.
if ((Test-Path $log) -and ((Get-Item $log).Length -gt 400KB)) {
  $tail = Get-Content $log -Tail 2000
  Set-Content -Path $log -Value $tail -Encoding utf8
}

exit $code
