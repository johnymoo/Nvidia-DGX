#!/usr/bin/env python3
"""Pinned f277b3d agent-shaped soak with strict machine-readable validity."""

import json
import os
import random
import re
import threading
import time
import urllib.request


URL = os.environ.get("URL", "http://127.0.0.1:8890/v1").rstrip("/")
MODEL = os.environ.get("MODEL", "deepseek-v4-flash-0731")
CONC = int(os.environ.get("CONC", "4"))
MINUTES = float(os.environ.get("MINUTES", "40"))
TAG = os.environ.get("TAG", "official-0731-patch4")
RESULT_PATH = os.environ.get("RESULT_PATH", "")
TEST_MODE = os.environ.get("ACCEPTANCE_TEST_MODE", "0") == "1"

PROMPTS = [
    ("tool", "You have a tool `search_inventory(query: str, limit: int)`. The user asks: 'find me size 10 Jordan 4s under $300'. Emit the tool call, then explain."),
    ("code", "Refactor this into async with proper error handling and type hints:\ndef fetch_all(urls):\n    out = []\n    for u in urls:\n        out.append(requests.get(u).json())\n    return out"),
    ("json", 'Return ONLY a JSON object: {"status":"ok","items":[...12 items, each {"sku":"...","qty":N,"price":F}...],"total":F}'),
    ("reason", "A warehouse has 3 zones. Zone A ships 40% of orders at 2.1 days, Zone B 35% at 1.8 days, Zone C the rest at 3.4 days. Compute weighted average delivery time, then explain which zone to expand and why."),
    ("long", "Summarize the tradeoffs between speculative decoding, tensor parallelism, and quantization for a 400B MoE served on two 128GB unified-memory nodes. Be specific about which lever affects step time vs acceptance."),
    ("chat", "Explain to a junior engineer why a burst of 80 tok/s can drop to 35 tok/s mid-generation on the same server with no config change."),
]
CJK = re.compile(r"[぀-ヿ一-鿿가-힯]")
TEMPLATE = re.compile(r"<\|.*?\|>|<｜.*?｜>|</?(?:think|tool_call|assistant)>", re.I)
stop = threading.Event()
lock = threading.Lock()
stats = {"requests": 0, "generated_tokens": 0, "soft_empty": 0, "garble": 0, "http_errors": 0, "request_seconds": 0.0}


def emit(message):
    with lock:
        print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def detect(label, text, tokens):
    body = TEMPLATE.sub("", text).strip()
    if tokens > 0 and not body:
        return "soft_empty"
    if len(body) > 200:
        window = body[-240:-200]
        if window and body.count(window) > 4:
            return "garble"
    cjk = len(CJK.findall(body))
    if cjk > 5 and label != "long":
        return "garble"
    if tokens > 0 and len(body) < tokens * 0.4:
        return "garble"
    return ""


def worker(worker_id):
    rng = random.Random(worker_id)
    while not stop.is_set():
        label, prompt = rng.choice(PROMPTS)
        body = {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": rng.choice([300, 500, 800]),
            "temperature": rng.choice([0.0, 0.3, 0.7]),
        }
        request = urllib.request.Request(
            URL + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                payload = json.load(response)
            elapsed = time.perf_counter() - started
            message = payload["choices"][0]["message"]
            text = message.get("content") or ""
            text += message.get("reasoning") or message.get("reasoning_content") or ""
            if message.get("tool_calls"):
                text += json.dumps(message["tool_calls"])
            tokens = int((payload.get("usage") or {}).get("completion_tokens") or 0)
            issue = detect(label, text, tokens)
            with lock:
                stats["requests"] += 1
                stats["generated_tokens"] += tokens
                stats["request_seconds"] += elapsed
                if issue:
                    stats[issue] += 1
            if issue:
                emit(f"ISSUE [{label}] {issue} tokens={tokens} head={text[:80]!r}")
        except Exception as exc:
            with lock:
                stats["http_errors"] += 1
            emit(f"ERROR [{label}] {type(exc).__name__}: {str(exc)[:140]}")
            time.sleep(2)


def heartbeat():
    started = time.monotonic()
    while not stop.wait(300):
        with lock:
            snapshot = dict(stats)
        emit(f"HEARTBEAT {(time.monotonic() - started) / 60:.0f}min {snapshot}")


def main():
    if not TEST_MODE and MINUTES != 40:
        print(f"ERROR: formal soak duration must be exactly 40 minutes, got {MINUTES}", flush=True)
        return 2
    if CONC != 4 and not TEST_MODE:
        print(f"ERROR: formal soak concurrency must be exactly 4, got {CONC}", flush=True)
        return 2
    emit(f"SOAK START [{TAG}] {URL} conc={CONC} minutes={MINUTES}")
    threads = [threading.Thread(target=worker, args=(index,), daemon=True) for index in range(CONC)]
    for thread in threads:
        thread.start()
    threading.Thread(target=heartbeat, daemon=True).start()
    try:
        time.sleep(MINUTES * 60)
    except KeyboardInterrupt:
        pass
    stop.set()
    for thread in threads:
        thread.join(timeout=5)
    with lock:
        result = dict(stats)
    result.update(
        {
            "schema_version": 1,
            "upstream_revision": "f277b3dfa718a5962bed64e69e7e640a5384ec2f",
            "tag": TAG,
            "url": URL,
            "model": MODEL,
            "concurrency": CONC,
            "minutes": MINUTES,
        }
    )
    valid = (
        result["requests"] > 0
        and result["generated_tokens"] > 0
        and result["soft_empty"] == 0
        and result["garble"] == 0
        and result["http_errors"] == 0
    )
    result["status"] = "passed" if valid else "failed"
    if RESULT_PATH:
        with open(RESULT_PATH, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    emit(f"SOAK DONE [{TAG}] {json.dumps(result, ensure_ascii=False)}")
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
