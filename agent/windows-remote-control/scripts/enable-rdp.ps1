# enable-rdp.ps1 - Zapne vstavany Remote Desktop (RDP) na Windows Pro/Enterprise.
# SPUSTI AKO ADMIN (pravy klik -> Run as administrator, alebo z admin PowerShellu).
#
# BEZPECNOST: RDP nikdy NEVYSTAVUJ priamo na internet (port 3389). Pouzivaj ho iba
# cez domacu siet alebo cez VPN (napr. Tailscale/WireGuard). Na ovladanie z telefonu
# odkialkolvek pouzi RustDesk (viz README) - ten nevyzaduje otvorene porty.

#Requires -RunAsAdministrator

# 1) Povolit RDP
Set-ItemProperty -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server' `
    -Name 'fDenyTSConnections' -Value 0

# 2) Vyzadovat Network Level Authentication (bezpecnejsie)
Set-ItemProperty -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp' `
    -Name 'UserAuthentication' -Value 1

# 3) Povolit RDP vo firewalle (iba pre Private/Domain profil, NIE Public)
Enable-NetFirewallRule -DisplayGroup 'Remote Desktop' -ErrorAction SilentlyContinue
Set-NetFirewallRule -DisplayGroup 'Remote Desktop' -Profile Domain,Private -ErrorAction SilentlyContinue

Write-Host "RDP zapnute. Pripajaj sa z ineho PC cez 'mstsc' na IP tohto pocitaca."
Write-Host "Odporucanie: pouzivaj VPN (Tailscale) namiesto vystavenia portu 3389."
