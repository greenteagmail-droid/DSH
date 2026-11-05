# -*- coding: utf-8 -*-
"""mic_asr.py - 用 sherpa-onnx 跑 SenseVoice-Small 把一段 WAV 转成文字。

用法: python mic_asr.py <in.wav> <out.txt> [model_dir]

输出约定和 mic_sapi.ps1 一致：一行一句，`!` 开头是错误，`#` 开头是诊断。
窗口那边完全不用改协议。

为什么是 SenseVoice：中文 CER 7.8%（FunASR 官方基准），且原生支持中/英/日/韩/粤
五种语言并自动判别；单帧 5 秒音频在 CPU 上约 0.3 秒。
"""
import os
import sys
import time


def fail(msg):
    sys.stderr.write(msg + "\n")
    try:
        with open(sys.argv[2], "w", encoding="utf-8") as f:
            f.write("! " + msg + "\n")
    except Exception:
        pass
    sys.exit(1)


def main():
    if len(sys.argv) < 3:
        fail("usage: mic_asr.py <in.wav> <out.txt> [model_dir]")
    wav = sys.argv[1]
    out = sys.argv[2]
    model_dir = sys.argv[3] if len(sys.argv) > 3 else os.environ.get(
        "DSH_ASR_MODEL",
        os.path.join(os.path.expanduser("~"), ".dsh", "bionic", "models",
                     "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"))

    t0 = time.time()
    try:
        import sherpa_onnx
    except Exception as exc:  # noqa: BLE001
        fail(f"import sherpa_onnx failed: {exc}")

    model = os.path.join(model_dir, "model.int8.onnx")
    if not os.path.exists(model):
        model = os.path.join(model_dir, "model.onnx")
    tokens = os.path.join(model_dir, "tokens.txt")
    if not os.path.exists(model) or not os.path.exists(tokens):
        fail(f"model not found under {model_dir}")

    try:
        rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=model,
            tokens=tokens,
            num_threads=4,
            use_itn=True,
            # 固定中文：auto 在短句上经常把普通话判成粤语/日语，
            # 出来就是"斋嘛搭肥鱼"这种。要别的语言设 DSH_ASR_LANG。
            language=os.environ.get("DSH_ASR_LANG", "zh"),
            debug=False,
        )
    except Exception as exc:  # noqa: BLE001
        fail(f"init recognizer failed: {exc}")

    try:
        import wave
        with wave.open(wav, "rb") as wf:
            sr = wf.getframerate()
            n = wf.getnframes()
            raw = wf.readframes(n)
        import array
        samples = array.array("h")
        samples.frombytes(raw)
        data = [s / 32768.0 for s in samples]
    except Exception as exc:  # noqa: BLE001
        fail(f"read wav failed: {exc}")

    try:
        stream = rec.create_stream()
        stream.accept_waveform(sr, data)
        rec.decode_stream(stream)
        text = (stream.result.text or "").strip()
        lang = getattr(stream.result, "lang", "") or ""
        dur = n / float(sr or 1)
    except Exception as exc:  # noqa: BLE001
        fail(f"decode failed: {exc}")

    # 诊断信息只走 stderr，不进结果文件 —— 结果文件里只有要发出去的那句话。
    sys.stderr.write(
        f"[asr] {time.time() - t0:.2f}s audio={dur:.1f}s lang={lang}\n")

    with open(out, "w", encoding="utf-8") as f:
        # 静音时会吐出一个孤零零的句号（实测），这种"只有标点"的结果当空处理，
        # 否则窗口会把它当一句话发出去。
        import re
        if not re.search(r"[0-9A-Za-z\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text):
            text = ""
        # **语气词过滤**：咳嗽、叹气、随口一个「啊」「嗯」会被识别成一个字，
        # 然后叫醒模型一次、再占一次麦克风锁 —— 全是噪音成本。
        # 只滤「1~2 个字且全是语气词」的情况，正常的短句（「好」「停」）不受影响。
        core = text.strip("。，！？、,.!?~～ ")
        fillers = set("啊嗯哦呃唉呀额欸喔噢嗷么嘛吧啊阿")
        fillers |= set("아응어야예")
        fillers |= set("あえーんう")
        if 0 < len(core) <= 2 and all(ch in fillers for ch in core):
            text = ""
        if text:
            f.write(text + "\n")
        else:
            f.write("! empty transcript\n")


if __name__ == "__main__":
    main()
