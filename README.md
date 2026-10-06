# video-audio-to-srt

从音频/视频文件的音轨生成本地 ASR 转写，产出带时间轴的 `.srt` 字幕。

## 解决的问题

视频没有可用的字幕轨、CC 或 AI 字幕时，系统自带的语音识别要么要联网上传，要么给不出时间轴。这个 skill 在本机 GPU 上用 faster-whisper large-v3 做推理——12 分钟音频约 2 分钟出结果，音频不出本机。转写结果经逐条校对后生成最终 `.srt`。

## 处理流程

```
音频/视频 ──取音轨──▶ 本地 GPU 转写（faster-whisper large-v3）
                          │
                    segments.json + proofread.tsv
                          │
                     逐条校对 → fixes.json（修错不改写）
                          │
                     build_srt.py ──▶ 最终 .srt
```

## 功能

- **输入**：任意来源的音频/视频文件（mp4 / m4s / wav / mp3 …）；B 站视频有内置的匿名取音频模块 `fetch_audio.js`（零依赖，Node 18+ 即可），其他平台自备音频文件。
- **输出**：`.srt` 字幕文件。转录文本另存 `segments.json`（机器用）与 `proofread.tsv`（校对视图，Excel 可开）。
- **校对机制**：`fixes.json` 里的每条修正都带「原始整段文本」，`build_srt.py` 逐字断言匹配，索引错位会直接失败而不是静默改错地方。批量场景可先跑 `align_fixes.py` 按内容重新定位。
- **批量模式**：整个系列（如一季 29 期）有独立的工程化跑法——建清单、断点续跑、跨期统一词表、最后统一命名并一次性批量输出。

## 依赖

- Windows / Linux / macOS，Python 3.13
- 模型：faster-whisper large-v3（默认读 `~/.workbuddy/models/fw-large-v3/`，可用 `--model` 或 `FW_MODEL_DIR` 指向别处）
- ffmpeg（脚本内置三级回退：imageio-ffmpeg → 系统 PATH → 报错指引）
- Python 包见 `requirements.txt`——版本组合为 RTX 50 系 GPU 上实测验证的，`ctranslate2` 与 `nvidia-*` 的配套关系不应随意升级

NVIDIA GPU 走 CUDA + float16；无 N 卡时加 `--cpu` 退回 CPU 推理（明显更慢）。

## 开始使用

整个目录放入 agent skills 目录即可，`SKILL.md` 是入口。首次使用需按 `references/environment-setup.md` 创建 `.venv-audio/` 并下载模型。

## 产物

唯一交付物是 `.srt` 文件。批量交付时额外落一份 `_交付报告.md` 到交付目录，含逐期清单、修正数与跨期存疑项。

`.srt` 首行约定写入来源链接（可选），便于下游拼跳转链接。

## 已知限制

- 转写是识别不是理解。同音字、段尾吞字、专有名词与数字公式是主要错误来源，靠校对循环修复——有视频简介或已知文本时可对照锁定片尾。
- 校对**只修识别错误**，不润色口癖、不改句式，不做翻译与内容改写。
- 多集内容不合并输出，每集一个独立 `.srt`。
- 固定使用 large-v3，脚本不会自行换小模型顶替——模型缺失时报错并给出获取命令。

## License

[MIT](LICENSE)
