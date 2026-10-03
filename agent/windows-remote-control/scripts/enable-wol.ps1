# enable-wol.ps1 - Pripravi PC na Wake-on-LAN (zapnutie na dialku).
# SPUSTI AKO ADMIN. Vypise aj MAC adresu, ktoru potrebujes na posielanie "magic packetu".
#
# Poznamka: WOL musi byt zapnuty aj v BIOS/UEFI ("Wake on LAN" / "Power on by PCI-E").
# A "Fast Startup" vo Windows moze WOL po vypnuti blokovat - odporucam ho vypnut:
#   powercfg /h off    (vypne aj hibernaciu)  ALEBO cez Ovladaci panel -> Napajanie.

#Requires -RunAsAdministrator

$adapters = Get-NetAdapter -Physical | Where-Object Status -eq 'Up'
foreach ($a in $adapters) {
    try {
        Enable-NetAdapterPowerManagement -Name $a.Name -WakeOnMagicPacket -ErrorAction Stop
        Write-Host "WOL zapnuty na adapteri: $($a.Name)  MAC: $($a.MacAddress)"
    } catch {
        Write-Host "Adapter $($a.Name): WOL nastavuj v ovladaci (Device Manager -> Power Management)."
        Write-Host "  MAC: $($a.MacAddress)"
    }
}
Write-Host ""
Write-Host "Zapamataj si MAC adresu vyssie. Na zobudenie posli magic packet (napr. z telefonu"
Write-Host "appka 'Wake On Lan') na tuto MAC. Cez internet potrebujes na routeri buď port"
Write-Host "forward UDP 9 na broadcast, alebo router s WOL funkciou / vzdy zapnuty mini-server."
