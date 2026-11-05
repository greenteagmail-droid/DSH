# ocr-worker.ps1 - persistent helper for dsh-bionic-intelligence
# Two jobs: (1) Windows.Media.Ocr on a PNG path, (2) foreground window title.
# Line protocol on stdin:
#   T <id>            -> T <id> {"title":"...","app":"...","pid":123}
#   O <id> <path>     -> O <id> {"path":"...","text":"...","ms":123}
# Errors: E <id> <message>
# NOTE: keep this file pure ASCII - PS 5.1 reads UTF-8 without BOM as ANSI.

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Add-Type -AssemblyName System.Runtime.WindowsRuntime

$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType=WindowsRuntime]

Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class FgWin {
  [DllImport("user32.dll")]
  public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll", CharSet = CharSet.Unicode)]
  public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
  [DllImport("user32.dll")]
  public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
}
public static class WinList {
  public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)]
  public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
  [DllImport("user32.dll")]
  public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
  [DllImport("user32.dll")]
  public static extern int GetWindowLong(IntPtr hWnd, int index);
  [DllImport("dwmapi.dll")]
  public static extern int DwmGetWindowAttribute(IntPtr hWnd, int attr, out RECT r, int size);
  [DllImport("dwmapi.dll")]
  public static extern int DwmGetWindowAttribute(IntPtr hWnd, int attr, out int value, int size);
  public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
}
'@

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await($op, $type) {
  $asTask = $asTaskGeneric.MakeGenericMethod($type)
  $netTask = $asTask.Invoke($null, @($op))
  $netTask.Wait(-1) | Out-Null
  $netTask.Result
}

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if (-not $engine) { [Console]::Out.WriteLine('E 0 no-ocr-engine'); exit 1 }

function Get-Title {
  $h = [FgWin]::GetForegroundWindow()
  $sb = New-Object System.Text.StringBuilder 512
  [void][FgWin]::GetWindowText($h, $sb, 512)
  $procId = 0
  [void][FgWin]::GetWindowThreadProcessId($h, [ref]$procId)
  $app = ''
  try { $app = (Get-Process -Id $procId -ErrorAction Stop).ProcessName } catch { }
  [pscustomobject]@{ title = $sb.ToString(); app = $app; pid = [int]$procId }
}

function Get-Windows {
  # Top-level windows in EnumWindows (z-order, top first). DWM extended frame
  # bounds = what is actually on screen, not the invisible resize border.
  $list = New-Object System.Collections.ArrayList
  $procs = @{}
  $cb = [WinList+EnumProc]{
    param($h, $l)
    if (-not [WinList]::IsWindowVisible($h)) { return $true }
    $sb = New-Object System.Text.StringBuilder 512
    [void][WinList]::GetWindowText($h, $sb, 512)
    $title = $sb.ToString()
    if ([string]::IsNullOrWhiteSpace($title)) { return $true }
    $cloaked = 0
    try { [void][WinList]::DwmGetWindowAttribute($h, 14, [ref]$cloaked, 4) } catch { }
    if ($cloaked -ne 0) { return $true }
    $r = New-Object WinList+RECT
    $ok = $false
    try { $ok = ([WinList]::DwmGetWindowAttribute($h, 9, [ref]$r, 16) -eq 0) } catch { $ok = $false }
    if (-not $ok) { [void][WinList]::GetWindowRect($h, [ref]$r) }
    $w = $r.Right - $r.Left
    $ht = $r.Bottom - $r.Top
    if ($w -lt 48 -or $ht -lt 32) { return $true }
    $procId = 0
    [void][WinList]::GetWindowThreadProcessId($h, [ref]$procId)
    $key = [int]$procId
    if ($procs.ContainsKey($key)) {
      $app = $procs[$key]
    } else {
      $app = ''
      try { $app = (Get-Process -Id $procId -ErrorAction Stop).ProcessName } catch { }
      $procs[$key] = $app
    }
    [void]$list.Add([pscustomobject]@{
      title = $title; app = $app; pid = [int]$procId
      x = $r.Left; y = $r.Top; w = $w; h = $ht
    })
    return $true
  }
  [void][WinList]::EnumWindows($cb, [IntPtr]::Zero)
  return @($list)
}

function Invoke-Ocr($path, $scale = 2) {
  $t0 = [DateTime]::UtcNow
  $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
  $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
  $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])

  # Upscale before recognition: measured on a 1920x1080 UI screenshot,
  # 2x cuts character error rate 26.4% -> 12.7% and 3-gram recall 69.6% -> 89.1%.
  # Upscaling adds no information, but helps the recognizer split lines and glyphs.
  # Done in memory via BitmapTransform: no extra file, no ffmpeg spawn.
  # NOTE: keep this file pure ASCII. PS 5.1 reads it as ANSI, and a Chinese
  # character's trailing byte can be 0x7D ('}'), which breaks the parser.
  if ($scale -gt 1) {
    $tf = New-Object Windows.Graphics.Imaging.BitmapTransform
    $tf.ScaledWidth = [uint32]([math]::Round($decoder.PixelWidth * $scale))
    $tf.ScaledHeight = [uint32]([math]::Round($decoder.PixelHeight * $scale))
    $tf.InterpolationMode = [Windows.Graphics.Imaging.BitmapInterpolationMode]::Fant
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync(
      [Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,
      [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied,
      $tf,
      [Windows.Graphics.Imaging.ExifOrientationMode]::IgnoreExifOrientation,
      [Windows.Graphics.Imaging.ColorManagementMode]::DoNotColorManage
    )) ([Windows.Graphics.Imaging.SoftwareBitmap])
  } else {
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  }

  $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
  $stream.Dispose()
  $ms = [int]([DateTime]::UtcNow - $t0).TotalMilliseconds

  # Word bounding boxes are in the *scaled* bitmap. Divide by scale so the
  # caller gets coordinates in the original frame ("where" -> native crop).
  $lines = @()
  foreach ($ln in $result.Lines) {
    $minX = [double]::MaxValue
    $minY = [double]::MaxValue
    $maxX = [double]::MinValue
    $maxY = [double]::MinValue
    foreach ($word in $ln.Words) {
      $br = $word.BoundingRect
      if ($null -eq $br) { continue }
      if ($br.X -lt $minX) { $minX = $br.X }
      if ($br.Y -lt $minY) { $minY = $br.Y }
      if (($br.X + $br.Width) -gt $maxX) { $maxX = $br.X + $br.Width }
      if (($br.Y + $br.Height) -gt $maxY) { $maxY = $br.Y + $br.Height }
    }
    if ($maxX -ge $minX -and $maxY -ge $minY) {
      $lines += [pscustomobject]@{
        text = $ln.Text
        x = [int][math]::Round($minX / $scale)
        y = [int][math]::Round($minY / $scale)
        w = [int][math]::Round(($maxX - $minX) / $scale)
        h = [int][math]::Round(($maxY - $minY) / $scale)
      }
    }
  }

  [pscustomobject]@{ path = $path; text = $result.Text; ms = $ms; scale = $scale; lines = @($lines) }
}

[Console]::Out.WriteLine('R')

while ($true) {
  $line = [Console]::In.ReadLine()
  if ($null -eq $line) { break }
  $line = $line.Trim()
  if ($line -eq '') { continue }

  $parts = $line.Split(' ', 4)
  $op = $parts[0]
  $id = if ($parts.Length -gt 1) { $parts[1] } else { '0' }

  try {
    if ($op -eq 'T') {
      $r = Get-Title
      [Console]::Out.WriteLine("T $id " + ($r | ConvertTo-Json -Compress))
    } elseif ($op -eq 'W') {
      $r = Get-Windows
      [Console]::Out.WriteLine("W $id " + ([pscustomobject]@{ windows = @($r) } | ConvertTo-Json -Compress -Depth 5))
    } elseif ($op -eq 'O' -and $parts.Length -ge 4) {
      # protocol: O <id> <scale> <path>  (path may contain spaces, so split into 4)
      $sc = 1.0
      [double]::TryParse($parts[2], [ref]$sc) | Out-Null
      $r = Invoke-Ocr $parts[3] $sc
      [Console]::Out.WriteLine("O $id " + ($r | ConvertTo-Json -Compress))
    } elseif ($op -eq 'Q') {
      break
    } else {
      [Console]::Out.WriteLine("E $id bad-request")
    }
  } catch {
    $msg = ($_.Exception.Message -replace '[\r\n]+', ' ')
    [Console]::Out.WriteLine("E $id " + $msg)
  }
  [Console]::Out.Flush()
}
