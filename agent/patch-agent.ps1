# ============================================================================
# Uprava PcAgent.ps1 pre zdielany cas s tabletom.
#
# 1. Vycerpany limit UZ NEBLOKUJE PC. Blokuje sa len na vyslovny pokyn rodica
#    (akcia 'block' z Telegramu). Dieta sa ma zastavit samo.
# 2. Cas sa meria dalej aj po prekroceni limitu, nech je vidiet o kolko.
# 3. Varovania dietatu 30/15/5/1/0 min - notifikacia + nahlas, kazdy stupen
#    raz za den. Texty su vo warnmsg.txt (UTF-8), lebo PS 5.1 by diakritiku
#    v .ps1 bez BOM zmrsil - rovnaky trik ako pri blockmsg.txt.
# 4. Nova akcia 'tick': Home Assistant posle strop na dnes (uz po odpocitani
#    minut na tablete) a dostane spat skutocnu spotrebu + ci niekto pri PC je.
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

# --- 1. novy udaj v stave: pokial sme uz varovali ---------------------------
Try-Swap 'state-default' @'
usedSeconds = 0; blocked = $false; manualBlock = $false; overrideToday = $false; blockDeadline = 0
'@ @'
usedSeconds = 0; blocked = $false; manualBlock = $false; overrideToday = $false; blockDeadline = 0; warnedStep = 9999
'@

Try-Swap 'state-load' @'
foreach ($p in 'date','limitMinutes','bonusMinutes','usedSeconds','blocked','manualBlock','overrideToday','blockDeadline') {
'@ @'
foreach ($p in 'date','limitMinutes','bonusMinutes','usedSeconds','blocked','manualBlock','overrideToday','blockDeadline','warnedStep') {
'@

# --- 2. texty varovani z UTF-8 suboru --------------------------------------
Try-Swap 'warn-load' @'
New-Item -ItemType Directory -Force -Path $ShotDir | Out-Null
'@ @'
New-Item -ItemType Directory -Force -Path $ShotDir | Out-Null

# Texty varovani: "<zostavajuce minuty>|<co povedat>", jeden stupen na riadok.
$WarnMessages = @{}
$warnFile = Join-Path $root 'warnmsg.txt'
if (Test-Path $warnFile) {
  foreach ($line in (Get-Content $warnFile -Encoding UTF8)) {
    if ($line -match '^\s*(\d+)\s*\|\s*(.+?)\s*$') { $WarnMessages[[int]$Matches[1]] = $Matches[2] }
  }
}
'@

# --- 3. reset varovani na novy den -----------------------------------------
Try-Swap 'day-reset' @'
      $s.manualBlock = $false; $s.overrideToday = $false; $s.blocked = $false; $s.blockDeadline = 0
'@ @'
      $s.manualBlock = $false; $s.overrideToday = $false; $s.blocked = $false; $s.blockDeadline = 0
      $s.warnedStep = 9999
'@

# --- 4. jadro tiku: uz ziadne blokovanie podla limitu ----------------------
Try-Swap 'tick-core' @'
    $capSec = ($s.limitMinutes + $s.bonusMinutes) * 60
    $blockNow = $s.manualBlock -or (($s.usedSeconds -ge $capSec) -and -not $s.overrideToday)
    if ($active -and -not $blockNow) { $s.usedSeconds += $elapsed }
    $blockNow = $s.manualBlock -or (($s.usedSeconds -ge $capSec) -and -not $s.overrideToday)
    $s.blocked = [bool]$blockNow
    if ($blockNow) { Ensure-Blocked } else { Ensure-Unblocked }
    Save-State $s
'@ @'
    # Vycerpany limit PC NEBLOKUJE - je to zamer, nie chybajuca funkcia.
    # Simonka sa ma vediet zastavit sama; my ju len upozornime a Home
    # Assistant o prekroceni da vediet rodicom. Blok ostava uz len na
    # vyslovny pokyn rodica (akcia 'block' z Telegramu).
    $blockNow = [bool]$s.manualBlock
    # Meriame aj nad ramec limitu, nech je vidiet o kolko ho prekrocila.
    if ($active) { $s.usedSeconds += $elapsed }
    $s.blocked = $blockNow
    if ($blockNow) { Ensure-Blocked } else { Ensure-Unblocked }
    Invoke-Warnings $s
    Save-State $s
'@

# --- 5. samotne varovania --------------------------------------------------
Try-Swap 'warn-func' @'
function Invoke-Tick {
'@ @'
# Povie dietatu, kolko casu mu zostava. Nic neblokuje.
# Kazdy stupen raz za den; stav je v state.json, takze restart PC ho nevynuluje.
function Invoke-Warnings($s) {
  try {
    if (-not $Script:LastActive) { return }          # nikto pri PC nie je, netreba
    $cap = [int]$s.limitMinutes + [int]$s.bonusMinutes
    $remain = [math]::Max(0, $cap - [math]::Floor($s.usedSeconds / 60))
    if ($null -eq $s.warnedStep) { $s | Add-Member -NotePropertyName warnedStep -NotePropertyValue 9999 -Force }
    # Ked casu pribudlo (rodic pridal cez /cas_add), varujeme odznova.
    if ($remain -gt [int]$s.warnedStep) { $s.warnedStep = 9999 }
    $step = $null
    foreach ($t in @(30,15,5,1,0)) { if ($remain -le $t) { $step = $t } }
    if ($null -eq $step) { return }
    if ([int]$s.warnedStep -le $step) { return }     # tento stupen uz odznel
    $s.warnedStep = $step
    $text = $WarnMessages[$step]
    if (-not $text) { return }
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($text))
    Start-ScriptFile 'notify.ps1' @('-TextB64', $b64) | Out-Null
    Start-ScriptFile 'speak.ps1'  @('-TextB64', $b64, '-SpeakVolume','70') | Out-Null
    Log "Varovanie: zostava $remain min (stupen $step)"
  } catch { Log "Varovanie chyba: $_" WARN }
}

function Invoke-Tick {
'@

# --- 6. akcia tick pre Home Assistant --------------------------------------
Try-Swap 'tick-action' @'
      default { $res.ok=$false; $res.text="neznamy prikaz: $action" }
'@ @'
      'tick' {
        # Ucet zdielaneho casu vedie Home Assistant. Posle nam strop na dnes
        # (uz po odpocitani minut na tablete), my vratime skutocnu spotrebu.
        # Bonus nulujeme - HA ho ma zapocitany uz v tom stope.
        if ($args -match '^\d+$') {
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
      }
      default { $res.ok=$false; $res.text="neznamy prikaz: $action" }
'@

if ($fail.Count) {
  Write-Host ("NEUPRAVENE (vzor nesedi): " + ($fail -join ', '))
  Write-Host "Subor ostal nezmeneny."
  exit 1
}

# syntakticka kontrola pred zapisom - radsej nic nez rozbity agent
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
