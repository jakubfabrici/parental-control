<#
  Install-Agent.ps1 - Nainstaluje PcAgent.ps1 ako scheduled task v session 1.
  SPUSTI AKO ADMIN. Otvori firewall port, prida urlacl a spusti agenta.
#>
#Requires -RunAsAdministrator
$root = $PSScriptRoot
$agent = Join-Path $root 'PcAgent.ps1'
$cfg = Get-Content (Join-Path $root 'config.json') -Raw | ConvertFrom-Json
$port = if ($cfg.Port) { [int]$cfg.Port } else { 8799 }
$taskName = 'HA-PcAgent'

# 1) urlacl (aby HttpListener na http://+:PORT/ fungoval aj bez plnej elevacie)
$me = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
cmd /c "netsh http add urlacl url=http://+:$port/ user=`"$me`"" 2>&1 | Out-Null

# 2) firewall
if (-not (Get-NetFirewallRule -Name "HA-PcAgent-$port" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name "HA-PcAgent-$port" -DisplayName "HA PC Agent (port $port)" `
        -Direction Inbound -Protocol TCP -Action Allow -LocalPort $port -Profile Any | Out-Null
    Write-Host "Firewall port $port otvoreny (Domain/Private)."
}

# 3) scheduled task - bezi v session 1 pri prihlaseni (kvoli screenshotu)
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$agent`""
# DVA triggery, nie jeden:
#   AtLogOn  - normalny start pri prihlaseni;
#   kazdych 5 minut - zachrana. 14. 9. 2026 bol agent pri odhlaseni zabity
#   (task result 0xC000013A) a druhy den uz nenabehol, takze cas sa cely
#   podvecer nepocital a nikto o tom nevedel. MultipleInstances je IgnoreNew,
#   takze bezuciemu agentovi opakovanie neublizi - len nabehne, ked nebezi.
$trigger = @(
    (New-ScheduledTaskTrigger -AtLogOn),
    (New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(2) `
        -RepetitionInterval (New-TimeSpan -Minutes 5))
)
# POZOR: nie USERDOMAIN\user (na WORKGROUP zlyha SID mapping) - realna identita:
$principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

Start-ScheduledTask -TaskName $taskName
Start-Sleep 2
$t = Get-ScheduledTask -TaskName $taskName
Write-Host "Task '$taskName': $($t.State). Agent pocuva na porte $port."
Write-Host "Odinstalovanie: Unregister-ScheduledTask -TaskName $taskName -Confirm:`$false; netsh http delete urlacl url=http://+:$port/"
