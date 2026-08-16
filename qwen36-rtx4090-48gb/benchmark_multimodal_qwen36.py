#!/usr/bin/env python3
"""Repeatable vision smoke benchmark for the local Ollama Qwen3.6 service."""

import argparse
import base64
import json
import statistics
import struct
import time
import urllib.request
import uuid
import zlib
from datetime import datetime, timezone
from pathlib import Path


URL = "http://127.0.0.1:8004/api/chat"
MODEL = "qwen3.6:27b"
WIDTH = 640
HEIGHT = 360
EXPECTED = {"blue_squares": 3, "yellow_circles": 2, "red_rectangles": 1}


def png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def build_test_card(path):
    pixels = bytearray([255, 255, 255] * WIDTH * HEIGHT)

    def pixel(x, y, color):
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            offset = (y * WIDTH + x) * 3
            pixels[offset : offset + 3] = bytes(color)

    def rectangle(x, y, width, height, color):
        for row in range(y, y + height):
            for column in range(x, x + width):
                pixel(column, row, color)

    def circle(center_x, center_y, radius, color):
        for row in range(center_y - radius, center_y + radius + 1):
            for column in range(center_x - radius, center_x + radius + 1):
                if (column - center_x) ** 2 + (row - center_y) ** 2 <= radius**2:
                    pixel(column, row, color)

    blue = (0, 102, 204)
    yellow = (255, 204, 0)
    red = (204, 51, 51)
    rectangle(55, 55, 80, 80, blue)
    rectangle(205, 55, 80, 80, blue)
    rectangle(355, 55, 80, 80, blue)
    circle(150, 255, 48, yellow)
    circle(330, 255, 48, yellow)
    rectangle(465, 225, 130, 70, red)

    raw = b"".join(
        b"\x00" + bytes(pixels[row * WIDTH * 3 : (row + 1) * WIDTH * 3])
        for row in range(HEIGHT)
    )
    image = b"\x89PNG\r\n\x1a\n"
    image += png_chunk(b"IHDR", struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0))
    image += png_chunk(b"IDAT", zlib.compress(raw, level=9))
    image += png_chunk(b"IEND", b"")
    path.write_bytes(image)


def stream_request(url, payload, timeout):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    first_token_at = None
    content = []
    final_event = None
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw_line in response:
            line = raw_line.strip()
            if not line:
                continue
            event = json.loads(line)
            message = event.get("message", {})
            token = message.get("content", "")
            if token:
                content.append(token)
                if first_token_at is None:
                    first_token_at = time.perf_counter()
            if event.get("done"):
                final_event = event
    completed = time.perf_counter()
    if final_event is None:
        raise RuntimeError("Ollama stream ended without a final event")
    return final_event, "".join(content), (first_token_at or completed) - started, completed - started


def is_numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def numeric_value(record, key, default=None):
    value = record.get(key)
    return value if is_numeric(value) else default


def seconds(event, key):
    duration = numeric_value(event, key)
    return duration / 1_000_000_000 if duration is not None else None


def mean_metric(runs, key):
    values = [numeric_value(run, key) for run in runs]
    values = [value for value in values if value is not None]
    return statistics.mean(values) if values else None


def format_metric(value, precision=1):
    return f"{value:.{precision}f}" if is_numeric(value) else "N/A"


def parse_answer(text):
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return {key: parsed.get(key) for key in EXPECTED}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=URL)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--image", type=Path, default=Path("benchmark_multimodal_card.png"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")

    build_test_card(args.image)
    encoded_image = base64.b64encode(args.image.read_bytes()).decode("ascii")
    benchmark_id = uuid.uuid4().hex
    prompt = (
        "Analyze the image. Count only filled geometric objects and exclude the white background. "
        "Return exactly compact JSON with integer fields blue_squares, yellow_circles, and red_rectangles."
    )
    runs = []
    for index in range(args.runs):
        payload = {
            "model": args.model,
            "stream": True,
            "think": False,
            "messages": [
                {
                    "role": "user",
                    "content": f"Benchmark request {benchmark_id}-{index + 1}. {prompt}",
                    "images": [encoded_image],
                }
            ],
            "options": {"temperature": 0, "num_predict": 64},
        }
        event, content, ttft_s, wall_s = stream_request(args.url, payload, args.timeout)
        answer = parse_answer(content)
        prompt_s = seconds(event, "prompt_eval_duration")
        eval_s = seconds(event, "eval_duration")
        result = {
            "run": index + 1,
            "answer": answer,
            "correct": answer == EXPECTED,
            "response": content,
            "client_ttft_ms": ttft_s * 1000,
            "client_wall_ms": wall_s * 1000,
            "prompt_tokens": numeric_value(event, "prompt_eval_count", 0),
            "completion_tokens": numeric_value(event, "eval_count", 0),
            "prompt_tok_s": numeric_value(event, "prompt_eval_count", 0) / prompt_s if prompt_s else None,
            "decode_tok_s": numeric_value(event, "eval_count", 0) / eval_s if eval_s else None,
        }
        runs.append(result)
        print(
            f"run {index + 1}: correct={result['correct']} ttft={format_metric(result['client_ttft_ms'], 0)} ms "
            f"prefill={format_metric(result['prompt_tok_s'])} tok/s "
            f"decode={format_metric(result['decode_tok_s'])} tok/s"
        )

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "benchmark_id": benchmark_id,
        "model": args.model,
        "url": args.url,
        "image": {"path": str(args.image), "width": WIDTH, "height": HEIGHT, "expected": EXPECTED},
        "runs": runs,
        "summary": {
            "runs": len(runs),
            "correct_runs": sum(run["correct"] for run in runs),
            "client_ttft_ms_mean": mean_metric(runs, "client_ttft_ms"),
            "prompt_tok_s_mean": mean_metric(runs, "prompt_tok_s"),
            "decode_tok_s_mean": mean_metric(runs, "decode_tok_s"),
        },
    }
    output = args.output or Path(
        f"benchmark_multimodal_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Saved: {output}")
    if result["summary"]["correct_runs"] != args.runs:
        raise SystemExit("Vision benchmark failed: one or more responses did not match the expected counts")


if __name__ == "__main__":
    main()
