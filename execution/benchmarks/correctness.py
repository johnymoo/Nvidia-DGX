#!/usr/bin/env python3
"""Correctness and agent-sanity acceptance for the official 0731 endpoint."""

import concurrent.futures
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid


BASE = os.environ.get("URL", "http://127.0.0.1:8890/v1").rstrip("/")
MODEL = os.environ.get("MODEL", "deepseek-v4-flash-0731")
RESULT_PATH = os.environ.get("RESULT_PATH", "")
MAX_TOKENS_OVERRIDE = int(os.environ["MAX_TOKENS_OVERRIDE"]) if os.environ.get("MAX_TOKENS_OVERRIDE") else None
SPECIAL = re.compile(r"<\|.*?\|>|<｜.*?｜>|�|\x00", re.I)


def request(messages, *, max_tokens=256, temperature=0.0, tools=None, timeout=600):
    if MAX_TOKENS_OVERRIDE is not None:
        max_tokens = MAX_TOKENS_OVERRIDE
    body = {"model": MODEL, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    req = urllib.request.Request(
        BASE + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = response.status
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from exc
    if status != 200:
        raise RuntimeError(f"HTTP {status}")
    wall = time.perf_counter() - started
    choice = payload["choices"][0]
    message = choice["message"]
    content = message.get("content") or ""
    reasoning = message.get("reasoning") or message.get("reasoning_content") or ""
    tool_calls = message.get("tool_calls") or []
    completion = int((payload.get("usage") or {}).get("completion_tokens") or 0)
    combined = content + reasoning + json.dumps(tool_calls, ensure_ascii=False)
    if completion <= 0 or not combined.strip():
        raise RuntimeError(f"empty output completion_tokens={completion}")
    if SPECIAL.search(combined):
        raise RuntimeError("garble or special-token leakage")
    prompt_text = " ".join(str(item.get("content") or "") for item in messages)
    if len(combined) > 40 and combined.strip() == prompt_text.strip():
        raise RuntimeError("prompt echo")
    return {
        "content": content,
        "reasoning": reasoning,
        "tool_calls": tool_calls,
        "completion_tokens": completion,
        "wall_seconds": wall,
        "finish_reason": choice.get("finish_reason"),
    }


def run_case(name, prompt, validator, **kwargs):
    row = request([{"role": "user", "content": prompt}], **kwargs)
    if not validator(row):
        raise RuntimeError(f"{name} semantic assertion failed: {row['content'][:160]!r}")
    return {"name": name, "status": "passed", "completion_tokens": row["completion_tokens"], "wall_seconds": row["wall_seconds"]}


def concurrent_round(concurrency):
    def one(index):
        salt = uuid.uuid4().hex
        expected = f"CONCURRENT_{concurrency}_{index}_{salt}"
        prompt = f"Return exactly this token and nothing else: {expected}"
        row = request([{"role": "user", "content": prompt}], max_tokens=80)
        if row["content"].strip() != expected:
            raise RuntimeError(f"concurrency exact-text mismatch expected={expected!r} got={row['content']!r}")
        return row

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        rows = list(executor.map(one, range(concurrency)))
    wall = time.perf_counter() - started
    total = sum(row["completion_tokens"] for row in rows)
    return {"concurrency": concurrency, "requests": len(rows), "completion_tokens": total, "wall_seconds": wall}


def main():
    result = {"schema_version": 1, "url": BASE, "model": MODEL, "max_tokens_override": MAX_TOKENS_OVERRIDE, "status": "failed", "cases": [], "concurrency": []}
    try:
        models = json.load(urllib.request.urlopen(BASE + "/models", timeout=30))
        ids = [item.get("id") for item in models.get("data") or []]
        if ids != [MODEL]:
            raise RuntimeError(f"model identity mismatch: {ids}")
        result["model_ids"] = ids
        exact = "DS4_ACCEPTANCE_EXACT_0731"
        result["cases"].append(run_case("deterministic_exact", f"Reply with exactly {exact} and nothing else.", lambda row: row["content"].strip() == exact, max_tokens=64))
        result["cases"].append(run_case("math", "Compute 37 * 29. Return the integer and one short verification.", lambda row: "1073" in row["content"], max_tokens=128))

        def valid_json(row):
            try:
                parsed = json.loads(row["content"])
            except json.JSONDecodeError:
                return False
            return parsed == {"status": "ok", "count": 3, "items": [1, 2, 3]}

        result["cases"].append(run_case("json", 'Return only this JSON object with no fence: {"status":"ok","count":3,"items":[1,2,3]}', valid_json, max_tokens=128))
        result["cases"].append(run_case("code", "Write only Python code for def add(a: int, b: int) -> int returning the sum.", lambda row: "def add" in row["content"] and "return" in row["content"], max_tokens=128))
        result["cases"].append(run_case("chinese", "用中文写一句话，必须包含“分布式推理验收通过”。", lambda row: "分布式推理验收通过" in row["content"], max_tokens=96))
        tools = [{"type": "function", "function": {"name": "lookup_inventory", "description": "Look up inventory", "parameters": {"type": "object", "properties": {"sku": {"type": "string"}}, "required": ["sku"]}}}]
        tool_row = request([{"role": "user", "content": "Use lookup_inventory for SKU GB10-0731. Do not answer from memory."}], tools=tools, max_tokens=128)
        if not tool_row["tool_calls"] or tool_row["tool_calls"][0].get("function", {}).get("name") != "lookup_inventory":
            raise RuntimeError(f"tool-call assertion failed: {tool_row}")
        result["cases"].append({"name": "tool_call", "status": "passed", "completion_tokens": tool_row["completion_tokens"], "wall_seconds": tool_row["wall_seconds"]})
        expected = f"CACHE_{uuid.uuid4().hex}"
        cold_prompt = f"Reply with exactly this token and nothing else: {expected}"
        cold = request([{"role": "user", "content": cold_prompt}], max_tokens=80)
        warm = request([{"role": "user", "content": cold_prompt}], max_tokens=80)
        if cold["content"].strip() != expected or warm["content"].strip() != expected:
            raise RuntimeError("cold/warm deterministic mismatch")
        result["cold_warm"] = {"cold_seconds": cold["wall_seconds"], "warm_seconds": warm["wall_seconds"], "exact_match": True}
        for concurrency in (2, 4, 6):
            result["concurrency"].append(concurrent_round(concurrency))
        result["status"] = "passed"
        return_code = 0
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return_code = 1
    if RESULT_PATH:
        with open(RESULT_PATH, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
