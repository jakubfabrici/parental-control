#!/usr/bin/env python3
"""PcAgent 1.0.0 -> 1.1.0: agent prestane robit pracu v ceste HTTP odpovede.

Preco (cely rozbor je v docs/VYSKUM-PREZENCIA.md):

  Agent je jednovlaknovy. Obsluha tiku dnes robi Save-State, cely Invoke-Tick
  (Get-Process LogonUI, Ensure-Unblocked, Invoke-Warnings vratane dvoch
  Start-Process) a az potom odpovie. Home Assistant ma timeout, takze kazde
  zaseknutie slucky = zahodena odpoved = HA nevie, ci dieta pri PC sedi.
  Dolozene cakania requestu vo fronte: 12-14 s, ~16 s, a 37 s medzi dvoma
  riadkami tej istej obsluhy (varovanie so Start-Process).

  Druhy problem: Save-State = Set-Content + Move-Item bez flushu na disk.
  Po tvrdom reste ostal neparsovatelny subor (28. 8. a 6. 9. 2026) a agent
  nabehol s usedSeconds = 0. Naposledy to znamenalo 154 -> 0 minut.

Zmeny:

  A1  tick odpoveda zo snimky (ziadne I/O), strop a seed sa preberu pred
      odpovedou, lebo po zavretom spojeni by sa uz kod za Send nevykonal.
  A2  po requeste sa Invoke-Tick vola len ked od posledneho ubehlo 20 s.
  A3  Invoke-Tick plni snimku (ts/used/active/idle/valid), pocita neorezane
      meskanie slucky a drzi jeho denne maximum (lag_max pre HA).
  A4  Save-State: FileStream + Flush($true), .bak az po overenom zapise,
      throttling 60 s (-Force pre kriticke zapisy). Load-State: kontrola
      prazdneho/bieleho suboru, povinnych poli a rozsahu, fallback na .bak,
      poskodeny subor sa odklada ako .bad-<stamp> (dokaz).
  A5  RunScript dociita stderr (inak deadlock pri >4 kB), timeout 15 -> 6 s,
      shutdown/restart idu fire-and-forget.
  A6  needs_seed: ked agent o svojej spotrebe nic nevie, povie to HA a raz
      prijme used_min - len v okne 600 s od startu, len nahor a najviac po
      hodnotu "kolko minut dnes vobec ubehlo" (to iste cislo strazi HA).
  A7  log: riadok na kazdy tik -> hodinovy suhrn.
  A9  agent hlasi svoju verziu (kontrola po aktualizacii z OMV).

Spustenie:  python3 patch-agent-1.1.0.py windows-remote-control/ha-agent/PcAgent.ps1
Je to idempotentne.
"""
import sys

p = sys.argv[1]
s = open(p, encoding="utf-8").read()
done = []


def swap(name, old, new):
    global s
    if new in s:
        return
    assert s.count(old) == 1, f"{name}: vzor sedi {s.count(old)}x"
    s = s.replace(old, new)
    done.append(name)


# --- A9: verzia -------------------------------------------------------------
swap(
    "verzia",
    """$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot""",
    """$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

# Verziu drzi subor VERSION vedla agenta (zapisuje ho Update-PcAgent.ps1 pri
# aktualizacii z OMV). Ked chyba, je to rucna instalacia.
$AgentVersion = try {
  $vf = Join-Path (Split-Path $root -Parent) 'VERSION'
  if (Test-Path $vf) { (Get-Content $vf -Raw).Trim() } else { '1.1.0' }
} catch { '1.1.0' }""",
)

# --- A4: durabilny zapis a tvrde nacitanie ---------------------------------
swap(
    "load-save-state",
    """function Load-State {
  if (Test-Path $StatePath) {
    try {
      $s = Get-Content $StatePath -Raw | ConvertFrom-Json
      foreach ($p in 'date','limitMinutes','bonusMinutes','usedSeconds','blocked','manualBlock','overrideToday','blockDeadline','warnedStep','warnedAt') {
        if ($null -eq $s.$p) { $s | Add-Member -NotePropertyName $p -NotePropertyValue (New-DefaultState).$p -Force }
      }
      return $s
    } catch { Log "state.json necitatelny, default: $_" WARN }
  }
  New-DefaultState
}
function Save-State($s) {
  try { $tmp = "$StatePath.tmp"; ($s | ConvertTo-Json -Compress) | Set-Content -Path $tmp -Encoding UTF8; Move-Item -Force $tmp $StatePath }
  catch { Log "Save-State chyba: $_" WARN }
}
$Script:State = Load-State""",
    """# Nacitanie stavu je tvrde: prazdny alebo biely subor vrati z ConvertFrom-Json
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
}""",
)

# --- A4: -Force na kriticke zapisy -----------------------------------------
swap(
    "force-blockdeadline",
    """    if (-not $Script:State.blockDeadline -or [long]$Script:State.blockDeadline -le 0) {
      $Script:State.blockDeadline = $now + $GraceSeconds
      Save-State $Script:State
    }""",
    """    if (-not $Script:State.blockDeadline -or [long]$Script:State.blockDeadline -le 0) {
      $Script:State.blockDeadline = $now + $GraceSeconds
      # -Force: komentar vyssie slubuje, ze deadline prezije restart. Bez
      # vynuteneho zapisu by to prvych 60 s nebola pravda a opakovany restart
      # by ho vzdy vynuloval.
      Save-State $Script:State -Force
    }""",
)

swap(
    "force-ensure-unblocked",
    """  if ([long]$Script:State.blockDeadline -ne 0) { $Script:State.blockDeadline = 0 }""",
    """  if ([long]$Script:State.blockDeadline -ne 0) { $Script:State.blockDeadline = 0; $Script:Dirty = $true }""",
)

# --- A6 + varovania: nulovy strop nesmie nic vyhlasit ----------------------
swap(
    "warn-cap-guard",
    """    if (-not $Script:LastActive) { return }          # nikto pri PC nie je, netreba
    $cap = [int]$s.limitMinutes + [int]$s.bonusMinutes""",
    """    if (-not $Script:LastActive) { return }          # nikto pri PC nie je, netreba
    $cap = [int]$s.limitMinutes + [int]$s.bonusMinutes
    # Nulovy strop = nevieme, kolko ma dnes k dispozicii (napr. Family Link
    # data vypadli a HA poslala -1). Vtedy sa NEVYHLASUJE nic - inak by dieta
    # dostalo "cas sa minul" len preto, ze zlyhalo cudzie API.
    if ($cap -le 0) { return }""",
)

swap(
    "warn-dirty",
    """    $s.warnedAt = $teraz
    $text = $WarnMessages[$step]
    if (-not $text) { return }""",
    """    $s.warnedAt = $teraz
    $text = $WarnMessages[$step]
    if (-not $text) { $Script:Dirty = $true; return }
    # Odvysielane varovanie je fakt, ktory ma prezit restart (nastava najviac
    # 5x denne, takze vynuteny zapis nic nestoji).
    Save-State $s -Force""",
)

swap(
    "warn-dirty-2",
    """    if ($remain -gt [int]$s.warnedStep) { $s.warnedStep = 9999 }""",
    """    if ($remain -gt [int]$s.warnedStep) { $s.warnedStep = 9999; $Script:Dirty = $true }""",
)

# --- A3: snimka, meskanie, Dirty -------------------------------------------
swap(
    "tick-snimka",
    """    $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    if ($null -eq $Script:LastTick) { $Script:LastTick = $now }
    $elapsed = [int]($now - $Script:LastTick); if ($elapsed -lt 0){$elapsed=0}; if ($elapsed -gt 90){$elapsed=90}
    $Script:LastTick = $now""",
    """    $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    if ($null -eq $Script:LastTick) { $Script:LastTick = $now }
    # $lagRaw je NEorezany rozdiel - na diagnostiku. $elapsed sa orezava na
    # 90 s, aby jeden dlhy vypadok nepripocital hodinu spotreby.
    $lagRaw = [int]($now - $Script:LastTick); if ($lagRaw -lt 0) { $lagRaw = 0 }
    $elapsed = $lagRaw; if ($elapsed -gt 90){$elapsed=90}
    $Script:LastTick = $now
    # Nominal je 20 s, prah 30 s = 1,5x nominal. Kazde taketo meskanie je
    # kandidat na zahodeny tik v HA, preto sa hlasi aj do odpovede (lag_max).
    if ($lagRaw -gt 30) { Log "slucka meskala $lagRaw s (ocakavanych ~20 s)" WARN }
    if ($lagRaw -gt $Script:LagMaxToday) { $Script:LagMaxToday = $lagRaw }""",
)

swap(
    "tick-koniec",
    """    $blockNow = [bool]$s.manualBlock
    # Meriame aj nad ramec limitu, nech je vidiet o kolko ho prekrocila.
    if (-not $blockNow) { $s.usedSeconds += $aktivnychSek }
    $s.blocked = $blockNow
    if ($blockNow) { Ensure-Blocked } else { Ensure-Unblocked }
    Invoke-Warnings $s
    Save-State $s
  } catch { Log "Tick chyba: $_" WARN }
}""",
    """    $blockNow = [bool]$s.manualBlock
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
}""",
)

swap(
    "tick-novy-den",
    """      $s.date = $today; $s.usedSeconds = 0; $s.bonusMinutes = 0
      $s.manualBlock = $false; $s.overrideToday = $false; $s.blocked = $false; $s.blockDeadline = 0
      $s.warnedStep = 9999; $s.warnedAt = 0""",
    """      $s.date = $today; $s.usedSeconds = 0; $s.bonusMinutes = 0
      $s.manualBlock = $false; $s.overrideToday = $false; $s.blocked = $false; $s.blockDeadline = 0
      $s.warnedStep = 9999; $s.warnedAt = 0
      $Script:LagMaxToday = 0
      $Script:Dirty = $true; Save-State $s -Force""",
)

# --- A5: RunScript ----------------------------------------------------------
swap(
    "runscript",
    """function RunScript($name,[string[]]$a=@(),[int]$TimeoutSec=15){""",
    """# TimeoutSec 6, nie 15: volume.ps1 aj status.ps1 bezia normalne pod sekundu a
# v logu su len uplne zaseknutia. 6 s je bohata rezerva nad normalom a hlboko
# pod 25 s timeoutom, ktory ma HA na rest_command.pc_cmd.
function RunScript($name,[string[]]$a=@(),[int]$TimeoutSec=6){""",
)

swap(
    "runscript-stderr",
    """    [void]$proc.Start(); $outTask = $proc.StandardOutput.ReadToEndAsync()
    if ($proc.WaitForExit($TimeoutSec * 1000)) { ($outTask.Result).TrimEnd() }
    else { try { $proc.Kill() } catch {}; Log "RunScript $name timeout" WARN; "chyba: $name trval prilis dlho" }""",
    """    [void]$proc.Start()
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
    else { try { $proc.Kill() } catch {}; Log "RunScript $name timeout ($TimeoutSec s)" WARN; "chyba: $name trval prilis dlho" }""",
)

swap(
    "shutdown-restart-async",
    """      'shutdown' { $dl= if($d.delay){[int]$d.delay}else{5}; RunScript 'shutdown.ps1' @('-Delay',"$dl") | Out-Null; $res.text="vypinam o $dl s" }
      'restart'  { $dl= if($d.delay){[int]$d.delay}else{5}; RunScript 'restart.ps1' @('-Delay',"$dl") | Out-Null; $res.text="restart o $dl s" }""",
    """      # Vystup nikto necita (| Out-Null), takze niet preco kvoli nim blokovat
      # slucku - a prave vypinanie po limite je najhorsi mozny cas na to.
      'shutdown' { $dl= if($d.delay){[int]$d.delay}else{5}; Start-ScriptFile 'shutdown.ps1' @('-Delay',"$dl") | Out-Null; $res.text="vypinam o $dl s" }
      'restart'  { $dl= if($d.delay){[int]$d.delay}else{5}; Start-ScriptFile 'restart.ps1' @('-Delay',"$dl") | Out-Null; $res.text="restart o $dl s" }""",
)

# --- A7: log bez riadku na kazdy tik ---------------------------------------
swap(
    "log-tick",
    """    $action = "$($d.action)".ToLower(); $args = "$($d.args)"
    Log "cmd: $action $args\"""",
    """    $action = "$($d.action)".ToLower(); $args = "$($d.args)"
    # Tik chodi kazdu minutu (1440 riadkov denne) - loguje sa len hodinovy
    # suhrn z Invoke-Tick. Vsetko ostatne je udalost, ktora ma byt v logu.
    if ($action -ne 'tick') { Log "cmd: $action $args" }""",
)

# --- A9: verzia v /ping a v state ------------------------------------------
swap(
    "ping-verzia",
    """    Send $ctx 200 @{ ok=$true; host=$env:COMPUTERNAME; session=(Get-Process -Id $PID).SessionId; blocked=$Script:State.blocked }""",
    """    Send $ctx 200 @{ ok=$true; host=$env:COMPUTERNAME; session=(Get-Process -Id $PID).SessionId; blocked=$Script:State.blocked; version=$AgentVersion }""",
)

# --- A1: tick odpoveda zo snimky -------------------------------------------
swap(
    "tick-akcia",
    """      'tick' {
        # Ucet zdielaneho casu vedie Home Assistant. Posle nam strop na dnes
        # (uz po odpocitani minut na tablete), my vratime skutocnu spotrebu.
        # Bonus nulujeme - HA ho ma zapocitany uz v tom stope.
        if ($args -match '^\\d+$') {
          $Script:State.limitMinutes = [int]$args
          $Script:State.bonusMinutes = 0
          Save-State $Script:State
        }
        Invoke-Tick
        $st = $Script:State
        $res.used    = [int][math]::Floor($st.usedSeconds / 60)
        $res.active  = [bool]$Script:LastActive
        $res.allowed = [int]($st.limitMinutes + $st.bonusMinutes)
        $res.text    = Limit-Text
      }""",
    """      'tick' {
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
        # ^[1-9]\\d*$, nie ^\\d+$: "0" alebo "-1" znamena, ze HA strop nepozna
        # (vypadli data z Family Link). Vtedy si drzime posledny znamy - inak
        # by agent dietatu oznamil, ze cas sa minul. Telegramove limit_set
        # nulu nadalej povoluje, to je vedomy prikaz rodica.
        if ($args -match '^[1-9]\\d*$') {
          $nl = [int]$args
          if ([int]$st.limitMinutes -ne $nl -or [int]$st.bonusMinutes -ne 0) {
            $st.limitMinutes = $nl; $st.bonusMinutes = 0
            Save-State $st -Force
          }
        }
        # Seed po strate stavu (vsetky poistky su v Accept-Seed).
        if ($Script:StateLost -and $null -ne $d.used_min -and "$($d.used_min)" -match '^\\d+$') {
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
      }""",
)

# --- A4: -Force na zvysne kriticke zapisy ----------------------------------
for name, old, new in [
    ("force-limit-set",
     """        if ($args -match '^\\d+$') { $Script:State.limitMinutes = [int]$args; $Script:State.overrideToday=$false; Save-State $Script:State; Invoke-Tick;""",
     """        if ($args -match '^\\d+$') { $Script:State.limitMinutes = [int]$args; $Script:State.overrideToday=$false; Save-State $Script:State -Force; Invoke-Tick;"""),
    ("force-addtime",
     """        if ($args -match '^\\d+$') { $Script:State.bonusMinutes += [int]$args; Save-State $Script:State; Invoke-Tick;""",
     """        if ($args -match '^\\d+$') { $Script:State.bonusMinutes += [int]$args; Save-State $Script:State -Force; Invoke-Tick;"""),
    ("force-block",
     """      'block'   { $Script:State.manualBlock=$true; Save-State $Script:State; Invoke-Tick;""",
     """      'block'   { $Script:State.manualBlock=$true; Save-State $Script:State -Force; Invoke-Tick;"""),
    ("force-unblock",
     """      'unblock' { $Script:State.manualBlock=$false; $Script:State.overrideToday=$true; Save-State $Script:State; Invoke-Tick;""",
     """      'unblock' { $Script:State.manualBlock=$false; $Script:State.overrideToday=$true; Save-State $Script:State -Force; Invoke-Tick;"""),
]:
    swap(name, old, new)

# --- A2: po requeste netikat bezpodmienecne --------------------------------
swap(
    "slucka",
    """    $ctx = $ctxTask.Result
    try { Handle-Request $ctx } catch { Log "handle chyba: $_" WARN }
    Invoke-Tick""",
    """    $ctx = $ctxTask.Result
    try { Handle-Request $ctx } catch { Log "handle chyba: $_" WARN }
    # Bezpodmienecny tik po kazdom requeste bol zbytocna praca navyse (HA sa
    # pyta kazdu minutu, timer tika kazdych 20 s). Presnost uctovania to
    # nemeni - elapsed sa rata z hodin, nie z poctu volani.
    if (([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [long]$Script:LastTick) -ge 20) { Invoke-Tick }""",
)

swap(
    "start-log",
    """Log "Agent bezi na http://+:$Port/  scripts=$ScriptsDir  session=$((Get-Process -Id $PID).SessionId)  limit=$($Script:State.limitMinutes)min\"""",
    """Log "Agent $AgentVersion bezi na http://+:$Port/  scripts=$ScriptsDir  session=$((Get-Process -Id $PID).SessionId)  limit=$($Script:State.limitMinutes)min  seed=$($Script:NeedsSeed)\"""",
)

open(p, "w", encoding="utf-8").write(s)
print("hotovo:", ", ".join(done) if done else "uz bolo zaplatane")
