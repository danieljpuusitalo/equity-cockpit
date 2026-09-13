# Registers the daily scheduled run. Idempotent - re-running replaces the task.
#
#   .\install-task.ps1              register at 07:40 on weekdays
#   .\install-task.ps1 -At 18:10    a different time
#   .\install-task.ps1 -Remove      unregister
#
# Weekdays only: the CSV is a snapshot and the markets are shut at the weekend,
# so a Saturday run would send you the same alert twice for no new information.

param([string] $At = "07:40", [switch] $Remove)

$ErrorActionPreference = "Stop"
$name = "EquityCockpit"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($Remove) {
  Unregister-ScheduledTask -TaskName $name -Confirm:$false
  Write-Host "Removed scheduled task '$name'."
  return
}

$action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$here\run.ps1`" run" `
  -WorkingDirectory $here

$trigger = New-ScheduledTaskTrigger -Weekly `
  -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $At

# StartWhenAvailable matters: a laptop that was shut at 07:40 should still run
# when it wakes, rather than skipping the day in silence.
$settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -DontStopIfGoingOnBatteries `
  -AllowStartIfOnBatteries `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
  -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
  -Settings $settings -Description "Equity cockpit: price the book, check the Equity Log, alert on change." `
  -Force | Out-Null

Write-Host "Registered '$name' - weekdays at $At."
Write-Host "Check it:  Get-ScheduledTaskInfo -TaskName $name"
Write-Host "Run now:   Start-ScheduledTask -TaskName $name"
