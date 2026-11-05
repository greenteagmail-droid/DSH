# -*- coding: utf-8 -*-
"""rapid-worker.py - 常驻 RapidOCR 服务，行协议和 ocr-worker.ps1 一致。

  O <id> <path>  -> O <id> {"path":..., "text":..., "ms":...}
  Q              -> 退出

为什么不和 PowerShell 那个合成一个：标题（前台窗口）只能用 Win32，
文字识别 PP-OCR 明显更准，两个引擎各跑一个进程，互不影响。任一挂掉都不拖死另一条路。
"""
import sys, json, time

# Windows 上通过管道通信时，python 默认用系统编码（中文机是 GBK），
# 而 Node 那边按 UTF-8 解 —— 不强制就会把「应用编辑」读成「Ӧ���༭」。
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

from rapidocr_onnxruntime import RapidOCR

engine = RapidOCR()
print("R", flush=True)

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    parts = line.split(" ", 2)
    op = parts[0]
    rid = parts[1] if len(parts) > 1 else "0"

    if op == "Q":
        break

    if op == "O" and len(parts) > 2:
        path = parts[2]
        t0 = time.time()
        try:
            res, _ = engine(path)
            text = "\n".join(x[1] for x in res) if res else ""
            lines = []
            for item in (res or []):
                try:
                    box, txt = item[0], item[1]
                    xs = [float(p[0]) for p in box]
                    ys = [float(p[1]) for p in box]
                    lines.append({
                        "text": str(txt),
                        "x": int(min(xs)), "y": int(min(ys)),
                        "w": int(max(xs) - min(xs)), "h": int(max(ys) - min(ys)),
                    })
                except Exception:
                    continue
            ms = int((time.time() - t0) * 1000)
            print("O %s %s" % (rid, json.dumps(
                {"path": path, "text": text, "ms": ms, "lines": lines}, ensure_ascii=False)), flush=True)
        except Exception as e:  # noqa: BLE001
            print("E %s %s" % (rid, str(e)[:200]), flush=True)
    else:
        print("E %s bad-request" % rid, flush=True)
