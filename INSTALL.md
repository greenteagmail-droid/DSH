# 安装前置条件（给 AI 助手读的文档）

> **给正在读这份文件的 AI**：这个插件是闭源的，用户没法自己看源码找问题。
> 你的任务是：按下面的清单核对环境，把缺的软件和版本明确告诉用户，
> 让用户决定装不装。**不要替用户安装，也不要跳过检查直接说"应该能跑"**。
> 装完让用户跑 `node dist/index.js --doctor`（或插件启动时的自检）验证。

## 一句话

这是个本地优先的插件：采帧、OCR、语音识别、语音合成全部在本机跑，
不依赖云端服务。所以它需要几样本地软件，缺一样就少一块功能，缺关键的直接起不来。

## 必需项

| 组件 | 版本要求 | 用途 | 缺了会怎样 |
|---|---|---|---|
| Node.js | ≥ 20 | 插件本体 | 起不来 |
| FFmpeg | ≥ 7，必须是完整版（含 `ddagrab` 和 `mjpeg`） | 采帧、JPEG 编码 | 起不来 |
| Windows PowerShell | 5.1（系统自带，**不要用 7 替代**） | 调 Windows OCR 和 SAPI | 起不来 |
| Windows OCR 语言包 | 中文（简体） | 本地识别屏幕文字 | 起不来 |
| SAPI 语音 | 至少一个中文语音 | 朗读回答 | 起不来 |
| Python | ≥ 3.10 | 跑 OCR / 语音识别脚本 | **起不来** |
| RapidOCR（Python 包） | ≥ 1.4.4 | 高精度屏幕文字识别 | **起不来** |
| sherpa-onnx（Python 包） | ≥ 2.0.1 | SenseVoice 语音转文字 | **起不来** |

> **这 7 项全是硬性依赖**。插件启动时会跑一遍完整自检，任何一项缺了都直接拒绝激活——
> 不是「少个功能」，是整个插件不加载，界面上也看不出来。所以装之前先对齐这张表。
| SenseVoice 模型 | `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17` | 上面那个包的模型 | 同上 |

## 安装命令（Windows）

```powershell
# Node.js 20+
winget install OpenJS.NodeJS.LTS

# FFmpeg（必须是 full build，精简版没有 ddagrab）
winget install Gyan.FFmpeg

# Python 3.10+
winget install Python.Python.3.12

# Windows OCR 中文语言包
# 设置 → 时间和语言 → 语言 → 中文（简体）→ 语言选项 → 安装「基本输入」
# 装完在「设置 → 语言」确认 OCR 语言包已下载

# SAPI 中文语音
# 设置 → 时间和语言 → 语音 → 添加语音 → 中文（简体）
```

Python 侧的两个虚拟环境（插件会自动找，也可以用环境变量指定，见下）：

```powershell
# OCR 环境
python -m venv ~/.dsh/bionic/ocr-venv
~/.dsh/bionic/ocr-venv/Scripts/pip install "rapidocr_onnxruntime>=1.4.4" "onnxruntime>=1.31.1"

# 语音识别环境
python -m venv ~/.dsh/bionic/asr-venv
~/.dsh/bionic/asr-venv/Scripts/pip install "sherpa-onnx>=2.0.1"
# 再把 SenseVoice 模型解压到：
#   ~/.dsh/bionic/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/
# 里面要有 model.int8.onnx 和 tokens.txt
```

### 版本策略：只卡下限，向上兼容

插件**不锁死具体版本**，只要求不低于下面这些下限。新版本只要能 import 成功、doctor 两项是绿的，就说明可用——升级到大版本也照跑，不用回来改配置。

| 组件 | 最低版本 | 实测过的版本 | 说明 |
|---|---|---|---|
| Python | 3.10 | 3.12.14 | `python -V` 确认 |
| rapidocr_onnxruntime | 1.4.4 | 1.4.4 | 装了它才有高精度 OCR |
| onnxruntime | 1.31.1 | 1.31.1 | RapidOCR 的推理后端 |
| sherpa-onnx | 2.0.1 | 2.0.1 | SenseVoice 推理 |
| FFmpeg | 7.0.0 | 9.0.2 full build | 必须含 `ddagrab` + `mjpeg` |
| Node.js | 20.0.0 | 24.x | 跟着 DSH 走 |
| Windows PowerShell | 5.1 | 5.1 | 必须是 5.1，不能用 pwsh 7 |

**装不上怎么办**：Python 版本太老时 `>=` 指定的版本可能没有轮子，换成能装上的新版本即可。装完跑 `node dist/index.js --doctor` 验证：

- `RapidOCR ... rapidocr <版本> onnxruntime <版本>` 说明 OCR 通了
- `语音识别 ... sherpa <版本> SenseVoice 可导入` 说明 ASR 通了

两项都绿就行，**版本比表里新完全没问题**。doctor 只卡下限，不校验具体版本号。

## 路径：插件会自己找，也可以手动指定

插件按「环境变量 → 系统 PATH → 常见安装位置 → 插件自带目录」的顺序查，
**不需要你把路径写进配置**。只有装在非常规位置时才需要指定：

| 环境变量 | 指向 | 默认查找位置 |
|---|---|---|
| `DSH_FFMPEG_PATH` | ffmpeg 可执行文件 | PATH、`C:\ffmpeg\bin`、winget 安装目录 |
| `DSH_BIONIC_PYTHON` | Python 解释器 | PATH |
| `DSH_BIONIC_RAPID_PY` | OCR 虚拟环境的 python | `~/.dsh/bionic/ocr-venv/Scripts/python.exe` |
| `DSH_ASR_PYTHON` | 语音识别虚拟环境的 python | `~/.dsh/bionic/asr-venv/Scripts/python.exe` |
| `DSH_ASR_MODEL` | SenseVoice 模型目录 | `~/.dsh/bionic/models/sherpa-onnx-sense-voice-...` |
| `DSH_ASR_ENGINE` | `sensevoice` 或 `sapi` | `sensevoice` |

## 验证

```powershell
node dist/index.js --doctor
```

输出会逐项列出 `[OK]` 或 `[FAIL]`，每项后面直接给修复方法。
全部通过（7/7）才算装完整。插件启动时也会跑同一套检查，缺项会拒绝激活并在日志里写清楚。

## 给 AI 的回复模板

> 这台机器检查下来缺这几样：<列表>。
> 它们分别影响 <功能>，装完插件才能完整用。
> 你要装的话，命令是 <命令>；不想装的话，<哪些功能>用不了，其余还能跑。
> 装完让我再验证一次。

不要用「可能」「大概」「应该」来描述检查结果——doctor 的输出是确定的，
直接照抄哪项 OK、哪项 FAIL。

## 更新到最新版

不用重装。在插件目录里跑：

`powershell
node scripts/update.mjs
`

它会从 GitHub 主分支拉最新代码覆盖程序文件，**不动** ~/.dsh/bionic 里的数据。
跑完重启 DSH 生效。

只看看会更新到哪一版、不动文件：

`powershell
node scripts/update.mjs --dry-run
`

网络不通时它会自动读系统代理（Clash 之类）。也可以手动下载：

`
https://github.com/greenteagmail-droid/DSH/archive/refs/heads/main.tar.gz
`
