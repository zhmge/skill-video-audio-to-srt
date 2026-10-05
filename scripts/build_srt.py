#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_srt.py — segments.json（+ 可选 fixes.json）→ 最终 .srt

用法:
  python build_srt.py --segments segments.json --out final.srt [--fixes fixes.json] [--source-url URL]

fixes.json 格式（数组，每项三条字段缺一不可）:
  [
    {"index": 0,   "old": "距离上个世纪", "new": "距离上个视频"},
    {"index": 423, "old": "就是六的五次", "new": "就是六的五次方"}
  ]
  index 是 proofread.tsv 中的行号（从 0 起）。
  old 是该段当前原文 —— 生成时逐字断言，不匹配则整体失败（防索引错位）。

SRT 约定:
  提供 --source-url 时，首行 = 来源链接、第二行 = 空行
  （下游工具约定读取首行拼跳转链接）；不提供则输出纯标准 SRT。
  时间码与正文以 CRLF 分隔。

退出码: 0 成功 | 2 参数错误 | 4 断言失败（old 与实际文本不符）
"""
import argparse
import json
import os
import sys

EXIT_OK, EXIT_ARGS, EXIT_MISMATCH = 0, 2, 4


def tc(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def main() -> None:
    ap = argparse.ArgumentParser(description="segments.json → SRT")
    ap.add_argument("--segments", required=True, help="transcribe.py 产出的 segments.json")
    ap.add_argument("--fixes", default=None, help="校对修正清单（可选）")
    ap.add_argument("--source-url", default=None, help="来源链接（可选，写入 SRT 首行）")
    ap.add_argument("--out", required=True, help="输出 .srt 路径")
    args = ap.parse_args()

    if not os.path.isfile(args.segments):
        print(f"[build_srt] ERROR: segments 不存在: {args.segments}", file=sys.stderr)
        sys.exit(EXIT_ARGS)
    with open(args.segments, encoding="utf-8") as f:
        data = json.load(f)
    segs = data["segments"]
    if not isinstance(segs, list) or not segs:
        print("[build_srt] ERROR: segments.json 中没有段", file=sys.stderr)
        sys.exit(EXIT_ARGS)

    applied = 0
    if args.fixes:
        if not os.path.isfile(args.fixes):
            print(f"[build_srt] ERROR: fixes 不存在: {args.fixes}", file=sys.stderr)
            sys.exit(EXIT_ARGS)
        with open(args.fixes, encoding="utf-8") as f:
            fixes = json.load(f)
        if not isinstance(fixes, list):
            print("[build_srt] ERROR: fixes.json 顶层必须是数组", file=sys.stderr)
            sys.exit(EXIT_ARGS)

        # ── 硬规则：old 必须逐字匹配当前文本 ──
        # 实测曾拦下一次索引错位（TSV 行号 ≠ 段索引），宁可整体失败也不静默改错段。
        mismatches = []
        for fx in fixes:
            try:
                idx, old, new = int(fx["index"]), fx["old"], fx["new"]
            except (KeyError, TypeError, ValueError):
                mismatches.append(f"格式错误: {fx!r}（需要 index/old/new 三字段）")
                continue
            actual = segs[idx]["text"] if 0 <= idx < len(segs) else None
            if actual != old:
                mismatches.append(f"index {idx}: 期望[{old}] 实际[{actual}]")
            else:
                segs[idx]["text"] = new
                applied += 1
        if mismatches:
            for m in mismatches:
                print(f"MISMATCH: {m}", file=sys.stderr)
            print(
                f"\n[build_srt] {len(mismatches)} 处断言失败，未写出文件。"
                "请以当前 proofread.tsv 为准核对 index 与 old 后重试。",
                file=sys.stderr,
            )
            sys.exit(EXIT_MISMATCH)

    lines = []
    if args.source_url:
        lines += [args.source_url, ""]
    for n, s in enumerate(segs, 1):
        lines += [str(n), f"{tc(s['start'])} --> {tc(s['end'])}", s["text"], ""]

    with open(args.out, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines).rstrip("\r\n") + "\n")

    src_note = f"，来源链接已写入首行" if args.source_url else ""
    print(f"OK: {len(segs)} 条 cue，应用 {applied} 处修正{src_note} -> {args.out}")


if __name__ == "__main__":
    main()
