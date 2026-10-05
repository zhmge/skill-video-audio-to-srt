#!/usr/bin/env node
/**
 * fetch_audio.js — 从 B 站视频链接匿名获取音频流（DASH m4s），无需登录。
 *
 * 用法:
 *   node fetch_audio.js <BV号或视频URL> <输出文件.m4s> [分P页码]
 *
 * 示例:
 *   node fetch_audio.js https://www.bilibili.com/video/BV1TG4y157f4 audio.m4s
 *   node fetch_audio.js BV1TG4y157f4 audio.m4s 2          # 第二个分P
 *
 * 流程: view API → cid/title → playurl(fnval=16) → 音频候选
 *       按 id 降序 30280(192k) > 30232(132k) > 30216(64k)，
 *       每个候选 baseUrl → backupUrl 逐个降级尝试。
 *       URL 带 ?p=N 时自动取对应分P（命令行第 3 参数优先）。
 *       本脚本只处理单个分P；合集/多P批量请逐个调用。
 *
 * 成功时向 stdout 打印 JSON: {"title","aid","bvid","cid","page","bytes","out"}
 *
 * 实测教训（勿简化）:
 *   1. 所有请求必须带 Referer: https://www.bilibili.com/ —— 否则 CDN 返回 403。
 *   2. curl 对部分 CDN 节点 SSL 握手直接失败(exit 35)，Node fetch 可靠 ——
 *      本脚本因此用 Node 而非 curl/wget。
 *   3. 响应体 > 1MB 才算下载成功（CDN 偶发返回空体/错误页，状态码可能是 200）。
 *
 * 退出码: 0 成功 | 2 参数错误 | 6 全部候选失败
 */

"use strict";

const fs = require("fs");
const path = require("path");

const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";
const HEADERS = {
  "User-Agent": UA,
  Referer: "https://www.bilibili.com/",
  Origin: "https://www.bilibili.com",
};

function die(code, msg) {
  console.error(`[fetch_audio] ERROR: ${msg}`);
  process.exit(code);
}

/** 从参数中提取 BV 号与可选的 p 页码 */
function parseTarget(raw) {
  const bvMatch = String(raw).match(/BV[0-9A-Za-z]{10}/);
  if (!bvMatch) return null;
  let page = null;
  try {
    const u = new URL(String(raw));
    const p = u.searchParams.get("p");
    if (p && /^\d+$/.test(p) && Number(p) > 0) page = Number(p);
  } catch (_) {
    /* 不是合法 URL，按裸 BV 号处理 */
  }
  return { bvid: bvMatch[0], page };
}

async function getJson(url) {
  const res = await fetch(url, { headers: HEADERS });
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
  return res.json();
}

async function download(url, outPath) {
  const res = await fetch(url, { headers: HEADERS });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const buf = Buffer.from(await res.arrayBuffer());
  if (buf.length < 1024 * 1024) {
    throw new Error(`body too small (${buf.length}B) — likely an error page`);
  }
  fs.writeFileSync(outPath, buf);
  return buf.length;
}

async function main() {
  const [rawTarget, outArg, pageArg] = process.argv.slice(2);
  if (!rawTarget || !outArg) {
    console.error(
      "用法: node fetch_audio.js <BV号或视频URL> <输出文件.m4s> [分P页码]"
    );
    process.exit(2);
  }
  const target = parseTarget(rawTarget);
  if (!target) die(2, `无法从参数中解析出 BV 号: ${rawTarget}`);
  const outPath = path.resolve(outArg);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });

  // 1) view API: 标题 + 默认 cid + 分P列表
  const view = await getJson(
    `https://api.bilibili.com/x/web-interface/view?bvid=${target.bvid}`
  );
  if (view.code !== 0 || !view.data) {
    die(6, `view API 失败 code=${view.code} message=${view.message}`);
  }
  const d = view.data;
  let cid = d.cid;
  let page = target.page ?? 1;
  if (Array.isArray(d.pages) && d.pages.length > 1) {
    const hit = d.pages.find((pg) => pg.page === page);
    if (!hit) {
      die(
        2,
        `分P ${page} 不存在（该视频共 ${d.pages.length} 个分P，范围 1-${d.pages.length}）`
      );
    }
    cid = hit.cid;
  } else {
    page = 1;
  }

  console.error(
    `[fetch_audio] title="${d.title}" page=${page}/${(d.pages || [1]).length} cid=${cid}`
  );

  // 2) playurl API: DASH 音频候选
  const play = await getJson(
    `https://api.bilibili.com/x/player/playurl?bvid=${target.bvid}&cid=${cid}&fnval=16`
  );
  if (play.code !== 0 || !play.data || !play.data.dash) {
    die(6, `playurl API 失败 code=${play.code} message=${play.message}`);
  }
  const audios = (play.data.dash.audio || [])
    .slice()
    .sort((a, b) => b.id - a.id); // 30280 > 30232 > 30216

  if (audios.length === 0) die(6, "playurl 未返回任何音频流");

  // 3) 逐候选下载: 每条音频先 baseUrl 再 backupUrl
  const candidates = [];
  for (const a of audios) {
    for (const u of [a.baseUrl, ...(a.backupUrl || [])]) {
      if (u) candidates.push({ id: a.id, url: u });
    }
  }
  for (const c of candidates) {
    try {
      const bytes = await download(c.url, outPath);
      const summary = {
        title: d.title,
        aid: d.aid,
        bvid: target.bvid,
        cid,
        page,
        bytes,
        out: outPath,
      };
      // 回调式退出：确保 stdout flush 完成后再 exit（管道模式下 write 是异步的）
      process.stdout.write(JSON.stringify(summary) + "\n", () => process.exit(0));
      return;
    } catch (e) {
      console.error(`[fetch_audio] 候选(id=${c.id})失败: ${e.message}`);
    }
  }
  die(6, `全部 ${candidates.length} 个候选均下载失败`);
}

main().catch((e) => die(6, e.stack || String(e)));
