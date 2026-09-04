# ============================================================================
# Druha uprava PcAgent.ps1 - dve veci, ktore Jakub nahlasil z prevadzky.
#
# 1. PRESNE MERANIE NECINNOSTI
#    Doteraz: ked bol vstup za poslednu minutu, pripocital sa CELY interval
#    (20 s). Cize aj ked sa myslo pohlo raz za 55 sekund, ratal sa cely cas.
#    Teraz sa z intervalu odrata, ako dlho je uz ticho - ked sa nehybalo
#    mysou ani nepisalo cely interval, nepripocita sa nic.
#
# 2. VAROVANIA NESPAMUJU
#    Stalo sa, ze do 20 sekund odznelo "zostava 5 minut" a hned "posledna
#    minuta". Nebola to chyba pocitania: strop pre PC posiela Home Assistant
#    a je to rozpocet minus cas na tablete - ked Simonka medzitym hrala na
#    tablete, strop skokovo klesol a agent poslusne ohlasil oba stupne.
#    Teraz medzi dvoma varovaniami musia uplynut aspon 2 minuty; preskocene
#    stupne sa ticho odpisu. Vynimka je nula, tu treba povedat vzdy.
#
# Skript je idempotentny: co uz je upravene, preskoci.
# ============================================================================

$ErrorActionPreference = 'Stop'
$dir = 'D:\Users\kuko\remote-control\windows-remote-control\ha-agent'
$p   = Join-Path $dir 'PcAgent.ps1'

Copy-Item $p ($p + '.bak-' + (Get-Date -Format 'yyyyMMdd_HHmmss')) -Force
$s = [IO.File]::ReadAllText($p)
$done = @(); $skip = @(); $fail = @()

function Try-Swap([string]$name, [string]$old, [string]$new) {
  if ($script:s.Contains($new)) { $script:skip += $name; return }
  if ($script:s.Contains($old)) { $script:s = $script:s.Replace($old, $new); $script:done += $name; return }
  $script:fail += $name
}

# --- 1. cas posledneho varovania do stavu ----------------------------------
Try-Swap 'state-default' @'
blockDeadline = 0; warnedStep = 9999
'@ @'
blockDeadline = 0; warnedStep = 9999; warnedAt = 0
'@

Try-Swap 'state-load' @'
'overrideToday','blockDeadline','warnedStep') {
'@ @'
'overrideToday','blockDeadline','warnedStep','warnedAt') {
'@

Try-Swap 'day-reset' @'
      $s.warnedStep = 9999
'@ @'
      $s.warnedStep = 9999; $s.warnedAt = 0
'@

# --- 2. presne meranie necinnosti ------------------------------------------
Try-Swap 'meranie' @'
    $idleMs = try { [IdleInfo]::Ms() } catch { 0 }
    # aktivny cas = je vstup do 1 min A session nie je zamknuta (LogonUI = lock screen).
    # Monitor v uspornom rezime = dlha necinnost -> idle prekroci prah -> aj tak sa nerata.
    $locked = [bool](Get-Process LogonUI -ErrorAction SilentlyContinue)
    $active = ($idleMs -lt $IdleThresholdMs) -and (-not $locked)
    $Script:LastIdleMs = $idleMs
    $Script:LastActive = $active
'@ @'
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
'@

Try-Swap 'zapocitanie' @'
    # Meriame aj nad ramec limitu, nech je vidiet o kolko ho prekrocila.
    if ($active) { $s.usedSeconds += $elapsed }
'@ @'
    # Meriame aj nad ramec limitu, nech je vidiet o kolko ho prekrocila.
    if (-not $blockNow) { $s.usedSeconds += $aktivnychSek }
'@

# --- 3. varovania s odstupom -----------------------------------------------
Try-Swap 'throttle' @'
    if ([int]$s.warnedStep -le $step) { return }     # tento stupen uz odznel
    $s.warnedStep = $step
'@ @'
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
'@

# --- 4. v prehlade nech je vidiet, kolko sa naozaj rata --------------------
Try-Swap 'prehlad' @'
  $ct = if ($Script:LastActive) { "prave sa pocita (aktivny)" } else { "nepocita sa (necinny " + [int]([math]::Round($Script:LastIdleMs/60000)) + " min)" }
'@ @'
  $ct = if ($Script:LastActive) { "prave sa pocita (necinny " + [int]([math]::Round($Script:LastIdleMs/1000)) + " s)" } else { "nepocita sa (necinny " + [int]([math]::Round($Script:LastIdleMs/60000)) + " min)" }
'@

if ($fail.Count) {
  Write-Host ("NEUPRAVENE (vzor nesedi): " + ($fail -join ', '))
  Write-Host "Subor ostal nezmeneny."
  exit 1
}

$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseInput($s, [ref]$null, [ref]$errors)
if ($errors -and $errors.Count) {
  Write-Host "SYNTAKTICKA CHYBA, nezapisujem:"
  $errors | ForEach-Object { Write-Host ("  " + $_.Message) }
  exit 1
}

[IO.File]::WriteAllText($p, $s, (New-Object Text.UTF8Encoding($false)))
Write-Host ("UPRAVENE: " + ($done -join ', '))
if ($skip.Count) { Write-Host ("UZ BOLO: " + ($skip -join ', ')) }
Write-Host "OK"
