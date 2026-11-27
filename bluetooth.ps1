param([ValidateSet('On','Off')][string]$State)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[void][Windows.Devices.Radios.Radio, Windows.System.Devices, ContentType=WindowsRuntime]
[void][Windows.Devices.Radios.RadioState, Windows.System.Devices, ContentType=WindowsRuntime]
function Await($operation, $resultType) {
    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
    $task = $method.MakeGenericMethod($resultType).Invoke($null, @($operation))
    $task.Wait()
    return $task.Result
}
$access = Await ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) ([Windows.Devices.Radios.RadioAccessStatus])
if ($access -ne 'Allowed') { throw "Windows denied Bluetooth access: $access" }
$radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
$bluetooth = @($radios | Where-Object { $_.Kind -eq 'Bluetooth' })
if (-not $bluetooth.Count) { throw 'No Bluetooth radio found.' }
foreach ($radio in $bluetooth) {
    $result = Await ($radio.SetStateAsync([Windows.Devices.Radios.RadioState]::$State)) ([Windows.Devices.Radios.RadioAccessStatus])
    if ($result -ne 'Allowed') { throw "Windows could not change Bluetooth: $result" }
}
