---
name: video-audio-to-srt
description: >-
  从音频/视频文件的音轨生成本地 ASR 转写、带时间轴的 .srt 字幕。
  本地 GPU 推理（faster-whisper large-v3，12 分钟音频约 2 分钟），无需上传云端。
  输入支持任意来源的音频/视频文件（mp4/m4s/wav/mp3…）；B 站视频链接有内置
  匿名取音频模块（fetch_audio.js），其他平台自备音频文件即可。
  适用：视频无可用字幕轨/CC/AI 字幕、需要快速拿到带时间轴的完整文本。
  不要用于：视频存在独立字幕轨或 CC 字幕（直接抓字幕轨更快更准，不要 ASR）；
  用户只要笔记/大纲/摘要（那是转写后的下游整理，不是本 skill 职责）；
  翻译、润色、改写字幕内容（本 skill 只忠实转写 + 校对纠错）。
---

# video-audio-to-srt：音轨 → ASR 转写 → 校对 → SRT

把音频/视频的音轨经本地 faster-whisper 转写成带时间轴的分段文本，
经逐条校对纠错后产出最终 `.srt`。核心经验来自一次完整实测：
B 站硬字幕视频 → 匿名取音频 → GPU 转写 538 段 → 75 处校对修正 → 交付 SRT。

## 能力边界

- **输入**：任意音频/视频文件；B 站链接（单视频，含多分P的指定分P）。
  合集/多集批量见「批量模式」，**不合并多集输出**（每集一个独立 .srt）。
- **输出**：唯一交付物是 `.srt` 文件。不产出 txt/markdown 正文。
- **语言**：默认自动检测；短片段建议显式传语言。
- 转写是识别不是理解：同音字、段尾吞字等错误靠校对循环修复（见下）。

## 批量模式（系列 / 合集）

单集走下面的「工作流」；**整个系列（如一季 29 期）另有一套工程化跑法**，别用单集流程硬怼。

1. **建清单** `manifest.json`：每项 `{nn, bvid, title, safe_title, duration}`。
2. **建断点续跑驱动**：循环每期「下载音频 → 转写」，已产出 `segments.json` 即跳过，
   日志落盘（这样中断后可从任意点重启，不必从头再来）。逐期音频/转写产物分目录存放。
3. **逐期校对**：对每期读 `proofread.tsv` → 写该期 `fixes/NN.json`（见 ⑤）。
4. **统一命名与输出**：`NN_标题.srt`（两位期号 + 与视频标题一致的标题），
   全部输出到同一个交付目录；**最后一次性批量 build**，不要中途零散交付。
5. **批量 build**：循环调 `build_srt.py`。若大面积 exit 4，先跑 `align_fixes.py`
   自愈重对齐（见 ⑤-边角），再重试，**不要逐条手改**。

**跨期一致性词表（强烈建议）**：同一系列的 ASR 变体高度重复（同音字、专有名词、
代码关键字如 ctrl加系列 / const / 遍历 / 初始化 / 复制粘贴…）。开跑前先攒一份
「跨期共同词表」，后期各期直接套用，比每期从零识别快得多。

## 工作流

### ① 确认输入
向用户确认（缺失必问，不要猜）：
1. **输入**：B 站链接，或音频/视频文件的绝对路径；
2. **输出 .srt 路径**；
3. **来源链接**（可选）：提供了则写入 SRT 首行（下游约定读首行拼跳转链接）。

### ② 获取音频
- **B 站链接** → `scripts/fetch_audio.js`（零依赖 Node 18+）：
  ```bash
  node scripts/fetch_audio.js "https://www.bilibili.com/video/BVxxxx" /abs/path/audio.m4s
  ```
  成功时 stdout 输出一行 JSON（含 title/aid/cid/bytes），把 title 用于命名输出文件。
- **本地文件** → 直接用，跳到 ③。

### ③ 环境自检
依次检查（缺哪项补哪项，补法见 `references/environment-setup.md`）：
1. skill 目录下有 `.venv-audio/`（没有 → 按文档第 1 节创建）；
2. 模型目录存在（默认 `~/.workbuddy/models/fw-large-v3/`，
   可被 `--model` 或环境变量 `FW_MODEL_DIR` 覆盖；
   不存在 → 报错并附文档第 2 节的获取命令，**不要自行换小模型顶替**）；
3. ffmpeg（脚本内置三级回退：imageio-ffmpeg → 系统 PATH → 报错指引，一般无需干预）。

### ④ 转写
```bash
.venv-audio/Scripts/python.exe scripts/transcribe.py <输入文件> \
  --out-dir <输出目录> [--source-url <链接>] [--language zh] [--cpu]
```
（Linux/macOS 用 `.venv-audio/bin/python`。）
- 先根据音频时长向用户**报告预计耗时**（GPU 约为音频时长的 1/7）。
- 产物：`segments.json`（机器用）+ `proofread.tsv`（校对视图，Excel 可开）。
- 默认走 GPU + float16（脚本写死，勿改）；无 N 卡加 `--cpu`。

### ⑤ 校对循环（质量的关键，不可跳过）
1. 读 `proofread.tsv`（index/start/end/text），逐条校对文本；
2. 重点盯高发模式（**中文实测**，其他语言类比）：**同音字**（氪金→科金）、
   **段尾吞字**（"六的五次方"丢"方"）；专有名词、数字与公式、片尾致辞是重灾区；
   有视频简介/已知文本可对照锁定片尾；
3. 把确认的错误写成 `fixes.json`（数组，每项 `{"index","old","new"}`）。
   **关键约束（实测踩坑）**：
   - `index` 是 **`segments.json` 的段索引**，**不是 `proofread.tsv` 的行号** ——
     两者段数可能不同（实测出现 ±1~±2 偏移），照搬 tsv 行号会让 build 大面积 exit 4；
   - `old` 必须是该段的**完整原文**（逐字全等，**子串也不行**；也不要把多行拼成一句）；
   - 落盘前用「读 `segments.json` 第 index 段文本」核对，而不是凭记忆/凭 tsv 行号；
   - 空条目（`old == new`）必须剔除，它无意义且会污染断言。
   **原则：修错不改写**——只改识别错误，不润色口癖、不改句式；
4. 生成最终 SRT：
   ```bash
   .venv-audio/Scripts/python.exe scripts/build_srt.py \
     --segments <out-dir>/segments.json --fixes fixes.json \
     [--source-url <链接>] --out <最终.srt>
   ```
   `old` 逐字断言不匹配会整体失败（exit 4）——这是防索引错位的保护机制，
   以**当前** `proofread.tsv` / `segments.json` 为准核对后重试，**不要绕过断言**。
5. **批量场景：先自愈再 build**。若已有一批 fixes 但 index 疑似错位（如整体偏移、
   `old` 抄成了拼接文本），不要逐条手改，先跑对齐脚本重新定位：
   ```bash
   python scripts/align_fixes.py --segments <segments.json> --fixes <fixes.json> [--write]
   ```
   它按 `old` 内容把每条修正重新对到真实段索引、剔除空条目，并单列
   「相似度重定位」「同文多址」「未对齐」三类待复核项。默认只报告，`--write` 才写回。
   `align_fixes.py` 之后仍以 `build_srt.py` 的断言作最终保护。

### ⑥ 交付报告
报告内容：.srt 路径、cue 条数、应用的修正数、**存疑项清单**
（校对中拿不准的条目，附 index 与原文），供用户复核。

**批量交付额外要求**（整个系列一次交付时）：
- 逐期清单：期号 / 文件名 / 来源链接 / cue 数；
- 逐期修正数；
- 跨期存疑清单（各期无法还原的片段汇总）。
建议落一份 `_交付报告.md` 到交付目录。

## 硬规则（实测教训，违者必错）

1. GPU `compute_type` 写死 `float16`——RTX 50 系上 auto 会选 int8_float16 直接崩；
2. CUDA DLL 必须追加进 `os.environ["PATH"]`（`add_dll_directory` 对 ctranslate2 无效）；
3. 音频必须以 numpy float32 数组喂 `transcribe()`——文件路径会走 PyAV 地雷；
4. B 站请求必须带 `Referer: https://www.bilibili.com/`，否则 403；下载用 Node 而非 curl（部分 CDN 节点 curl SSL 握手失败）；
5. fixes.json 的 `old` 必须逐字匹配（断言机制实测拦下过索引错位）；
6. fixes.json 的 `index` 是 `segments.json` 的段索引，**不是 proofread.tsv 的行号**；
   `old` 必须是整段完整原文（子串、跨行拼接都不行），空条目须剔除；
7. `.srt` 是唯一交付物；不出 txt 正文，不合并多集，不翻译不改写。

## References（按需读取）

- `references/environment-setup.md` —— 首次使用 / 缺依赖 / 模型缺失 / 换机部署时读。
  含模型获取完整命令（hf-mirror 直链 5 文件 + 字节数校验）、venv 创建、GPU/CPU 取舍。
- `references/troubleshooting.md` —— 运行失败或结果异常时读。
  按症状索引：DLL 加载失败、CUBLAS 状态错误、PyAV TypeError、403、
  SSL exit 35、断言失败、吞字/同音字、语言误判等。
