# -*- coding: utf-8 -*-
"""mic_record.py - 录一段麦克风音频到 WAV，直到出现「停止文件」。

为什么用停止文件而不是 kill：
批式 ASR 需要一段**完整的**音频。直接 TerminateProcess 掉录音进程，WAV 头里的
长度字段来不及回填，文件就是坏的。所以由窗口创建 stopfile，本进程看到就收尾退出。

用法: python mic_record.py <out.wav> <stopfile>
依赖: sounddevice（PortAudio），装在 ~/.dsh/bionic/asr-venv 里
"""
import os
import sys
import time
import wave

import sounddevice as sd

RATE = 16000
CHANNELS = 1

# 这些名字是虚拟/远程设备。它们排到默认位置时，录出来是一整段静音，
# 表现为「说话没反应」，ASR 对着空白音频瞎猜出一个字。
VIRTUAL_HINTS = (
    "sound mapper", "uu", "远程", "virtual", "stereo mix",
    "vb-audio", "voicemeeter", "cable output",
)


def pick_device():
    """挑一个能录到真实声音的输入设备。

    `DSH_MIC_DEVICE` 可以强制指定（设备序号或名字片段）。没指定时：
    默认设备不是虚拟的就用默认，否则挑第一个不像虚拟的。
    """
    override = (os.environ.get("DSH_MIC_DEVICE") or "").strip()
    if override:
        return int(override) if override.isdigit() else override

    try:
        devices = sd.query_devices()
    except Exception:
        return None

    default = sd.default.device
    default_in = default[0] if isinstance(default, (list, tuple)) else default

    inputs = [i for i, d in enumerate(devices) if d.get("max_input_channels", 0) > 0]
    if not inputs:
        return None

    def virtual(name):
        low = str(name).lower()
        return any(hint in low for hint in VIRTUAL_HINTS)

    if default_in in inputs and not virtual(devices[default_in]["name"]):
        return default_in

    for i in inputs:
        if not virtual(devices[i]["name"]):
            return i

    return default_in if default_in in inputs else inputs[0]


def main():
    out = sys.argv[1]
    stopfile = sys.argv[2]
    if os.path.exists(stopfile):
        try:
            os.remove(stopfile)
        except OSError:
            pass

    wf = wave.open(out, "wb")
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(2)          # int16
    wf.setframerate(RATE)

    def callback(indata, frames, _time, status):  # noqa: ANN001
        if status:
            sys.stderr.write(str(status) + "\n")
        wf.writeframes(indata.tobytes())

    device = pick_device()
    try:
        with sd.InputStream(samplerate=RATE, channels=CHANNELS, dtype="int16",
                            blocksize=1024, callback=callback, device=device):
            while not os.path.exists(stopfile):
                time.sleep(0.1)
    finally:
        wf.close()
        sys.stdout.write("ok\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
