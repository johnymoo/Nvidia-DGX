#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8004")
MODEL = os.environ.get("MODEL", "qwen3.6-35b-fp8")
TAG = os.environ.get("EVAL_TAG", "unknown")
OUT_DIR = Path(os.environ.get("OUT_DIR", "/home/chriswang/project/nvidia-dgx/qwen36-dgx-spark/benchmark_outputs"))
OUT_DIR.mkdir(parents=True, exist_ok=True)
TS = datetime.now().strftime("%Y%m%d-%H%M%S")
OUT_JSON = OUT_DIR / f"quality-eval-{TAG}-{TS}.json"
OUT_MD = OUT_DIR / f"quality-eval-{TAG}-{TS}.md"

# Lightweight deterministic regression/quality suite.
# The goal is not a full benchmark leaderboard, but a fast FP8 vs NVFP4 sanity check.
TESTS = [
    {"id":"arith_1", "cat":"math", "prompt":"只输出最终答案，不要解释：37 * 24 + 19 = ?", "expect":["907"]},
    {"id":"arith_2", "cat":"math", "prompt":"只输出最终答案，不要解释：如果 3x + 7 = 52，x 等于多少？", "expect":["15"]},
    {"id":"arith_3", "cat":"math", "prompt":"只输出最终答案，不要解释：A train travels 120 km in 2 hours. What is the average speed in km/h?", "expect":["60"]},
    {"id":"riddle_1", "cat":"reasoning", "prompt":"只输出最终答案，不要解释：一个农民有17只羊，除了9只以外都死了，还剩几只？", "expect":["9"]},
    {"id":"riddle_2", "cat":"reasoning", "prompt":"只输出最终答案，不要解释：5台机器5分钟生产5个零件，100台机器生产100个零件需要多少分钟？", "expect":["5"]},
    {"id":"riddle_3", "cat":"reasoning", "prompt":"只输出最终答案，不要解释：Sally has 3 brothers. Each brother has 1 sister. How many sisters does Sally have?", "expect":["0"]},
    {"id":"bat_ball", "cat":"reasoning", "prompt":"只输出最终答案，不要解释：A bat and a ball cost $1.10 together. The bat costs $1 more than the ball. How much does the ball cost?", "expect":["0.05", "5 cents", "$0.05"]},
    {"id":"logic_1", "cat":"logic", "prompt":"只输出最终答案，不要解释：All bloops are razzies. All razzies are lazzies. Are all bloops definitely lazzies? Answer yes or no.", "expect":["yes"]},
    {"id":"logic_2", "cat":"logic", "prompt":"只输出最终答案，不要解释：If no mammals are reptiles and all dogs are mammals, can a dog be a reptile? Answer yes or no.", "expect":["no"]},
    {"id":"alg_1", "cat":"coding", "prompt":"只输出最终答案，不要解释：最长递增子序列 LIS 的经典 O(n log n) 算法时间复杂度是什么？", "expect":["O(n log n)", "O(N log N)", "n log n"]},
    {"id":"python_1", "cat":"coding", "prompt":"只输出最终答案，不要解释：Python 表达式 list(reversed([1,2,3])) 的结果是什么？", "expect":["[3, 2, 1]", "[3,2,1]"]},
    {"id":"json_1", "cat":"format", "prompt":"只输出合法 JSON，不要解释：给出对象，字段 answer 的值为 42，字段 ok 的值为 true。", "expect":["json_answer_42_ok_true"]},
    {"id":"zh_knowledge", "cat":"knowledge", "prompt":"只输出最终答案，不要解释：中国四大发明之一、用于确定方向的工具是什么？", "expect":["指南针"]},
    {"id":"en_knowledge", "cat":"knowledge", "prompt":"Only output the final answer: What gas do plants primarily absorb during photosynthesis?", "expect":["carbon dioxide", "CO2", "carbon-dioxide"]},
    {"id":"long_retrieve_small", "cat":"long_retrieval", "prompt":"开头事实：紫色钥匙编号是 7319。" + ("无关背景。"*800) + "末尾问题：只输出紫色钥匙编号。", "expect":["7319"]},
    {"id":"long_two_fact", "cat":"long_retrieval", "prompt":"开头事实：A=137。" + ("中间噪声文本。"*1000) + "末尾事实：B=29。请只输出 A*B+64 的最终数字。", "expect":["4037"]},
]


def request_chat(prompt: str) -> dict:
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 256,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = Request(f"{BASE_URL}/v1/chat/completions", data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers={"Content-Type":"application/json"}, method="POST")
    t0 = time.perf_counter()
    with urlopen(req, timeout=180) as resp:
        raw = resp.read().decode("utf-8")
    wall = time.perf_counter() - t0
    data = json.loads(raw)
    if "error" in data:
        return {"error": data["error"], "wall_s": wall, "raw": data}
    choice = data.get("choices", [{}])[0]
    msg = choice.get("message", {})
    content = msg.get("content") or ""
    reasoning = msg.get("reasoning") or msg.get("reasoning_content") or ""
    return {
        "content": content,
        "reasoning": reasoning,
        "finish_reason": choice.get("finish_reason"),
        "usage": data.get("usage", {}),
        "wall_s": wall,
        "raw": data,
    }


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def judge(test: dict, content: str) -> tuple[bool, str]:
    norm = normalize(content)
    # Handle JSON special judge.
    if "json_answer_42_ok_true" in test["expect"]:
        try:
            obj = json.loads(content)
            return (obj.get("answer") == 42 and obj.get("ok") is True), "json_exact"
        except Exception:
            # fallback if JSON embedded in prose
            m = re.search(r"\{[\s\S]*\}", content)
            if m:
                try:
                    obj = json.loads(m.group(0))
                    return (obj.get("answer") == 42 and obj.get("ok") is True), "json_embedded"
                except Exception:
                    pass
            return False, "json_parse_failed"
    for exp in test["expect"]:
        e = normalize(exp)
        if e in norm:
            return True, f"contains:{exp}"
    return False, "no_expected_substring"


def main():
    results = []
    for i, test in enumerate(TESTS, 1):
        print(f"[{i}/{len(TESTS)}] {TAG} {test['id']}...", flush=True)
        res = request_chat(test["prompt"])
        content = res.get("content", "")
        ok, why = judge(test, content)
        row = {
            "id": test["id"],
            "category": test["cat"],
            "ok": ok,
            "judge": why,
            "expected": test["expect"],
            "content": content,
            "content_preview": content[:400],
            "finish_reason": res.get("finish_reason"),
            "usage": res.get("usage"),
            "wall_s": res.get("wall_s"),
            "error": res.get("error"),
        }
        results.append(row)
        print(json.dumps({"id": row["id"], "ok": ok, "finish": row["finish_reason"], "wall_s": row["wall_s"], "preview": row["content_preview"][:120]}, ensure_ascii=False), flush=True)
    total = len(results)
    passed = sum(1 for r in results if r["ok"])
    by_cat = {}
    for r in results:
        c = r["category"]
        by_cat.setdefault(c, {"total":0,"passed":0})
        by_cat[c]["total"] += 1
        by_cat[c]["passed"] += int(r["ok"])
    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "tag": TAG,
        "model": MODEL,
        "endpoint": BASE_URL,
        "total": total,
        "passed": passed,
        "accuracy": passed/total if total else 0,
        "by_category": by_cat,
        "results": results,
    }
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# Quality eval {TAG}", "",
        f"- time: {report['timestamp']}",
        f"- score: **{passed}/{total} = {passed/total:.1%}**", "",
        "| ID | Category | Pass | Finish | Output preview |",
        "|---|---|---:|---|---|",
    ]
    for r in results:
        preview = (r["content_preview"] or "").replace("|", "\\|").replace("\n", " ")[:120]
        lines.append(f"| `{r['id']}` | {r['category']} | {'✅' if r['ok'] else '❌'} | {r['finish_reason']} | {preview} |")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print("SAVED", OUT_JSON, OUT_MD)

if __name__ == "__main__":
    main()
