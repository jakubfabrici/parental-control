# screenshot.ps1 - Spraví snímku celej obrazovky (všetky monitory) a uloží ju.
# Vráti cestu k súboru na stdout (posledný riadok) - používa to aj Telegram bot.
param([string]$OutDir = "$env:TEMP\remote-shots")

# DPI awareness - inak pri skalovani Windows (napr. 125%) odfoti len vyrez.
try {
    Add-Type -TypeDefinition @"
using System.Runtime.InteropServices;
public static class DpiAwareShot {
    [DllImport("shcore.dll")] static extern int SetProcessDpiAwareness(int value);
    [DllImport("user32.dll")] static extern bool SetProcessDPIAware();
    public static void Enable(){ try { SetProcessDpiAwareness(2); } catch { try { SetProcessDPIAware(); } catch {} } }
}
"@ -ErrorAction SilentlyContinue
    [DpiAwareShot]::Enable()
} catch { }

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$path  = Join-Path $OutDir "shot_$stamp.png"

$bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$gfx = [System.Drawing.Graphics]::FromImage($bmp)
$gfx.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
$gfx.Dispose(); $bmp.Dispose()

Write-Output $path
