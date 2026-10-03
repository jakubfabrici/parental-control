<#
  volume.ps1 - Nastaví alebo zistí hlasitosť systému (užitočné pred čítaním nahlas,
  aby si nehovoril do stlmených reproduktorov).

  Použitie:
    .\volume.ps1              # vypíše aktuálnu hlasitosť
    .\volume.ps1 -Level 70    # nastaví na 70 %
    .\volume.ps1 -Unmute      # zruší stlmenie
    .\volume.ps1 -Mute
#>
param(
    [int]$Level = -1,
    [switch]$Mute,
    [switch]$Unmute
)

# Core Audio API cez P/Invoke - bez externých nástrojov
Add-Type -Language CSharp @'
using System;
using System.Runtime.InteropServices;

[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {
  int _0(); int _1(); int _2(); int _3();
  int SetMasterVolumeLevelScalar(float level, ref Guid ctx);
  int _5();
  int GetMasterVolumeLevelScalar(out float level);
  int _7(); int _8(); int _9(); int _10();
  int SetMute([MarshalAs(UnmanagedType.Bool)] bool mute, ref Guid ctx);  // vtable slot 11
  int GetMute(out bool mute);                                             // vtable slot 12
}
[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice {
  int Activate(ref Guid id, int clsCtx, IntPtr act, [MarshalAs(UnmanagedType.IUnknown)] out object dev);
}
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator {
  int _0();
  int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice ep);
}
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumeratorComObject { }

public static class Audio {
  static IAudioEndpointVolume Vol() {
    var en = (IMMDeviceEnumerator)(new MMDeviceEnumeratorComObject());
    IMMDevice dev; en.GetDefaultAudioEndpoint(0, 1, out dev);
    Guid iid = typeof(IAudioEndpointVolume).GUID;
    object o; dev.Activate(ref iid, 23, IntPtr.Zero, out o);
    return (IAudioEndpointVolume)o;
  }
  public static float Get() { float v; Vol().GetMasterVolumeLevelScalar(out v); return v * 100; }
  public static void Set(float pct) { Guid g = Guid.Empty; Vol().SetMasterVolumeLevelScalar(pct / 100f, ref g); }
  public static bool GetMute() { bool m; Vol().GetMute(out m); return m; }
  public static void SetMute(bool m) { Guid g = Guid.Empty; Vol().SetMute(m, ref g); }
}
'@

if ($Mute)   { [Audio]::SetMute($true) }
if ($Unmute) { [Audio]::SetMute($false) }
if ($Level -ge 0) {
    [Audio]::Set([Math]::Max(0, [Math]::Min(100, $Level)))
    [Audio]::SetMute($false)     # nastavenie hlasitosti automaticky zruší mute
}

$cur = [math]::Round([Audio]::Get(), 0)
$m   = if ([Audio]::GetMute()) { " (STLMENE)" } else { "" }
Write-Output "Hlasitost: $cur %$m"
