<#
  Blocker.ps1 - TRVALY viditelny banner so spravou pri bloku (nie fullscreen -
  dieta moze medzitym ukladat pracu). Top-most, needkradne trvalo fokus, neda sa
  zavriet uzivatelom. Agent ho zabije pri odblokovani. Text z blockmsg.txt (UTF-8).
#>
$root = $PSScriptRoot
$msgFile = Join-Path $root 'blockmsg.txt'
$msg = if (Test-Path $msgFile) { (Get-Content $msgFile -Raw -Encoding UTF8).Trim() } else { 'Cas na pocitaci vyprsal. Mas 5 minut na ulozenie prace, potom sa PC vypne.' }

try {
  Add-Type -TypeDefinition @"
using System.Runtime.InteropServices;
public static class DpiB { [DllImport("shcore.dll")] static extern int SetProcessDpiAwareness(int v);
  [DllImport("user32.dll")] static extern bool SetProcessDPIAware();
  public static void E(){ try{SetProcessDpiAwareness(2);}catch{try{SetProcessDPIAware();}catch{}} } }
"@ -ErrorAction SilentlyContinue
  [DpiB]::E()
} catch {}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$form = New-Object System.Windows.Forms.Form
$form.FormBorderStyle = 'None'
$form.BackColor = [System.Drawing.Color]::FromArgb(140,20,20)
$form.TopMost = $true
$form.ShowInTaskbar = $false
$form.StartPosition = 'Manual'
# vycentrovany banner (nie cely ekran), aby sa dalo pracovat okolo neho
$wa = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
$w = [Math]::Min(1100, $wa.Width - 80); $h = 260
$form.Width = $w; $form.Height = $h
$form.Left = $wa.X + [int](($wa.Width - $w)/2)
$form.Top  = $wa.Y + [int](($wa.Height - $h)/3)

$lbl = New-Object System.Windows.Forms.Label
$lbl.Text = $msg
$lbl.ForeColor = [System.Drawing.Color]::White
$lbl.Font = New-Object System.Drawing.Font('Segoe UI', 16, [System.Drawing.FontStyle]::Bold)
$lbl.TextAlign = 'MiddleCenter'
$lbl.Dock = 'Fill'
$form.Controls.Add($lbl)

# drz navrchu (bez kradnutia fokusu - iba TopMost, ziadne Activate)
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 1000
$timer.add_Tick({ try { if (-not $form.TopMost) { $form.TopMost = $true } } catch {} })
$timer.Start()

# uzivatel ho nezavrie (Alt+F4); zabije ho iba agent
$form.add_FormClosing({ param($s,$e) if ($e.CloseReason -eq [System.Windows.Forms.CloseReason]::UserClosing) { $e.Cancel = $true } })

[System.Windows.Forms.Application]::Run($form)
