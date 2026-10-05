# 环境搭建（environment-setup）

本 skill 运行需要三样东西：**Python 依赖**、**ASR 模型**、**ffmpeg**。
以下步骤在全新机器上按顺序执行一遍即可。文末附本机实测参考值。

## 1. Python 依赖

要求 Python ≥ 3.9（实测 3.13）。在 skill 目录内建独立 venv，避免污染全局：

```bash
cd <skill目录>/video-audio-to-srt
python -m venv .venv-audio
# Windows (bash):
.venv-audio/Scripts/python.exe -m pip install -r requirements.txt
# Linux/macOS:
# .venv-audio/bin/pip install -r requirements.txt
```

`requirements.txt` 中 `ctranslate2` 与 `nvidia-*` 各版本是配套实测组合，
**不要单独升级其中某一个**（CUDA 12.x 系列内部强耦合）。

> 该组合**不包含 torch**——faster-whisper(ctranslate2) 直接调 cublas/cudnn，
> 比常规 GPU 推理栈轻得多。

## 2. 模型获取（不入 skill，独立存放）

默认模型目录约定为 `~/.workbuddy/models/fw-large-v3/`（跨项目复用，路径直观）。
也可用环境变量 `FW_MODEL_DIR` 或 `transcribe.py --model` 指向任意位置。

faster-whisper 版 large-v3（CT2 float16 格式，来源 HuggingFace `Systran/faster-whisper-large-v3`），
经国内镜像 hf-mirror 直链下载 5 个文件（**直连即可，无需代理**）：

```bash
mkdir -p ~/.workbuddy/models/fw-large-v3
cd ~/.workbuddy/models/fw-large-v3
BASE=https://hf-mirror.com/Systran/faster-whisper-large-v3/resolve/main
for f in config.json preprocessor_config.json tokenizer.json vocabulary.json model.bin; do
  curl -L -o "$f" "$BASE/$f"
done
```

**下载完成后按字节数校验**（型号目录里多一个/少一个字节的损坏文件会以
玄学方式失败）：

| 文件 | 字节数（应完全一致） |
| --- | --- |
| model.bin | 3,087,284,237 |
| tokenizer.json | 2,480,617 |
| vocabulary.json | 1,068,114 |
| config.json | 2,394 |
| preprocessor_config.json | 340 |

校验命令：`ls -l`（Git Bash / Linux）或
PowerShell `Get-ChildItem | Select-Object Name,Length`。

## 3. ffmpeg

`transcribe.py` 按以下三级回退自动定位，任一可用即可：

1. **imageio-ffmpeg**（`requirements.txt` 已含）——自带二进制，零配置，推荐；
2. **系统 PATH** 中的 ffmpeg（winget / apt / brew 安装的均可）；
3. 都没有 → 报错并附安装指引（此时 `pip install imageio-ffmpeg` 最省事）。

注意：系统级安装（如 winget）只刷新**新开的终端**，当前已开的 shell
需要重开才能在 PATH 中看到 ffmpeg——但第 1 级 imageio-ffmpeg 不受影响。

> **分段漂移提示**（实测）：不同 ffmpeg 实现的 AAC 解码存在 ±LSB 级
> 差异（同一视频 0.0123% 字节不同），会让转写分段粒度略有不同
> （538 段 vs 528 段），属正常现象，详见 troubleshooting.md 第 12 条。
> 需要与既有转写产物对齐时，用系统 ffmpeg 预转 16kHz 单声道 wav。

## 4. GPU 与 CPU

| 模式 | compute_type | 命令 | 适用 |
| --- | --- | --- | --- |
| GPU（默认） | float16（脚本内写死） | `transcribe.py ...` | 有 NVIDIA 显卡；**float16 对全部显卡架构安全**，勿改成 auto |
| CPU | int8 | `transcribe.py ... --cpu` | 无 N 卡 / 小模型 |

性能基准（实测）：716 秒中文音频，large-v3 + GPU（float16 / beam 5 / VAD），
含 3.5s 模型加载共约 102 秒。CPU 慢一个量级以上，长音频慎用。

非 Windows（Linux/macOS）说明：脚本的 DLL 注册只在 Windows 生效；
Linux 上若报找不到 libcublas，设置
`export LD_LIBRARY_PATH=<venv>/lib/python*/site-packages/nvidia/{cublas,cudnn,cuda_nvrtc}/lib:$LD_LIBRARY_PATH`。

## 本机实测参考值（2026-10，示例）

- Windows 11 + RTX 5070 Ti Laptop（Blackwell），31.4 GB 内存
- Python 3.13.12（managed venv），faster-whisper 1.2.1 + ctranslate2 4.8.2
- nvidia-cublas-cu12 12.9.2.10 / nvidia-cudnn-cu12 9.27.0.42
- 模型 `~/.workbuddy/models/fw-large-v3/`，5 文件共 3,090,835,702 字节
- 模型加载 3.5s；538 段 / 12 分钟音频约 102s 完成
