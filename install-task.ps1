# Registers the scheduled runs. Idempotent - re-running replaces the task.
#
#   .\install-task.ps1              register both: daily 07:40, refresh 09:30-22:00
#   .\install-task.ps1 -At 18:10    a different time for the daily run
#   .\install-task.ps1 -NoRefresh   daily run only
#   .\install-task.ps1 -Remove      unregister both
#
# Two tasks, because they are two different jobs:
#
#   EquityCockpit         weekdays 07:40. Reads every source, re-checks the
#                         Equity Log, and is the only one allowed to message
#                         Telegram or write the daily history line.
#   EquityCockpitRefresh  weekdays, every 30 min 09:30-22:00. Re-prices and
#                         re-renders. No Notion, no Telegram, no history.
#
# The window is 09:30 to 22:00 deliberately: Helsinki and Stockholm open at
# 10:00 CET and close at 17:30, New York closes at 22:00. Nothing this book
# holds trades outside it, so a refresh outside it would spend a rate limit to
# redraw the same numbers.
#
# Weekdays only: the CSV is a snapshot and the markets are shut at the weekend,
# so a Saturday run would send you the same alert twice for no new information.

param([string] $At = "07:40",
      [string] $RefreshFrom = "09:30",
      [string] $RefreshUntil = "22:00",
      [int] $RefreshMinutes = 30,
      [switch] $NoRefresh,
      [switch] $Remove)

$ErrorActionPreference = "Stop"
$name = "EquityCockpit"
$refreshName = "EquityCockpitRefresh"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$weekdays = @("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")

if ($Remove) {
  foreach ($n in @($name, $refreshName)) {
    $existing = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
    if ($existing) {
      Unregister-ScheduledTask -TaskName $n -Confirm:$false
      Write-Host "Removed scheduled task '$n'."
    } else {
      Write-Host "No task '$n' to remove."
    }
  }
  return
}

# The refresh window is expressed as two clock times and converted to minutes
# here. Not as hours: `New-TimeSpan -Hours` takes an Int32, so a 12.5-hour
# window silently truncates to 12 and the last refresh fires at 21:30 - half an
# hour before the New York close, which is one of the two moments the whole task
# exists for. It registered quietly and the script printed "to 22:00" anyway.
#
# Computed before anything is registered, so a bad argument leaves the machine
# as it found it rather than half-applied.
$windowMinutes = [int]([datetime]::Parse($RefreshUntil) -
                       [datetime]::Parse($RefreshFrom)).TotalMinutes
if (-not $NoRefresh -and $windowMinutes -le 0) {
  throw "-RefreshUntil ($RefreshUntil) must be later in the day than -RefreshFrom ($RefreshFrom)."
}

function New-CockpitAction([string] $CockpitArg) {
  New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$here\run.ps1`" $CockpitArg" `
    -WorkingDirectory $here
}

# --- the daily full run ----------------------------------------------------

$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdays -At $At

# StartWhenAvailable matters: a laptop that was shut at 07:40 should still run
# when it wakes, rather than skipping the day in silence.
$settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -DontStopIfGoingOnBatteries `
  -AllowStartIfOnBatteries `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
  -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $name -Action (New-CockpitAction "run") -Trigger $trigger `
  -Settings $settings -Description "Equity cockpit: price the book, check the Equity Log, alert on change." `
  -Force | Out-Null

Write-Host "Registered '$name' - weekdays at $At."

# --- the intraday refresh --------------------------------------------------

if ($NoRefresh) {
  Write-Host "Skipped '$refreshName' (-NoRefresh)."
} else {
  # A weekly trigger has no -RepetitionInterval parameter, so the repetition is
  # built on a throwaway -Once trigger and grafted on. This is the documented
  # way to get "every N minutes, weekdays only" out of a single task.
  $refreshTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdays -At $RefreshFrom
  $refreshTrigger.Repetition = (New-ScheduledTaskTrigger -Once -At $RefreshFrom `
    -RepetitionInterval (New-TimeSpan -Minutes $RefreshMinutes) `
    -RepetitionDuration (New-TimeSpan -Minutes $windowMinutes)).Repetition

  # The default is $true, which stops any instance still running when the
  # duration expires - and the last repetition starts exactly on that boundary.
  # That is the 22:00 one, the New York close, the single most valuable refresh
  # of the day, and it would be racing the scheduler to finish. ExecutionTimeLimit
  # still bounds it at 10 minutes, so nothing runs away.
  $refreshTrigger.Repetition.StopAtDurationEnd = $false

  # NOT StartWhenAvailable. A missed 14:00 refresh is worthless by 19:00 - the
  # next one is half an hour away and will be correct. Catching up on skipped
  # runs would only repaint the page with a price it is about to replace.
  # The time limit is short for the same reason: a refresh still running when
  # the next one is due has failed, and should be killed rather than queued.
  $refreshSettings = New-ScheduledTaskSettingsSet `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew

  Register-ScheduledTask -TaskName $refreshName -Action (New-CockpitAction "refresh") `
    -Trigger $refreshTrigger -Settings $refreshSettings `
    -Description "Equity cockpit: re-price and re-render only. No Notion, no Telegram." `
    -Force | Out-Null

  # Read the window back off the registered task rather than re-deriving it from
  # the parameters. The bug this replaces was a success message computed from
  # the inputs while a truncated duration went to the scheduler - it printed a
  # window that was never registered.
  $reg = (Get-ScheduledTask -TaskName $refreshName).Triggers[0].Repetition
  $end = ([datetime]::Parse($RefreshFrom) +
          [System.Xml.XmlConvert]::ToTimeSpan($reg.Duration)).ToString("HH:mm")
  Write-Host ("Registered '$refreshName' - weekdays every " +
              "$([System.Xml.XmlConvert]::ToTimeSpan($reg.Interval).TotalMinutes) min, " +
              "$RefreshFrom to $end (duration $($reg.Duration)).")
}

Write-Host ""
Write-Host "Check it:  Get-ScheduledTaskInfo -TaskName $name"
Write-Host "Run now:   Start-ScheduledTask -TaskName $name"
