# doctor-probe.ps1 - probe Windows-only capabilities for dsh-bionic-intelligence.
# Pure ASCII on purpose: PowerShell 5.1 reads UTF-8 without BOM as ANSI.
# Prints one line of compact JSON on stdout; never exits non-zero.

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$result = [ordered]@{
  ps   = $PSVersionTable.PSVersion.ToString()
  ocr  = [ordered]@{ ok = $false; error = 'not-probed' }
  sapi = [ordered]@{ ok = $false; error = 'not-probed' }
}

# --- Windows.Media.Ocr (WinRT OCR) -------------------------------------------
try {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
  $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
  if ($engine) {
    $lang = $null
    try { $lang = $engine.RecognizerLanguage.LanguageTag } catch { $lang = $null }
    $result.ocr = [ordered]@{ ok = $true; lang = $lang }
  } else {
    $result.ocr = [ordered]@{ ok = $false; error = 'no-engine' }
  }
} catch {
  $result.ocr = [ordered]@{ ok = $false; error = $_.Exception.GetType().Name }
}

# --- System.Speech (SAPI voice) ----------------------------------------------
try {
  Add-Type -AssemblyName System.Speech
  $voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $voices = @($voice.GetInstalledVoices()).Count
  $voice.Dispose()
  $result.sapi = [ordered]@{ ok = $true; voices = $voices }
} catch {
  $result.sapi = [ordered]@{ ok = $false; error = $_.Exception.GetType().Name }
}

$result | ConvertTo-Json -Compress -Depth 5
