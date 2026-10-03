# shutdown.ps1 - Vypne PC.
# Parameter -Delay udáva odklad v sekundách (default 5s, nech sa dá stihnúť zrušiť).
# Zrušenie behom odkladu: shutdown /a
param([int]$Delay = 5)
shutdown.exe /s /t $Delay /c "Vzdialene vypnutie (remote-control)"
Write-Host "PC sa vypne o $Delay s. Zrusit: shutdown /a"
