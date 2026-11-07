# 故障修复手册（给 AI 助手读的文档）

> **给正在读这份文件的 AI**：这个插件闭源，用户看不到源码，所以出问题时你是唯一的
> 排查入口。按下面的顺序做，**每一步都要先问用户、再动手**，不要自己改系统设置。
>
> 核心原则：先定位「哪个功能不能用」，再按功能查对应的依赖，最后给出最小修复动作。

## 第一步：问清楚，不要猜

出问题先问这三句，答案不同，修的方向完全不同：

1. **哪个功能不行？**（采帧 / 看图 / 语音转文字 / 语音朗读 / 悬浮窗 / 打字提问）
2. **是完全没反应，还是报错？**（有报错就把原文发我）
3. **之前能用吗？**（一直不能 = 环境缺东西；突然不能 = 状态或文件权限）

拿到答案再往下查，不要一上来就重装。

## 第二步：跑自检，拿到确定结论

```powershell
node dist/index.js --doctor
```

七项检查，每项要么 `[OK]` 要么 `[FAIL]`，`[FAIL]` 后面直接写了修法。**照抄结果**，
不要用「可能」「应该」来描述。全部 OK 但功能还是不行，说明不是依赖问题，跳到第四节。

## 第三步：按功能查依赖

| 功能 | 依赖 | 自检项 | 不通时的最小修复 |
|---|---|---|---|
| 采帧存帧 | FFmpeg ≥ 7 完整版（要 `ddagrab` + `mjpeg`） | `ffmpeg` | `winget install Gyan.FFmpeg`，确认不是精简版；装完重开终端 |
| 看图（交给模型） | FFmpeg + 至少一帧被录下来 | `ffmpeg` | 先确认插件在采帧（status 里有帧数）；帧数为 0 就是采帧没起来 |
| 屏幕文字识别 | RapidOCR 或 Windows OCR | `rapidocr` / `ocr` | 缺 RapidOCR 会退回 Windows OCR，能用但准确率低；要装看 INSTALL.md |
| 语音转文字 | sherpa-onnx + SenseVoice 模型 | `语音识别` | 缺就退回 SAPI 识别，准确率明显下降；要装看 INSTALL.md |
| 语音朗读 | SAPI 中文语音 | `sapi` | 设置 → 时间和语言 → 语音 → 添加中文语音 |
| 悬浮窗 | Python 3.10+ 带 tkinter | 无（Python 不在自检里） | 见下方"悬浮窗专项" |
| 打字提问 | 悬浮窗可用 | 无 | 同悬浮窗专项 |

## 悬浮窗专项（自检不覆盖，单独查）

悬浮窗是 Python 起的独立进程，它起不来时插件本体是正常的，只是没窗口。

```powershell
# 1. 手动跑一次，看真实报错
python examples\floating-chat\window.py
```

| 报错 | 原因 | 修法 |
|---|---|---|
| `ModuleNotFoundError: tkinter` | Python 没带 tkinter | 重装 Python，勾选 tcl/tk and IDLE |
| `需要带 tkinter 的 Python` | 用到了精简版/Store 版 | 换 python.org 的完整安装包 |
| 无报错但没窗口 | 窗口在屏幕外 | 删 `~/.dsh/watch-window.json` 再启动，位置会重置 |
| 窗口一闪就没 | 父进程 pid 判断失败 | 手动跑能撑住就是插件调用方式的问题，把日志发出来 |

## 第四节：全都 OK 但功能不行

按这个顺序排除：

1. **插件有没有真的加载**：看 DSH 日志里有没有 `[bionic]` 开头的行。没有就是插件没激活。
2. **在不在采帧**：`bionic({action:"status"})`。没在录先调 `record`。
3. **帧有没有**：status 里帧数 0 说明 ffmpeg 起来了但没画面（多半是 ddagrab 在远程桌面/虚拟机上失效）。
4. **提问窗有没有在听**：status 里「提问窗」那一行。没在听，打字和语音都不会唤醒会话。
5. **语音链路**：`~/.dsh/bionic/voice.log`，看有没有 `spawned` 之后紧跟 `child closed`——那是 SAPI 进程崩了。

## 第五步：路径问题怎么修

插件按「环境变量 → PATH → 常见安装位置 → 约定目录」自动找，正常不需要配。
装在非常规位置时，用环境变量指过去（设完要重启 DSH）：

```powershell
[Environment]::SetEnvironmentVariable('DSH_FFMPEG_PATH','D:\tools\ffmpeg\bin\ffmpeg.exe','User')
[Environment]::SetEnvironmentVariable('DSH_BIONIC_PYTHON','D:\Python312\python.exe','User')
[Environment]::SetEnvironmentVariable('DSH_BIONIC_RAPID_PY','D:\venvs\ocr\Scripts\python.exe','User')
[Environment]::SetEnvironmentVariable('DSH_ASR_PYTHON','D:\venvs\asr\Scripts\python.exe','User')
[Environment]::SetEnvironmentVariable('DSH_ASR_MODEL','D:\models\sensevoice','User')
```

设完让用户**关掉 DSH 再开**，环境变量不会热生效。

想验证某个路径找没找到，让用户跑：

```powershell
node -e "import('./src/paths.js').then(m=>console.log(m.resolveAll()))"
```

输出里每项都带 `from`，说明是按哪条规则找到的；`null` 就是没找到。

## 第六步：修不动的时候

如果依赖都装了、路径也对、还是不行，判断是不是插件自己的问题：

1. 让用户把 `~/.dsh/bionic/` 下的 `ask.log`、`voice.log`、`mic.state` 发过来
2. 看 `mic.state` 最后一行：卡在 `waiting` 说明回复没送到，卡在 `processing` 说明转写卡死
3. 这些日志里没有任何隐私内容（只有时间戳和状态词），可以放心让用户发

**不要做的事**：
- 不要让用户重装 DSH 来"试试看"
- 不要改 `~/.dsh` 之外的系统配置
- 不要在没跑 doctor 的情况下凭猜测说"缺 XX"
- 不要建议关闭杀毒软件（除非确认是它拦了 ffmpeg 子进程）

## 给用户的回复模板

> 检查结果：<贴 doctor 输出里 FAIL 的那几行>。
> 影响的功能是 <功能>，不修的话 <具体表现>。
> 修法：<一条命令或一个设置项>。
> 要我改吗？改完需要重启 DSH 才生效。
