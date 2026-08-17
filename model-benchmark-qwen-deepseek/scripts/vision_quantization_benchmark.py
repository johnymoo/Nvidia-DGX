#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

from quality_benchmark import VISION, clean_exact, png, post


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--quantization", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--thinking",
        choices=["server-default", "off", "low", "medium", "xhigh"],
        default="off",
    )
    args = parser.parse_args()

    rows = []
    for name, rectangles, prompt, expected in VISION:
        encoded = base64.b64encode(png(160, 120, rectangles)).decode()
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{encoded}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        response = post(args.base_url, args.model, messages, 64, args.thinking)
        actual = clean_exact(response["content"])
        row = {
            "id": name,
            "expected": expected,
            "actual": actual,
            "passed": actual == expected,
            "seconds": response["seconds"],
            "response": response["content"],
            "finish_reason": response["finish_reason"],
            "usage": response["usage"],
        }
        rows.append(row)
        print(json.dumps({key: row[key] for key in ("id", "passed", "seconds")}, ensure_ascii=False))

    result = {
        "schema_version": 1,
        "harness_id": "qwen38-quantization-vision-v1",
        "tag": args.tag,
        "model": args.model,
        "runtime": args.runtime,
        "quantization": args.quantization,
        "thinking_mode": args.thinking,
        "passed": sum(row["passed"] for row in rows),
        "total": len(rows),
        "score": sum(row["passed"] for row in rows) / len(rows),
        "cases": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"tag": args.tag, "score": result["score"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
