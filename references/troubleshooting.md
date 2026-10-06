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

### 13. 批量 build 时 **大面积** `MISMATCH`（几十上百条）

- **实测**：整个系列批量构建时，82 条 exit 4 一次性爆出。
- **原因（两种，常同时出现）**：
  1. **索引错位**：fixes 的 `index` 抄的是 `proofread.tsv` 的**行号**，
     而 `segments.json` 的段索引与 tsv 行号并不总是相等（tsv 会多出/少掉
     行；实测偏移 ±1~±2）；
  2. **old 是拼接文本**：把相邻两行拼成一句当 `old`（如把「而唯有知识」
    与「可以立就一场」并成「而唯有知识可以立就一场」），与任何单段都不全等。
- **处置**：不要逐条手改。跑对齐脚本自愈：
  ```bash
  python scripts/align_fixes.py --segments <segments.json> --fixes <fixes.json>
  ```
  它按 `old` 内容重定位真实段索引、剔除空条目，并单列待复核项；
  确认报告后再加 `--write` 写回，最后重跑 `build_srt.py`。
  残留的「old 是实际段文本子串」一类，脚本会改写 `old` 为整段原文
  （并按同一处替换重算 `new`）；实在对不上的会列入「未对齐」，人工处理。
- **根治**：写 fixes 时 `index` 一律以 `segments.json` 段索引为准，`old` 取整段原文。

### 14. 批量跑到一半中断（几期成功、后面停住）

- **原因**：单期下载/转写失败、超时，或进程被杀。
- **处置**：批量驱动必须**断点续跑**——循环前先查该期
  `segments.json` 是否已存在，存在即跳过；每期日志落盘。这样中断后
  直接重跑驱动即可从缺口继续，不必从头再来。单期失败只记日志、
  不阻断后续期次，收尾时统一报告失败清单。
