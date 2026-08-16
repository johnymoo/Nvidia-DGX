#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import struct
import subprocess
import time
import urllib.request
import uuid
import zlib
from pathlib import Path


def png(width: int, height: int, rectangles: list[tuple[int, int, int, int, tuple[int, int, int]]]) -> bytes:
    pixels = [[(245, 245, 245) for _ in range(width)] for _ in range(height)]
    for x0, y0, x1, y1, color in rectangles:
        for y in range(max(0, y0), min(height, y1)):
            for x in range(max(0, x0), min(width, x1)):
                pixels[y][x] = color
    raw = b"".join(b"\x00" + b"".join(bytes(pixel) for pixel in row) for row in pixels)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


VISION = [
    ("dominant_blue", [(0, 0, 160, 120, (35, 105, 220))], "What is the dominant color? Answer exactly one lowercase word.", "blue"),
    ("three_red_blocks", [(10, 20, 40, 70, (220, 45, 45)), (65, 20, 95, 70, (220, 45, 45)), (120, 20, 150, 70, (220, 45, 45))], "How many red rectangles are visible? Answer with one integer.", "3"),
    ("red_left_blue", [(15, 30, 65, 90, (220, 45, 45)), (95, 30, 145, 90, (35, 105, 220))], "Is the red block left or right of the blue block? Answer exactly left or right.", "left"),
    ("green_top_left", [(0, 0, 80, 60, (25, 170, 90)), (80, 0, 160, 60, (235, 200, 35)), (0, 60, 80, 120, (220, 45, 45)), (80, 60, 160, 120, (35, 105, 220))], "What color is the top-left quadrant? Answer exactly one lowercase word.", "green"),
    ("middle_tallest", [(15, 70, 45, 115, (70, 120, 205)), (65, 15, 95, 115, (70, 120, 205)), (115, 45, 145, 115, (70, 120, 205))], "Which bar is tallest: left, middle, or right? Answer exactly one word.", "middle"),
    ("two_blue_one_red", [(15, 25, 55, 85, (35, 105, 220)), (60, 25, 100, 85, (35, 105, 220)), (105, 25, 145, 85, (220, 45, 45))], "How many blue blocks are visible? Answer with one integer.", "2"),
]

PROGRAMMING = [
    ("is_prime", "Write Python code only. Implement def is_prime(n: int) -> bool.", [("is_prime(-3)", False), ("is_prime(0)", False), ("is_prime(1)", False), ("is_prime(2)", True), ("is_prime(97)", True), ("is_prime(221)", False)]),
    ("merge_intervals", "Write Python code only. Implement def merge_intervals(items) returning sorted merged [start,end] lists. Touching intervals merge.", [("merge_intervals([])", []), ("merge_intervals([[1,3],[2,6],[8,10],[10,12]])", [[1,6],[8,12]]), ("merge_intervals([[5,7],[1,2]])", [[1,2],[5,7]])]),
    ("group_anagrams", "Write Python code only. Implement def group_anagrams(words). Return groups sorted internally and sort groups by their first item.", [("group_anagrams(['eat','tea','tan','ate','nat','bat'])", [['ate','eat','tea'],['bat'],['nat','tan']]), ("group_anagrams([])", [])]),
    ("balanced", "Write Python code only. Implement def is_balanced(text: str) -> bool for (), [], and {}, ignoring other characters.", [("is_balanced('a({[]})')", True), ("is_balanced('([)]')", False), ("is_balanced('(()')", False), ("is_balanced('')", True)]),
    ("top_k", "Write Python code only. Implement def top_k_frequent(values, k). Return the k most frequent values ordered by descending frequency, then ascending value.", [("top_k_frequent([1,1,1,2,2,3],2)", [1,2]), ("top_k_frequent([4,4,2,2,1],2)", [2,4]), ("top_k_frequent([],0)", [])]),
]

WRITING = [
    {"id": "zh_release", "prompt": "用中文写一篇 180 到 260 个汉字的三段式产品发布短文。必须原样包含“本地推理”“隐私保护”“性能取舍”，不要使用项目符号。", "terms": ["本地推理", "隐私保护", "性能取舍"], "min": 180, "max": 260, "mode": "cjk", "paragraphs": 3, "no_bullets": True},
    {"id": "en_summary", "prompt": "Write a 120-160 word English technical summary in exactly two paragraphs. It must include the exact terms 'context window', 'GPU memory', and 'throughput'. No bullet list.", "terms": ["context window", "GPU memory", "throughput"], "min": 120, "max": 160, "mode": "words", "paragraphs": 2, "no_bullets": True},
    {"id": "risk_memo", "prompt": "Write a 160-230 word English decision memo with exactly three headings: Benefits, Risks, Recommendation. Mention benchmark evidence and rollback explicitly.", "terms": ["benchmark evidence", "rollback"], "headings": ["Benefits", "Risks", "Recommendation"], "min": 160, "max": 230, "mode": "words"},
    {"id": "zh_explainer", "prompt": "用中文写一篇 160 到 240 个汉字的说明文，用“高速公路”作类比解释并发推理。必须包含“请求”“吞吐”“延迟”，最后一句必须是“容量不是免费的。”", "terms": ["高速公路", "请求", "吞吐", "延迟", "容量不是免费的。"], "min": 160, "max": 240, "mode": "cjk", "ending": "容量不是免费的。"},
]

MATH = [
    ("percent", "A price of 200 is discounted by 15%, then taxed by 10%. What is the final price? Answer with the number only.", "187"),
    ("work_rate", "A can finish a job in 6 days and B in 3 days. How many days together? Answer with the number only.", "2"),
    ("sequence", "Find the next number: 2, 6, 12, 20, 30, ?. Answer with the integer only.", "42"),
    ("probability", "A fair die is rolled twice. What is the probability the sum is 7? Answer as a reduced fraction only.", "1/6"),
    ("algebra", "Solve 3(x-4)+2=2x+9. Answer with x only.", "19"),
    ("geometry", "A right triangle has legs 9 and 12. What is its hypotenuse? Answer with the number only.", "15"),
    ("combinatorics", "How many distinct arrangements are there of the letters in LEVEL? Answer with the integer only.", "30"),
    ("mixture", "How many liters of 20% solution must be mixed with 10 liters of 50% solution to get 30% solution? Answer with the number only.", "20"),
    ("modular", "What is the remainder when 7^100 is divided by 10? Answer with the integer only.", "1"),
    ("average", "The average of five numbers is 18. Four are 12, 17, 21, and 25. What is the fifth? Answer with the integer only.", "15"),
    ("distance", "A car travels 60 km/h for 1.5 hours and 80 km/h for 2 hours. Total distance? Answer with the number only.", "250"),
    ("logic", "All zargs are mips. No mip is a lon. Can any zarg be a lon? Answer exactly yes or no.", "no"),
]


def post(
    base: str,
    model: str,
    messages: list[dict],
    max_tokens: int = 700,
    thinking: str = "server-default",
) -> dict:
    body = {"model": model, "messages": messages, "temperature": 0, "max_tokens": max_tokens}
    if thinking == "off":
        body["chat_template_kwargs"] = {"enable_thinking": False}
    elif thinking != "server-default":
        body["chat_template_kwargs"] = {"enable_thinking": True}
        body["reasoning_effort"] = thinking
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    started = time.monotonic()
    with urllib.request.urlopen(req, timeout=900) as response:
        payload = json.load(response)
    message = payload["choices"][0]["message"]
    return {
        "content": message.get("content") or "",
        "reasoning": message.get("reasoning") or message.get("reasoning_content") or "",
        "finish_reason": payload["choices"][0].get("finish_reason"),
        "seconds": round(time.monotonic() - started, 3),
        "usage": payload.get("usage") or {},
    }


def clean_exact(value: str) -> str:
    return re.sub(r"[^a-z0-9/.-]+", "", value.strip().lower())


def extract_code(value: str) -> str:
    match = re.search(r"```(?:python)?\s*(.*?)```", value, re.S | re.I)
    return (match.group(1) if match else value).strip()


def run_code(code: str, checks: list[tuple[str, object]]) -> tuple[bool, str]:
    marker = uuid.uuid4().hex
    runner = "import base64,json,os\nns={}\nexec(compile(base64.b64decode(os.environ['SUBMISSION']),'<submission>','exec'),ns)\nvalues=[eval(item,ns) for item in json.loads(base64.b64decode(os.environ['EXPRESSIONS']))]\nprint(os.environ['MARKER']+json.dumps(values,separators=(',',':')))"
    command = ["docker", "run", "--rm", "--network", "none", "--read-only", "--memory", "128m", "--cpus", "1", "--pids-limit", "64", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "65534:65534", "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m", "-e", f"SUBMISSION={base64.b64encode(code.encode()).decode()}", "-e", f"EXPRESSIONS={base64.b64encode(json.dumps([item[0] for item in checks]).encode()).decode()}", "-e", f"MARKER={marker}", "python@sha256:a630a63cdb314e2d138a2fca3e375e319e8568346ffafac5b980f888630ac4f1", "python", "-I", "-c", runner]
    completed = subprocess.run(command, text=True, capture_output=True, timeout=20, check=False)
    detail = (completed.stdout + completed.stderr)[-2000:]
    matched = re.search(rf"(?m)^{marker}(.+)$", completed.stdout)
    actual = json.loads(matched.group(1)) if completed.returncode == 0 and matched else None
    expected = [item[1] for item in checks]
    return actual == expected, detail


def writing_score(case: dict, text: str) -> tuple[int, int, dict]:
    paragraphs = [item for item in re.split(r"\n\s*\n", text.strip()) if item.strip()]
    count = len(re.findall(r"[\u4e00-\u9fff]", text)) if case["mode"] == "cjk" else len(re.findall(r"\b[\w'-]+\b", text))
    checks = {"length": case["min"] <= count <= case["max"]}
    if "paragraphs" in case:
        checks["paragraphs"] = len(paragraphs) == case["paragraphs"]
    if case.get("no_bullets"):
        checks["no_bullets"] = not bool(re.search(r"(?m)^\s*[-*•]\s", text))
    checks.update({f"term:{term}": term.lower() in text.lower() for term in case["terms"]})
    for heading in case.get("headings", []):
        checks[f"heading:{heading}"] = len(re.findall(rf"(?mi)^\s*(?:#+\s*)?{re.escape(heading)}\s*:?[ \t]*$", text)) == 1
    if case.get("ending"):
        checks["ending"] = text.strip().endswith(case["ending"])
    return sum(checks.values()), len(checks), {"unit_count": count, "paragraph_count": len(paragraphs), "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exclude-category", action="append", choices=["image_recognition"], default=[])
    parser.add_argument(
        "--thinking",
        choices=["server-default", "off", "low", "medium", "xhigh"],
        default="server-default",
    )
    parser.add_argument("--max-token-multiplier", type=int, default=1)
    args = parser.parse_args()
    if args.max_token_multiplier < 1:
        parser.error("--max-token-multiplier must be at least 1")
    excluded = set(args.exclude_category)
    result = {
        "schema_version": 2,
        "harness_id": "x570-qwen-quality-v2",
        "tag": args.tag,
        "model": args.model,
        "base_url": args.base_url,
        "excluded_categories": sorted(excluded),
        "thinking_mode": args.thinking,
        "max_token_multiplier": args.max_token_multiplier,
        "categories": {},
        "status": "failed",
    }

    if "image_recognition" not in excluded:
        vision_rows = []
        for name, rects, prompt, expected in VISION:
            data = base64.b64encode(png(160, 120, rects)).decode()
            row = post(args.base_url, args.model, [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}}, {"type": "text", "text": prompt}]}], 64 * args.max_token_multiplier, args.thinking)
            actual = clean_exact(row["content"])
            vision_rows.append({"id": name, "prompt": prompt, "expected": expected, "actual": actual, "response": row["content"], "passed": actual == expected, "seconds": row["seconds"]})
        result["categories"]["image_recognition"] = {"score": sum(r["passed"] for r in vision_rows) / len(vision_rows), "passed": sum(r["passed"] for r in vision_rows), "total": len(vision_rows), "cases": vision_rows}

    code_rows = []
    for name, prompt, checks in PROGRAMMING:
        row = post(args.base_url, args.model, [{"role": "user", "content": prompt}], 900 * args.max_token_multiplier, args.thinking)
        passed, detail = run_code(extract_code(row["content"]), checks)
        code_rows.append({"id": name, "prompt": prompt, "expected": checks, "response": row["content"], "reasoning": row["reasoning"], "finish_reason": row["finish_reason"], "passed": passed, "seconds": row["seconds"], "executor_tail": detail})
    result["categories"]["programming"] = {"score": sum(r["passed"] for r in code_rows) / len(code_rows), "passed": sum(r["passed"] for r in code_rows), "total": len(code_rows), "cases": code_rows}

    writing_rows = []
    writing_points = writing_total = 0
    for case in WRITING:
        row = post(args.base_url, args.model, [{"role": "user", "content": case["prompt"]}], 700 * args.max_token_multiplier, args.thinking)
        points, total, detail = writing_score(case, row["content"])
        writing_points += points
        writing_total += total
        writing_rows.append({"id": case["id"], "prompt": case["prompt"], "points": points, "max_points": total, "score": points / total, "seconds": row["seconds"], "detail": detail, "response": row["content"], "reasoning": row["reasoning"], "finish_reason": row["finish_reason"], "usage": row["usage"]})
    result["categories"]["article_writing"] = {"score": writing_points / writing_total, "points": writing_points, "max_points": writing_total, "total": len(writing_rows), "cases": writing_rows}

    math_rows = []
    for name, prompt, expected in MATH:
        question = prompt.split(" Answer", 1)[0]
        row = post(args.base_url, args.model, [{"role": "user", "content": question + " Put the answer on the first line in the exact format FINAL: <answer>. Then show concise reasoning."}], 512 * args.max_token_multiplier, args.thinking)
        match = re.search(r"(?m)^FINAL:\s*([^\s]+)", row["content"], re.I)
        actual = clean_exact(match.group(1) if match else "")
        math_rows.append({"id": name, "prompt": question, "expected": expected, "actual": actual, "response": row["content"], "reasoning": row["reasoning"], "finish_reason": row["finish_reason"], "usage": row["usage"], "passed": actual == expected, "seconds": row["seconds"]})
    result["categories"]["mathematical_reasoning"] = {"score": sum(r["passed"] for r in math_rows) / len(math_rows), "passed": sum(r["passed"] for r in math_rows), "total": len(math_rows), "cases": math_rows}

    scores = [category["score"] for category in result["categories"].values()]
    result["overall_macro_score"] = sum(scores) / len(scores)
    result["status"] = "passed"
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"tag": args.tag, "overall_macro_score": result["overall_macro_score"], "categories": {key: value["score"] for key, value in result["categories"].items()}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
