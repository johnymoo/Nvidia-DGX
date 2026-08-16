#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def load(path: Path) -> dict:
    value = json.loads(path.read_text())
    if value.get("status") != "passed":
        raise RuntimeError(f"quality benchmark failed: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qwen36", type=Path, required=True)
    parser.add_argument("--qwen38", type=Path, required=True)
    parser.add_argument("--deepseek", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    q36, q38 = load(args.qwen36), load(args.qwen38)
    deepseek = load(args.deepseek) if args.deepseek else None
    if q36.get("harness_id") != "x570-qwen-quality-v2" or q38.get("harness_id") != q36.get("harness_id"):
        raise RuntimeError("harness identity mismatch")
    if set(q36["categories"]) != set(q38["categories"]):
        raise RuntimeError("category mismatch")
    if deepseek:
        if deepseek.get("harness_id") != q36.get("harness_id"):
            raise RuntimeError("DeepSeek harness identity mismatch")
        if set(deepseek["categories"]) != set(q36["categories"]) - {"image_recognition"}:
            raise RuntimeError("DeepSeek must contain exactly the non-vision categories")
    categories = {}
    for name in q36["categories"]:
        left, right = q36["categories"][name], q38["categories"][name]
        if [(case["id"], case.get("prompt"), case.get("expected")) for case in left["cases"]] != [(case["id"], case.get("prompt"), case.get("expected")) for case in right["cases"]]:
            raise RuntimeError(f"case mismatch: {name}")
        if name == "article_writing":
            lscore = sum(case["points"] for case in left["cases"]) / sum(case["max_points"] for case in left["cases"])
            rscore = sum(case["points"] for case in right["cases"]) / sum(case["max_points"] for case in right["cases"])
        else:
            lscore = sum(bool(case["passed"]) for case in left["cases"]) / len(left["cases"])
            rscore = sum(bool(case["passed"]) for case in right["cases"]) / len(right["cases"])
        values = {"qwen36": round(lscore, 6), "qwen38": round(rscore, 6), "qwen38_delta": round(rscore - lscore, 6), "total_cases": len(left["cases"])}
        if deepseek and name in deepseek["categories"]:
            third = deepseek["categories"][name]
            if [(case["id"], case.get("prompt"), case.get("expected")) for case in left["cases"]] != [(case["id"], case.get("prompt"), case.get("expected")) for case in third["cases"]]:
                raise RuntimeError(f"DeepSeek case mismatch: {name}")
            if name == "article_writing":
                dscore = sum(case["points"] for case in third["cases"]) / sum(case["max_points"] for case in third["cases"])
            else:
                dscore = sum(bool(case["passed"]) for case in third["cases"]) / len(third["cases"])
            values.update({"deepseek": round(dscore, 6), "deepseek_delta": round(dscore - lscore, 6)})
        else:
            values.update({"deepseek": None, "deepseek_delta": None})
        categories[name] = values
    q36_macro = round(sum(item["qwen36"] for item in categories.values()) / len(categories), 6)
    q38_macro = round(sum(item["qwen38"] for item in categories.values()) / len(categories), 6)
    result = {
        "status": "passed",
        "harness_id": q36["harness_id"],
        "qwen36_macro": q36_macro,
        "qwen38_macro": q38_macro,
        "macro_delta": round(q38_macro - q36_macro, 6),
        "deepseek_macro": round(sum(item["deepseek"] for item in categories.values() if item["deepseek"] is not None) / sum(item["deepseek"] is not None for item in categories.values()), 6) if deepseek else None,
        "categories": categories,
        "input_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (args.qwen36, args.qwen38, args.deepseek) if path},
        "scoring_note": "Vision, programming, and math are exact/binary; writing is objective constraint fulfillment, not subjective literary quality.",
    }
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
