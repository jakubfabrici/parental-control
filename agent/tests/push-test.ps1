# Test hlasenia: overi, ze Send-Push poskladá spravne telo a ze zlyhanie
# spojenia nezhodi agenta. Pouziva skutocny kod z PcAgent.ps1.
$ErrorActionPreference='Stop'
function T($n,$c){ if($c){"OK   $n"}else{"ZLE  $n"} }
$src = Get-Content (Join-Path $PSScriptRoot '../windows-remote-control/ha-agent/PcAgent.ps1') -Raw
$a = $src.IndexOf('function Send-Push')
$b = $src.IndexOf('function Limit-Text')
$code = $src.Substring($a, $b - $a)

$AgentVersion = '1.2.0'
$PushIntervalSec = 30
$Script:LastPush = 0
$Script:PushFails = 0
$Script:LastPushActive = $false
$Script:StateLost = $false
$Script:LagMaxToday = 7
$Script:Log = @()
function Log($m,$lvl='INFO'){ $Script:Log += "$lvl $m" }
$now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$Script:Snap  = [pscustomobject]@{ ts=($now-4); used=18; active=$true; idle=3; valid=$true }
$Script:State = [pscustomobject]@{ limitMinutes=100; bonusMinutes=5 }

# Adresa, na ktorej nikto nepocuva -> spojenie zlyha
$PushUrl = 'http://127.0.0.1:59999/api/webhook/test'
Invoke-Expression $code

Send-Push -Force
T 'zlyhanie spojenia agenta nezhodi' ($true)
T 'zlyhanie sa zapocitalo' ($Script:PushFails -eq 1)
T 'prve zlyhanie sa zalogovalo' (($Script:Log | Where-Object { $_ -like '*hlasenie do HA zlyhalo (1x*' }).Count -eq 1)
Send-Push -Force
T 'druhe zlyhanie sa uz neloguje' (($Script:Log | Where-Object { $_ -like '*zlyhalo*' }).Count -eq 1)
T 'pocitadlo rastie' ($Script:PushFails -eq 2)

# Kadencia: bez -Force sa do 30 s neposiela
$Script:LastPush = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$predtym = $Script:PushFails
Send-Push
T 'do 30 s sa hlasenie neopakuje' ($Script:PushFails -eq $predtym)

# Bez adresy sa nerobi nic
$PushUrl = ''
Invoke-Expression $code
$predtym = $Script:PushFails
Send-Push -Force
T 'bez PushUrl sa nehlasi nic' ($Script:PushFails -eq $predtym)

# Telo hlasenia
$sn = $Script:Snap; $st = $Script:State
$telo = @{ used=[int]$sn.used; active=[bool]$sn.active; allowed=[int]($st.limitMinutes+$st.bonusMinutes)
           version=$AgentVersion; needs_seed=[bool]$Script:StateLost; lag_max=[int]$Script:LagMaxToday }
if ($sn.valid) { $age=$now-[long]$sn.ts; if($age -lt 0){$age=0}; $telo.idle_sec=[int]$sn.idle; $telo.age_sec=[int]$age }
$j = $telo | ConvertTo-Json -Compress | ConvertFrom-Json
T 'telo: used' ($j.used -eq 18)
T 'telo: allowed = limit + bonus' ($j.allowed -eq 105)
T 'telo: idle_sec' ($j.idle_sec -eq 3)
T 'telo: age_sec 3-5 s' ($j.age_sec -ge 3 -and $j.age_sec -le 5)
T 'telo: lag_max' ($j.lag_max -eq 7)
T 'telo: version' ($j.version -eq '1.2.0')
