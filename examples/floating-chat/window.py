#!/usr/bin/env python3
"""悬浮提问窗：一条黑色药丸，收起时是图标条，展开后带输入框。

窗口只负责三件事：

1. 把用户输入（打字或说话）写进 chat.jsonl，插件读它来叫醒模型；
2. 录音 + 转写：调同目录的 mic_record.py / mic_asr.py，或退回 Windows 识别；
3. 等回复真的送到（replied.at + spoken.done + turn.done），再解开话筒锁。

不显示聊天记录，不截图，不做视觉特效。
"""

import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import time

try:
    import tkinter as tk
    from tkinter import font as tkfont
except Exception as exc:
    sys.stderr.write(f"需要带 tkinter 的 Python：{sys.executable}\n{exc}\n")
    raise SystemExit(2)

# ------------------------------------------------------------------ 路径

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DSH_HOME = os.environ.get("DSH_HOME") or os.path.expanduser("~/.dsh")


def data_dir():
    override = os.environ.get("DSH_VIDEO_CACHE_DIR")
    if override:
        return override
    local = os.environ.get("LOCALAPPDATA")
    if os.name == "nt" and local:
        return os.path.join(local, "bionic", "cache")
    return os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "bionic")


DATA = data_dir()
CHAT = os.path.join(DATA, "chat.jsonl")
MIC_TEXT = os.path.join(DATA, "mic.txt")
MIC_WAV = os.path.join(DATA, "mic.wav")
MIC_STOP = os.path.join(DATA, "mic.stop")
MIC_START = os.path.join(DATA, "mic.start")
TEXT_START = os.path.join(DATA, "text.start")
NAME_FILE = os.path.join(DATA, "name")
MIC_STATE = os.path.join(DATA, "mic.state")
CLOSED = os.path.join(DATA, "window.closed")
REPLY_AT = os.path.join(DATA, "replied.at")
SPOKEN_DONE = os.path.join(DATA, "spoken.done")
TURN_DONE = os.path.join(DATA, "turn.done")

RECORDER = os.path.join(ROOT_DIR, "mic_record.py")
TRANSCRIBER = os.path.join(ROOT_DIR, "mic_asr.py")
SAPI_SCRIPT = os.path.join(ROOT_DIR, "mic_sapi.ps1")

ASR = (os.environ.get("DSH_ASR_ENGINE") or "sensevoice").strip().lower()
ASR_PYTHON = os.environ.get("DSH_ASR_PYTHON") or os.path.join(
    DSH_HOME, "bionic", "asr-venv", "Scripts", "python.exe")

SESSION_FILE = os.path.join(DSH_HOME, "watch-window.json")
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# ------------------------------------------------------------------ 外观

INK = "#0b0c0e"
EDGE = "#2c3038"
WELL = "#15171c"
TEXT = "#f2f3f5"
DIM = "#6e7683"
DOT_BACK = "#1a1f27"
ICON = "#d8dce4"
ICON_MUTED = "#4f5664"
MIC_HOT = "#7a2b2b"
MIC_HOT_FG = "#ffd9d9"

LAMP = {
    "idle": "#0a84ff",
    "recording": "#e05050",
    "processing": "#d89a2a",
    "waiting": "#d8c02a",
}

ICON_FONT = "Segoe MDL2 Assets"
MIC_GLYPH = "\ue720"
EXPAND_GLYPH = "\ue740"
COLLAPSE_GLYPH = "\ue73f"
POWER_GLYPH = "\ue7e8"
ACCENT = "#0a84ff"

STRIP_W = 178
STRIP_H = 56
STRIP_DOT = 36
STRIP_STEP = 42

BAR_W = 366
BAR_H = 54
BAR_DOT = 34

EDGE_GAP = 24


def load_session():
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_session(patch):
    state = load_session()
    state.update(patch or {})
    try:
        os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
        tmp = SESSION_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SESSION_FILE)
    except Exception:
        pass


def push_message(text, source="text"):
    text = str(text or "").strip()
    if not text:
        return False
    try:
        os.makedirs(os.path.dirname(CHAT), exist_ok=True)
        with open(CHAT, "a", encoding="utf-8") as f:
            f.write(json.dumps({"role": "user", "text": text,
                                "source": source,
                                "at": int(time.time() * 1000)},
                               ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def record_state(state):
    try:
        with open(MIC_STATE, "w", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} state={state}\n")
    except Exception:
        pass


def enable_dpi():
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def blend(a, b, t):
    t = max(0.0, min(1.0, t))
    pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(pa[i] + (pb[i] - pa[i]) * t) for i in range(3))


def pill_points(x1, y1, x2, y2, r, steps=8):
    import math
    r = max(0.0, min(r, (x2 - x1) / 2.0, (y2 - y1) / 2.0))
    pts = []
    arcs = [
        (x2 - r, y1 + r, -math.pi / 2, 0.0),
        (x2 - r, y2 - r, 0.0, math.pi / 2),
        (x1 + r, y2 - r, math.pi / 2, math.pi),
        (x1 + r, y1 + r, math.pi, math.pi * 1.5),
    ]
    for cx, cy, a0, a1 in arcs:
        for i in range(steps + 1):
            angle = a0 + (a1 - a0) * i / steps
            pts.extend([cx + r * math.cos(angle), cy + r * math.sin(angle)])
    return pts


class Bubble:
    """药丸窗口：收起态是图标条，展开态带输入框。"""

    def __init__(self):
        self.state = load_session()
        self.scale = 1.0
        self.collapsed = bool(os.environ.get("DSH_WINDOW_START_MINI"))
        self.vertical = bool(self.state.get("mini_vertical"))
        if "--expanded" in sys.argv:
            self.collapsed = False
        if "--collapsed" in sys.argv:
            self.collapsed = True
        self.title = self._title()
        self.icon_state = "idle"
        self.hint = ""
        self.dragging = False
        self.last_move = 0.0
        self.grab_at = (0, 0)
        self.window_at = (0, 0)
        self.rec = None
        self.sent_at = 0.0
        self.notice = None
        self.entry_id = None
        self.send_parts = ()
        self.field_focused = False
        self.had_text_focus = False
        self.lock = None
        self.rendering = False
        self.events = queue.Queue()

        try:
            self.host_pid = int(os.environ.get("DSH_PARENT_PID") or 0)
        except Exception:
            self.host_pid = 0

        self.win = tk.Tk()
        self.win.withdraw()
        self.win.title(self.title)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=INK)

        self._scale()
        self._compose()
        self._place()
        self.win.deiconify()

        self._on_top()
        self.win.after(300, self._nudge_on_screen)
        self.win.after(800, self._top_loop)
        self.win.after(900, self._reply_loop)
        self.win.after(2000, self._host_loop)
        self.win.after(120, self._pump)
        self.win.after(4000, self._name_loop)

    # -------------------------------------------------------------- 基础

    def _scale(self):
        try:
            self.win.update_idletasks()
            self.scale = max(1.0, min(2.0, self.win.winfo_fpixels("1i") / 96.0))
        except Exception:
            self.scale = 1.0

    def px(self, value):
        return int(round(value * self.scale))

    def _title(self):
        from_env = (os.environ.get("DSH_BIONIC_NAME") or "").strip()
        if from_env:
            return from_env[:24]
        configured = self.state.get("name")
        if isinstance(configured, str) and configured.strip():
            return configured.strip()[:24]
        return "仿生智能"

    def _text_font(self, size, bold=False):
        family = "Microsoft YaHei UI"
        try:
            if family not in set(tkfont.families(self.win)):
                family = "Segoe UI"
        except Exception:
            pass
        return tkfont.Font(family=family, size=int(round(size * self.scale)),
                           weight="bold" if bold else "normal")

    def _icon_font(self, size):
        return tkfont.Font(family=ICON_FONT, size=int(round(size * self.scale)))

    def _size(self):
        if self.collapsed:
            # 收起态有两种朝向：贴着左右边时竖排，拖回中间横排。
            if self.vertical:
                return self.px(STRIP_H), self.px(STRIP_W)
            return self.px(STRIP_W), self.px(STRIP_H)
        return self.px(BAR_W), self.px(BAR_H)

    def _compose(self):
        self.canvas = tk.Canvas(self.win, bg=INK, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        self.field = tk.Entry(self.canvas, relief="flat", bd=0, bg=WELL, fg=TEXT,
                              insertbackground=TEXT, highlightthickness=0,
                              disabledbackground=WELL, disabledforeground=ICON_MUTED,
                              font=self._text_font(11))
        self.field.bind("<Return>", self._submit)
        self.field.bind("<Escape>", lambda _e: self.field.delete(0, "end"))
        self.field.bind("<KeyRelease>", self._on_key)
        self.field.bind("<FocusIn>", self._on_field_focus_in)
        self.field.bind("<FocusOut>", self._on_field_focus_out)

        self.canvas.bind("<Button-1>", self._grab)
        self.canvas.bind("<B1-Motion>", self._move)
        self.canvas.bind("<ButtonRelease-1>", self._drop)
        self.canvas.bind("<Button-3>", lambda _e: self._shutdown())
        self.win.bind("<Escape>", lambda _e: self._shutdown())

    def _place(self):
        w, h = self._size()
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        x, y = self.state.get("x"), self.state.get("y")
        # 存的坐标可能来自另一块屏、或者窗口变大后从右/下边溢出去。
        # 只要放不下就回到默认位置，绝不把窗口丢到看不见的地方。
        if (not isinstance(x, int) or not isinstance(y, int)
                or x < 0 or y < 0 or x + w > sw or y + h > sh):
            x, y = self.px(28), int((sh - h) / 2)
        self.win.geometry(f"{w}x{h}+{x}+{y}")
        self._render()

    # -------------------------------------------------------------- 绘制

    def _render(self):
        # 重绘会删掉输入框的 canvas window 再重建，过程中可能冒出
        # FocusIn/FocusOut。用这个标志兜住，别让焦点回调再触发一次重绘。
        if self.rendering:
            return
        self.rendering = True
        try:
            self._render_inner()
        finally:
            self.rendering = False

    def _render_inner(self):
        w, h = self._size()
        if self.win.winfo_width() != w or self.win.winfo_height() != h:
            self.win.geometry(f"{w}x{h}")
        self.canvas.configure(width=w, height=h)
        # 重绘时**保留输入框那个 canvas window**，其余全删。
        # 整块 delete("all") 会把它一起删掉，重建后 Tk 可能补发一次
        # FocusIn，标志位又变回"在用文本"，话筒就永远点不动了。
        for item in self.canvas.find_all():
            if item != self.entry_id:
                self.canvas.delete(item)
        if self.collapsed and self.entry_id is not None:
            # 收起态没有输入框，这时候才真正删掉它
            self.canvas.delete(self.entry_id)
            self.entry_id = None

        # R 角取短边的一半：横条和竖条是同一个胶囊转了个方向，
        # 不能拿高度算，否则竖起来会变成一个圆头长条。
        self.canvas.create_polygon(pill_points(0.5, 0.5, w - 0.5, h - 0.5, min(w, h) / 2.0),
                                   smooth=True, splinesteps=16, fill=INK,
                                   outline=EDGE, width=1)
        if self.collapsed:
            self._render_strip(w, h)
        else:
            self._render_bar(w, h)
        self._clip(w, h)

    def _clip(self, w, h):
        if os.name != "nt":
            return
        try:
            hwnd = self._handle()
            if not hwnd:
                return
            # 圆角只跟短边走：横条和竖条是同一个胶囊，不能拿高度算，
            # 否则竖起来两头会被裁成尖的（SetWindowRgn 的椭圆半径过大）。
            r = int(min(w, h))
            rgn = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, int(w) + 1, int(h) + 1, r, r)
            if rgn:
                ctypes.windll.user32.SetWindowRgn(hwnd, rgn, True)
        except Exception:
            pass

    def _mic_style(self):
        """话筒键配色，横排竖排共用。

        空闲＝跟别的键一样亮；录音＝红；锁住＝灰。
        锁住有两种来源：语音自己在跑，或者文本刚发出去还没回完。
        """
        if self.icon_state == "recording":
            return MIC_HOT_FG, MIC_HOT
        if self.icon_state in ("processing", "waiting"):
            return ICON_MUTED, "#12161d"
        # 文本在用（焦点在输入框）或刚发出去还没回完，话筒都是灰的
        if self.field_focused or self.lock == "text":
            return ICON_MUTED, "#12161d"
        return ICON, DOT_BACK

    def _dot(self, cx, cy, r, glyph=None, glyph_color=ICON, back=DOT_BACK, tag=None):
        self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=back, outline="")
        if glyph:
            self.canvas.create_text(cx, cy, text=glyph, fill=glyph_color,
                                    font=self._icon_font(13),
                                    tags=((tag,) if tag else ()))

    def _lamp_dot(self, cx, cy, r):
        color = LAMP.get(self.icon_state, LAMP["idle"])
        self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=DOT_BACK, outline="")
        rr = max(2.0, 3.2 * self.scale)
        self.canvas.create_oval(cx - rr * 2.2, cy - rr * 2.2, cx + rr * 2.2, cy + rr * 2.2,
                                outline=blend(color, "#0f1218", 0.55), width=1)
        self.canvas.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, fill=color, outline="")

    def _bind_click(self, tag, key):
        self.canvas.tag_bind(tag, "<Button-1>", lambda _e, k=key: self._press(k))

    def _render_strip(self, w, h):
        """收起态：状态灯 / 话筒 / 展开 / 关机，四个圆。

        横排贴上下边，竖排贴左右边 —— 贴边时药丸横着会有一段圆弧探出屏幕，
        竖过来刚好是一根竖直胶囊。
        """
        r = self.px(STRIP_DOT) / 2.0
        step = self.px(STRIP_STEP)
        first = self.px(26)
        if self.vertical:
            cx = w / 2.0
            spots = [(cx, first + step * i) for i in range(4)]
        else:
            cy = h / 2.0
            spots = [(first + step * i, cy) for i in range(4)]

        self._lamp_dot(spots[0][0], spots[0][1], r)

        mic_fg, mic_bg = self._mic_style()
        self._dot(spots[1][0], spots[1][1], r, MIC_GLYPH, mic_fg, mic_bg, tag="k-mic")
        self._bind_click("k-mic", "mic")

        self._dot(spots[2][0], spots[2][1], r, EXPAND_GLYPH, ICON, DOT_BACK, tag="k-expand")
        self._bind_click("k-expand", "expand")

        self._dot(spots[3][0], spots[3][1], r, POWER_GLYPH, ICON, DOT_BACK, tag="k-power")
        self._bind_click("k-power", "power")

    def _render_bar(self, w, h):
        """展开态：状态灯 / 名字 / 输入框 / 话筒 / 发送 / 收起。"""
        cy = h / 2.0
        r = self.px(BAR_DOT) / 2.0
        pad = self.px(10)

        self._lamp_dot(pad + r, cy, r)

        title_x = pad + r * 2 + self.px(8)
        item = self.canvas.create_text(title_x, cy, text=self.title, anchor="w",
                                       fill=TEXT, font=self._text_font(9, True))
        box = self.canvas.bbox(item)
        well_x1 = (box[2] if box else title_x + self.px(50)) + self.px(10)

        right = w - pad
        collapse_cx = right - r
        self._dot(collapse_cx, cy, r, COLLAPSE_GLYPH, ICON, DOT_BACK, tag="k-collapse")
        self._bind_click("k-collapse", "collapse")

        mic_cx = collapse_cx - self.px(40)
        mic_fg, mic_bg = self._mic_style()
        self._dot(mic_cx, cy, r, MIC_GLYPH, mic_fg, mic_bg, tag="k-mic")
        self._bind_click("k-mic", "mic")

        # 发送键做成一颗写着「发送」的胶囊：固定宽度，字形比箭头占地方
        send_w = self.px(54)
        send_h = self.px(30)
        send_x2 = mic_cx - r - self.px(8)
        send_x1 = send_x2 - send_w
        has_text = bool(self.field.get().strip())
        send_fill = ACCENT if has_text else DOT_BACK
        send_fg = "#ffffff" if has_text else ICON
        send_bg = self.canvas.create_polygon(
            pill_points(send_x1, cy - send_h / 2.0, send_x2, cy + send_h / 2.0, send_h / 2.0),
            smooth=True, splinesteps=10, fill=send_fill, outline="", tags=("k-send",))
        send_text = self.canvas.create_text(
            (send_x1 + send_x2) / 2.0, cy, text="发送", fill=send_fg,
            font=self._text_font(9), tags=("k-send",))
        self.send_parts = (send_bg, send_text)
        self._bind_click("k-send", "send")

        # 输入槽：药丸形，曲率和窗口本体一致（R = 半高）。
        # 窗口宽度已经按缩短后的输入箱重算过，这里直接占满，不留空白。
        well_h = self.px(30)
        well_x2 = send_x1 - self.px(8)
        well_w = max(self.px(72), well_x2 - well_x1)
        well_x2 = well_x1 + well_w
        # 语音占着时，整条输入槽降成和话筒灰态一样的底，并写「语音中…」
        voice_locked = self.lock == "voice" or self.icon_state in ("recording", "processing")
        well_fill = "#12161d" if voice_locked else WELL
        self.canvas.create_polygon(
            pill_points(well_x1, cy - well_h / 2.0, well_x2, cy + well_h / 2.0, well_h / 2.0),
            smooth=True, splinesteps=10, fill=well_fill, outline="")

        field_x = well_x1 + self.px(10)
        field_w = max(self.px(40), int(well_w - self.px(20)))
        if self.entry_id is None:
            self.entry_id = self.canvas.create_window(field_x, cy, window=self.field,
                                                      anchor="w", width=field_w,
                                                      height=self.px(26))
        else:
            self.canvas.coords(self.entry_id, field_x, cy)
            self.canvas.itemconfigure(self.entry_id, width=field_w)

        # 提示文字和 Entry 抢同一块地方。Entry 是真实控件，会盖住画布上的字，
        # 所以状态提示在的时候把 Entry 藏起来，字才看得见。
        hint_text = "语音中…" if voice_locked else self.hint
        # 焦点已经在框里时绝不能显示提示：提示靠隐藏 Entry 来露出来，
        # 藏了就没法打字，等于点进去反而打不进字。
        show_hint = (not self.field_focused) and (not self.field.get()) and bool(hint_text)
        if self.entry_id is not None:
            self.canvas.itemconfigure(self.entry_id,
                                      state="hidden" if show_hint else "normal")
        if show_hint:
            self.canvas.create_text(well_x1 + self.px(12), cy, text=hint_text, anchor="w",
                                    fill="#4f5664" if voice_locked else "#9aa3b2",
                                    font=self._text_font(10))

    # -------------------------------------------------------------- 交互

    def _press(self, key):
        # 点按钮会顺带触发画布的按下/松开，如果不拦，_drop 会把这次"点击"
        # 当成拖动结束去做贴边，于是在边上展开一下就被收回竖排。
        self.suppress_stick = True
        if key == "send":
            self._submit(None)
        elif key == "mic":
            self._mic()
        elif key == "collapse":
            self._fold(True)
        elif key == "expand":
            self._fold(False)
        elif key == "power":
            self._shutdown()

    def _on_key(self, _event=None):
        """有字才把发送键点亮，和旧版一致。"""
        try:
            has = bool(self.field.get().strip())
        except Exception:
            has = False
        parts = getattr(self, "send_parts", ())
        if len(parts) == 2:
            try:
                self.canvas.itemconfigure(parts[0], fill=ACCENT if has else DOT_BACK)
                self.canvas.itemconfigure(parts[1], fill="#ffffff" if has else ICON)
            except Exception:
                pass

    def _on_field_focus_in(self, _event=None):
        self.field_focused = True
        self._mark_text_start()
        # 一进焦点话筒就该变灰；重绘中触发的焦点事件不再递归
        if not self.rendering:
            try:
                self._render()
            except Exception:
                pass

    def _on_field_focus_out(self, _event=None):
        self.field_focused = False
        # 「在打字…」是一次性提醒，失焦就该消失，不能一直挂在输入框里
        if self.hint.startswith("在打字"):
            self.hint = ""
        if not self.rendering:
            try:
                self._render()
            except Exception:
                pass

    def _mark_text_start(self):
        """点进输入框就算「开始输入」：记下这一刻，识别窗口往回看 15 秒。"""
        try:
            with open(TEXT_START, "w", encoding="utf-8") as f:
                f.write(str(int(time.time() * 1000)))
        except Exception:
            pass

    def _submit(self, _event=None, source="text"):
        text = self.field.get().strip()
        if not text:
            return "break"
        if source != "voice":
            # 打字提问不认上一次语音留下的锚点
            try:
                os.remove(MIC_START)
            except OSError:
                pass
        else:
            # 语音提问不认打字留下的锚点
            try:
                os.remove(TEXT_START)
            except OSError:
                pass
        if push_message(text, source):
            self.field.delete(0, "end")
            self.sent_at = time.time()
            # 谁先发起就锁住对方，直到这一轮回复结束
            self.lock = "voice" if source == "voice" else "text"
            self._set_state("waiting")
        else:
            self._say("写不进去，检查数据目录")
        return "break"

    def _say(self, text):
        self.hint = text or ""
        self._render()

    def _set_state(self, state):
        self.icon_state = state
        record_state(state)
        if state == "idle":
            self.lock = None
        self.hint = {"idle": "", "recording": "在听…", "processing": "识别中…",
                     "waiting": "等回复…"}.get(state, "")
        # 语音占着的时候就锁住文本：输入框禁用，点不进去也打不了字。
        try:
            self.field.configure(state="normal" if state == "idle" else "disabled")
        except Exception:
            pass
        try:
            self._render()
        except Exception:
            pass

    def _shutdown(self):
        try:
            os.makedirs(os.path.dirname(CLOSED), exist_ok=True)
            with open(CLOSED, "w", encoding="utf-8") as f:
                f.write(str(int(time.time() * 1000)))
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass

    def _fold(self, collapsed):
        if self.collapsed == collapsed:
            return
        self._blur()
        self.collapsed = collapsed
        # 展开一定是横的；收起来先保持横的，只有贴到左右边才转竖。
        if not collapsed:
            self.vertical = False
        save_session({"mini": collapsed, "mini_vertical": self.vertical})
        w, h = self._size()
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        # 左边的竖条展开成 406 宽会探出屏幕，先把位置夹回来，不然像"点了没反应"
        x = max(0, min(sw - w, self.win.winfo_x()))
        y = max(0, min(sh - h, self.win.winfo_y()))
        self.win.geometry(f"{w}x{h}+{x}+{y}")
        self.entry_id = None
        self._render()

    # -------------------------------------------------------------- 麦克风

    def _mic(self):
        # 只看"此刻"焦点在不在输入框。这里**只提醒、不设锁**：
        # lock 的语义是"有一条消息在等回复"，没发消息就设锁会永远解不开。
        if self.field_focused:
            self._say("在打字，先点一下空白再说话")
            return
        if self.lock == "text":
            self._say("上一条还在等回复")
            return
        if self.icon_state == "recording":
            self._stop_mic()
            return
        if self.icon_state != "idle":
            note = {"processing": "正在转写，稍等",
                    "waiting": "等我把上一条回完"}.get(self.icon_state, "忙")
            if self.notice != note:
                self.notice = note
                self._say(note)
            return

        self.notice = None
        self._set_state("recording")

        try:
            os.makedirs(os.path.dirname(MIC_START), exist_ok=True)
            with open(MIC_START, "w", encoding="utf-8") as f:
                f.write(str(int(time.time() * 1000)))
        except Exception:
            pass
        try:
            with open(MIC_TEXT, "w", encoding="utf-8") as f:
                f.write("")
        except Exception:
            pass

        if ASR == "sapi":
            if not os.path.exists(SAPI_SCRIPT):
                self._say(f"找不到 {SAPI_SCRIPT}")
                self._set_state("idle")
                return
            cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                   "-File", SAPI_SCRIPT, "-Out", MIC_TEXT]
        else:
            if not (os.path.exists(RECORDER) and os.path.exists(TRANSCRIBER)):
                self._say("找不到录音或转写脚本")
                self._set_state("idle")
                return
            if not os.path.exists(ASR_PYTHON):
                self._say(f"找不到 ASR 的 python：{ASR_PYTHON}")
                self._set_state("idle")
                return
            try:
                os.remove(MIC_STOP)
            except OSError:
                pass
            cmd = [ASR_PYTHON, RECORDER, MIC_WAV, MIC_STOP]

        try:
            self.rec = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.PIPE, text=True,
                                        encoding="utf-8", errors="replace",
                                        creationflags=CREATE_NO_WINDOW)
        except Exception as exc:
            self._say(f"起不来麦克风：{exc}")
            self._set_state("idle")
            return
        record_state("recording")

    def _stop_mic(self):
        proc = self.rec
        self.rec = None
        self._set_state("processing")
        if proc is None:
            self._set_state("idle")
            return
        threading.Thread(target=self._transcribe, args=(proc,), daemon=True).start()

    def _transcribe(self, proc):
        err = None
        if ASR == "sapi":
            try:
                proc.wait(timeout=1.4)
            except Exception:
                try:
                    proc.terminate()
                    proc.wait(timeout=1.0)
                except Exception:
                    pass
        else:
            try:
                with open(MIC_STOP, "w", encoding="utf-8") as f:
                    f.write("stop")
            except Exception:
                pass
            try:
                proc.wait(timeout=6)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass
            try:
                done = subprocess.run([ASR_PYTHON, TRANSCRIBER, MIC_WAV, MIC_TEXT],
                                      capture_output=True, text=True, encoding="utf-8",
                                      errors="replace", timeout=90,
                                      creationflags=CREATE_NO_WINDOW)
                if done.returncode not in (0, None):
                    err = f"转写失败：{(done.stderr or '').strip()[:100]}"
            except Exception as exc:
                err = f"转写起不来：{exc}"
        self.events.put(("mic", err))

    def _mic_done(self, err):
        if err:
            self._say(err)
            self._set_state("idle")
            return
        text = ""
        try:
            with open(MIC_TEXT, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read()
        except Exception:
            raw = ""
        # 第一行是转写器的诊断信息（# sherpa-onnx ...），只用来排错，
        # 不能喂给会话，也不能显示在输入框里。
        lines = [ln for ln in raw.splitlines() if not ln.lstrip().startswith("#")]
        text = " ".join(" ".join(lines).split())
        if not text or text.startswith("!"):
            self._say("没听到内容")
            self._set_state("idle")
            return
        # 语音占着时输入框是 disabled，写之前先放开
        try:
            self.field.configure(state="normal")
        except Exception:
            pass
        self.field.insert(0, text)
        self._submit(source="voice")

    # -------------------------------------------------------------- 回复

    def _reply(self):
        try:
            with open(REPLY_AT, "r", encoding="utf-8") as f:
                raw = f.read().strip()
        except Exception:
            return None
        at, text, voice = None, "", True
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                at = float(obj.get("at") or 0) / 1000.0
                text = str(obj.get("text") or "")
                voice = bool(obj.get("voice", True))
            elif isinstance(obj, (int, float)):
                at = float(obj) / 1000.0
        except Exception:
            at = None
        if not at:
            try:
                at = os.path.getmtime(REPLY_AT)
            except Exception:
                return None
        return {"at": at, "text": text, "voice": voice}

    @staticmethod
    def _same_sentence(a, b):
        na = "".join(str(a or "").split())
        nb = "".join(str(b or "").split())
        return bool(na) and na == nb

    def _spoken(self, info):
        try:
            size = os.path.getsize(SPOKEN_DONE)
            with open(SPOKEN_DONE, "rb") as f:
                f.seek(max(0, size - 8192))
                tail = f.read().decode("utf-8", "replace")
        except Exception:
            return False
        for line in reversed(tail.split("\n")):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            try:
                at = float(obj.get("at") or 0) / 1000.0
            except Exception:
                continue
            if at < info["at"]:
                return False
            text = str(obj.get("text") or "")
            if not text or self._same_sentence(text, info["text"]):
                return True
        return False

    def _turn_finished(self, info):
        try:
            with open(TURN_DONE, "r", encoding="utf-8") as f:
                obj = json.loads(f.read().strip())
            return float(obj.get("at") or 0) / 1000.0 >= info["at"]
        except Exception:
            return False

    def _estimate(self, text):
        plain = "".join(ch for ch in str(text or "") if not ch.isspace())
        return min(40.0, max(1.5, len(plain) / 3.6 + 1.0))

    def _reply_loop(self):
        try:
            self._maybe_release()
        except Exception:
            pass
        try:
            self.win.after(400, self._reply_loop)
        except Exception:
            pass

    def _maybe_release(self):
        if self.icon_state != "waiting":
            return
        sent = self.sent_at or 0
        now = time.time()
        # 45 秒还没等到回复就放开话筒：等太久用户只会以为卡死了。
        # 正常几秒就回，超过这个数基本是这条没送出去。
        if sent and now > sent + 45.0:
            self.lock = None
            self._say("刚才那条没送出去，再说一次")
            self._set_state("idle")
            return
        info = self._reply()
        if not info or info["at"] <= sent:
            return
        soft = info["at"] + self._estimate(info["text"])
        hard = info["at"] + 180.0
        if info.get("voice"):
            if os.path.exists(SPOKEN_DONE):
                if not self._spoken(info) and now < hard:
                    return
            elif now < soft:
                return
        if os.path.exists(TURN_DONE):
            if not self._turn_finished(info) and now < hard:
                return
        elif now < soft:
            return
        self._set_state("idle")

    # -------------------------------------------------------------- 窗口

    def _blur(self):
        """交还焦点。无边框窗口里 canvas.focus_set() 经常抢不到焦点，
        所以标志位也要立刻落下来，否则话筒会一直按"文本在用"锁着。"""
        self.field_focused = False
        if self.hint.startswith("在打字"):
            self.hint = ""
        try:
            self.win.focus_set()
        except Exception:
            pass
        try:
            self.canvas.focus_set()
        except Exception:
            pass
        try:
            self.field.selection_clear()
        except Exception:
            pass

    def _grab(self, event):
        # 点进这里之前光标在不在输入框里 —— 用焦点事件维护的标志位，
        # 不靠 focus_get()：无边框窗口里 canvas.focus_set() 未必拿得到焦点。
        self.had_text_focus = self.field_focused
        self._blur()
        self.dragging = True
        self.suppress_stick = False
        self.grab_at = (event.x_root, event.y_root)
        self.window_at = (self.win.winfo_x(), self.win.winfo_y())

    def _move(self, event):
        if not self.dragging:
            return
        dx = event.x_root - self.grab_at[0]
        dy = event.y_root - self.grab_at[1]
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        w = self.win.winfo_width()
        h = self.win.winfo_height()
        nx = max(0, min(sw - w, self.window_at[0] + dx))
        ny = max(0, min(sh - h, self.window_at[1] + dy))
        self.win.geometry(f"+{nx}+{ny}")

    def _drop(self, _event=None):
        if not self.dragging:
            return
        self.dragging = False
        # 没有消息在途的文本锁一律清掉：按钮点击带出的假拖动也要清，
        # 否则 lock 会一直挂着一个不存在的"等待回复"，话筒永远灰着。
        if self.lock == "text" and self.icon_state != "waiting":
            self.lock = None
        if getattr(self, "suppress_stick", False):
            # 这是点按钮带出来的假拖动，别做贴边
            self.suppress_stick = False
            return
        # 点在空白处（不是按钮）＝ 文本结束，解除文本锁
        if self.lock == "text":
            self.lock = None
            self._render()
        # 窗口根本没动（就是点了一下空白处），也不做贴边。
        # 否则展开态停在边缘时，随手一点就被收回竖排。
        moved = (abs(self.win.winfo_x() - self.window_at[0]) >= 2
                 or abs(self.win.winfo_y() - self.window_at[1]) >= 2)
        if not moved:
            return
        # 先让 Tk 把最后一次 geometry 落定，否则 winfo_y 还是拖动中的旧值，
        # 上下贴边就判不到。
        try:
            self.win.update_idletasks()
        except Exception:
            pass
        self._stick()

    def _stick(self):
        """松手时贴边。照旧版：26 像素内算贴边，展开的先收成图标条再竖排。"""
        x, y = self.win.winfo_x(), self.win.winfo_y()
        w, h = self.win.winfo_width(), self.win.winfo_height()
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        thr = self.px(26)

        left = x <= thr
        right = sw - (x + w) <= thr
        vert_thr = thr

        changed = False
        nx, ny = x, y

        if left or right:
            # 贴边：展开的就收起来，再竖排
            if not self.collapsed:
                self.collapsed = True
                changed = True
            if not self.vertical:
                self.vertical = True
                changed = True
            nw, nh = self._size()
            if left:
                nx = 0
            else:
                nx = sw - nw
            ny = int(max(0, min(sh - nh, y + h / 2.0 - nh / 2.0)))
            h = nh
            w = nw
        elif self.vertical:
            # 离开左右边，恢复横排；放不下就先把窗口挪进来
            self.vertical = False
            w, h = self._size()
            nx = max(0, min(sw - w, x))
            changed = True

        if y <= vert_thr:
            ny = 0
        elif sh - (y + h) <= vert_thr:
            ny = sh - h
        nx = max(0, min(sw - w, nx))
        ny = max(0, min(sh - h, ny))

        if changed or (nx, ny) != (x, y):
            self.win.geometry(f"{w}x{h}+{nx}+{ny}")
            save_session({"x": nx, "y": ny, "mini": self.collapsed,
                          "mini_vertical": self.vertical})
            self.entry_id = None
            self._render()

    def _nudge_on_screen(self):
        try:
            sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
            x, y = self.win.winfo_x(), self.win.winfo_y()
            w, h = self.win.winfo_width(), self.win.winfo_height()
            if x + w < 40 or y + h < 40 or x > sw - 40 or y > sh - 40:
                self.win.geometry(f"+{self.px(28)}+{int((sh - h) / 2)}")
        except Exception:
            pass

    def _handle(self):
        if os.name != "nt":
            return None
        try:
            user32 = ctypes.windll.user32
            pid = os.getpid()
            hits = []

            def visit(hwnd, _lp):
                owner = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
                if owner.value != pid:
                    return True
                rect = (ctypes.c_long * 4)()
                if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    if rect[2] - rect[0] > 0 and rect[3] - rect[1] > 0:
                        hits.append(hwnd)
                return True

            cb = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(visit)
            user32.EnumWindows(cb, 0)
            return hits[0] if hits else None
        except Exception:
            return None

    def _on_top(self):
        if os.name != "nt":
            return
        try:
            hwnd = self._handle()
            if not hwnd:
                return
            user32 = ctypes.windll.user32
            user32.SetWindowPos.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
            ]
            user32.SetWindowPos.restype = ctypes.c_bool
            user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
        except Exception:
            pass

    def _top_loop(self):
        try:
            self._on_top()
        except Exception:
            pass
        try:
            self.win.after(1500, self._top_loop)
        except Exception:
            pass

    def _host_loop(self):
        if self.host_pid and os.name == "nt":
            alive = True
            try:
                handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, self.host_pid)
                if not handle:
                    alive = False
                else:
                    code = ctypes.windll.kernel32.WaitForSingleObject(handle, 0)
                    ctypes.windll.kernel32.CloseHandle(handle)
                    alive = code == 258
            except Exception:
                alive = True
            if not alive:
                try:
                    self.win.destroy()
                except Exception:
                    pass
                return
        try:
            self.win.after(2000, self._host_loop)
        except Exception:
            pass

    def _name_loop(self):
        """运行中改名也生效：插件会把解析到的名字写进 name 文件，这里跟着换。"""
        try:
            with open(NAME_FILE, "r", encoding="utf-8") as f:
                name = f.read().strip()
            if name and name != self.title:
                self.title = name[:24]
                try:
                    self.win.title(self.title)
                except Exception:
                    pass
                self._render()
        except Exception:
            pass
        try:
            self.win.after(4000, self._name_loop)
        except Exception:
            pass

    def _pump(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "mic":
                    self._mic_done(payload)
        except queue.Empty:
            pass
        except Exception:
            pass
        try:
            self.win.after(120, self._pump)
        except Exception:
            pass

    def run(self):
        try:
            self.win.mainloop()
        except KeyboardInterrupt:
            pass


def main():
    enable_dpi()
    Bubble().run()


if __name__ == "__main__":
    main()
