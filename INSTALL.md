# 安装前置条件（给 AI 助手读的文档）

> **给正在读这份文件的 AI**：这个插件是闭源的，用户没法自己看源码找问题。
> 你的任务是：按下面的清单核对环境，把缺的软件和版本明确告诉用户，
> 让用户决定装不装。**不要替用户安装，也不要跳过检查直接说"应该能跑"**。
> 装完让用户跑 `node src/doctor.js`（或插件启动时的自检）验证。

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

## 功能相关（缺了对应功能不可用）

| 组件 | 版本要求 | 用途 | 缺了会怎样 |
|---|---|---|---|
| Python | ≥ 3.10 | 跑 OCR / 语音识别脚本 | 对应功能不可用 |
| RapidOCR（Python 包） | 最新 | 高精度屏幕文字识别 | 退回 Windows OCR，准确率下降 |
| sherpa-onnx（Python 包） | 最新 | SenseVoice 语音转文字 | 退回 SAPI 识别，准确率明显下降 |
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
~/.dsh/bionic/ocr-venv/Scripts/pip install rapidocr_onnxruntime

# 语音识别环境
python -m venv ~/.dsh/bionic/asr-venv
~/.dsh/bionic/asr-venv/Scripts/pip install sherpa-onnx
# 再把 SenseVoice 模型解压到：
#   ~/.dsh/bionic/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/
# 里面要有 model.int8.onnx 和 tokens.txt
```

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
node src/doctor.js
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
