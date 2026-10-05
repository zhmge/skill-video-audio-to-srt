#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
transcribe.py — 音频/视频 → faster-whisper 本地转写 → segments.json + proofread.tsv

用法:
  python transcribe.py <音频/视频文件> --out-dir <输出目录> [选项]

选项:
  --out-dir DIR     产物目录（默认：输入文件所在目录）
  --model DIR       模型目录。优先级：本参数 > 环境变量 FW_MODEL_DIR
                    > 默认 ~/.workbuddy/models/fw-large-v3
  --language LANG   语言代码（如 zh、en）。默认自动检测；
                    短片段建议显式指定以防误判。
  --cpu             强制 CPU 推理（int8）。默认走 GPU（float16）。
  --source-url URL  来源链接（可选，仅记录进 segments.json 便于追溯）

产物:
  segments.json   {"language", "source_url", "model", "device", "segments":[{start,end,text}]}
  proofread.tsv   校对视图（index/start/end/text，UTF-8 带 BOM，Excel 可直接打开）

退出码: 0 成功 | 2 参数错误 | 3 环境缺失（模型/ffmpeg） | 7 转写失败
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import time
import wave

EXIT_OK, EXIT_ARGS, EXIT_ENV, EXIT_TRANSCRIBE = 0, 2, 3, 7

DEFAULT_MODEL = os.path.join(
    os.path.expanduser("~"), ".workbuddy", "models", "fw-large-v3"
)


def die(code: int, msg: str) -> None:
    print(f"[transcribe] ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


# ────────────────────────── 实测教训（勿简化） ──────────────────────────
# ctranslate2 用普通 LoadLibrary 查找 cublas64_12.dll，只搜索 PATH；
# os.add_dll_directory() 对它无效，必须把 nvidia pip wheel 的 bin 目录追加进
# PATH。删掉这段，GPU 模式必报 "Library cublas64_12.dll is not found"。
def register_cuda_dll_dirs() -> None:
    if os.name != "nt":
        return  # 非 Windows 走系统 CUDA，见 references/environment-setup.md
    site = sysconfig.get_paths()["purelib"]
    dll_dirs = []
    for sub in (
        os.path.join("nvidia", "cublas", "bin"),
        os.path.join("nvidia", "cudnn", "bin"),
        os.path.join("nvidia", "cuda_nvrtc", "bin"),
    ):
        p = os.path.join(site, sub)
        if os.path.isdir(p):
            dll_dirs.append(p)
            os.add_dll_directory(p)
    if dll_dirs:
        os.environ["PATH"] = ";".join(dll_dirs) + ";" + os.environ["PATH"]
        for p in dll_dirs:
            print(f"[dll] {p}", flush=True)
    else:
        print(
            "[warn] site-packages 下未找到 nvidia/*/bin —— "
            "nvidia-cublas-cu12 等是否已安装？见 references/environment-setup.md",
            file=sys.stderr,
        )


def find_ffmpeg():
    """三级回退: imageio-ffmpeg 自带二进制 → 系统 PATH → None（报错附指引）。"""
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            return exe, "imageio-ffmpeg"
    except Exception:
        pass
    exe = shutil.which("ffmpeg")
    if exe:
        return exe, "PATH"
    return None, None


def prepare_audio(input_path: str, out_dir: str, ffmpeg_exe: str):
    """任何输入 → 16kHz 单声道 pcm_s16le wav。返回 (wav路径, 是否经过转码)。"""
    try:
        with wave.open(input_path, "rb") as w:
            if (
                w.getframerate() == 16000
                and w.getnchannels() == 1
                and w.getsampwidth() == 2
            ):
                return input_path, False  # 已是目标格式，直接用
    except wave.Error:
        pass  # 不是标准 wav（m4s/mp4/mp3…），走 ffmpeg 转码

    out_wav = os.path.join(
        out_dir,
        os.path.splitext(os.path.basename(input_path))[0] + ".audio16k.wav",
    )
    cmd = [
        ffmpeg_exe, "-y", "-i", input_path,
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", out_wav,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(out_wav):
        tail = (r.stderr or "")[-800:]
        die(EXIT_ENV, f"ffmpeg 转码失败（exit {r.returncode}）:\n{tail}")
    return out_wav, True


def main() -> None:
    ap = argparse.ArgumentParser(description="faster-whisper 本地转写")
    ap.add_argument("input", help="音频/视频文件（含 B 站音频流 .m4s）")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--language", default=None,
                    help="语言代码（zh/en…）；缺省自动检测")
    ap.add_argument("--cpu", action="store_true")
    ap.add_argument("--source-url", default=None)
    args = ap.parse_args()

    if not os.path.isfile(args.input):
        die(EXIT_ARGS, f"输入文件不存在: {args.input}")
    out_dir = os.path.abspath(args.out_dir or os.path.dirname(os.path.abspath(args.input)))
    os.makedirs(out_dir, exist_ok=True)

    model_dir = (
        args.model
        or os.environ.get("FW_MODEL_DIR")
        or DEFAULT_MODEL
    )
    model_dir = os.path.expanduser(model_dir)
    if not os.path.isdir(model_dir):
        die(
            EXIT_ENV,
            "模型目录不存在: {}\n获取方法见 skill 的 references/environment-setup.md"
            "（hf-mirror 直链下载 4 个文件 + 字节数校验）".format(model_dir),
        )

    # ffmpeg（在 import faster_whisper 之前定位，缺依赖尽早报错）
    ffmpeg_exe, src = find_ffmpeg()
    if not ffmpeg_exe:
        die(
            EXIT_ENV,
            "找不到 ffmpeg。任选其一:\n"
            "  1) 在当前 venv 内 pip install imageio-ffmpeg（自带二进制，推荐）\n"
            "  2) 系统级安装 ffmpeg（winget install Gyan.FFmpeg / apt install ffmpeg），"
            "装完新开终端使 PATH 生效",
        )
    print(f"[ffmpeg] using {src}: {ffmpeg_exe}", flush=True)

    wav_path, converted = prepare_audio(args.input, out_dir, ffmpeg_exe)
    if converted:
        print(f"[audio] transcoded -> {wav_path}", flush=True)

    # DLL 注册必须在 import faster_whisper 之前
    register_cuda_dll_dirs()
    from faster_whisper import WhisperModel

    device = "cpu" if args.cpu else "cuda"
    # ── 实测教训（勿简化）──
    # RTX 50 系(Blackwell) 上 compute_type 默认 auto 会选 int8_float16，
    # 直接报 CUBLAS_STATUS_NOT_SUPPORTED；显式 float16 在各代显卡上均安全。
    compute_type = "int8" if args.cpu else "float16"
    print(f"[load] model={model_dir} device={device} compute_type={compute_type}",
          flush=True)
    t0 = time.time()
    model = WhisperModel(model_dir, device=device, compute_type=compute_type)
    print(f"[load] done in {time.time() - t0:.1f}s", flush=True)

    # ── 实测教训（勿简化）──
    # 不要把文件路径直接交给 transcribe()：fw 会走 PyAV（av.open(..., metadata_errors=...)），
    # venv 中 av 与该签名不兼容时必报 TypeError。
    # 用 wave+numpy 读 wav，以 float32 数组喂模型，彻底绕开 PyAV。
    with wave.open(wav_path, "rb") as w:
        pcm = np_frombuffer_i16(w)
    audio_np = pcm.astype("float32") / 32768.0
    dur = len(audio_np) / 16000.0
    est = "GPU 约 1/7（实测 716s 音频含加载共 102s）；CPU 慢一个量级以上" if not args.cpu else "CPU 较慢，视核数而定"
    print(f"[audio] {dur:.1f}s loaded; 预计耗时: {est}", flush=True)

    t1 = time.time()
    try:
        segments, info = model.transcribe(
            audio_np,
            language=args.language,  # None = 自动检测
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        result = []
        for seg in segments:
            text = seg.text.strip()
            if text:
                result.append(
                    {"start": round(seg.start, 3), "end": round(seg.end, 3), "text": text}
                )
                print(f"[{seg.start:8.2f} -> {seg.end:8.2f}] {text}", flush=True)
    except Exception as e:
        die(EXIT_TRANSCRIBE, f"转写失败: {e}")
    print(f"[transcribe] {len(result)} segments in {time.time() - t1:.1f}s "
          f"(detected language: {info.language})", flush=True)

    seg_json = os.path.join(out_dir, "segments.json")
    with open(seg_json, "w", encoding="utf-8") as f:
        json.dump(
            {
                "language": info.language,
                "source_url": args.source_url,
                "model": model_dir,
                "device": device,
                "segments": result,
            },
            f, ensure_ascii=False, indent=1,
        )

    tsv_path = os.path.join(out_dir, "proofread.tsv")
    with open(tsv_path, "w", encoding="utf-8-sig", newline="") as f:
        f.write("index\tstart\tend\ttext\n")
        for i, s in enumerate(result):
            f.write(f"{i}\t{s['start']}\t{s['end']}\t{s['text']}\n")

    print(f"[done] {seg_json}\n[done] {tsv_path}", flush=True)


def np_frombuffer_i16(w):
    """延迟导入 numpy；断言保证 wav 是 16kHz 单声道 pcm_s16le（prepare_audio 保证）。"""
    import numpy as np

    assert (
        w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2
    ), "wav 必须是 16kHz 单声道 pcm_s16le"
    return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


if __name__ == "__main__":
    main()
