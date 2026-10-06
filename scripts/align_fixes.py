#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
align_fixes.py — 把 fixes.json 的 index 重新对齐到 segments.json，并清扫空条目

用法:
  python align_fixes.py --segments segments.json --fixes fixes.json [--write]

背景（实测教训）:
  fixes.json 的 index 必须是 segments.json 的「段索引」，old 必须是该段「完整原文」。
  批量场景下极易把校对视图 proofread.tsv 的「行号」当成段索引写进 fixes——
  两者段数可能不同（实测出现 ±1~±2 偏移），于是 build_srt.py 大面积 exit 4。
  本脚本按 old 内容把每条修正重新定位到真实段索引，替代逐条手改。

做法:
  1. 剔除 old == new 的空条目（无意义改动）。
  2. 对 index 处文本 == old 的条目：视为已对齐，跳过。
  3. 否则在 segments 中按 old 匹配：
     a. 优先「全等匹配」；命中多个时取离原 index 最近的一个。
     b. 其次「包含匹配」（old 是某段文本的子串，或某段文本是 old 的子串）——
        此时把 old 改写为该段的完整原文，并按同一处替换重算 new。
     c. 再退化为相似度最近匹配（difflib，阈值可调）；命中则重定位 index，
        但**同时把 old 改写为该段完整原文**，new 保持用户意图（前缀扩展）。
        —— 这一档风险较高，会在报告中单列，建议人工复核。
  4. 仍无法定位的条目：保留原样，列入「未对齐」清单，绝不静默丢弃。

默认只打印报告、不写文件；加 --write 才就地覆盖 fixes.json。
退出码: 0 正常 | 2 参数错误 | 3 有未对齐项（配合 --write 时不阻断写入）
"""
import argparse
import difflib
import json
import os
import sys

EXIT_OK, EXIT_ARGS, EXIT_UNALIGNED = 0, 2, 3


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def replace_once(text, old_sub, new_sub):
    """在 text 中把 old_sub 替换为 new_sub（仅第一次）。返回 (新文本, 是否发生替换)。"""
    if old_sub and old_sub in text:
        return text.replace(old_sub, new_sub, 1), True
    return text, False


def align(segments, fixes, sim_threshold=0.6):
    texts = [s["text"] for s in segments]
    stats = {"total": len(fixes), "empty": 0, "already": 0,
             "exact": 0, "contains": 0, "fuzzy": 0, "ambiguous": 0}
    unaligned, fuzzy_items, ambiguous_items = [], [], []

    out = []
    for fx in fixes:
        try:
            idx = int(fx["index"])
            old = fx["old"]
            new = fx["new"]
        except (KeyError, TypeError, ValueError):
            unaligned.append({"reason": "缺 index/old/new 字段", "fix": fx})
            out.append(fx)
            continue

        # 1. 空条目
        if old == new:
            stats["empty"] += 1
            continue

        actual = texts[idx] if 0 <= idx < len(texts) else None

        # 2. 已对齐
        if actual == old:
            stats["already"] += 1
            out.append(fx)
            continue

        # 3a. 全等匹配
        exacts = [i for i, t in enumerate(texts) if t == old]
        if exacts:
            pick = min(exacts, key=lambda i: abs(i - idx))
            out.append({"index": pick, "old": old, "new": new})
            stats["exact"] += 1
            if len(exacts) > 1:
                # 同一 old 文本出现多次：取离原 index 最近者，但列入待复核
                stats["ambiguous"] += 1
                ambiguous_items.append((idx, exacts, pick, old))
            continue

        # 3b. 包含匹配（old 是某段子串）
        supers = [i for i, t in enumerate(texts) if old and old in t]
        if supers:
            pick = min(supers, key=lambda i: abs(i - idx))
            seg_text = texts[pick]
            rebuilt, ok = replace_once(seg_text, old, new)
            if ok:
                out.append({"index": pick, "old": seg_text, "new": rebuilt})
                stats["contains"] += 1
                continue

        # 3c. 相似度匹配（高风险，单独列出）
        best_i, best_r = -1, 0.0
        for i, t in enumerate(texts):
            r = difflib.SequenceMatcher(None, old, t).ratio()
            if r > best_r:
                best_r, best_i = r, i
        if best_i >= 0 and best_r >= sim_threshold:
            seg_text = texts[best_i]
            # 尝试用 old 的公共前后缀推测 new 的落点：直接以整段为准重算
            rebuilt, ok = replace_once(seg_text, old, new)
            if not ok:
                # old 不是整段子串：用相似度最高的公共片段替换
                sm = difflib.SequenceMatcher(None, old, seg_text)
                blocks = sm.get_matching_blocks()
                common = max(blocks, key=lambda b: b.size)
                sub_old = old[common.a:common.a + common.size]
                sub_new = new[common.a:common.a + common.size] if common.size else new
                if sub_old:
                    rebuilt, ok = replace_once(seg_text, sub_old, sub_new)
            if ok:
                out.append({"index": best_i, "old": seg_text, "new": rebuilt})
                stats["fuzzy"] += 1
                fuzzy_items.append((idx, best_i, round(best_r, 2), old, seg_text))
                continue

        # 4. 未对齐
        unaligned.append({"reason": "无法定位", "fix": fx,
                          "actual": actual, "best_ratio": round(best_r, 2)})
        out.append(fx)

    return out, stats, unaligned, fuzzy_items, ambiguous_items


def main():
    ap = argparse.ArgumentParser(description="把 fixes.json 的 index 对齐到 segments.json")
    ap.add_argument("--segments", required=True, help="segments.json 路径")
    ap.add_argument("--fixes", required=True, help="fixes.json 路径")
    ap.add_argument("--write", action="store_true",
                    help="就地覆盖 fixes.json（默认只打印报告）")
    ap.add_argument("--sim-threshold", type=float, default=0.6,
                    help="相似度匹配阈值（默认 0.6，越低越激进）")
    args = ap.parse_args()

    for p in (args.segments, args.fixes):
        if not os.path.isfile(p):
            print(f"[align_fixes] ERROR: 文件不存在: {p}", file=sys.stderr)
            sys.exit(EXIT_ARGS)

    data = load_json(args.segments)
    segs = data["segments"]
    fixes = load_json(args.fixes)
    if not isinstance(fixes, list):
        print("[align_fixes] ERROR: fixes.json 顶层必须是数组", file=sys.stderr)
        sys.exit(EXIT_ARGS)

    out, stats, unaligned, fuzzy_items, ambiguous_items = align(segs, fixes, args.sim_threshold)
    print(f"总条目 {stats['total']} | 剔除空条目 {stats['empty']} | "
          f"已对齐 {stats['already']} | 全等重定位 {stats['exact']} | "
          f"包含重定位 {stats['contains']} | 相似度重定位 {stats['fuzzy']} | "
          f"同文多址 {stats['ambiguous']}")

    if ambiguous_items:
        print(f"\n[同一 old 文本出现多次 {len(ambiguous_items)} 条 — 已取离原 index 最近者，建议复核]")
        for orig, cands, pick, old in ambiguous_items:
            print(f"  idx {orig} -> 选中 {pick}（候选 {cands}）：{old}")

    if fuzzy_items:
        print(f"\n[相似度重定位 {len(fuzzy_items)} 条 — 建议人工复核]")
        for orig, new_i, r, old, act in fuzzy_items:
            print(f"  idx {orig} -> {new_i} (sim={r})")
            print(f"    旧old: {old}")
            print(f"    实际 : {act}")

    if unaligned:
        print(f"\n[未对齐 {len(unaligned)} 条 — 请人工处理，不会自动丢弃]")
        for u in unaligned:
            print(f"  {u['reason']}: {u['fix']}")

    if args.write:
        with open(args.fixes, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"\n已写回 {args.fixes}（{len(out)} 条）")
    else:
        print("\n（未加 --write，仅报告，未修改文件）")

    sys.exit(EXIT_UNALIGNED if unaligned else EXIT_OK)


if __name__ == "__main__":
    main()
