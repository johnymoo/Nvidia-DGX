#!/usr/bin/env python3
"""Vision-suite runner for the GLM-5.3 validation window.

Reuses execution/benchmarks/vision_compare.py verbatim (09-03 protocol:
6 synthetic vision cases, week36 menu task with the 47-item frozen truth,
1024x768 streaming c1/c2) after injecting a `glm` service entry. GLM reads
chat_template_kwargs {enable_thinking, reasoning_effort} exactly like the
qwen entry. If the strict JSON-schema menu call fails (schema/xgrammar path),
retries once without response_format and records the fallback.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import urllib.request
from pathlib import Path


async def run_suite(vc, args) -> int:
    vc.SERVICES["glm"] = {
        "base_url": args.base.rstrip("/") + "/v1",
        "model": args.model,
        "thinking": {
            "off": {"enable_thinking": False},
            "on": {"enable_thinking": True, "reasoning_effort": "low"},
        },
    }
    sys.argv = [
        "vision_compare",
        "--output", str(args.output),
        "--menu-image", str(args.menu_image),
        "--service", "glm",
        "--c1-repeats", str(args.c1_repeats),
        "--c2-repeats", str(args.c2_repeats),
    ]
    return await vc.main()


def menu_fallback(base: str, model: str, menu_image: Path, out_path: Path) -> dict:
    """Retry the menu task without response_format (pure-JSON prompt only)."""
    import base64

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import vision_compare as vc  # noqa: PLC0415 - reuse prompt + grader

    encoded = base64.b64encode(menu_image.read_bytes()).decode()
    messages = [{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
            {"type": "text", "text": vc.MENU_PROMPT},
        ],
    }]
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": 4096,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(
        base.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            payload = json.load(resp)
        content = payload["choices"][0]["message"].get("content") or ""
        row = {
            "elapsed_s": round(time.perf_counter() - started, 3),
            "finish_reason": payload["choices"][0].get("finish_reason"),
            "usage": payload.get("usage") or {},
            "content": content,
            "error": None,
        }
        parsed = vc.parse_json_object(content)
        row["grade"] = vc.grade_menu(parsed)
    except Exception as exc:  # noqa: BLE001
        row = {"elapsed_s": round(time.perf_counter() - started, 3), "error": f"{type(exc).__name__}: {exc}"}
    out_path.write_text(json.dumps(row, indent=2, ensure_ascii=False))
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vision-compare", required=True, help="path to vision_compare.py copy")
    ap.add_argument("--menu-image", required=True, help="path to week36-menu.png")
    ap.add_argument("--base", default="http://127.0.0.1:8890")
    ap.add_argument("--model", default="GLM-5.3-Flash-EXL3")
    ap.add_argument("--output", required=True)
    ap.add_argument("--c1-repeats", type=int, default=3)
    ap.add_argument("--c2-repeats", type=int, default=2)
    args = ap.parse_args()

    sys.path.insert(0, str(Path(args.vision_compare).resolve().parent))
    import vision_compare as vc  # noqa: PLC0415

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    rc = asyncio.run(run_suite(vc, args))

    data = json.loads(output.read_text())
    menu = data["treatments"]["off"]["glm"]["menu"]
    if menu.get("error"):
        print("[vision] menu with response_format failed -> retrying without schema", flush=True)
        fallback = menu_fallback(args.base, args.model, Path(args.menu_image), output.with_name("menu-fallback.json"))
        data["treatments"]["off"]["glm"]["menu_fallback"] = fallback
        output.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
