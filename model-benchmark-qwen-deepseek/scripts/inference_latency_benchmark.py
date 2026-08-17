#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


PROMPT = (
    "You are a data lakehouse engineer. Explain in exactly four concise bullet points "
    "how to diagnose an Apache Spark job stalled by shuffle skew. Keep the final answer "
    "under 180 English words."
)


def request_body(model: str, profile: str, max_tokens: int) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": max_tokens,
        "seed": 42,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if profile in {"qwen36-thinking", "qwen38-low"}:
        body.update({"temperature": 1.0, "top_p": 0.95, "top_k": 20, "presence_penalty": 0.0})
        body["chat_template_kwargs"] = {"enable_thinking": True}
        if profile == "qwen38-low":
            body["reasoning_effort"] = "low"
    elif profile.startswith("deepseek-private-"):
        effort = profile.removeprefix("deepseek-private-")
        if effort not in {"high", "max"}:
            raise ValueError(f"unsupported private DeepSeek effort: {effort}")
        body.update({"temperature": 1.0, "top_p": 1.0, "reasoning_effort": effort})
        body["chat_template_kwargs"] = {"thinking": True}
        body["allowed_openai_params"] = ["reasoning_effort"]
    elif profile.startswith("deepseek-online-"):
        effort = profile.removeprefix("deepseek-online-")
        if effort not in {"low", "high", "max"}:
            raise ValueError(f"unsupported online DeepSeek effort: {effort}")
        body.update({"thinking": {"type": "enabled"}, "reasoning_effort": effort})
    else:
        raise ValueError(f"unsupported profile: {profile}")
    return body


def stream_request(
    base_url: str,
    model: str,
    profile: str,
    max_tokens: int,
    timeout: int,
    api_key: str | None,
) -> dict:
    body = request_body(model, profile, max_tokens)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers=headers,
    )
    started = time.perf_counter()
    first_token_at = None
    last_token_at = None
    first_token_kind = None
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    usage: dict = {}
    finish_reason = None
    saw_done = False
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    saw_done = True
                    break
                event = json.loads(data)
                if event.get("usage"):
                    usage = event["usage"]
                for choice in event.get("choices") or []:
                    delta = choice.get("delta") or {}
                    reasoning = delta.get("reasoning") or delta.get("reasoning_content") or ""
                    content = delta.get("content") or ""
                    if reasoning or content:
                        token_at = time.perf_counter()
                        if first_token_at is None:
                            first_token_at = token_at
                            first_token_kind = "reasoning" if reasoning else "content"
                        last_token_at = token_at
                    reasoning_parts.append(reasoning)
                    content_parts.append(content)
                    if choice.get("finish_reason") is not None:
                        finish_reason = choice["finish_reason"]
    except urllib.error.HTTPError as exc:
        return {"error": {"type": "http", "status": exc.code, "reason": str(exc.reason)}}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
        return {"error": {"type": type(exc).__name__, "reason": str(reason)}}

    completed = time.perf_counter()
    if not saw_done or not usage or finish_reason is None:
        return {
            "error": {
                "type": "incomplete_stream",
                "saw_done": saw_done,
                "has_usage": bool(usage),
                "finish_reason": finish_reason,
            }
        }
    first_token_at = first_token_at or completed
    ttft = first_token_at - started
    e2e = completed - started
    completion_tokens = int(usage.get("completion_tokens", 0))
    decode_tokens = max(completion_tokens - 1, 0)
    decode_seconds = max((last_token_at or first_token_at) - first_token_at, 0.0)
    content = "".join(content_parts)
    reasoning = "".join(reasoning_parts)
    return {
        "ttft_seconds": round(ttft, 6),
        "response_seconds": round(e2e, 6),
        "decode_seconds": round(decode_seconds, 6),
        "decode_tokens_per_second": round(decode_tokens / decode_seconds, 6) if decode_tokens and decode_seconds else None,
        "first_token_kind": first_token_kind,
        "finish_reason": finish_reason,
        "usage": usage,
        "content_chars": len(content),
        "reasoning_chars": len(reasoning),
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "reasoning_sha256": hashlib.sha256(reasoning.encode()).hexdigest(),
    }


def summary(runs: list[dict]) -> dict:
    valid = [run for run in runs if "error" not in run]
    if not valid:
        return {"runs": len(runs), "successful_runs": 0, "errors": len(runs)}

    def stats(field: str) -> dict:
        values = [float(run[field]) for run in valid if run.get(field) is not None]
        return {
            "mean": statistics.fmean(values),
            "min": min(values),
            "max": max(values),
            "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
        }

    return {
        "runs": len(runs),
        "successful_runs": len(valid),
        "errors": len(runs) - len(valid),
        "ttft_seconds": stats("ttft_seconds"),
        "response_seconds": stats("response_seconds"),
        "decode_tokens_per_second": stats("decode_tokens_per_second"),
        "completion_tokens_mean": statistics.fmean(
            int(run.get("usage", {}).get("completion_tokens", 0)) for run in valid
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--endpoint-label", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--profile",
        choices=[
            "qwen36-thinking",
            "qwen38-low",
            "deepseek-private-high",
            "deepseek-private-max",
            "deepseek-online-low",
            "deepseek-online-high",
            "deepseek-online-max",
        ],
        required=True,
    )
    parser.add_argument("--api-key-env")
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if min(args.max_tokens, args.runs, args.timeout) < 1 or args.warmup < 0:
        parser.error("numeric arguments must be positive; --warmup may be zero")
    api_key = os.environ.get(args.api_key_env) if args.api_key_env else None
    if args.api_key_env and not api_key:
        parser.error(f"environment variable {args.api_key_env} is empty")

    for index in range(args.warmup):
        result = stream_request(args.base_url, args.model, args.profile, args.max_tokens, args.timeout, api_key)
        if "error" in result:
            raise RuntimeError(f"warmup {index + 1} failed: {result['error']}")

    runs = []
    for index in range(args.runs):
        result = stream_request(args.base_url, args.model, args.profile, args.max_tokens, args.timeout, api_key)
        result["run"] = index + 1
        runs.append(result)
        print(json.dumps({"run": index + 1, **result}, ensure_ascii=False), flush=True)

    record = {
        "schema_version": 1,
        "status": "passed" if all("error" not in run for run in runs) else "completed_with_errors",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "endpoint": args.endpoint_label,
        "model": args.model,
        "profile": args.profile,
        "method": {
            "transport": "OpenAI-compatible SSE streaming",
            "ttft": "request dispatch to first non-empty reasoning or content delta",
            "response_time": "request dispatch to SSE completion",
            "decode_tps": "tokens after the first streamed token / (last non-empty delta time - first non-empty delta time)",
            "prompt": PROMPT,
            "seed": 42,
            "max_tokens": args.max_tokens,
            "warmup_runs": args.warmup,
            "measured_runs": args.runs,
            "single_stream": True,
        },
        "summary": summary(runs),
        "runs": runs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"output": str(args.output), "summary": record["summary"]}, ensure_ascii=False))
    return 0 if record["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
