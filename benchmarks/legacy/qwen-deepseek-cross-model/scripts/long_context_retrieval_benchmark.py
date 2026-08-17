#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


FILLER = "archive row: pipeline healthy; no access code is present in this ordinary record.\n"


def post_json(url: str, body: dict, timeout: int) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def token_count(base_url: str, content: str, timeout: int) -> int:
    result = post_json(
        base_url.rstrip("/").removesuffix("/v1") + "/tokenize",
        {"content": content, "add_special": False},
        timeout,
    )
    return len(result["tokens"])


def make_prompt(repeats: int, begin_code: str, end_code: str) -> str:
    left = repeats // 2
    right = repeats - left
    return (
        "Read the complete archive. Return exactly the two access codes in the form "
        "BEGIN_CODE|END_CODE, with no explanation.\n"
        f"BEGIN ACCESS CODE: {begin_code}\n"
        + FILLER * left
        + FILLER * right
        + f"END ACCESS CODE: {end_code}\n"
        "Now return the two access codes exactly as requested."
    )


def calibrate_prompt(base_url: str, target_tokens: int, begin_code: str, end_code: str, timeout: int) -> tuple[str, int]:
    repeats = max(1, target_tokens // 12)
    prompt = ""
    measured = 0
    for _ in range(4):
        prompt = make_prompt(repeats, begin_code, end_code)
        measured = token_count(base_url, prompt, timeout)
        if abs(measured - target_tokens) <= 256:
            break
        repeats = max(1, round(repeats * target_tokens / measured))
    return prompt, measured


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--context-size", type=int, required=True)
    parser.add_argument("--target-tokens", type=int, required=True)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.target_tokens >= args.context_size - 256:
        parser.error("target tokens must leave at least 256 tokens of context headroom")

    identity = f"{args.context_size}:{args.target_tokens}"
    digest = hashlib.sha256(identity.encode()).hexdigest().upper()
    begin_code = f"B-{digest[:12]}"
    end_code = f"E-{digest[-12:]}"
    expected = f"{begin_code}|{end_code}"
    prompt, raw_tokens = calibrate_prompt(
        args.base_url, args.target_tokens, begin_code, end_code, args.timeout
    )

    started = time.perf_counter()
    response = post_json(
        args.base_url.rstrip("/") + "/chat/completions",
        {
            "model": args.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 64,
            "seed": 42,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        args.timeout,
    )
    elapsed = time.perf_counter() - started
    choice = response["choices"][0]
    content = (choice["message"].get("content") or "").strip()
    usage = response.get("usage") or {}
    passed = content == expected
    record = {
        "schema_version": 1,
        "status": "passed" if passed else "failed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "context_size": args.context_size,
        "target_raw_tokens": args.target_tokens,
        "measured_raw_tokens": raw_tokens,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "prompt_bytes": len(prompt.encode()),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "expected": expected,
        "content": content,
        "finish_reason": choice.get("finish_reason"),
        "response_seconds": round(elapsed, 6),
        "method": "Two deterministic access codes placed near the beginning and end of a synthetic archive",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(record, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
