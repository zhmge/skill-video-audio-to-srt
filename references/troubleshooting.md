# 故障排查（troubleshooting）

按症状查找。每条 = 症状 → 原因 → 处置。

---

### 1. `Library cublas64_12.dll is not found or cannot be loaded`

- **原因**：ctranslate2 用普通 `LoadLibrary` 查找 CUDA DLL，只搜 `PATH`；
  `os.add_dll_directory()` 对它无效。
- **处置**：`transcribe.py` 已内置「把 `site-packages/nvidia/{cublas,cudnn,cuda_nvrtc}/bin`
  追加进 `os.environ["PATH"]`」的注册逻辑（标注"实测教训，勿简化"）。
  若自己另写的入口脚本触发此错，补上同样的注册；并确认
  `nvidia-cublas-cu12` / `nvidia-cudnn-cu12` 已装进**当前 venv**。

### 2. `CUBLAS_STATUS_NOT_SUPPORTED`（GPU 模式一加载就崩）

- **原因**：`compute_type="auto"` 在 RTX 50 系（Blackwell）上会选 `int8_float16`，
  该卡不支持。
- **处置**：保持脚本写死的 `float16`（对全部显卡架构安全）。不要改回 auto。

### 3. `TypeError: av.open() got an unexpected keyword argument 'metadata_errors'`

- **原因**：faster-whisper 收到**文件路径**时内部走 PyAV；venv 中的 av 版本
  与 fw 调用签名不兼容。
- **处置**：`transcribe.py` 已用 wave+numpy 读 wav、以 float32 数组喂
  `transcribe()` 绕开 PyAV。不要为省事把文件路径直接传给 `transcribe()`。

### 4. B 站音频下载 403 / 空文件

- **原因**：请求缺 `Referer` 头；或 CDN 返回 200 但 body 是错误页（<1MB）。
- **处置**：`fetch_audio.js` 已带 `Referer/UA/Origin`，并要求 body > 1MB，
  不达标自动换下一个候选（baseUrl → backupUrl、30280 → 30232 → 30216）。
  不要裸用 curl/wget。

### 5. curl 下载 B 站 CDN 报 SSL 错误（exit 35）

- **原因**：部分 CDN 节点（如 upos-sz-mirrorcos）与 curl 的 SSL 握手不兼容。
- **处置**：用 `fetch_audio.js`（Node fetch 实测可靠），不要用 curl。

### 6. `MISMATCH: index N: 期望[...] 实际[...]`（build_srt 断言失败）

- **原因**：fixes.json 的 `old` 与该段当前文本不一致——通常是索引错位
  （拿旧 proofread.tsv 的行号改新转写）或 old 抄错。
- **处置**：这是**保护机制，勿绕过**。以**当前** proofread.tsv 为准核对
  index 与 old 后重试。宁可整体失败，不可静默改错段。

### 7. 转写文本段尾吞字 / 同音字错（如「五次方」丢「方」、氪金→科金）

- **原因**：ASR 固有错误模式（中文实测高发：同音字、段尾吞字；片尾致辞、
  专有名词、数字公式重灾区）。
- **处置**：走 proofread.tsv 校对循环，重点核专有名词与数字；有视频简介/
  已知文本可对照锁定片尾。修错不改写。

### 8. 短音频语言识别错误

- **原因**：自动语言检测在短片段上不可靠。
- **处置**：`transcribe.py --language zh`（或其他语言代码）显式指定。

### 9. `找不到 ffmpeg`

- **原因**：imageio-ffmpeg 未装且系统 PATH 无 ffmpeg。
- **处置**：当前 venv 内 `pip install imageio-ffmpeg`（最省事），或系统级
  安装 ffmpeg。winget 装完**新开终端** PATH 才生效。

### 10. `模型目录不存在`

- **原因**：默认路径 `~/.workbuddy/models/fw-large-v3/` 未放置模型。
- **处置**：按 `environment-setup.md` 第 2 节下载（hf-mirror 直链 +
  字节数校验），或用 `--model` / 环境变量 `FW_MODEL_DIR` 指向已有模型。

### 11. GPU 转写比预期慢很多

- **排查顺序**：① 日志里是否 `device=cuda compute_type=float16`；
  ② 是否误加 `--cpu`；③ 任务管理器确认 GPU 在跑而非回退 CPU；
  ④ beam_size 是否被调大（默认 5 是速度/质量实测平衡点）。

### 12. 同一视频两次转写段数不同（±N 段），或与既有转写产物对不上

- **实测**：同一视频、同参数，用 imageio-ffmpeg 转码得 528 段，用系统
  ffmpeg 9.0.2 转码得 538 段——两个 wav 大小相同，但 0.0123% 的字节
  不同（AAC 解码的浮点实现差异）。±LSB 级微扰足以让 VAD/encoder 改变
  个别分段决策；GPU 非确定性也可能贡献少量漂移。
- **定性**：正常现象，不是 bug。分段粒度不是转写质量的承诺，逐条全文
  差异只有零星局部词（实测 12 处 opcode），主体内容一致。
- **处置**：校对以**本环境的转写产物**为准。若需要与既有产物对齐
  （比如接着上次的校对继续），用**系统 ffmpeg** 预转 16kHz 单声道 wav
  再喂 `transcribe.py`——脚本检测到输入已是 16k/mono/pcm_s16le 时会
  跳过转码直接使用。
