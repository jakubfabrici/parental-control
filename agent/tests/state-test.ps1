# Test odolnosti stavu agenta (A4 z vyskumu): durabilny zapis, zaloha,
# odmietnutie poskodenych dat. Spustenie: pwsh -File state-test.ps1
# Cita PRIAMO PcAgent.ps1, takze test starne spolu s kodom.
$ErrorActionPreference = 'Stop'
$src = Get-Content (Join-Path $PSScriptRoot '../windows-remote-control/ha-agent/PcAgent.ps1') -Raw
$start = $src.IndexOf('# Nacitanie stavu je tvrde')
$end   = $src.IndexOf('$Script:State = Load-State')
$code  = $src.Substring($start, $end - $start)

$StateDir = Join-Path ([IO.Path]::GetTempPath()) ("stest-" + [guid]::NewGuid().ToString('N').Substring(0,8))
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
$StatePath = Join-Path $StateDir 'state.json'
$Script:Log = @()
function Log($m,$lvl='INFO'){ $Script:Log += "[$lvl] $m" }
function New-DefaultState {
  [pscustomobject]@{ date=(Get-Date -Format 'yyyy-MM-dd'); limitMinutes=180; bonusMinutes=0;
    usedSeconds=0; blocked=$false; manualBlock=$false; overrideToday=$false; blockDeadline=0; warnedStep=9999; warnedAt=0 }
}
Invoke-Expression $code

function T($name,$cond){ if($cond){"OK   $name"}else{"ZLE  $name"} }

# 1) zapis + .bak
$s = New-DefaultState; $s.usedSeconds = 120
Save-State $s -Force
T '1 state.json existuje' (Test-Path $StatePath)
T '1 .bak existuje' (Test-Path "$StatePath.bak")
T '1 obsah sedi' ((Get-Content $StatePath -Raw | ConvertFrom-Json).usedSeconds -eq 120)
T '1 bez BOM' ((Get-Content $StatePath -AsByteStream -TotalCount 1)[0] -eq 123)

# 2) throttling: bez Dirty sa nezapisuje
$s.usedSeconds = 999
$Script:Dirty = $false
Save-State $s
T '2 bez Dirty nezapisal' ((Get-Content $StatePath -Raw | ConvertFrom-Json).usedSeconds -eq 120)
$Script:Dirty = $true
Save-State $s
T '2 do 60 s nezapisal ani s Dirty' ((Get-Content $StatePath -Raw | ConvertFrom-Json).usedSeconds -eq 120)
Save-State $s -Force
T '2 -Force zapisal' ((Get-Content $StatePath -Raw | ConvertFrom-Json).usedSeconds -eq 999)
T '2 Dirty vynulovany' ($Script:Dirty -eq $false)

# 3) poskodeny hlavny -> obnova zo .bak
[IO.File]::WriteAllBytes($StatePath, (New-Object byte[] 188))   # 188x NUL, presne ako 6.9.
$r = Load-State
T '3 obnovene zo zalohy' ($r.usedSeconds -eq 999)
T '3 poskodeny odlozeny ako .bad' ((Get-ChildItem (Join-Path $StateDir "*.bad-*")).Count -eq 1)
T '3 strata stavu nie je hlasena' ($Script:StateLost -eq $false)

# 4) prazdny subor (Get-Content -Raw da $null, ConvertFrom-Json nehodi vynimku)
Save-State $r -Force
Set-Content $StatePath -Value '' -NoNewline
$r2 = Load-State
T '4 prazdny subor odchyteny, obnova zo .bak' ($r2.usedSeconds -eq 999)

# 5) nezmyselna hodnota
Save-State $r2 -Force
'{"date":"2026-09-07","usedSeconds":1800000000,"limitMinutes":60}' | Set-Content $StatePath -NoNewline
$r3 = Load-State
T '5 nezmyselne usedSeconds odmietnute' ($r3.usedSeconds -eq 999)

# 6) ani hlavny ani zaloha -> needs_seed
Remove-Item "$StatePath*" -Force
$Script:StateLost = $false
$r4 = Load-State
T '6 default od nuly' ($r4.usedSeconds -eq 0)
T '6 strata stavu hlasena' ($Script:StateLost -eq $true)

# 7) chybajuce polia sa doplnia
'{"date":"2026-09-07","usedSeconds":60}' | Set-Content $StatePath -NoNewline
$r5 = Load-State
T '7 doplnene limitMinutes' ($r5.limitMinutes -eq 180)
T '7 doplnene warnedStep' ($r5.warnedStep -eq 9999)

Remove-Item $StateDir -Recurse -Force
