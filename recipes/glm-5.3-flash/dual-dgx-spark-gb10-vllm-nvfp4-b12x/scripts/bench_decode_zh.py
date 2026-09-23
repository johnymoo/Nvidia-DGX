#!/usr/bin/env python3
"""中文散文 decode 基准（2026-09-21 方法论定稿）。

本栈（GLM-5.3 NVFP4 B12X）的中文行为（实测结论，见 working doc 09-21）：
  - 中文技术提问 → 先长英文 reasoning（thinking on/off 皆然；off 时正文也是英文，
    语言遵从性差，属模型行为）；
  - 因此中文正文速度必须用"轻思考写作任务 + reasoning/content 分相计时"来测。

方法：写作类中文任务（直接开始正文），流式分相计时：
  reasoning 相（英文）与 content 相（中文）各报 chars/s；
  content 的 tok/s 用 usage 总 token 按字符比例折算（est 口径）。
"""

import json
import os
import statistics
import time
import urllib.request

BASE = os.environ.get("BENCH_BASE", "http://127.0.0.1:8890")
MODEL = os.environ.get("BENCH_MODEL", "GLM-5.3-Flash-EXL3")
ZH_PROMPT = "请用中文写一篇约400字的短文，主题：秋天的校园。直接开始正文。"


def run(max_tokens=3000, prompt=ZH_PROMPT):
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0, "max_tokens": max_tokens,
        "stream": True, "stream_options": {"include_usage": True},
    }
    req = urllib.request.Request(
        BASE + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    r_first = c_first = r_last = c_last = None
    r_chars = c_chars = 0
    content = []
    usage = None
    with urllib.request.urlopen(req, timeout=900) as resp:
        for raw in resp:
            line = raw.strip()
            if not line.startswith(b"data:"):
                continue
            p = line[5:].strip()
            if p == b"[DONE]":
                continue
            o = json.loads(p)
            if o.get("usage"):
                usage = o["usage"]
            ch = (o.get("choices") or [{}])[0].get("delta") or {}
            t = time.perf_counter()
            rc = ch.get("reasoning_content") or ch.get("reasoning") or ""
            cc = ch.get("content") or ""
            if rc:
                if r_first is None:
                    r_first = t
                r_last = t
                r_chars += len(rc)
            if cc:
                if c_first is None:
                    c_first = t
                c_last = t
                c_chars += len(cc)
                content.append(cc)
    text = "".join(content)
    zh = sum(1 for x in text if "\u4e00" <= x <= "\u9fff")
    total = (usage or {}).get("completion_tokens") or 0
    r_s = (r_last - r_first) if r_first else 0
    c_s = (c_last - c_first) if c_first else 0
    c_toks_est = round(total * c_chars / max(r_chars + c_chars, 1)) if c_chars else 0
    return {
        "reasoning_chars": r_chars, "reasoning_s": round(r_s, 1),
        "content_chars": c_chars, "content_zh_chars": zh,
        "content_s": round(c_s, 1),
        "content_tok_s_est": round(c_toks_est / c_s, 1) if c_s else None,
        "content_chars_s": round(c_chars / c_s, 1) if c_s else None,
        "content_head": text[:50],
    }


if __name__ == "__main__":
    run(max_tokens=200)  # warm
    runs = [run() for _ in range(3)]
    tps = [r["content_tok_s_est"] for r in runs if r["content_tok_s_est"]]
    cps = [r["content_chars_s"] for r in runs if r["content_chars_s"]]
    out = {
        "prompt": "zh-essay-autumn-campus", "model": MODEL,
        "note": "content tok/s 为 usage 按字符比例折算的 est 口径",
        "runs": runs,
        "content_tok_s_median": statistics.median(tps) if tps else None,
        "content_chars_s_median": statistics.median(cps) if cps else None,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
