#!/usr/bin/env python3
"""Streaming chat-completions client + idle-window guard.

`stream_request` generalizes `execution/kv-offload-d0/d0_probes.py::stream_request`:
SSE parsing, TTFT, per-token timestamps, and `stream_options.include_usage`
carry over; base_url/model/messages are now parameters (not hardcoded), and
it also handles tool-call deltas, temperature=None (server default),
response_format, and an explicit `thinking` override.
"""
from __future__ import annotations

import json
import statistics
import time
import urllib.error
import urllib.request
from typing import Any

import metrics


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        try:
            body = exc.read().decode("utf-8", errors="replace")[:2000]
        except Exception:
            body = ""
        return f"HTTP {exc.code}: {body}"
    return f"{type(exc).__name__}: {exc}"


def _merge_tool_call_delta(acc: dict[int, dict], deltas: list[dict]) -> None:
    for item in deltas:
        idx = item.get("index", 0)
        slot = acc.setdefault(idx, {"id": None, "type": None, "name": None, "arguments": ""})
        if item.get("id"):
            slot["id"] = item["id"]
        if item.get("type"):
            slot["type"] = item["type"]
        fn = item.get("function") or {}
        if fn.get("name"):
            slot["name"] = fn["name"]
        if fn.get("arguments"):
            slot["arguments"] += fn["arguments"]


def stream_request(
    base_url: str,
    model: str,
    messages: list[dict],
    max_tokens: int,
    *,
    temperature: float | None = 0.0,
    timeout: int = 1800,
    thinking: str | None = None,
    tools: list[dict] | None = None,
    tool_choice: Any = None,
    response_format: dict | None = None,
    extra_body: dict | None = None,
) -> dict[str, Any]:
    """POST a streaming chat completion. `thinking` is None by default (omit
    `chat_template_kwargs` entirely -> production default thinking=true,
    reasoning_effort=low); pass "off"/"low"/"high" to override explicitly.

    Returns: ttft_s, first_token_ts (epoch), token_ts (list[epoch], one per
    content/reasoning delta), gen_tok_s, itl_p95_s, itl_max_s, usage,
    cached_tokens, finish_reason, text, reasoning_text, tool_calls, error.
    """
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if temperature is not None:
        body["temperature"] = temperature
    if thinking is not None:
        body["chat_template_kwargs"] = (
            {"thinking": False} if thinking == "off" else {"thinking": True, "reasoning_effort": thinking}
        )
    if tools is not None:
        body["tools"] = tools
    if tool_choice is not None:
        body["tool_choice"] = tool_choice
    if response_format is not None:
        body["response_format"] = response_format
    if extra_body:
        body.update(extra_body)

    url = f"{base_url}/v1/chat/completions"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})

    t0 = time.time()
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    token_ts: list[float] = []
    tool_call_acc: dict[int, dict] = {}
    usage: dict = {}
    finish_reason: str | None = None

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data: "):
                    continue
                data = line[len("data: "):]
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if chunk.get("usage"):
                    usage = chunk["usage"]
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                delta = choice.get("delta") or {}
                piece = delta.get("content") or ""
                reasoning_piece = delta.get("reasoning_content") or delta.get("reasoning") or ""
                if piece or reasoning_piece:
                    token_ts.append(time.time())
                    if piece:
                        content_parts.append(piece)
                    if reasoning_piece:
                        reasoning_parts.append(reasoning_piece)
                if delta.get("tool_calls"):
                    _merge_tool_call_delta(tool_call_acc, delta["tool_calls"])
                choice_finish = choice.get("finish_reason")
                if choice_finish:
                    finish_reason = choice_finish
    except Exception as exc:
        return {
            "ttft_s": None, "first_token_ts": None, "token_ts": [],
            "gen_tok_s": None, "itl_p95_s": None, "itl_max_s": None,
            "usage": {}, "cached_tokens": None, "finish_reason": None,
            "text": "".join(content_parts), "reasoning_text": "".join(reasoning_parts),
            "tool_calls": [], "error": _error_text(exc),
        }

    first_token_ts = token_ts[0] if token_ts else None
    ttft_s = (first_token_ts - t0) if first_token_ts is not None else None
    completion_tokens = usage.get("completion_tokens")
    gen_tok_s = itl_p95_s = itl_max_s = None
    if len(token_ts) > 1:
        span = token_ts[-1] - token_ts[0]
        if completion_tokens and span > 0:
            gen_tok_s = completion_tokens / span
        itls = [b - a for a, b in zip(token_ts, token_ts[1:])]
        itl_max_s = max(itls)
        itl_p95_s = statistics.quantiles(itls, n=100)[94] if len(itls) >= 2 else itls[0]
    cached_tokens = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
    tool_calls = [
        {"id": v["id"], "type": v["type"], "function": {"name": v["name"], "arguments": v["arguments"]}}
        for _, v in sorted(tool_call_acc.items())
    ]
    return {
        "ttft_s": round(ttft_s, 4) if ttft_s is not None else None,
        "first_token_ts": first_token_ts,
        "token_ts": token_ts,
        "gen_tok_s": round(gen_tok_s, 2) if gen_tok_s is not None else None,
        "itl_p95_s": round(itl_p95_s, 4) if itl_p95_s is not None else None,
        "itl_max_s": round(itl_max_s, 4) if itl_max_s is not None else None,
        "usage": usage,
        "cached_tokens": cached_tokens,
        "finish_reason": finish_reason,
        "text": "".join(content_parts),
        "reasoning_text": "".join(reasoning_parts),
        "tool_calls": tool_calls,
        "error": None,
    }


def needle_pass(marker: str, answer_text: str) -> bool:
    return marker in answer_text


def fetch_num_requests_running(metrics_url: str, timeout: int = 10) -> float:
    return metrics.num_requests_running(metrics.snapshot(metrics.fetch(metrics_url, timeout=timeout)))


def idle_window_ok(metrics_url: str, poll_gap_s: float = 60.0) -> tuple[bool, str]:
    """num_requests_running == 0 and generation_tokens_total unchanged
    across two polls >= poll_gap_s apart."""
    snap1 = metrics.snapshot(metrics.fetch(metrics_url))
    running1 = metrics.num_requests_running(snap1)
    if running1 > 0:
        return False, f"num_requests_running={running1} on first poll (not idle)"
    gen1 = metrics.sum_metric(snap1, "vllm:generation_tokens_total")
    time.sleep(poll_gap_s)
    snap2 = metrics.snapshot(metrics.fetch(metrics_url))
    running2 = metrics.num_requests_running(snap2)
    if running2 > 0:
        return False, f"num_requests_running={running2} on second poll (not idle)"
    gen2 = metrics.sum_metric(snap2, "vllm:generation_tokens_total")
    if gen1 != gen2:
        return False, f"generation_tokens_total moved {gen1} -> {gen2} across {poll_gap_s:.0f}s (not idle)"
    return True, "idle"
