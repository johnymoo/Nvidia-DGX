#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import time
import urllib.request
from pathlib import Path


def request(base_url: str, body: dict, timeout: int = 900) -> dict:
    req = urllib.request.Request(
        f"{base_url}/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def content(response: dict) -> str:
    value = response["choices"][0]["message"].get("content")
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def exact_case(base_url: str, model: str, marker: str) -> dict:
    response = request(
        base_url,
        {
            "model": model,
            "temperature": 0,
            "max_tokens": 32,
            "messages": [{"role": "user", "content": f"Reply exactly {marker}"}],
        },
    )
    answer = content(response).strip()
    if answer != marker:
        raise RuntimeError(f"marker mismatch: {answer!r}")
    return {"status": "passed", "marker": marker}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--soak-seconds", type=int, default=180)
    parser.add_argument("--long-repetitions", type=int, default=48000)
    args = parser.parse_args()
    result: dict = {"status": "running", "cases": {}}

    with urllib.request.urlopen(f"{args.base_url}/v1/models", timeout=30) as response:
        models = json.load(response)
    model = next((item for item in models.get("data", []) if item.get("id") == args.model), None)
    if model is None:
        raise RuntimeError("model alias missing")
    params = int((model.get("meta") or {}).get("n_params") or 0)
    if not 26_000_000_000 <= params <= 28_500_000_000:
        raise RuntimeError(f"unexpected parameter count: {params}")
    result["cases"]["identity"] = {"status": "passed", "n_params": params}
    result["cases"]["text"] = exact_case(args.base_url, args.model, "QWEN38-TEXT-OK")

    image_data = "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAARUlEQVR4nO3PQQ0AIBDAsAP/nuGNAvZoFSzZOjNnyNi1dwfgUQCeBeBZAB4F4FkAngXgWQCeBeBZAB4F4FkAngXgWQCeBeBZAB4F4FkA3gBrpAH/mYKSJQAAAABJRU5ErkJggg=="
    vision = request(
        args.base_url,
        {
            "model": args.model,
            "temperature": 0,
            "max_tokens": 80,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_data}"}},
                        {"type": "text", "text": "What is the dominant color? Answer with one color word."},
                    ],
                }
            ],
        },
    )
    if "blue" not in content(vision).lower():
        raise RuntimeError("vision grounding failed")
    result["cases"]["vision"] = {"status": "passed"}

    structured = request(
        args.base_url,
        {
            "model": args.model,
            "temperature": 0,
            "max_tokens": 80,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "user",
                    "content": 'Return only JSON with keys "model" and "ready"; values must be "qwen3.8" and true.',
                }
            ],
        },
    )
    if json.loads(content(structured)) != {"model": "qwen3.8", "ready": True}:
        raise RuntimeError("structured output mismatch")
    result["cases"]["structured"] = {"status": "passed"}

    tool = request(
        args.base_url,
        {
            "model": args.model,
            "temperature": 0,
            "max_tokens": 128,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup_inventory",
                        "description": "Look up inventory",
                        "parameters": {
                            "type": "object",
                            "properties": {"sku": {"type": "string"}},
                            "required": ["sku"],
                        },
                    },
                }
            ],
            "tool_choice": {"type": "function", "function": {"name": "lookup_inventory"}},
            "messages": [{"role": "user", "content": "Look up SKU Q38-RTX3090."}],
        },
    )
    calls = tool["choices"][0]["message"].get("tool_calls") or []
    arguments = (
        json.loads(calls[0].get("function", {}).get("arguments") or "{}")
        if calls
        else {}
    )
    if (
        not calls
        or calls[0].get("function", {}).get("name") != "lookup_inventory"
        or arguments != {"sku": "Q38-RTX3090"}
    ):
        raise RuntimeError("tool call missing")
    result["cases"]["tool"] = {"status": "passed"}

    for count in (4, 8):
        started = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
            list(
                pool.map(
                    lambda index: exact_case(args.base_url, args.model, f"Q38-C{count}-{index}"),
                    range(count),
                )
            )
        result["cases"][f"concurrency_{count}"] = {
            "status": "passed",
            "seconds": round(time.monotonic() - started, 3),
            "requests": count,
        }

    marker = "Q38-LONG-CONTEXT-OK"
    started = time.monotonic()
    long_response = request(
        args.base_url,
        {
            "model": args.model,
            "temperature": 0,
            "max_tokens": 32,
            "messages": [
                {
                    "role": "user",
                    "content": ("alpha " * args.long_repetitions) + f"\nReply exactly {marker}",
                }
            ],
        },
    )
    usage = long_response.get("usage") or {}
    if marker not in content(long_response) or int(usage.get("prompt_tokens") or 0) < 40_000:
        raise RuntimeError("long-context validation failed")
    result["cases"]["long_context"] = {
        "status": "passed",
        "seconds": round(time.monotonic() - started, 3),
        "prompt_tokens": usage["prompt_tokens"],
    }

    deadline = time.monotonic() + args.soak_seconds
    completed = 0
    started = time.monotonic()
    while time.monotonic() < deadline:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(
                pool.map(
                    lambda index: exact_case(args.base_url, args.model, f"Q38-SOAK-{completed}-{index}"),
                    range(4),
                )
            )
        completed += 4
    result["cases"]["soak"] = {
        "status": "passed",
        "seconds": round(time.monotonic() - started, 3),
        "requests": completed,
        "concurrency": 4,
    }
    result["status"] = "passed"
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
