# setup_task_scheduler.ps1
# Run as Administrator in PowerShell
# Creates 7 daily Task Scheduler jobs for PP line fetch + VPS push

$bat = "C:\Users\thoma\SportsPredictor\deploy\fetch_and_push_pp.bat"
$action = New-ScheduledTaskAction -Execute $bat

$times = @("02:00", "03:15", "05:15", "08:15", "09:00", "12:00", "14:45")
$labels = @("Golf-pre", "NHL-pre", "NBA-pre", "MLB-pre", "MidMorning", "Afternoon", "MLB-eve")

for ($i = 0; $i -lt $times.Length; $i++) {
    $trigger = New-ScheduledTaskTrigger -Daily -At $times[$i]
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable
    $name = "SP-PPFetch-$($labels[$i])"

    Register-ScheduledTask -TaskName $name `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -RunLevel Highest `
        -Force

    Write-Host "Created: $name at $($times[$i])"
}

Write-Host ""
Write-Host "All 7 PP fetch tasks created. View in Task Scheduler under root folder."
