#!/usr/bin/env python3
"""Compare two OpenAI-compatible multimodal services without changing them."""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import json
import re
import statistics
import struct
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone
from pathlib import Path


SERVICES = {
    "deepseek": {
        "base_url": "http://192.168.88.181:8890/v1",
        "model": "deepseek-v4-flash-0731",
        "thinking": {
            "off": {"thinking": False},
            "on": {"thinking": True, "reasoning_effort": "high"},
        },
    },
    "qwen": {
        "base_url": "http://192.168.88.181:8004/v1",
        "model": "qwen3.8-27b-mtp2",
        "thinking": {
            "off": {"enable_thinking": False},
            "on": {"enable_thinking": True, "reasoning_effort": "low"},
        },
    },
}

VISION_CASES = [
    ("dominant_blue", [(0, 0, 160, 120, (35, 105, 220))], "What is the dominant color? Answer exactly one lowercase word.", "blue"),
    ("three_red_blocks", [(10, 20, 40, 70, (220, 45, 45)), (65, 20, 95, 70, (220, 45, 45)), (120, 20, 150, 70, (220, 45, 45))], "How many red rectangles are visible? Answer with one integer.", "3"),
    ("red_left_blue", [(15, 30, 65, 90, (220, 45, 45)), (95, 30, 145, 90, (35, 105, 220))], "Is the red block left or right of the blue block? Answer exactly left or right.", "left"),
    ("green_top_left", [(0, 0, 80, 60, (25, 170, 90)), (80, 0, 160, 60, (235, 200, 35)), (0, 60, 80, 120, (220, 45, 45)), (80, 60, 160, 120, (35, 105, 220))], "What color is the top-left quadrant? Answer exactly one lowercase word.", "green"),
    ("middle_tallest", [(15, 70, 45, 115, (70, 120, 205)), (65, 15, 95, 115, (70, 120, 205)), (115, 45, 145, 115, (70, 120, 205))], "Which bar is tallest: left, middle, or right? Answer exactly one word.", "middle"),
    ("two_blue_one_red", [(15, 25, 55, 85, (35, 105, 220)), (60, 25, 100, 85, (35, 105, 220)), (105, 25, 145, 85, (220, 45, 45))], "How many blue blocks are visible? Answer with one integer.", "2"),
]

MENU_FIELDS = ["breakfast", "lunch_rice", "lunch_main_meat", "lunch_side1", "lunch_side2", "lunch_soup", "fruit", "afternoon_snack"]
MENU_PROMPT = """请识别这张图片中的幼儿园每周菜谱信息，并以 JSON 格式返回。

请严格按照以下 JSON 格式返回（不要包含其他文字，只返回 JSON）：
{
  "week_start": "YYYY-MM-DD",
  "week_end": "YYYY-MM-DD",
  "daily_menus": [
    {
      "date": "YYYY-MM-DD",
      "day_of_week": "周一",
      "breakfast": "早餐内容",
      "lunch_rice": "午餐主食",
      "lunch_main_meat": "午餐主荤",
      "lunch_side1": "午餐配菜1",
      "lunch_side2": "午餐配菜2（没有则填null）",
      "lunch_soup": "午餐汤",
      "fruit": "水果",
      "afternoon_snack": "下午点心"
    }
  ]
}

注意：
- 日期格式必须是 YYYY-MM-DD
- 如果某个字段图片中没有，填 null
- lunch_side2 如果只有一个配菜，填 null
- 汤、羹、粥、梨汤等汤水类菜品必须放入 lunch_soup，不要放入 lunch_side1 或 lunch_side2
- 只有一个配菜时，lunch_side2 填 null，汤类仍放入 lunch_soup
- 即使汤类出现在第二个配菜位置，也必须归入 lunch_soup；例如罗宋汤、芋头排骨汤、碧绿香菇竹笋汤、老鸭粉丝汤
- 如果有多个非汤类配菜，第一个放 lunch_side1，第二个放 lunch_side2
- 只返回纯 JSON，不要用 markdown 代码块包裹"""
MENU_TRUTH = {
    "week_start": "2026-09-01",
    "week_end": "2026-09-04",
    "daily_menus": [
        {"day_of_week": "周一", "breakfast": None, "lunch_rice": None, "lunch_main_meat": None, "lunch_side1": None, "lunch_side2": None, "lunch_soup": None, "fruit": None, "afternoon_snack": None},
        {"day_of_week": "周二", "breakfast": "烧卖、全脂牛奶", "lunch_rice": None, "lunch_main_meat": "意大利肉酱面", "lunch_side1": "彩椒鱼片", "lunch_side2": "爆炒双花", "lunch_soup": "菌菇鸽子汤", "fruit": "柚子/梨", "afternoon_snack": "绿豆薏仁汤"},
        {"day_of_week": "周三", "breakfast": "葱油花卷、全脂牛奶", "lunch_rice": "香米米饭", "lunch_main_meat": "什锦鲜菇蒸肉丸", "lunch_side1": "番茄炒蛋", "lunch_side2": "清炒时蔬", "lunch_soup": "海带豆腐羹", "fruit": "西瓜/苹果", "afternoon_snack": "蒸饺"},
        {"day_of_week": "周四", "breakfast": "鲜肉包、全脂牛奶", "lunch_rice": None, "lunch_main_meat": "芝士火腿三明治", "lunch_side1": "西芹虾仁", "lunch_side2": "彩虹色拉", "lunch_soup": "意式牛肉蔬菜汤", "fruit": "香蕉/玉菇甜瓜", "afternoon_snack": "杭白菜肉糜粥"},
        {"day_of_week": "周五", "breakfast": "红糖燕麦开花馒头、全脂牛奶", "lunch_rice": "扬州炒饭", "lunch_main_meat": "宫爆鸡丁", "lunch_side1": "蒜泥空心菜", "lunch_side2": None, "lunch_soup": "冬瓜小排汤", "fruit": "梨/西州蜜瓜", "afternoon_snack": "手抓饼"},
    ],
}


def menu_response_format() -> dict:
    properties = {"date": {"type": ["string", "null"]}, "day_of_week": {"type": ["string", "null"]}}
    properties.update({field: {"type": ["string", "null"]} for field in MENU_FIELDS})
    daily = {"type": "object", "additionalProperties": False, "properties": properties, "required": list(properties)}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "weekly_menu",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "week_start": {"type": ["string", "null"]},
                    "week_end": {"type": ["string", "null"]},
                    "daily_menus": {"type": "array", "minItems": 5, "maxItems": 5, "items": daily},
                },
                "required": ["week_start", "week_end", "daily_menus"],
            },
        },
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def png(width: int, height: int, rectangles: list[tuple[int, int, int, int, tuple[int, int, int]]], marker: int = 0) -> bytes:
    background = bytes((245, 245, 245))
    rows = [bytearray(background * width) for _ in range(height)]
    for x0, y0, x1, y1, color in rectangles:
        pixel = bytes(color)
        for y in range(max(0, y0), min(height, y1)):
            rows[y][max(0, x0) * 3 : min(width, x1) * 3] = pixel * max(0, min(width, x1) - max(0, x0))
    rows[-1][-3:] = bytes((marker % 251, (marker * 7) % 251, (marker * 13) % 251))
    raw = b"".join(b"\x00" + row for row in rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = binascii.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def image_part(data: bytes) -> dict:
    encoded = base64.b64encode(data).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}}


def request(url: str, body: dict, timeout: int = 900):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def error_text(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:2000]}"
    return f"{type(exc).__name__}: {exc}"


def clean_exact(value: str) -> str:
    return re.sub(r"[^a-z0-9/.-]+", "", value.strip().lower())


def normalize_menu_value(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "-"}:
        return None
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]+", text))
    return cjk or re.sub(r"[\s,，、/／]+", "", text).lower()


def parse_json_object(text: str) -> dict:
    stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I | re.S)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start, end = stripped.find("{"), stripped.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(stripped[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("menu response is not a JSON object")
    return value


def grade_menu(value: dict) -> dict:
    checks = []
    for field in ("week_start", "week_end"):
        checks.append({"field": field, "expected": MENU_TRUTH[field], "actual": value.get(field), "passed": value.get(field) == MENU_TRUTH[field]})
    actual_days = value.get("daily_menus") if isinstance(value.get("daily_menus"), list) else []
    by_day = {row.get("day_of_week"): row for row in actual_days if isinstance(row, dict)}
    for expected_day in MENU_TRUTH["daily_menus"]:
        day = expected_day["day_of_week"]
        actual_day = by_day.get(day, {})
        checks.append({"field": f"{day}.day_of_week", "expected": day, "actual": actual_day.get("day_of_week"), "passed": actual_day.get("day_of_week") == day})
        for field in MENU_FIELDS:
            expected = normalize_menu_value(expected_day[field])
            actual = normalize_menu_value(actual_day.get(field))
            checks.append({"field": f"{day}.{field}", "expected": expected_day[field], "actual": actual_day.get(field), "passed": actual == expected})
    return {"passed": sum(bool(row["passed"]) for row in checks), "total": len(checks), "checks": checks, "unscored_dates": [row.get("date") for row in actual_days if isinstance(row, dict)]}


def base_body(service: dict, mode: str, messages: list[dict], max_tokens: int) -> dict:
    return {
        "model": service["model"],
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
        "chat_template_kwargs": service["thinking"][mode],
    }


def quality_one(service_name: str, mode: str, case: tuple) -> dict:
    service = SERVICES[service_name]
    case_id, rectangles, prompt, expected = case
    body = base_body(service, mode, [{"role": "user", "content": [image_part(png(160, 120, rectangles)), {"type": "text", "text": prompt}]}], 1024)
    started = time.perf_counter()
    try:
        with request(service["base_url"] + "/chat/completions", body) as response:
            payload = json.load(response)
        elapsed = time.perf_counter() - started
        choice = payload["choices"][0]
        message = choice["message"]
        content = message.get("content") or ""
        reasoning = message.get("reasoning") or message.get("reasoning_content") or ""
        return {
            "id": case_id,
            "expected": expected,
            "actual": clean_exact(content),
            "passed": clean_exact(content) == expected,
            "elapsed_s": round(elapsed, 4),
            "finish_reason": choice.get("finish_reason"),
            "usage": payload.get("usage") or {},
            "content": content,
            "reasoning": reasoning,
            "error": None,
        }
    except Exception as exc:
        return {"id": case_id, "expected": expected, "passed": False, "elapsed_s": round(time.perf_counter() - started, 4), "error": error_text(exc)}


def menu_one(service_name: str, mode: str, image_data: bytes, max_tokens: int | None = None) -> dict:
    service = SERVICES[service_name]
    messages = [{"role": "user", "content": [image_part(image_data), {"type": "text", "text": MENU_PROMPT}]}]
    body = base_body(service, mode, messages, max_tokens or (16384 if mode == "on" else 4096))
    body["response_format"] = menu_response_format()
    started = time.perf_counter()
    try:
        with request(service["base_url"] + "/chat/completions", body) as response:
            payload = json.load(response)
        elapsed = time.perf_counter() - started
        choice = payload["choices"][0]
        message = choice["message"]
        content = message.get("content") or ""
        reasoning = message.get("reasoning") or message.get("reasoning_content") or ""
        row = {
            "elapsed_s": round(elapsed, 4),
            "finish_reason": choice.get("finish_reason"),
            "usage": payload.get("usage") or {},
            "content": content,
            "reasoning": reasoning,
            "error": None,
        }
        try:
            parsed = parse_json_object(content)
            row.update({"grade": grade_menu(parsed), "parsed": parsed})
        except Exception as exc:
            row["error"] = error_text(exc)
        return row
    except Exception as exc:
        return {"elapsed_s": round(time.perf_counter() - started, 4), "error": error_text(exc)}


def performance_image(marker: int) -> bytes:
    rectangles = [
        (70, 80, 330, 650, (35, 105, 220)),
        (390, 250, 650, 650, (220, 45, 45)),
        (710, 390, 970, 650, (25, 170, 90)),
    ]
    return png(1024, 768, rectangles, marker)


def stream_one(service_name: str, mode: str, marker: int) -> dict:
    service = SERVICES[service_name]
    prompt = (
        "Inspect the image. Begin with exactly 'blue tallest' if the blue bar is tallest. "
        "Then provide a detailed numbered description of colors, relative positions, and bar heights until the response limit."
    )
    messages = [{"role": "user", "content": [image_part(performance_image(marker)), {"type": "text", "text": prompt}]}]
    body = base_body(service, mode, messages, 256)
    body.update({"stream": True, "stream_options": {"include_usage": True}})
    started = time.perf_counter()
    first = None
    usage = {}
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    finish_reason = None
    try:
        with request(service["base_url"] + "/chat/completions", body) as response:
            for raw in response:
                line = raw.decode(errors="replace").strip()
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                event = json.loads(line[6:])
                choices = event.get("choices") or []
                if choices:
                    choice = choices[0]
                    delta = choice.get("delta") or {}
                    content = delta.get("content") or ""
                    reasoning = delta.get("reasoning") or delta.get("reasoning_content") or ""
                    if first is None and (content or reasoning):
                        first = time.perf_counter()
                    content_parts.append(content)
                    reasoning_parts.append(reasoning)
                    finish_reason = choice.get("finish_reason") or finish_reason
                usage = event.get("usage") or usage
        finished = time.perf_counter()
        first = first or finished
        completion_tokens = int(usage.get("completion_tokens") or 0)
        return {
            "elapsed_s": round(finished - started, 4),
            "ttft_s": round(first - started, 4),
            "decode_s": round(finished - first, 4),
            "completion_tokens": completion_tokens,
            "output_tok_s": round(completion_tokens / max(0.001, finished - first), 4),
            "prompt_tokens": usage.get("prompt_tokens"),
            "finish_reason": finish_reason,
            "grounded_prefix": "".join(content_parts).strip().lower().startswith("blue tallest"),
            "content": "".join(content_parts),
            "reasoning": "".join(reasoning_parts),
            "error": None,
        }
    except Exception as exc:
        return {"elapsed_s": round(time.perf_counter() - started, 4), "error": error_text(exc)}


async def performance_trial(service_name: str, mode: str, concurrency: int, marker: int) -> dict:
    started = time.perf_counter()
    requests = await asyncio.gather(*[
        asyncio.to_thread(stream_one, service_name, mode, marker * 10 + lane)
        for lane in range(concurrency)
    ])
    elapsed = time.perf_counter() - started
    successful = [row for row in requests if row.get("error") is None]
    total_tokens = sum(row["completion_tokens"] for row in successful)
    return {
        "concurrency": concurrency,
        "wall_s": round(elapsed, 4),
        "success": len(successful),
        "errors": concurrency - len(successful),
        "aggregate_tok_s": round(total_tokens / max(0.001, elapsed), 4),
        "median_ttft_s": round(statistics.median(row["ttft_s"] for row in successful), 4) if successful else None,
        "median_output_tok_s": round(statistics.median(row["output_tok_s"] for row in successful), 4) if successful else None,
        "grounded": sum(bool(row.get("grounded_prefix")) for row in successful),
        "requests": requests,
    }


def summarize_trials(rows: list[dict]) -> dict:
    successful = [row for row in rows if row["success"] == row["concurrency"]]
    return {
        "trials": len(rows),
        "fully_successful_trials": len(successful),
        "median_wall_s": round(statistics.median(row["wall_s"] for row in successful), 4) if successful else None,
        "median_ttft_s": round(statistics.median(row["median_ttft_s"] for row in successful), 4) if successful else None,
        "median_output_tok_s": round(statistics.median(row["median_output_tok_s"] for row in successful), 4) if successful else None,
        "median_aggregate_tok_s": round(statistics.median(row["aggregate_tok_s"] for row in successful), 4) if successful else None,
        "grounded_requests": sum(row["grounded"] for row in rows),
        "total_requests": sum(row["concurrency"] for row in rows),
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--menu-image", type=Path, required=True)
    parser.add_argument("--service", action="append", choices=sorted(SERVICES), dest="services")
    parser.add_argument("--qwen-base-url")
    parser.add_argument("--qwen-model")
    parser.add_argument("--c1-repeats", type=int, default=3)
    parser.add_argument("--c2-repeats", type=int, default=2)
    args = parser.parse_args()
    if args.qwen_base_url:
        SERVICES["qwen"]["base_url"] = args.qwen_base_url.rstrip("/")
    if args.qwen_model:
        SERVICES["qwen"]["model"] = args.qwen_model
    selected_services = args.services or list(SERVICES)
    menu_image = args.menu_image.read_bytes()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = {"schema_version": 1, "started_at": utc_now(), "services": SERVICES, "treatments": {}, "status": "running"}

    marker = 1
    for mode in ("off", "on"):
        result["treatments"][mode] = {}
        for service_name in selected_services:
            print(f"quality mode={mode} service={service_name}", flush=True)
            quality = [quality_one(service_name, mode, case) for case in VISION_CASES]
            print(f"menu mode={mode} service={service_name}", flush=True)
            menu = menu_one(service_name, mode, menu_image)
            perf = {}
            for concurrency, repeats in ((1, args.c1_repeats), (2, args.c2_repeats)):
                trials = []
                for repeat in range(repeats):
                    print(f"performance mode={mode} service={service_name} c={concurrency} repeat={repeat + 1}/{repeats}", flush=True)
                    trials.append(await performance_trial(service_name, mode, concurrency, marker))
                    marker += 1
                perf[f"c{concurrency}"] = {"summary": summarize_trials(trials), "trials": trials}
            result["treatments"][mode][service_name] = {
                "quality": {"passed": sum(bool(row["passed"]) for row in quality), "total": len(quality), "cases": quality},
                "menu": menu,
                "performance": perf,
            }
            args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")

    errors = [
        row["error"]
        for treatment in result["treatments"].values()
        for service in treatment.values()
        for row in service["quality"]["cases"] + ([service["menu"]] if service["menu"].get("error") else [])
        if row.get("error")
    ]
    result["finished_at"] = utc_now()
    result["status"] = "passed" if not errors else "completed_with_errors"
    result["quality_errors"] = errors
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"status": result["status"], "output": str(args.output)}, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
