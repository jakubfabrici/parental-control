<#
  PcAgent.ps1 - HTTP agent na ovladanie Windows PC z Home Assistanta (FABRICI.bot).
  Bezi ako scheduled task HA-PcAgent v session 1 (kuko), port 8799, token v config.json.

  Novinka: DENNY LIMIT CASU. Agent v async slucke kazdych ~20s "tikne" - meria aktivny
  cas (idle detekcia), po vycerpani limitu zablokuje PC (fullscreen Blocker overlay +
  vypnuty Task Manager). Rodic nastavuje/odblokuje cez Telegram. Stav v state.json.
  Odstrasenie, nie nepriestrelna ochrana (kuko je admin bez hesla).
#>

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

# Verziu drzi subor VERSION vedla agenta (zapisuje ho Update-PcAgent.ps1 pri
# aktualizacii z OMV). Ked chyba, je to rucna instalacia.
$AgentVersion = try {
  $vf = Join-Path (Split-Path $root -Parent) 'VERSION'
  if (Test-Path $vf) { (Get-Content $vf -Raw).Trim() } else { '1.2.1' }
} catch { '1.2.1' }

# ---- DPI awareness (pred meranim obrazovky) ----
try {
  Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
public static class DpiAware {
  [DllImport("shcore.dll")] static extern int SetProcessDpiAwareness(int value);
  [DllImport("user32.dll")] static extern bool SetProcessDPIAware();
  public static void Enable(){ try { SetProcessDpiAwareness(2); } catch { try { SetProcessDPIAware(); } catch {} } }
}
"@ -ErrorAction SilentlyContinue
  [DpiAware]::Enable()
} catch { }

# ---- idle detekcia (GetLastInputInfo) ----
try {
  Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
public static class IdleInfo {
  [StructLayout(LayoutKind.Sequential)] struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
  [DllImport("user32.dll")] static extern bool GetLastInputInfo(ref LASTINPUTINFO plii);
  public static uint Ms(){ var l = new LASTINPUTINFO(); l.cbSize = (uint)Marshal.SizeOf(l); if(!GetLastInputInfo(ref l)) return 0; return ((uint)Environment.TickCount) - l.dwTime; }
}
"@ -ErrorAction SilentlyContinue
} catch { }

# ---- config ----
$cfgPath = Join-Path $root 'config.json'
if (-not (Test-Path $cfgPath)) { throw "Chyba config.json v $root" }
$cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
$Token      = $cfg.Token
$Port       = if ($cfg.Port) { [int]$cfg.Port } else { 8799 }
$ScriptsDir = if ($cfg.ScriptsDir) { (Resolve-Path (Join-Path $root $cfg.ScriptsDir)).Path } else { (Resolve-Path (Join-Path $root '..\scripts')).Path }
$ShotDir    = if ($cfg.ShotDir) { $cfg.ShotDir } else { Join-Path $env:TEMP 'remote-shots' }
$BlockerPath = Join-Path $root 'Blocker.ps1'
$DefaultLimit = if ($cfg.DefaultLimitMinutes) { [int]$cfg.DefaultLimitMinutes } else { 180 }
$IdleThresholdMs = 60000    # 1 min bez vstupu = nepocita sa (aktivny cas, nie PC-on cas)
$TickIntervalMs  = 20000    # tik kazdych 20s
# Kam hlasit. Cela adresa vratane webhook id je v config.json - je to
# tajomstvo, do repozitara nepatri. Ked chyba, agent sa sprava ako 1.1.0
# a caka na otazky z HA.
$PushUrl = "$($cfg.PushUrl)"
$PushIntervalSec = 30       # 30 s: dvojnasobok kadencie, ktoru HA potrebuje
$GraceSeconds = if ($cfg.GraceSeconds) { [int]$cfg.GraceSeconds } else { 300 }   # cas na ulozenie pred vypnutim
# sprava pri bloku - z UTF-8 suboru (PS 5.1 by diakritiku v .ps1 bez BOM zmrsil)
$msgFile = Join-Path $root 'blockmsg.txt'
$BlockMessage = if (Test-Path $msgFile) { (Get-Content $msgFile -Raw -Encoding UTF8).Trim() } else { 'Cas na pocitaci vyprsal. Mas 5 minut na ulozenie prace, potom sa PC vypne.' }
New-Item -ItemType Directory -Force -Path $ShotDir | Out-Null

# Texty varovani: "<zostavajuce minuty>|<co povedat>", jeden stupen na riadok.
$WarnMessages = @{}
$warnFile = Join-Path $root 'warnmsg.txt'
if (Test-Path $warnFile) {
  foreach ($line in (Get-Content $warnFile -Encoding UTF8)) {
    if ($line -match '^\s*(\d+)\s*\|\s*(.+?)\s*$') { $WarnMessages[[int]$Matches[1]] = $Matches[2] }
  }
}

# stav mimo profilu dietata
$StateDir = 'D:\ProgramData\PcControl'
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
$StatePath = Join-Path $StateDir 'state.json'

$LogFile = Join-Path $root 'agent.log'
function Log($m,$lvl='INFO'){ $l="{0} [{1}] {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'),$lvl,$m; Write-Host $l; try{Add-Content $LogFile $l -Encoding UTF8}catch{} }

if ([string]::IsNullOrWhiteSpace($Token)) { Log "FATAL: prazdny Token" ERROR; exit 1 }

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

# ---- STATE ----
function New-DefaultState {
  [pscustomobject]@{
    date = (Get-Date -Format 'yyyy-MM-dd'); limitMinutes = $DefaultLimit; bonusMinutes = 0;
    usedSeconds = 0; blocked = $false; manualBlock = $false; overrideToday = $false; blockDeadline = 0; warnedStep = 9999; warnedAt = 0
  }
}
# Nacitanie stavu je tvrde: prazdny alebo biely subor vrati z ConvertFrom-Json
# $null BEZ vynimky, takze sa to musi kontrolovat rucne. Ked je hlavny subor
# poskodeny, skusi sa .bak; ked ani ten, startujeme od nuly a v odpovedi na
# tick si pytame seed z Home Assistanta (needs_seed).
function Load-State {
  foreach ($f in @($StatePath, "$StatePath.bak")) {
    if (-not (Test-Path $f)) { continue }
    try {
      $raw = Get-Content $f -Raw
      if ([string]::IsNullOrWhiteSpace($raw)) { throw 'prazdny subor' }
      $s = $raw | ConvertFrom-Json
      if ($null -eq $s -or $null -eq $s.date -or $null -eq $s.usedSeconds) { throw 'chybaju povinne polia' }
      # 200 000 s = 55,5 h, teda 2,3x dlzka dna: chyta hruby nezmysel z
      # poskodenych dat, nie hranicne pripady okolo polnoci.
      if ([double]$s.usedSeconds -lt 0 -or [double]$s.usedSeconds -gt 200000) { throw "nezmyselne usedSeconds: $($s.usedSeconds)" }
      foreach ($p in 'date','limitMinutes','bonusMinutes','usedSeconds','blocked','manualBlock','overrideToday','blockDeadline','warnedStep','warnedAt') {
        if ($null -eq $s.$p) { $s | Add-Member -NotePropertyName $p -NotePropertyValue (New-DefaultState).$p -Force }
      }
      if ($f -ne $StatePath) { Log "state.json poskodeny - obnovene zo zalohy (used=$($s.usedSeconds)s)" WARN }
      return $s
    } catch {
      Log "stav '$f' necitatelny: $_" WARN
      # Poskodeny subor ODKLADAME, nie prepisujeme - inak sa dokaz straca.
      try { Move-Item $f "$f.bad-$(Get-Date -Format 'yyyyMMdd_HHmmss')" -Force } catch { }
    }
  }
  Log 'ziadny pouzitelny stav - startujem od nuly a pytam si spotrebu z HA' WARN
  $Script:StateLost = $true
  New-DefaultState
}

# Zapis je durabilny: FileStream + Flush($true) vynuti zapis na plotnu, inak
# po strate napajania ostane v NTFS metadata bez obsahu (presne to sa stalo
# 28. 8. a 6. 9. 2026). Zaloha .bak sa robi az PO overenom zapise.
#
# Bez -Force sa zapisuje najviac raz za 60 s a len ked sa naozaj nieco zmenilo
# ($Script:Dirty). V najhorsom pripade sa tak strati < 1 minuta spotreby -
# oproti 154 straten m minutam pri dnesnom sprava ni je to zanedbatelne.
# -Force pouzivaju vsetky kriticke zapisy: strop z HA, bonus, blok/odblok,
# deadline vypnutia a odvysielane varovanie.
function Save-State($s, [switch]$Force) {
  $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
  if (-not $Force) {
    if (-not $Script:Dirty) { return }
    if (($now - $Script:LastSaveAt) -lt 60) { return }
  }
  try {
    $tmp   = "$StatePath.tmp"
    $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes(($s | ConvertTo-Json -Compress))
    $fs = [IO.File]::Open($tmp, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $fs.Write($bytes, 0, $bytes.Length); $fs.Flush($true) } finally { $fs.Dispose() }
    Move-Item -Force $tmp $StatePath
    Copy-Item $StatePath "$StatePath.bak" -Force
    $Script:LastSaveAt = $now; $Script:Dirty = $false
  } catch { Log "Save-State chyba: $_" WARN }
}
# Deklaracie musia byt PRED Load-State - ten uz nastavuje StateLost.
$Script:Dirty        = $false   # zmenil sa stav od posledneho zapisu?
$Script:LastSaveAt   = 0
$Script:StateLost    = $false   # nemame vlastny stav, pytame si ho z HA
$Script:SeedDeadline = 0        # dokedy seed z HA prijmeme (viz nizsie)
$Script:LagMaxToday  = 0        # najvacsie meskanie tiku za dnesok (s)
$Script:TickCount    = 0        # pocitadlo pre hodinovy suhrn v logu
$Script:HourMark     = 0
$Script:LastPush     = 0        # kedy naposledy odislo hlasenie do HA
$Script:PushFails    = 0        # kolko hlaseni po sebe zlyhalo
$Script:LastPushActive = $false # aku prezenciu uz HA vie
# Okno na prijatie seedu. 600 s pokryva aj 5-minutovy backoff HA: 6. 9. po
# boote 13:56:57Z prisiel prvy uspesny tik az o 14:00:00Z (157 s), po pade
# 14:04:25Z uz o 14:05:00Z (8 s). Ked okno vyprsi, seed sa uz neprijme -
# zmeskany seed znamena used = 0, teda viac casu pre dieta (bezpecny smer).
$SeedWindowSec = 600
# Snimka musi byt platny objekt uz pred prvym Invoke-Tick: cely Invoke-Tick je
# v try/catch, takze prvy tik moze zlyhat ticho - a $null.ts by v odpovedi dalo
# vek okolo 1,79e9 sekund. valid=false znamena "este nemerane", polia idle/age
# sa vtedy neposielaju vobec a HA si necha predoslu hodnotu.
$Script:Snap = [pscustomobject]@{
  ts = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds(); used = 0; active = $false; idle = 0; valid = $false
}
$Script:State = Load-State
$Script:SeedDeadline = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() + $SeedWindowSec

# Seed je jediny sposob, ako usedSeconds skoci nahor bez toho, aby ubehol
# realny cas - preto ma vlastne poistky: len po skutocnej strate stavu, len
# raz, len v case okna, len nahor a len do stropu "kolko minut dnes vobec
# ubehlo" (to iste cislo strazi aj HA na svojej strane).
function Accept-Seed([int]$seedMin) {
  $s = $Script:State
  if (-not $Script:StateLost) { return }
  if ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() -gt $Script:SeedDeadline) {
    $Script:StateLost = $false; return
  }
  if ($seedMin -lt 0 -or $seedMin -gt 1440) { Log "seed $seedMin mimo rozsahu - ignorujem" WARN; return }
  $odPolnoci = [int]((Get-Date) - (Get-Date).Date).TotalMinutes
  if ($seedMin -gt $odPolnoci) { Log "seed $seedMin min > $odPolnoci min od polnoci - ignorujem" WARN; return }
  if ($seedMin * 60 -le [double]$s.usedSeconds) { $Script:StateLost = $false; return }
  Log ("seed z HA: usedSeconds {0} -> {1} (obnova po strate stavu)" -f [int]$s.usedSeconds, ($seedMin * 60)) WARN
  $s.usedSeconds = $seedMin * 60
  $Script:StateLost = $false
  Save-State $s -Force
}
$Script:LastTick = $null
$Script:ShutdownArmed = $false
$Script:BlockerProc = $null
$Script:LastIdleMs = 0        # posledny nameraný idle (pre transparentnost v /state)
$Script:LastActive = $false   # ratal sa posledny tik ako aktivny?

# Uprac zvysky z predosleho (fullscreen) modelu bloku: zabi stare Blocker overlaye
# a znovu povol Task Manager (starsi model ho vypinal).
try {
  Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*Blocker.ps1*' -and $_.ProcessId -ne $PID } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
} catch { }
try {
  $tmk = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Policies\System'
  if (Test-Path $tmk) { Remove-ItemProperty -Path $tmk -Name DisableTaskMgr -ErrorAction SilentlyContinue }
} catch { }

# Blok = zobraz spravu (notifikacia + nahlas) a spusti odpocet do vypnutia.
# Dieta ma $GraceSeconds na ulozenie prace, potom Windows PC vypne.
function Ensure-Blocked {
  $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
  if (-not $Script:ShutdownArmed) {
    try { $bm64=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($BlockMessage)); Start-ScriptFile 'speak.ps1' @('-TextB64', $bm64, '-SpeakVolume','70') | Out-Null } catch { }
    # NEPOUZIVAME shutdown /t (ten ukazuje Windows dialog "Budete odhlaseni").
    # Cas strazi agent sam - deadline v state (prezije restart, dieta ho nevynuluje restartom).
    if (-not $Script:State.blockDeadline -or [long]$Script:State.blockDeadline -le 0) {
      $Script:State.blockDeadline = $now + $GraceSeconds
      # -Force: komentar vyssie slubuje, ze deadline prezije restart. Bez
      # vynuteneho zapisu by to prvych 60 s nebola pravda a opakovany restart
      # by ho vzdy vynuloval.
      Save-State $Script:State -Force
    }
    $Script:ShutdownArmed = $true
    Log "Block: grace do $($Script:State.blockDeadline) (unix), teraz $now"
  }
  # trvaly viditelny banner so spravou (relaunch ak by zmizol)
  if (-not $Script:BlockerProc -or $Script:BlockerProc.HasExited) {
    try { $Script:BlockerProc = Start-Process powershell.exe -PassThru -WindowStyle Hidden `
      -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File', $BlockerPath) } catch { }
  }
  # grace uplynul -> ticho vypni (bez Windows dialogu)
  if ([long]$Script:State.blockDeadline -gt 0 -and $now -ge [long]$Script:State.blockDeadline) {
    Log "Grace uplynul - vypinam PC (shutdown /s /t 0 /f)"
    try { & shutdown.exe /s /t 0 /f 2>$null } catch { }
  }
}
function Ensure-Unblocked {
  if ($Script:ShutdownArmed) {
    try { & shutdown.exe /a 2>$null } catch { }   # poistka, ak by z minula visel Windows shutdown
    $Script:ShutdownArmed = $false
    Log "Block zruseny"
  }
  if ([long]$Script:State.blockDeadline -ne 0) { $Script:State.blockDeadline = 0; $Script:Dirty = $true }
  if ($Script:BlockerProc -and -not $Script:BlockerProc.HasExited) {
    try { $Script:BlockerProc.Kill() } catch { }
  }
  $Script:BlockerProc = $null
}

# Povie dietatu, kolko casu mu zostava. Nic neblokuje.
# Kazdy stupen raz za den; stav je v state.json, takze restart PC ho nevynuluje.
function Invoke-Warnings($s) {
  try {
    if (-not $Script:LastActive) { return }          # nikto pri PC nie je, netreba
    $cap = [int]$s.limitMinutes + [int]$s.bonusMinutes
    # Nulovy strop = nevieme, kolko ma dnes k dispozicii (napr. HA nema minuty
    # tabletu, lebo nebezi most TimeLimit, a poslala -1). Vtedy sa
    # NEVYHLASUJE nic - inak by dieta dostalo "cas sa minul" len preto, ze
    # zlyhal zdroj dat.
    if ($cap -le 0) { return }
    $remain = [math]::Max(0, $cap - [math]::Floor($s.usedSeconds / 60))
    if ($null -eq $s.warnedStep) { $s | Add-Member -NotePropertyName warnedStep -NotePropertyValue 9999 -Force }
    # Ked casu pribudlo (rodic pridal cez /cas_add), varujeme odznova.
    if ($remain -gt [int]$s.warnedStep) { $s.warnedStep = 9999; $Script:Dirty = $true }
    $step = $null
    foreach ($t in @(30,15,5,1,0)) { if ($remain -le $t) { $step = $t } }
    if ($null -eq $step) { return }
    if ([int]$s.warnedStep -le $step) { return }     # tento stupen uz odznel
    # Ked strop skokovo klesne (Simonka medzitym hrala na tablete), preskocene
    # stupne len ticho odpiseme - inak by dve varovania odzneli tesne po sebe.
    # Nula sa povie vzdy, tu treba vediet.
    $teraz = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $odPosledneho = if ([long]$s.warnedAt -gt 0) { $teraz - [long]$s.warnedAt } else { 99999 }
    $s.warnedStep = $step
    if ($step -ne 0 -and $odPosledneho -lt 120) {
      Log "Varovanie $step min preskocene - predchadzajuce odznelo pred $odPosledneho s"
      return
    }
    $s.warnedAt = $teraz
    $text = $WarnMessages[$step]
    if (-not $text) { $Script:Dirty = $true; return }
    # Odvysielane varovanie je fakt, ktory ma prezit restart (nastava najviac
    # 5x denne, takze vynuteny zapis nic nestoji).
    Save-State $s -Force
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($text))
    Start-ScriptFile 'notify.ps1' @('-TextB64', $b64) | Out-Null
    Start-ScriptFile 'speak.ps1'  @('-TextB64', $b64, '-SpeakVolume','70') | Out-Null
    Log "Varovanie: zostava $remain min (stupen $step)"
  } catch { Log "Varovanie chyba: $_" WARN }
}

function Invoke-Tick {
  try {
    $s = $Script:State
    $today = Get-Date -Format 'yyyy-MM-dd'
    if ($s.date -ne $today) {
      Log "novy den ($today) - reset limitu"
      $s.date = $today; $s.usedSeconds = 0; $s.bonusMinutes = 0
      $s.manualBlock = $false; $s.overrideToday = $false; $s.blocked = $false; $s.blockDeadline = 0
      $s.warnedStep = 9999; $s.warnedAt = 0
      $Script:LagMaxToday = 0
      $Script:Dirty = $true; Save-State $s -Force
    }
    $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    if ($null -eq $Script:LastTick) { $Script:LastTick = $now }
    # $lagRaw je NEorezany rozdiel - na diagnostiku. $elapsed sa orezava na
    # 90 s, aby jeden dlhy vypadok nepripocital hodinu spotreby.
    $lagRaw = [int]($now - $Script:LastTick); if ($lagRaw -lt 0) { $lagRaw = 0 }
    $elapsed = $lagRaw; if ($elapsed -gt 90){$elapsed=90}
    $Script:LastTick = $now
    # Nominal je 20 s, prah 30 s = 1,5x nominal. Kazde taketo meskanie je
    # kandidat na zahodeny tik v HA, preto sa hlasi aj do odpovede (lag_max).
    if ($lagRaw -gt 30) { Log "slucka meskala $lagRaw s (ocakavanych ~20 s)" WARN }
    if ($lagRaw -gt $Script:LagMaxToday) { $Script:LagMaxToday = $lagRaw }
    $idleMs = try { [IdleInfo]::Ms() } catch { 0 }
    $locked = [bool](Get-Process LogonUI -ErrorAction SilentlyContinue)
    $Script:LastIdleMs = $idleMs
    # "Sedi prave pri PC" - pre Home Assistant a pre upozornenia.
    $active = ($idleMs -lt $IdleThresholdMs) -and (-not $locked)
    $Script:LastActive = $active
    # Rata sa LEN cas, ked sa naozaj hybalo mysou alebo pisalo: z intervalu
    # odratame, ako dlho je uz ticho. Ticho cely interval -> nepripocita sa
    # nic; prestala sa hybat v jeho polovici -> pripocita sa polovica.
    # Pozor: pozeranie videa bez dotyku mysi sa tym padom nerata.
    $idleSec = [int][math]::Floor($idleMs / 1000)
    $aktivnychSek = if ($locked) { 0 } else { [math]::Max(0, $elapsed - $idleSec) }
    # Vycerpany limit PC NEBLOKUJE - je to zamer, nie chybajuca funkcia.
    # Simonka sa ma vediet zastavit sama; my ju len upozornime a Home
    # Assistant o prekroceni da vediet rodicom. Blok ostava uz len na
    # vyslovny pokyn rodica (akcia 'block' z Telegramu).
    $blockNow = [bool]$s.manualBlock
    # Meriame aj nad ramec limitu, nech je vidiet o kolko ho prekrocila.
    if (-not $blockNow) { $s.usedSeconds += $aktivnychSek }
    if ($aktivnychSek -gt 0) { $Script:Dirty = $true }
    if ([bool]$s.blocked -ne $blockNow) { $Script:Dirty = $true }
    $s.blocked = $blockNow
    if ($blockNow) { Ensure-Blocked } else { Ensure-Unblocked }
    Invoke-Warnings $s
    Save-State $s
    # Snimka az na konci: valid = $true znamena "prave odmerane". Z nej
    # odpoveda obsluha tiku, takze v ceste HTTP odpovede uz nie je ziadne I/O.
    $Script:Snap = [pscustomobject]@{
      ts = $now; used = [int][math]::Floor($s.usedSeconds / 60)
      active = [bool]$active; idle = [int][math]::Floor($idleMs / 1000); valid = $true
    }
    # A7: namiesto riadku na kazdy tik jeden suhrn za hodinu.
    $Script:TickCount++
    if ($now - $Script:HourMark -ge 3600) {
      if ($Script:HourMark -gt 0) {
        Log ("suhrn: {0} tikov, max meskanie {1} s, pouzite {2} min, strop {3} min" -f `
             $Script:TickCount, $Script:LagMaxToday, [int][math]::Floor($s.usedSeconds/60), ([int]$s.limitMinutes + [int]$s.bonusMinutes))
      }
      $Script:HourMark = $now; $Script:TickCount = 0
    }
  } catch { Log "Tick chyba: $_" WARN }
}

# Hlasenie do HA. Bezi v casovacovej vetve slucky, nikdy nie v ceste HTTP
# odpovede - inak by sme si vyrobili presne ten problem, ktory riesime.
# Chyba sa loguje len pri prvom, piatom a dvadsiatom zlyhani po sebe: ked je
# HA dole pol dna, nechceme mat z agent.log zoznam neuspechov.
function Send-Push {
  param([switch]$Force)
  if ([string]::IsNullOrWhiteSpace($PushUrl)) { return }
  $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
  if (-not $Force -and ($now - $Script:LastPush) -lt $PushIntervalSec) { return }
  $Script:LastPush = $now
  try {
    $sn = $Script:Snap
    $st = $Script:State
    $telo = @{
      used       = [int]$sn.used
      active     = [bool]$sn.active
      allowed    = [int]($st.limitMinutes + $st.bonusMinutes)
      version    = $AgentVersion
      needs_seed = [bool]$Script:StateLost
      lag_max    = [int]$Script:LagMaxToday
    }
    # idle_sec/age_sec len z platnej snimky - nech HA radsej nedostane nic,
    # nez vymysel. Bez nich si HA necha predoslu znacku vstupu.
    if ($sn.valid) {
      $age = $now - [long]$sn.ts
      if ($age -lt 0) { $age = 0 }
      $telo.idle_sec = [int]$sn.idle
      $telo.age_sec  = [int]$age
    }
    $bajty = [Text.Encoding]::UTF8.GetBytes(($telo | ConvertTo-Json -Compress))
    $req = [Net.HttpWebRequest]::Create($PushUrl)
    $req.Method = 'POST'
    $req.ContentType = 'application/json'
    $req.Timeout = 5000
    $req.ReadWriteTimeout = 5000
    $req.ContentLength = $bajty.Length
    $prud = $req.GetRequestStream()
    try { $prud.Write($bajty, 0, $bajty.Length) } finally { $prud.Close() }
    $odp = $req.GetResponse()
    $odp.Close()
    if ($Script:PushFails -gt 0) { Log "hlasenie do HA znova chodi (po $($Script:PushFails) zlyhaniach)" }
    $Script:PushFails = 0
    $Script:LastPushActive = [bool]$sn.active
  } catch {
    $Script:PushFails++
    if ($Script:PushFails -eq 1 -or $Script:PushFails -eq 5 -or $Script:PushFails -eq 20) {
      Log "hlasenie do HA zlyhalo ($($Script:PushFails)x po sebe): $($_.Exception.Message)" WARN
    }
  }
}

# Prezencia sa ma v HA objavit hned, nie az pri najblizsom 30 s hlaseni.
function Push-IfChanged {
  if ([string]::IsNullOrWhiteSpace($PushUrl)) { return }
  if ([bool]$Script:Snap.active -ne [bool]$Script:LastPushActive) { Send-Push -Force }
  else { Send-Push }
}

function Limit-Text {
  $s = $Script:State
  $cap = $s.limitMinutes + $s.bonusMinutes
  $usedMin = [math]::Floor($s.usedSeconds / 60)
  $remain = [math]::Max(0, $cap - $usedMin)
  $st = if ($s.blocked) { "ZABLOKOVANE" } elseif ($s.overrideToday) { "odblokovane na dnes" } else { "aktivne" }
  $ct = if ($Script:LastActive) { "prave sa pocita (necinny " + [int]([math]::Round($Script:LastIdleMs/1000)) + " s)" } else { "nepocita sa (necinny " + [int]([math]::Round($Script:LastIdleMs/60000)) + " min)" }
  "Limit dnes : $($s.limitMinutes) min" + $(if($s.bonusMinutes){" (+$($s.bonusMinutes) bonus)"}else{""}) + "`n" +
  "Pouzite    : $usedMin min (len aktivny cas)`n" +
  "Zostava    : $remain min`n" +
  "Stav       : $st`n" +
  "Cas        : $ct"
}

# ---- screenshot (inline, session 1) ----
function TakeShot {
  $vs = [System.Windows.Forms.SystemInformation]::VirtualScreen
  $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
  $file = Join-Path $ShotDir "shot_$stamp.png"
  $bmp = New-Object System.Drawing.Bitmap $vs.Width, $vs.Height
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($vs.Location, [System.Drawing.Point]::Empty, $vs.Size)
  $bmp.Save($file, [System.Drawing.Imaging.ImageFormat]::Png)
  $g.Dispose(); $bmp.Dispose()
  Get-ChildItem "$ShotDir\*.png" | Sort-Object LastWriteTime -Descending | Select-Object -Skip 20 | Remove-Item -Force -ErrorAction SilentlyContinue
  return $file
}

# ---- spusti skript s TIMEOUTOM (pre veci mimo agentovho procesu) ----
# TimeoutSec 6, nie 15: volume.ps1 aj status.ps1 bezia normalne pod sekundu a
# v logu su len uplne zaseknutia. 6 s je bohata rezerva nad normalom a hlboko
# pod 25 s timeoutom, ktory ma HA na rest_command.pc_cmd.
function RunScript($name,[string[]]$a=@(),[int]$TimeoutSec=6){
  $p = Join-Path $ScriptsDir $name
  if (-not (Test-Path $p)) { return "skript $name neexistuje" }
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = 'powershell.exe'
  $psi.Arguments = (@('-NoProfile','-ExecutionPolicy','Bypass','-File', "`"$p`"") + $a) -join ' '
  $psi.UseShellExecute = $false; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true; $psi.CreateNoWindow = $true
  $proc = New-Object System.Diagnostics.Process; $proc.StartInfo = $psi
  try {
    [void]$proc.Start()
    $outTask = $proc.StandardOutput.ReadToEndAsync()
    # Stderr sa MUSI dociitat, inak sa dcersky proces pri viac nez ~4 kB
    # zablokuje na plnom pipe az do Kill - a s nim aj cela slucka agenta.
    $errTask = $proc.StandardError.ReadToEndAsync()
    if ($proc.WaitForExit($TimeoutSec * 1000)) {
      # .Result bez timeoutu vie visiet navzdy; proces uz skoncil, ide len o
      # dociitanie hotovych bufferov.
      $out = if ($outTask.Wait(1000)) { $outTask.Result } else { '' }
      [void]$errTask.Wait(500)
      $out.TrimEnd()
    }
    else { try { $proc.Kill() } catch {}; Log "RunScript $name timeout ($TimeoutSec s)" WARN; "chyba: $name trval prilis dlho" }
  } catch { "chyba: $_" } finally { try { $proc.Dispose() } catch {} }
}
function Start-ScriptFile($name,[string[]]$a=@()){
  $p = Join-Path $ScriptsDir $name
  if (-not (Test-Path $p)) { return $false }
  # Start-Process s polom argumentov NEquotuje hodnoty s medzerami (rozbije text).
  # Preto poskladame jeden argument-string a hodnoty s medzerami/uvodzovkami zabalime.
  $q = ($a | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"','\"') + '"' } else { $_ } }) -join ' '
  $argline = "-NoProfile -ExecutionPolicy Bypass -File `"$p`" $q"
  Start-Process powershell.exe -WindowStyle Hidden -ArgumentList $argline
  return $true
}

# ---- HTTP ----
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://+:$Port/")
try { $listener.Start() } catch { Log "FATAL: HttpListener nestartol: $_" ERROR; exit 1 }
Log "Agent $AgentVersion bezi na http://+:$Port/  scripts=$ScriptsDir  session=$((Get-Process -Id $PID).SessionId)  limit=$($Script:State.limitMinutes)min  seed=$($Script:NeedsSeed)"

function Send($ctx,$code,$obj){
  $json = ($obj | ConvertTo-Json -Compress -Depth 6)
  $buf = [Text.Encoding]::UTF8.GetBytes($json)
  $ctx.Response.StatusCode = $code; $ctx.Response.ContentType = 'application/json; charset=utf-8'
  $ctx.Response.OutputStream.Write($buf,0,$buf.Length); $ctx.Response.OutputStream.Close()
}

function Handle-Request($ctx){
  $req = $ctx.Request
  $path = $req.Url.AbsolutePath.ToLower()
  $qtok = $req.QueryString['token']

  if ($req.HttpMethod -eq 'GET' -and $path -eq '/shot') {
    if ($qtok -ne $Token) { $ctx.Response.StatusCode=403; $ctx.Response.Close(); return }
    $f = Join-Path $ShotDir ([IO.Path]::GetFileName($req.QueryString['f']))
    if (Test-Path $f) { $b=[IO.File]::ReadAllBytes($f); $ctx.Response.ContentType='image/png'; $ctx.Response.OutputStream.Write($b,0,$b.Length); $ctx.Response.OutputStream.Close() }
    else { $ctx.Response.StatusCode=404; $ctx.Response.Close() }
    return
  }
  if ($req.HttpMethod -eq 'GET' -and $path -eq '/ping') {
    if ($qtok -ne $Token) { $ctx.Response.StatusCode=403; $ctx.Response.Close(); return }
    Send $ctx 200 @{ ok=$true; host=$env:COMPUTERNAME; session=(Get-Process -Id $PID).SessionId; blocked=$Script:State.blocked; version=$AgentVersion }
    return
  }
  if ($req.HttpMethod -eq 'POST' -and $path -eq '/cmd') {
    # VZDY UTF-8 - $req.ContentEncoding pri JSON bez charsetu padne na systemovy CP1250 a zmrsi diakritiku
    $body = (New-Object IO.StreamReader($req.InputStream, [Text.Encoding]::UTF8)).ReadToEnd()
    $d = $null; try { $d = $body | ConvertFrom-Json } catch {}
    if (-not $d -or $d.token -ne $Token) { Log "odmietnuty (zly token)" WARN; Send $ctx 403 @{ok=$false;error='forbidden'}; return }
    $action = "$($d.action)".ToLower(); $args = "$($d.args)"
    # Tik chodi kazdu minutu (1440 riadkov denne) - loguje sa len hodinovy
    # suhrn z Invoke-Tick. Vsetko ostatne je udalost, ktora ma byt v logu.
    if ($action -ne 'tick') { Log "cmd: $action $args" }
    $res = @{ ok=$true; action=$action }
    switch ($action) {
      'status' {
        # TickCount64 na starsom .NET vracia prazdno -> pouzi 32-bit TickCount (uint = az ~49 dni)
        $up = [TimeSpan]::FromMilliseconds([uint32][Environment]::TickCount)
        $ips = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notlike '169.*' -and $_.IPAddress -ne '127.0.0.1' } | Select-Object -ExpandProperty IPAddress) -join ', '
        $res.text = "Host      : $env:COMPUTERNAME`nUser      : $env:USERNAME`nUptime    : {0}d {1}h {2}m`nLokalne IP: $ips`n`n$(Limit-Text)" -f $up.Days,$up.Hours,$up.Minutes
      }
      'lock'     { Start-ScriptFile 'lock.ps1' | Out-Null; $res.text='zamknute' }
      'logoff'   { $res.text='odhlasujem'; Start-ScriptFile 'logoff.ps1' | Out-Null }
      'sleep'    { $res.text='uspavam'; Start-ScriptFile 'sleep.ps1' | Out-Null }
      # Vystup nikto necita (| Out-Null), takze niet preco kvoli nim blokovat
      # slucku - a prave vypinanie po limite je najhorsi mozny cas na to.
      'shutdown' { $dl= if($d.delay){[int]$d.delay}else{5}; Start-ScriptFile 'shutdown.ps1' @('-Delay',"$dl") | Out-Null; $res.text="vypinam o $dl s" }
      'restart'  { $dl= if($d.delay){[int]$d.delay}else{5}; Start-ScriptFile 'restart.ps1' @('-Delay',"$dl") | Out-Null; $res.text="restart o $dl s" }
      'cancel'   { try { & shutdown.exe /a 2>$null } catch { }; $res.text='zrusene' }
      'speak'    { if($args){ $b64=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($args)); Start-ScriptFile 'speak.ps1' @('-TextB64',$b64,'-SpeakVolume','70'); $res.text='citam' } else { $res.ok=$false;$res.text='chyba text' } }
      'notify'   { if($args){ $b64=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($args)); Start-ScriptFile 'notify.ps1' @('-TextB64',$b64); $res.text='notifikacia' } else { $res.ok=$false;$res.text='chyba text' } }
      'msg'      { if($args){ $b64=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($args)); Start-ScriptFile 'notify.ps1' @('-TextB64',$b64); Start-ScriptFile 'speak.ps1' @('-TextB64',$b64,'-SpeakVolume','70'); $res.text='zobrazene + citam' } else { $res.ok=$false;$res.text='chyba text' } }
      'volume'   { $res.text = if($args -match '^\d+$'){ RunScript 'volume.ps1' @('-Level',$args) } else { RunScript 'volume.ps1' } }
      'mute'     { $res.text = RunScript 'volume.ps1' @('-Mute') }
      'unmute'   { $res.text = RunScript 'volume.ps1' @('-Unmute') }
      'screenshot' {
        try { $f = TakeShot
          # IP na ktoru HA prislo (robustne voci zmene IP wifi<->kabel)
          $ip = $req.LocalEndPoint.Address.ToString()
          if ($ip -eq '0.0.0.0' -or [string]::IsNullOrWhiteSpace($ip)) { $ip=((Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -like '192.168.*'}).IPAddress | Select-Object -First 1) }
          $res.shot = "http://$($ip):$Port/shot?token=$Token&f=$([IO.Path]::GetFileName($f))"; $res.text='screenshot ok' }
        catch { $res.ok=$false; $res.text="screenshot zlyhal: $_" }
      }
      # ---- LIMIT ----
      'usage'     { $res.text = Limit-Text }
      'limit_get' { $res.text = Limit-Text }
      'state' {
        $s = $Script:State; $cap = $s.limitMinutes + $s.bonusMinutes; $usedMin = [math]::Floor($s.usedSeconds/60)
        $res.state = @{ limit=$s.limitMinutes; bonus=$s.bonusMinutes; used=$usedMin; remaining=[math]::Max(0,$cap-$usedMin); blocked=[bool]$s.blocked; override=[bool]$s.overrideToday; idle_sec=[int]([math]::Round($Script:LastIdleMs/1000)); counting=[bool]$Script:LastActive }
        $res.text = Limit-Text
      }
      'limit_set' {
        if ($args -match '^\d+$') { $Script:State.limitMinutes = [int]$args; $Script:State.overrideToday=$false; Save-State $Script:State -Force; Invoke-Tick; $res.text = "Limit nastaveny.`n`n$(Limit-Text)" }
        else { $res.ok=$false; $res.text='pouzitie: limit_set <minuty>' }
      }
      'addtime' {
        if ($args -match '^\d+$') { $Script:State.bonusMinutes += [int]$args; Save-State $Script:State -Force; Invoke-Tick; $res.text = "Pridane $args min.`n`n$(Limit-Text)" }
        else { $res.ok=$false; $res.text='pouzitie: addtime <minuty>' }
      }
      'block'   { $Script:State.manualBlock=$true; Save-State $Script:State -Force; Invoke-Tick; $res.text="PC zablokovane.`n`n$(Limit-Text)" }
      'unblock' { $Script:State.manualBlock=$false; $Script:State.overrideToday=$true; Save-State $Script:State -Force; Invoke-Tick; $res.text="PC odblokovane (do polnoci).`n`n$(Limit-Text)" }
      'tick' {
        # Ucet zdielaneho casu vedie Home Assistant. Posle nam strop na dnes
        # (uz po odpocitani minut na tablete), my vratime skutocnu spotrebu.
        # Bonus nulujeme - HA ho ma zapocitany uz v tom stope.
        #
        # PORADIE JE ZAMERNE: najprv lacne prevzatie stropu a seedu, potom
        # odpoved. Keby bol Send prvy, pri uz zavretom spojeni (HA po timeoute
        # - v logu su take pripady) by vynimka preskocila zvysok a agent by
        # ostal na starom strope. Ziadne Get-Process ani Start-Process tu
        # nie su - to je cela pointa zmeny.
        $st = $Script:State
        # ^[1-9]\d*$, nie ^\d+$: "0" alebo "-1" znamena, ze HA strop nepozna
        # (HA nema minuty tabletu - napr. nebezi most TimeLimit). Vtedy si
        # drzime posledny znamy - inak by agent dietatu oznamil, ze cas sa
        # minul. Telegramove limit_set nulu nadalej povoluje, to je vedomy
        # prikaz rodica.
        if ($args -match '^[1-9]\d*$') {
          $nl = [int]$args
          if ([int]$st.limitMinutes -ne $nl -or [int]$st.bonusMinutes -ne 0) {
            $st.limitMinutes = $nl; $st.bonusMinutes = 0
            Save-State $st -Force
          }
        }
        # Seed po strate stavu (vsetky poistky su v Accept-Seed).
        if ($Script:StateLost -and $null -ne $d.used_min -and "$($d.used_min)" -match '^\d+$') {
          Accept-Seed ([int]$d.used_min)
        }
        # Odpoved zo snimky - ziadne I/O, ziadne merania, ziadny spawn.
        $sn = $Script:Snap
        $res.used       = [int]$sn.used
        $res.active     = [bool]$sn.active
        $res.allowed    = [int]($st.limitMinutes + $st.bonusMinutes)
        $res.needs_seed = [bool]$Script:StateLost
        # Denne maximum, nie "od posledneho tiku": prave tik s velkym
        # meskanim casto padne na timeout, takze by sa spicka stratila.
        $res.lag_max    = [int]$Script:LagMaxToday
        $res.version    = $AgentVersion
        # idle_sec/age_sec posielame LEN z platnej snimky. Ked chybaju, HA si
        # necha predoslu znacku vstupu - to je bezpecnejsie nez vymysel.
        if ($sn.valid) {
          $age = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [long]$sn.ts
          if ($age -lt 0) { $age = 0 }        # hodiny skocili dozadu (NTP po boote)
          $res.idle_sec = [int]$sn.idle
          $res.age_sec  = [int]$age
        }
        # $res.text sa zamerne nepocita - HA ho pri tiku necita a Limit-Text
        # je zbytocna praca v ceste odpovede.
        Send $ctx 200 $res
        return
      }
      default { $res.ok=$false; $res.text="neznamy prikaz: $action" }
    }
    Send $ctx 200 $res
    return
  }
  $ctx.Response.StatusCode = 404; $ctx.Response.Close()
}

# ---- hlavna async slucka: obsluha requestov + tik casovaca ----
Invoke-Tick
# Hned po starte, nech HA nemusi cakat 30 s na to, ze agent zije.
Send-Push -Force
while ($listener.IsListening) {
  try {
    $ctxTask = $listener.GetContextAsync()
    while (-not $ctxTask.Wait($TickIntervalMs)) { Invoke-Tick; Push-IfChanged }
    $ctx = $ctxTask.Result
    try { Handle-Request $ctx } catch { Log "handle chyba: $_" WARN }
    # Bezpodmienecny tik po kazdom requeste bol zbytocna praca navyse (HA sa
    # pyta kazdu minutu, timer tika kazdych 20 s). Presnost uctovania to
    # nemeni - elapsed sa rata z hodin, nie z poctu volani.
    if (([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [long]$Script:LastTick) -ge 20) { Invoke-Tick; Push-IfChanged }
  } catch { Log "loop chyba: $_" WARN; Start-Sleep -Milliseconds 500 }
}
