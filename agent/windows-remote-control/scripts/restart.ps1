# restart.ps1 - Restartuje PC.
param([int]$Delay = 5)
shutdown.exe /r /t $Delay /c "Vzdialeny restart (remote-control)"
Write-Host "PC sa restartuje o $Delay s. Zrusit: shutdown /a"
