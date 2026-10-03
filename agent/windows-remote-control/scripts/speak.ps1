<#
  speak.ps1 - Prečíta text nahlas cez reproduktory PC (Windows TTS / SAPI).

  Použitie:
    .\speak.ps1 -Text "Ahoj, som doma o hodinu"
    .\speak.ps1 -TextB64 <base64 UTF-8>              # text bezpecne voci codepage
    .\speak.ps1 -Text "Pozor" -SpeakVolume 70        # docasne 70%, po dohovoreni vrati povodnu
    .\speak.ps1 -ListVoices                          # vypíše nainštalované hlasy

  Slovensky hlas: "Microsoft Filip" (sk-SK). Ak nie je, cesky cita SK dobre.
#>
param(
    [string]$Text = "",
    [string]$TextB64 = "",   # text ako base64(UTF-8) - obchadza codepage mrsenie diakritiky na prikazovom riadku
    [int]$Rate = 0,          # -10 (pomaly) až 10 (rýchlo)
    [int]$Volume = 100,      # 0-100 (hlasitost samotneho SAPI syntetizatora)
    [int]$SpeakVolume = -1,  # ak >=0: docasne nastav SYSTEMOVU hlasitost na tuto uroven, po dohovoreni vrat povodnu
    [string]$Voice = "",     # časť názvu hlasu, napr. "Filip" alebo "Zira"
    [switch]$ListVoices
)

if ($TextB64) { try { $Text = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($TextB64)) } catch { } }

# ---- systemova hlasitost cez Core Audio (spravne vtable poradie: SetMute=11, GetMute=12) ----
Add-Type -Language CSharp @"
using System.Runtime.InteropServices;
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAEV {
  int _0(); int _1(); int _2(); int _3();
  int SetMasterVolumeLevelScalar(float level, ref System.Guid ctx);
  int _5();
  int GetMasterVolumeLevelScalar(out float level);
  int _7(); int _8(); int _9(); int _10();
  int SetMute([MarshalAs(UnmanagedType.Bool)] bool mute, ref System.Guid ctx);
  int GetMute(out bool mute);
}
[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMD { int Activate(ref System.Guid id, int clsCtx, System.IntPtr act, [MarshalAs(UnmanagedType.IUnknown)] out object dev); }
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDE { int _0(); int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMD ep); }
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDEC { }
public static class Vol {
  static IAEV Get() {
    var en = (IMMDE)(new MMDEC()); IMMD dev; en.GetDefaultAudioEndpoint(0, 1, out dev);
    System.Guid iid = typeof(IAEV).GUID; object o; dev.Activate(ref iid, 23, System.IntPtr.Zero, out o); return (IAEV)o;
  }
  public static int GetV(){ float v; Get().GetMasterVolumeLevelScalar(out v); return (int)(v*100+0.5f); }
  public static void SetV(int pct){ System.Guid g = System.Guid.Empty; Get().SetMasterVolumeLevelScalar(pct/100f, ref g); }
  public static bool GetM(){ bool m; Get().GetMute(out m); return m; }
  public static void SetM(bool m){ System.Guid g = System.Guid.Empty; Get().SetMute(m, ref g); }
}
"@ -ErrorAction SilentlyContinue

Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer

if ($ListVoices) {
    $synth.GetInstalledVoices() | ForEach-Object { $i = $_.VoiceInfo; "{0}  [{1}]  {2}" -f $i.Name, $i.Culture.Name, $i.Gender }
    $synth.Dispose(); exit 0
}

if ([string]::IsNullOrWhiteSpace($Text)) {
    Write-Error "Chyba text. Použitie: .\speak.ps1 -Text 'ahoj'"; $synth.Dispose(); exit 1
}

# Výber hlasu: explicitný -> slovenský -> český -> default
try {
    $voices = $synth.GetInstalledVoices() | Where-Object { $_.Enabled }
    $pick = $null
    if ($Voice) { $pick = $voices | Where-Object { $_.VoiceInfo.Name -like "*$Voice*" } | Select-Object -First 1 }
    if (-not $pick) { $pick = $voices | Where-Object { $_.VoiceInfo.Culture.Name -like 'sk*' } | Select-Object -First 1 }
    if (-not $pick) { $pick = $voices | Where-Object { $_.VoiceInfo.Culture.Name -like 'cs*' } | Select-Object -First 1 }
    if ($pick) { $synth.SelectVoice($pick.VoiceInfo.Name) }
} catch { Write-Warning "Hlas sa nepodarilo nastaviť: $_" }

$synth.Rate   = [Math]::Max(-10, [Math]::Min(10, $Rate))
$synth.Volume = [Math]::Max(0, [Math]::Min(100, $Volume))

# uloz povodnu systemovu hlasitost/mute, nastav docasnu, po dohovoreni vrat spat
$origVol = $null; $origMute = $null
if ($SpeakVolume -ge 0) {
    try { $origVol = [Vol]::GetV(); $origMute = [Vol]::GetM(); [Vol]::SetM($false); [Vol]::SetV([Math]::Max(0,[Math]::Min(100,$SpeakVolume))) } catch { }
}

try { $synth.Speak($Text) } finally {
    $synth.Dispose()
    if ($SpeakVolume -ge 0 -and $null -ne $origVol) {
        try { [Vol]::SetV($origVol); if ($origMute) { [Vol]::SetM($true) } } catch { }
    }
}

Write-Output "OK: precitane (hlas: $(if($pick){$pick.VoiceInfo.Name}else{'default'}))"
