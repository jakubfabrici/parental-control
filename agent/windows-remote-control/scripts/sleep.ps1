# sleep.ps1 - Uspí PC (Sleep). Pozn.: ak je zapnutý hibernate, treba ho vypnuť
# aby fungoval skutočný Sleep: powercfg -h off  (spusti raz ako admin).
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::SetSuspendState('Suspend', $false, $false) | Out-Null
