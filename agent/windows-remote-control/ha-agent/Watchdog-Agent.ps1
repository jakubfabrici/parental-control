<#
  Watchdog-Agent.ps1 - drzi PcAgent.ps1 nazive.

  Preco vznikol (dva incidenty za tri dni):
    13. 9. 2026 - proces agenta bezal, ale jeho jednovlaknova slucka bola
      zaseknuta; port 8799 bol otvoreny (drzi ho http.sys), takze Windows
      nemal preco nic restartovat, a HA dostavala same timeouty.
    14.-15. 9. 2026 - agenta pri odhlaseni nieco zabilo (task result
      0xC000013A) a druhy den uz nenabehol, lebo task mal jediny trigger
      "pri prihlaseni". Cas sa nepocital cely podvecer.

  Opakovany trigger v HA-PcAgent riesi druhy pripad (ked proces nebezi).
  Tento watchdog riesi prvy: agent moze bezat a pritom neodpovedat.

  Ako to robi: dva razy si vypyta /ping (bez tokenu staci HTTP 403 - to uz
  dokazuje, ze slucka odpoveda). Az ked zlyhaju OBA pokusy, agenta zabije
  a task spusti znova. Pise do agent.log, nech je to vidiet na jednom mieste.

  Spusta sa ako scheduled task HA-PcAgent-Watchdog kazdych 5 minut.
#>
$ErrorActionPreference = 'SilentlyContinue'

$root     = $PSScriptRoot
$logFile  = Join-Path $root 'agent.log'
$taskName = 'HA-PcAgent'

$port = 8799
try {
  $cfg = Get-Content (Join-Path $root 'config.json') -Raw | ConvertFrom-Json
  if ($cfg.Port) { $port = [int]$cfg.Port }
} catch { }

function Log($m) {
  $line = "{0} [WDOG] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m
  try { Add-Content $logFile $line -Encoding UTF8 } catch { }
}

# Odpoveda agent? 403 (chyba token) je platna odpoved - slucka zije.
function Test-Agent {
  try {
    $req = [Net.HttpWebRequest]::Create("http://127.0.0.1:$port/ping")
    $req.Timeout = 5000
    $req.ReadWriteTimeout = 5000
    $req.Method = 'GET'
    $resp = $req.GetResponse()
    $resp.Close()
    return $true
  } catch [Net.WebException] {
    # HTTP 403 pride ako WebException s odpovedou - to je zdravy agent.
    if ($_.Exception.Response) { return $true }
    return $false
  } catch { return $false }
}

if (Test-Agent) { exit 0 }
Start-Sleep -Seconds 10
if (Test-Agent) { exit 0 }

Log "agent neodpoveda na /ping - restartujem ho"

# Zabijeme len nas proces, nie kazdy powershell: hladame ho podla prikazoveho
# riadku (PcAgent.ps1). Bez toho by watchdog zabil hoci aj rodicovsku konzolu.
try {
  Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.CommandLine -like '*PcAgent.ps1*' } |
    ForEach-Object {
      Log ("zabijam zaseknuty proces PID " + $_.ProcessId)
      Stop-Process -Id $_.ProcessId -Force
    }
} catch { Log "zabijanie zlyhalo: $_" }

Start-Sleep -Seconds 2
try { Start-ScheduledTask -TaskName $taskName; Log "task $taskName spusteny" }
catch { Log "start tasku zlyhal: $_" }

Start-Sleep -Seconds 12
if (Test-Agent) { Log "agent je znova nazive" } else { Log "agent stale neodpoveda" }
