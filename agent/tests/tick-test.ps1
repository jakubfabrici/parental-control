# Test logiky odpovede na tick (A1/A6 z vyskumu): odpoved zo snimky,
# pasmo platnosti stropu, podmienky seedu. Spustenie: pwsh -File tick-test.ps1
$ErrorActionPreference='Stop'
function T($n,$c){ if($c){"OK   $n"}else{"ZLE  $n"} }

# --- regex stropu: "0" a "-1" sa nesmu prijat ---
foreach ($v in @('60','1','1440')) { T "strop '$v' prijaty" ($v -match '^[1-9]\d*$') }
foreach ($v in @('0','-1','','abc','01')) { T "strop '$v' odmietnuty" (-not ($v -match '^[1-9]\d*$')) }

# --- odpoved zo snimky: neplatna snimka neposiela idle/age ---
function Odpoved($snap) {
  $res = @{ ok=$true; action='tick' }
  $res.used = [int]$snap.used; $res.active = [bool]$snap.active
  if ($snap.valid) {
    $age = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [long]$snap.ts
    if ($age -lt 0) { $age = 0 }
    $res.idle = [int]$snap.idle; $res.age = [int]$age
  }
  $res
}
$now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$init = [pscustomobject]@{ ts=$now; used=0; active=$false; idle=0; valid=$false }
$r = Odpoved $init
T 'init snimka: bez idle/age' (-not $r.ContainsKey('idle') -and -not $r.ContainsKey('age'))
$plat = [pscustomobject]@{ ts=($now-3); used=42; active=$true; idle=12; valid=$true }
$r = Odpoved $plat
T 'platna snimka: idle=12' ($r.idle -eq 12)
T 'platna snimka: age 2-4 s' ($r.age -ge 2 -and $r.age -le 4)
T 'platna snimka: used=42' ($r.used -eq 42)
$buducnost = [pscustomobject]@{ ts=($now+500); used=1; active=$true; idle=0; valid=$true }
T 'ts v buducnosti -> age=0' ((Odpoved $buducnost).age -eq 0)

# --- co by dnesny NULL Snap urobil bez inicializacie (regresny dokaz) ---
$null_snap = $null
$naive = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [long]$null_snap.ts
T 'bez inicializacie by age bol nezmyselny' ($naive -gt 1000000000)

# --- Accept-Seed: poistky proti nezmyselnemu seedu -------------------------
# Funkciu berieme PRIAMO z PcAgent.ps1, nech test starne spolu s kodom.
$src = Get-Content (Join-Path $PSScriptRoot '../windows-remote-control/ha-agent/PcAgent.ps1') -Raw
$a = $src.IndexOf('function Accept-Seed')
$b = $src.IndexOf('$Script:LastTick = $null')
$Script:Log2 = @()
function Log($m,$lvl='INFO'){ $Script:Log2 += "$lvl $m" }
function Save-State($s,[switch]$Force){ }
Invoke-Expression $src.Substring($a, $b - $a)

function NovyStav($used){ [pscustomobject]@{ usedSeconds = $used } }
$odPolnoci = [int]((Get-Date) - (Get-Date).Date).TotalMinutes

# 1) bez straty stavu sa seed ignoruje
$Script:State = NovyStav 60; $Script:StateLost = $false
$Script:SeedDeadline = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() + 600
Accept-Seed 100
T 'seed sa bez straty stavu ignoruje' ($Script:State.usedSeconds -eq 60)

# 2) po strate stavu sa prijme a okno sa zavrie
$Script:State = NovyStav 0; $Script:StateLost = $true
Accept-Seed 5
T 'seed po strate stavu prijaty' ($Script:State.usedSeconds -eq 300)
T 'seed sa berie len raz' ($Script:StateLost -eq $false)

# 3) seed nikdy neznizi uz napocitane
$Script:State = NovyStav 600; $Script:StateLost = $true
Accept-Seed 5
T 'seed neznizi vyssiu hodnotu' ($Script:State.usedSeconds -eq 600)

# 4) seed nad "minuty od polnoci" sa odmietne
$Script:State = NovyStav 0; $Script:StateLost = $true
Accept-Seed ($odPolnoci + 30)
T 'seed nad cas od polnoci odmietnuty' ($Script:State.usedSeconds -eq 0)
T 'a strata stavu ostava, aby sa dal prijat spravny' ($Script:StateLost -eq $true)

# 5) mimo rozsahu
$Script:State = NovyStav 0; $Script:StateLost = $true
Accept-Seed 5000
T 'seed nad 1440 odmietnuty' ($Script:State.usedSeconds -eq 0)

# 6) po vyprsani okna sa uz neprijme
$Script:State = NovyStav 0; $Script:StateLost = $true
$Script:SeedDeadline = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - 1
Accept-Seed 5
T 'seed po vyprsani okna odmietnuty' ($Script:State.usedSeconds -eq 0)
T 'okno sa zatvara natrvalo' ($Script:StateLost -eq $false)
