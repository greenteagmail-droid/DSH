# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)，格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

规则：`1.0.x` 只修 bug，`1.x.0` 加功能但不动对外接口，`2.0.0` 才允许改接口。
每一次发布，这里必须有一段对应版本的记录，`node scripts/release.mjs` 会检查。

## [Unreleased]

### 变更

- 插件更名为 **Bionic Intelligence**，npm 包名 `dsh-bionic-intelligence`，插件 id 同步更改。
  工具名 `bionic` 与数据目录 `~/.dsh/bionic` 保持不变（改数据目录会丢已有记录）。
- 全部源文件重写：png、speech、timer、tool-spec、capture、chat、voice、window、index、
  pipeline，以及 test 下的测试文件。

### 新增

- 画面比对（`src/motion.js`）：按步长取点比较相邻帧，给出变化面积占比。
  采样点 32400 个，每帧 0.195 ms。
- 双档落帧节拍：变化 ≤ 0.2%（约四个鼠标指针）时 1 帧/秒，超过时 4 帧/秒。
- `look` 直接返回落盘的 JPEG，不再转 PNG：省掉 85–108 ms 的转码，像素不变，体积小 4 倍。

- 运行支撑检查（`src/doctor.js`）：启动前全量校验 Node、FFmpeg、PowerShell/Windows OCR、
  SAPI、RapidOCR，任何一项不满足就拒绝安装与启动。
- 发布闸门（`scripts/release.mjs`）：版本一致性、CHANGELOG、测试、打包内容四项检查。
- `doctor-probe.ps1`：纯 ASCII 的 Windows 能力探针，输出 JSON，不依赖 PowerShell 7。

## [1.0.0] - 待发布

### 新增

- 静默屏幕记录：固定 1920×1080 JPEG 落盘，本地 OCR 建索引，不叫醒模型。
- 提问窗：候选帧列表、单帧查看、语音回答。
- 保留策略：5GB / 7 天，先到先删。

## [0.1.0] - 开发中（未发布）

- 改名前的内部版本，仅用于本地验证；发布时由 1.0.0 取代。
