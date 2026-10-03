<#
  Update-PcAgent.ps1 - launcher agenta s automatickou aktualizaciou.

  Scheduled task HA-PcAgent spusta TENTO skript (nie PcAgent.ps1 priamo). Pri
  kazdom starte (= po zapnuti PC / prihlaseni):
    1. stiahne manifest.json z OMV (UpdateUrl v config.json),
    2. ak je tam novsia verzia, stiahne jej subory, overi SHA-256 kazdeho
       suboru a HMAC-SHA256 podpis manifestu (UpdateKey v config.json),
    3. skontroluje syntax vsetkych .ps1 (Parser), zalohuje aktualne subory,
       vymeni ich a zapise installed.json,
    4. spusti PcAgent.ps1 v tomto istom procese (ziadny dalsi rezidentny
       proces navyse - PC je slaby).

  Poistky:
    - bez siete / bez OMV -> bezi sucasna verzia, nic sa nedeje,
    - chyba hash alebo podpis -> aktualizacia sa zahodi, bezi sucasna verzia,
    - crash-loop: ked agent 3x po sebe skonci do 60 s od startu, verzia sa
      oznaci ako zla a vrati sa predchadzajuca zaloha,
    - config.json, agent.log a state.json (D:\ProgramData\PcControl) sa
      NIKDY neprepisuju - nie su v manifeste.

  Log ide do agent.log s prefixom [UPD].
#>
[CmdletBinding()]
param(
  [switch]$CheckOnly,   # len zisti, ci je nova verzia; nic nemeni, nespusta agenta
  [switch]$NoStart,     # aktualizuj (ak treba), ale agenta nespustaj
  [string]$UpdateDir = 'D:\ProgramData\PcControl\update'   # stav updatera; iny adresar = izolovany test
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot                                  # ...\ha-agent
$live = Split-Path $root -Parent                       # ...\windows-remote-control
$AgentPath = Join-Path $root 'PcAgent.ps1'
$LogFile = Join-Path $root 'agent.log'
$UpdDir = $UpdateDir
$InstalledPath = Join-Path $UpdDir 'installed.json'
$BadPath = Join-Path $UpdDir 'bad-versions.txt'
$Releases = Join-Path $UpdDir 'releases'
$Staging = Join-Path $UpdDir 'staging'
$CrashWindowSec = 60
$CrashLimit = 3
$KeepBackups = 2

function Log($m, $lvl = 'INFO') {
  $l = "{0} [{1}] [UPD] {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $lvl, $m
  Write-Host $l
  try { Add-Content $LogFile $l -Encoding UTF8 } catch { }
}

function Read-Json($path) {
  if (-not (Test-Path $path)) { return $null }
  try { return (Get-Content $path -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { return $null }
}

# Zapis cez docasny subor + flush na disk + rename. Bez flushu by po strate
# napajania mohol zostat 0 B subor (presne to sa stalo state.json agenta).
function Write-JsonDurable($path, $obj) {
  $tmp = "$path.tmp"
  $bytes = [Text.Encoding]::UTF8.GetBytes(($obj | ConvertTo-Json -Compress -Depth 6))
  $fs = [IO.File]::Open($tmp, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::None)
  try { $fs.Write($bytes, 0, $bytes.Length); $fs.Flush($true) } finally { $fs.Dispose() }
  Move-Item -Force $tmp $path
}

function Get-Sha256Hex($path) { (Get-FileHash -Path $path -Algorithm SHA256).Hash.ToLowerInvariant() }

function Get-HmacHex([byte[]]$keyBytes, [byte[]]$data) {
  $h = New-Object System.Security.Cryptography.HMACSHA256 (, $keyBytes)
  try { return ([BitConverter]::ToString($h.ComputeHash($data)) -replace '-', '').ToLowerInvariant() } finally { $h.Dispose() }
}

function Get-Http($url, [int]$timeoutSec = 8, $outFile = $null) {
  # PS 5.1: -UseBasicParsing, aby to nesahalo na IE engine
  if ($outFile) { Invoke-WebRequest -Uri $url -OutFile $outFile -UseBasicParsing -TimeoutSec $timeoutSec | Out-Null; return $null }
  $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec $timeoutSec
  return $r.Content
}

function Test-PsSyntax($path) {
  $errs = $null
  [void][System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$null, [ref]$errs)
  if ($errs -and $errs.Count) { return ($errs | ForEach-Object { $_.Message }) -join '; ' }
  return $null
}

function Test-SafeRelPath($p) {
  # manifest smie ukazovat len dovnutra live adresara (ziadne '..', ziadne absolutne cesty)
  if ([string]::IsNullOrWhiteSpace($p)) { return $false }
  if ($p -match '^[A-Za-z]:' -or $p.StartsWith('\') -or $p.StartsWith('/')) { return $false }
  if (($p -split '[\\/]') -contains '..') { return $false }
  # lokalne subory sa cez update nikdy nemenia
  $leaf = [IO.Path]::GetFileName($p).ToLowerInvariant()
  if ($leaf -in @('config.json', 'agent.log', 'state.json')) { return $false }
  return $true
}

New-Item -ItemType Directory -Force -Path $UpdDir, $Releases, $Staging | Out-Null

# ---- config ---------------------------------------------------------------
$cfg = Read-Json (Join-Path $root 'config.json')
$UpdateUrl = if ($cfg -and $cfg.UpdateUrl) { [string]$cfg.UpdateUrl } else { 'http://192.168.1.185/pc-agent/' }
if (-not $UpdateUrl.EndsWith('/')) { $UpdateUrl += '/' }
$UpdateKey = if ($cfg -and $cfg.UpdateKey) { [string]$cfg.UpdateKey } else { '' }

# ---- stav instalacie + crash-loop -----------------------------------------
$inst = Read-Json $InstalledPath
if (-not $inst) {
  # prva instalacia launchera: za verziu berieme VERSION subor, ak je, inak 0.0.0
  $vf = Join-Path $live 'VERSION'
  $v0 = if (Test-Path $vf) { (Get-Content $vf -Raw).Trim() } else { '0.0.0' }
  $inst = [pscustomobject]@{ version = $v0; previous = ''; installedAt = (Get-Date -Format 's'); lastStart = 0; quickExits = 0 }
}
foreach ($p in 'version', 'previous', 'installedAt', 'lastStart', 'quickExits') {
  if ($null -eq $inst.$p) { $inst | Add-Member -NotePropertyName $p -NotePropertyValue $(if ($p -in 'lastStart', 'quickExits') { 0 } else { '' }) -Force }
}
$bad = @(); if (Test-Path $BadPath) { $bad = @(Get-Content $BadPath | Where-Object { $_ -and $_.Trim() }) }

if (-not $CheckOnly) {
  $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
  if ([long]$inst.lastStart -gt 0 -and ($now - [long]$inst.lastStart) -lt $CrashWindowSec) { $inst.quickExits = [int]$inst.quickExits + 1 }
  else { $inst.quickExits = 0 }
  $inst.lastStart = $now

  if ([int]$inst.quickExits -ge $CrashLimit) {
    $prevDir = Join-Path $Releases $inst.previous
    if ($inst.previous -and (Test-Path $prevDir)) {
      Log "Agent verzie $($inst.version) skoncil $($inst.quickExits)x po sebe do $CrashWindowSec s - vraciam $($inst.previous)" WARN
      Get-ChildItem $prevDir -Recurse -File | ForEach-Object {
        $rel = $_.FullName.Substring($prevDir.Length).TrimStart('\')
        $dst = Join-Path $live $rel
        New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent) | Out-Null
        Copy-Item -Force $_.FullName $dst
      }
      if ($bad -notcontains $inst.version) { Add-Content $BadPath $inst.version }
      $inst.version = $inst.previous; $inst.previous = ''; $inst.quickExits = 0
    } else {
      Log "Agent skoncil $($inst.quickExits)x po sebe do $CrashWindowSec s, ale nemam zalohu na navrat" WARN
      $inst.quickExits = 0
    }
  }
  Write-JsonDurable $InstalledPath $inst
}

# ---- kontrola novej verzie ------------------------------------------------
# Manifest stahujeme ako SUROVE BAJTY (nie cez .Content): HMAC musi sediet na
# presne tych bajtoch, ktore server podpisal, bez ohladu na charset dekodovanie.
$manifestText = $null; $manBytes = $null
$manTmp = Join-Path $UpdDir 'manifest.download'
try {
  Get-Http ($UpdateUrl + 'current/manifest.json') 5 $manTmp | Out-Null
  $manBytes = [IO.File]::ReadAllBytes($manTmp)
  $manifestText = [Text.Encoding]::UTF8.GetString($manBytes)
} catch { Log "OMV nedostupne ($($UpdateUrl)): $($_.Exception.Message) - bezi verzia $($inst.version)" }

$doUpdate = $false; $man = $null
if ($manifestText) {
  try { $man = $manifestText | ConvertFrom-Json } catch { Log "manifest.json sa neda precitat: $_" WARN }
}
if ($man -and $man.version) {
  $remote = [string]$man.version
  if ($remote -eq [string]$inst.version) { Log "Verzia $remote je aktualna" }
  elseif ($bad -contains $remote) { Log "Verzia $remote je oznacena ako zla (crash-loop), preskakujem" WARN }
  else { $doUpdate = $true }
}
if ($CheckOnly) {
  [pscustomobject]@{ installed = $inst.version; remote = $(if ($man) { $man.version } else { $null }); update = $doUpdate } | ConvertTo-Json -Compress
  exit 0
}

if ($doUpdate) {
  $remote = [string]$man.version
  Log "Nova verzia $remote (mam $($inst.version)) - stahujem"
  $ok = $false
  try {
    if (-not $UpdateKey) { throw "config.json nema UpdateKey - nepodpisane aktualizacie odmietam" }
    # 1) podpis manifestu (HMAC-SHA256 nad presnymi bajtmi manifest.json)
    $sig = (Get-Http ($UpdateUrl + 'current/manifest.sig') 5).Trim().ToLowerInvariant()
    $keyBytes = [Text.Encoding]::UTF8.GetBytes($UpdateKey)
    $calc = Get-HmacHex $keyBytes $manBytes
    if ($calc -ne $sig) { throw "podpis manifestu nesedi (ocakavane $sig, vypocitane $calc)" }
    if (-not $man.files -or -not $man.base) { throw "manifest nema files/base" }
    $base = [string]$man.base; if (-not $base.EndsWith('/')) { $base += '/' }

    # 2) stiahnut do stagingu + overit SHA-256
    $stage = Join-Path $Staging $remote
    if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    foreach ($f in $man.files) {
      $rel = [string]$f.path
      if (-not (Test-SafeRelPath $rel)) { throw "manifest obsahuje nepovolenu cestu: $rel" }
      $dst = Join-Path $stage ($rel -replace '/', '\')
      New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent) | Out-Null
      $url = $UpdateUrl + $base + ($rel -replace '\\', '/')
      Get-Http $url 20 $dst | Out-Null
      $h = Get-Sha256Hex $dst
      if ($h -ne ([string]$f.sha256).ToLowerInvariant()) { throw "SHA-256 nesedi pre $rel" }
    }
    # 3) syntax vsetkych .ps1 v novej verzii
    Get-ChildItem $stage -Recurse -Filter *.ps1 | ForEach-Object {
      $e = Test-PsSyntax $_.FullName
      if ($e) { throw "syntakticka chyba v $($_.Name): $e" }
    }
    # 4) zaloha aktualnych suborov (len tych, ktore ideme prepisat) a vymena
    $bak = Join-Path $Releases $inst.version
    if (Test-Path $bak) { Remove-Item -Recurse -Force $bak }
    foreach ($f in $man.files) {
      $rel = ([string]$f.path) -replace '/', '\'
      $src = Join-Path $stage $rel
      $dst = Join-Path $live $rel
      if (Test-Path $dst) {
        $b = Join-Path $bak $rel
        New-Item -ItemType Directory -Force -Path (Split-Path $b -Parent) | Out-Null
        Copy-Item -Force $dst $b
      }
      New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent) | Out-Null
      Copy-Item -Force $src "$dst.new"
      Move-Item -Force "$dst.new" $dst
    }
    $inst.previous = $inst.version; $inst.version = $remote; $inst.installedAt = (Get-Date -Format 's'); $inst.quickExits = 0
    Write-JsonDurable $InstalledPath $inst
    Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
    # nechaj len poslednych N zaloh
    Get-ChildItem $Releases -Directory | Sort-Object LastWriteTime -Descending | Select-Object -Skip $KeepBackups | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Log "Aktualizovane $($inst.previous) -> $remote"
    $ok = $true
  } catch {
    Log "Aktualizacia na $remote zlyhala: $($_.Exception.Message) - ostava $($inst.version)" WARN
  }
}

if ($NoStart) { exit 0 }

# ---- start agenta v tomto procese -----------------------------------------
if (-not (Test-Path $AgentPath)) { Log "FATAL: chyba $AgentPath" ERROR; exit 1 }
$e = Test-PsSyntax $AgentPath
if ($e) { Log "FATAL: PcAgent.ps1 ma syntakticku chybu: $e" ERROR; exit 1 }   # exit 1 -> task ho o minutu spusti znova -> crash-loop -> navrat
$env:PCAGENT_VERSION = [string]$inst.version
& $AgentPath
exit $LASTEXITCODE
