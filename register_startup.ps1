$ErrorActionPreference = 'Stop'
$taskName = 'Soundroom Server'
$entryPoint = Join-Path $PSScriptRoot 'start_hidden.vbs'
$windowsScriptHost = Join-Path $env:WINDIR 'System32\wscript.exe'
$userId = "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute $windowsScriptHost -Argument ('"{0}"' -f $entryPoint) -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Description 'Starts the Soundroom local server when this Windows user signs in.' -Force | Out-Null
Write-Host 'Soundroom will start when this Windows user signs in.'
