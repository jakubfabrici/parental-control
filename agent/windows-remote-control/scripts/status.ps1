# status.ps1 - rychly stav PC bez WMI a bez Add-Type (co po reboote zamrzalo/spomalovalo).
$up = [TimeSpan]::FromMilliseconds([Environment]::TickCount64)
$ips = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '169.*' -and $_.IPAddress -ne '127.0.0.1' } |
        Select-Object -ExpandProperty IPAddress) -join ', '
"Host      : $env:COMPUTERNAME"
"User      : $env:USERNAME"
"Uptime    : {0}d {1}h {2}m" -f $up.Days, $up.Hours, $up.Minutes
"Lokalne IP: $ips"
