<#
  notify.ps1 - Zobrazí správu na obrazovke PC ako systémovú notifikáciu (toast).
  Neblokuje prácu na PC (na rozdiel od MessageBoxu).

  Použitie:
    .\notify.ps1 -Text "Vypni to a pod von"
    .\notify.ps1 -Title "Fabrici HOME" -Text "Sprava z telefonu"
#>
param(
    [string]$Text = "",
    [string]$TextB64 = "",   # text ako base64(UTF-8) - spravna diakritika (obchadza codepage)
    [string]$Title = "Fabrici HOME"
)
if ($TextB64) { try { $Text = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($TextB64)) } catch { } }
if (-not $Text) { $Text = " " }

# 1) Skús natívny Windows 10/11 toast (WinRT)
$toastOk = $false
try {
    [void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
    [void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]

    $appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
    $xml = @"
<toast>
  <visual><binding template="ToastGeneric">
    <text>$([System.Security.SecurityElement]::Escape($Title))</text>
    <text>$([System.Security.SecurityElement]::Escape($Text))</text>
  </binding></visual>
</toast>
"@
    $doc = New-Object Windows.Data.Xml.Dom.XmlDocument
    $doc.LoadXml($xml)
    $toast = New-Object Windows.UI.Notifications.ToastNotification $doc
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
    $toastOk = $true
} catch {
    $toastOk = $false
}

# 2) Fallback: balónik pri hodinách (funguje všade)
if (-not $toastOk) {
    Add-Type -AssemblyName System.Windows.Forms
    $ni = New-Object System.Windows.Forms.NotifyIcon
    $ni.Icon = [System.Drawing.SystemIcons]::Information
    $ni.BalloonTipTitle = $Title
    $ni.BalloonTipText  = $Text
    $ni.Visible = $true
    $ni.ShowBalloonTip(10000)
    Start-Sleep -Seconds 11
    $ni.Dispose()
}

Write-Output "OK: notifikacia zobrazena"
