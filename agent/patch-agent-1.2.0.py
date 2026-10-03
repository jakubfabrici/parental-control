#!/usr/bin/env python3
"""PcAgent 1.1.0 -> 1.2.0: agent hlasi sam, uz necaka na otazku z HA.

Preco:

  Doterajsi model bol dopyt - HA sa kazdu minutu spytala a cakala na odpoved.
  Na Core2 Duo z roku 2008, kde hra v prehliadaci vytazi obe jadra, agent
  obcas neodpovie vcas a HA zahodi aj to, co uz bolo zmerane. Predlzovanie
  timeoutu je len posuvanie hranice; podstata je, ze meranie a jeho doruceni e
  su zviazane do jednej synchronnej vymeny.

  Ked hlasi agent sam, ziadne preteky nie su. Posle, ked stihne - o sekundu
  alebo o polminuty neskor, na nameranej hodnote to nic nemeni. Zmeskany beh
  uz nie je strata dat, len oneskorenie.

Zmeny:

  P1  Send-Push: POST na webhook v HA s tym, co agent prave vie (used,
      idle_sec, age_sec, active, allowed, version, needs_seed, lag_max).
      Bezi v casovacovej vetve slucky, NIE v ceste HTTP odpovede.
  P2  kadencia: kazdych 30 s, a navyse hned, ked sa zmeni 'active' (aby
      prezencia v HA nemeskala) alebo ked agent prave nastartoval.
  P3  strop si agent pyta sam tym, ze v hlaseni posiela, na aky strop veri.
      Ked sa lisi od HA, HA mu posle novy cez limit_set. V ustalenom stave
      teda po sieti nechodi nic navyse.
  P4  akcia 'tick' ostava - HA ju pouziva ako zachrannu siet, ked hlasenie
      nechodi. Protokol sa teda nelami.

  Adresa webhooku je v config.json (PushUrl) - v repozitari nie je a nesmie
  byt, je to tajomstvo rovnako ako token.

Spustenie:  python3 patch-agent-1.2.0.py windows-remote-control/ha-agent/PcAgent.ps1
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


# --- verzia -----------------------------------------------------------------
swap(
    "verzia",
    """  if (Test-Path $vf) { (Get-Content $vf -Raw).Trim() } else { '1.1.0' }
} catch { '1.1.0' }""",
    """  if (Test-Path $vf) { (Get-Content $vf -Raw).Trim() } else { '1.2.0' }
} catch { '1.2.0' }""",
)

# --- P1: konfiguracia hlasenia ---------------------------------------------
swap(
    "config-push",
    """$IdleThresholdMs = 60000    # 1 min bez vstupu = nepocita sa (aktivny cas, nie PC-on cas)
$TickIntervalMs  = 20000    # tik kazdych 20s""",
    """$IdleThresholdMs = 60000    # 1 min bez vstupu = nepocita sa (aktivny cas, nie PC-on cas)
$TickIntervalMs  = 20000    # tik kazdych 20s
# Kam hlasit. Cela adresa vratane webhook id je v config.json - je to
# tajomstvo, do repozitara nepatri. Ked chyba, agent sa sprava ako 1.1.0
# a caka na otazky z HA.
$PushUrl = "$($cfg.PushUrl)"
$PushIntervalSec = 30       # 30 s: dvojnasobok kadencie, ktoru HA potrebuje""",
)

# --- P1: samotne hlasenie ---------------------------------------------------
swap(
    "funkcia-push",
    """function Limit-Text {""",
    """# Hlasenie do HA. Bezi v casovacovej vetve slucky, nikdy nie v ceste HTTP
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

function Limit-Text {""",
)

# --- P1: premenne -----------------------------------------------------------
swap(
    "premenne-push",
    """$Script:TickCount    = 0        # pocitadlo pre hodinovy suhrn v logu
$Script:HourMark     = 0""",
    """$Script:TickCount    = 0        # pocitadlo pre hodinovy suhrn v logu
$Script:HourMark     = 0
$Script:LastPush     = 0        # kedy naposledy odislo hlasenie do HA
$Script:PushFails    = 0        # kolko hlaseni po sebe zlyhalo
$Script:LastPushActive = $false # aku prezenciu uz HA vie""",
)

# --- P2: volanie zo slucky --------------------------------------------------
swap(
    "slucka-push",
    """    $ctxTask = $listener.GetContextAsync()
    while (-not $ctxTask.Wait($TickIntervalMs)) { Invoke-Tick }""",
    """    $ctxTask = $listener.GetContextAsync()
    while (-not $ctxTask.Wait($TickIntervalMs)) { Invoke-Tick; Push-IfChanged }""",
)

swap(
    "slucka-push-2",
    """    if (([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [long]$Script:LastTick) -ge 20) { Invoke-Tick }""",
    """    if (([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [long]$Script:LastTick) -ge 20) { Invoke-Tick; Push-IfChanged }""",
)

# --- P2: prve hlasenie hned po starte ---------------------------------------
swap(
    "start-push",
    """# ---- hlavna async slucka: obsluha requestov + tik casovaca ----
Invoke-Tick""",
    """# ---- hlavna async slucka: obsluha requestov + tik casovaca ----
Invoke-Tick
# Hned po starte, nech HA nemusi cakat 30 s na to, ze agent zije.
Send-Push -Force""",
)

open(p, "w", encoding="utf-8").write(s)
print("hotovo:", ", ".join(done) if done else "uz bolo zaplatane")
