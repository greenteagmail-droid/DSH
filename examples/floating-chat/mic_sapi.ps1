# mic_sapi.ps1 - dictation via Windows SAPI (zh-CN), results appended to a FILE.
#
# Why a file instead of stdout: the host spawns this with redirected pipes and
# kills it when the user stops. Pipe buffering plus a kill make the last line of
# text easy to lose, and UTF-8 through a pipe on a cp936 console is one more
# failure mode. A file is dumb and always works.
#
# BOM matters: a BOM shows up as a bogus first line, the host reads lines and
# sends them, and the user gets an invisible "blank" message. So every write is
# UTF-8 WITHOUT BOM.
#
# Usage: powershell -File mic_sapi.ps1 -Out C:\path\mic.txt
# NOTE: keep this file pure ASCII - PS 5.1 reads it as ANSI.

param(
    [Parameter(Mandatory = $false)][string]$Out = ""
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($Out)) {
    $Out = Join-Path $env:TEMP "dsh-mic.txt"
}
$parent = Split-Path -Parent $Out
if ($parent -and -not (Test-Path $parent)) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
}

$script:Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($Out, "", $script:Utf8NoBom)

function Write-Line([string]$text) {
    if ([string]::IsNullOrWhiteSpace($text)) { return }
    [System.IO.File]::AppendAllText($Out, $text + "`n", $script:Utf8NoBom)
}

Add-Type -AssemblyName System.Speech

# `#` 开头的行是诊断，窗口会丢掉不显示 —— 只在排查"到底有没有跑起来"时有价值。
Write-Line ("# start " + (Get-Date -Format "HH:mm:ss"))

try {
    $culture = [System.Globalization.CultureInfo]::GetCultureInfo('zh-CN')
    $rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine($culture)
} catch {
    Write-Line ("! no zh-CN recognizer: " + $_.Exception.Message)
    exit 2
}

try {
    $rec.SetInputToDefaultAudioDevice()
    $rec.InitialSilenceTimeout = [TimeSpan]::FromSeconds(20)
    $rec.BabbleTimeout = [TimeSpan]::FromSeconds(20)
    $rec.EndSilenceTimeout = [TimeSpan]::FromMilliseconds(600)
    $rec.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
    Write-Line ("# device ok " + ($rec.RecognizerInfo.Name))
} catch {
    Write-Line ("! audio init failed: " + $_.Exception.Message)
    exit 3
}

$rounds = 0
while ($true) {
    $rounds += 1
    try {
        $r = $rec.Recognize([TimeSpan]::FromSeconds(2))
    } catch {
        Write-Line ("! " + $_.Exception.Message)
        break
    }
    if ($r -and $r.Text) {
        Write-Line $r.Text
    } elseif ($rounds -le 3) {
        # 前几轮把"没听到"也记下来：能区分"进程没跑"和"跑起来了但没拾到音"
        Write-Line ("# silence round " + $rounds)
    }
}
