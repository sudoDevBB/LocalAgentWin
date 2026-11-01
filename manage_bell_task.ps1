param(
    [Parameter(Mandatory = $true)][ValidateSet('Register', 'Remove')][string]$Mode,
    [Parameter(Mandatory = $true)][int]$BellId,
    [string]$FireAt
)

$ErrorActionPreference = 'Stop'
$taskName = "Soundroom Bell $BellId"

if ($Mode -eq 'Remove') {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    exit 0
}

if (-not $FireAt) { throw 'FireAt is required when registering a room bell.' }
$python = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
$wakeScript = Join-Path $PSScriptRoot 'wake_bell.py'
$userId = "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute $python -Argument ('"{0}" {1}' -f $wakeScript, $BellId) -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -Once -At ([datetime]::Parse($FireAt))
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 3)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Wakes Soundroom for a scheduled room bell.' -Force | Out-Null
