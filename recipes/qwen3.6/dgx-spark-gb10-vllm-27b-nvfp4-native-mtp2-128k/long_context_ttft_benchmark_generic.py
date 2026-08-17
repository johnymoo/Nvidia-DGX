#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8004")
CHAT_URL = f"{BASE_URL}/v1/chat/completions"
TOKENIZE_URL = f"{BASE_URL}/tokenize"
METRICS_URL = f"{BASE_URL}/metrics"
MODEL = os.environ.get("MODEL", "qwen3.6-35b-fp8")
TAG = os.environ.get("BENCH_TAG", "fp8")
CONTAINER = os.environ.get("VLLM_CONTAINER", "vllm-qwen36-fp8-optimized")
DISABLE_THINKING = os.environ.get("DISABLE_THINKING", "1") == "1"
OUT_DIR = Path(os.environ.get("OUT_DIR", "/home/YOUR_USERNAME/project/nvidia-dgx/qwen36-dgx-spark/benchmark_outputs"))
OUT_DIR.mkdir(parents=True, exist_ok=True)
TS = datetime.now().strftime("%Y%m%d-%H%M%S")
OUT_JSON = OUT_DIR / f"long-context-ttft-{TAG}-{TS}.json"
OUT_MD = OUT_DIR / f"long-context-ttft-{TAG}-{TS}.md"
LOG_TXT = OUT_DIR / f"long-context-ttft-{TAG}-{TS}.log.txt"

TESTS = [
    {"label": "64K", "target_prompt_tokens": 65536, "max_tokens": 256},
    {"label": "128K", "target_prompt_tokens": 131072, "max_tokens": 256},
    {"label": "256K", "target_prompt_tokens": 256000, "max_tokens": 256},
]

FILLER = (
    "Context filler sentence for long context benchmarking. "
    "The quick brown fox jumps over the lazy dog while the ocean remains calm. "
    "This paragraph is intentionally repetitive and semantically neutral.\n"
)

METRIC_NAMES = [
    "vllm:prompt_tokens_total",
    "vllm:generation_tokens_total",
    "vllm:request_success_total",
    "vllm:time_to_first_token_seconds_count",
    "vllm:time_to_first_token_seconds_sum",
    "vllm:e2e_request_latency_seconds_count",
    "vllm:e2e_request_latency_seconds_sum",
    "vllm:request_queue_time_seconds_count",
    "vllm:request_queue_time_seconds_sum",
    "vllm:request_inference_time_seconds_count",
    "vllm:request_inference_time_seconds_sum",
    "vllm:request_prefill_time_seconds_count",
    "vllm:request_prefill_time_seconds_sum",
    "vllm:request_decode_time_seconds_count",
    "vllm:request_decode_time_seconds_sum",
    "vllm:request_time_per_output_token_seconds_count",
    "vllm:request_time_per_output_token_seconds_sum",
]


def http_json(url: str, payload: dict, timeout: int = 600) -> dict:
    req = Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def tokenize_messages_count(user_content: str) -> int:
    data = http_json(TOKENIZE_URL, {"model": MODEL, "messages": [{"role": "user", "content": user_content}]}, timeout=900)
    return int(data["count"])


def make_base_parts(label: str) -> tuple[str, str, int]:
    label_num = int(re.sub(r"\D", "", label))
    a, b = 137, 29
    expected = a * b + label_num
    salt = f"{TAG}-{label}-{TS}-{time.time_ns()}"
    prefix = f"""唯一测试ID：{salt}
你正在进行长上下文推理与延迟测试。请记住开头事实：A={a}。
下面会有大量无关背景文本。最终问题需要同时使用开头事实 A 和末尾事实 B。
不要复述背景文本。\n\n"""
    suffix = f"""\n\n长上下文结束。末尾事实：B={b}。
任务：请计算 A * B + {label_num}，并用 3-5 句话解释你如何从长上下文的开头和末尾提取事实完成计算。
最终答案必须包含数字 {expected}。"""
    return prefix, suffix, expected


def build_prompt_for_target(label: str, target_prompt_tokens: int) -> tuple[str, int, int]:
    prefix, suffix, expected = make_base_parts(label)
    def content(n: int) -> str:
        return prefix + (FILLER * n) + suffix
    lo, hi = 0, 1
    while tokenize_messages_count(content(hi)) < target_prompt_tokens:
        lo, hi = hi, hi * 2
        print(f"  tokenize upper search {label}: hi={hi}", flush=True)
    best_n, best_count = lo, tokenize_messages_count(content(lo))
    while lo <= hi:
        mid = (lo + hi) // 2
        cnt = tokenize_messages_count(content(mid))
        if cnt <= target_prompt_tokens:
            best_n, best_count = mid, cnt
            lo = mid + 1
        else:
            hi = mid - 1
    return content(best_n), best_count, expected


def fetch_metrics() -> dict[str, float]:
    raw = urlopen(METRICS_URL, timeout=30).read().decode("utf-8", errors="replace")
    values: dict[str, float] = {}
    for line in raw.splitlines():
        if not line or line.startswith("#"):
            continue
        name = line.split("{", 1)[0].split(" ", 1)[0]
        if name not in METRIC_NAMES:
            continue
        try:
            val = float(line.rsplit(" ", 1)[1])
        except Exception:
            continue
        values[name] = values.get(name, 0.0) + val
    return values


def mdiff(after: dict[str, float], before: dict[str, float], name: str) -> float:
    return after.get(name, 0.0) - before.get(name, 0.0)


def stream_chat(prompt: str, max_tokens: int) -> dict:
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if DISABLE_THINKING:
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    req = Request(CHAT_URL, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    start = time.perf_counter()
    first_event = first_nonempty = last_nonempty = None
    text_parts: list[str] = []
    raw_events = 0
    usage = None
    finish_reason = None
    with urlopen(req, timeout=3600) as resp:
        for raw in resp:
            now = time.perf_counter()
            line = raw.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            raw_events += 1
            if first_event is None:
                first_event = now
            try:
                obj = json.loads(data)
            except Exception:
                continue
            if obj.get("usage"):
                usage = obj["usage"]
            choices = obj.get("choices") or []
            if choices:
                ch = choices[0]
                finish_reason = ch.get("finish_reason") or finish_reason
                delta = ch.get("delta") or {}
                piece = delta.get("content") or delta.get("reasoning_content") or delta.get("reasoning") or ""
                if piece:
                    if first_nonempty is None:
                        first_nonempty = now
                    last_nonempty = now
                    text_parts.append(piece)
    end = time.perf_counter()
    content = "".join(text_parts)
    return {
        "client_wall_s": end - start,
        "client_first_event_s": (first_event - start) if first_event else None,
        "client_ttft_s": (first_nonempty - start) if first_nonempty else None,
        "client_decode_s": (last_nonempty - first_nonempty) if first_nonempty and last_nonempty else None,
        "raw_events": raw_events,
        "usage": usage,
        "finish_reason": finish_reason,
        "content": content,
        "content_preview": content[:500],
    }


def docker_logs_since(iso_since: str) -> str:
    try:
        proc = subprocess.run(["docker", "logs", "--since", iso_since, CONTAINER], text=True, capture_output=True, timeout=60)
        return proc.stdout + proc.stderr
    except Exception as e:
        return f"docker logs failed: {e}"


def run_one(test: dict) -> dict:
    label, target, max_tokens = test["label"], test["target_prompt_tokens"], test["max_tokens"]
    print(f"\n=== preparing {TAG} {label} target_prompt_tokens={target} ===", flush=True)
    prompt, prompt_tokens, expected = build_prompt_for_target(label, target)
    print(f"=== running {TAG} {label}: prompt_tokens={prompt_tokens}, max_tokens={max_tokens}, expected={expected} ===", flush=True)
    since_iso = datetime.now(timezone.utc).isoformat()
    before = fetch_metrics()
    start_iso_local = datetime.now().isoformat(timespec="seconds")
    stream = stream_chat(prompt, max_tokens)
    after = fetch_metrics()
    end_iso_local = datetime.now().isoformat(timespec="seconds")

    deltas = {name: mdiff(after, before, name) for name in METRIC_NAMES}
    usage_completion = stream.get("usage", {}).get("completion_tokens") if stream.get("usage") else None
    usage_prompt = stream.get("usage", {}).get("prompt_tokens") if stream.get("usage") else None
    m_gen = deltas["vllm:generation_tokens_total"]
    gen_tokens = usage_completion or m_gen or None
    client_tps = gen_tokens / stream["client_decode_s"] if gen_tokens and stream.get("client_decode_s") else None
    ttft_count = deltas["vllm:time_to_first_token_seconds_count"]
    e2e_count = deltas["vllm:e2e_request_latency_seconds_count"]
    prefill_count = deltas["vllm:request_prefill_time_seconds_count"]
    decode_count = deltas["vllm:request_decode_time_seconds_count"]
    infer_count = deltas["vllm:request_inference_time_seconds_count"]
    queue_count = deltas["vllm:request_queue_time_seconds_count"]
    logs = docker_logs_since(since_iso)
    interesting_logs = "\n".join(line for line in logs.splitlines() if any(k in line for k in ["Avg prompt throughput", "Avg generation throughput", "GPU KV cache", "SpecDecoding metrics", "HTTP/1.1"]))[-12000:]
    def avg(sum_name, count):
        return deltas[sum_name] / count if count else None
    decode_s = avg("vllm:request_decode_time_seconds_sum", decode_count)
    result = {
        "deployment_tag": TAG,
        "container": CONTAINER,
        "label": label,
        "target_prompt_tokens": target,
        "actual_prompt_tokens_tokenize": prompt_tokens,
        "usage_prompt_tokens": usage_prompt,
        "max_tokens": max_tokens,
        "expected_answer": expected,
        "answer_contains_expected": str(expected) in (stream.get("content") or ""),
        "start": start_iso_local,
        "end": end_iso_local,
        "finish_reason": stream.get("finish_reason"),
        "client": {
            "wall_s": stream["client_wall_s"],
            "first_event_s": stream["client_first_event_s"],
            "ttft_first_nonempty_s": stream["client_ttft_s"],
            "decode_s_first_to_last_token": stream["client_decode_s"],
            "avg_tps_completion_over_client_decode": client_tps,
            "raw_events": stream["raw_events"],
        },
        "tokens": {
            "usage_completion_tokens": usage_completion,
            "metrics_prompt_tokens_delta": deltas["vllm:prompt_tokens_total"],
            "metrics_generation_tokens_delta": m_gen,
        },
        "server_metrics_delta": {
            "ttft_s": avg("vllm:time_to_first_token_seconds_sum", ttft_count),
            "e2e_latency_s": avg("vllm:e2e_request_latency_seconds_sum", e2e_count),
            "queue_s": avg("vllm:request_queue_time_seconds_sum", queue_count),
            "inference_s": avg("vllm:request_inference_time_seconds_sum", infer_count),
            "prefill_s": avg("vllm:request_prefill_time_seconds_sum", prefill_count),
            "decode_s": decode_s,
            "avg_tps_generation_over_decode": (m_gen / decode_s) if m_gen and decode_s else None,
            "avg_tps_generation_over_e2e": (m_gen / avg("vllm:e2e_request_latency_seconds_sum", e2e_count)) if m_gen and e2e_count and avg("vllm:e2e_request_latency_seconds_sum", e2e_count) else None,
        },
        "content_preview": stream.get("content_preview"),
        "interesting_logs": interesting_logs,
    }
    print(json.dumps({k: result[k] for k in ["deployment_tag", "label", "actual_prompt_tokens_tokenize", "finish_reason", "answer_contains_expected", "client", "tokens", "server_metrics_delta"]}, ensure_ascii=False, indent=2), flush=True)
    return result


def main():
    all_results = []
    for t in TESTS:
        try:
            all_results.append(run_one(t))
        except Exception as e:
            print(f"ERROR in {TAG} {t['label']}: {type(e).__name__}: {e}", flush=True)
            all_results.append({"deployment_tag": TAG, "label": t["label"], "target_prompt_tokens": t["target_prompt_tokens"], "error": f"{type(e).__name__}: {e}"})
    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "deployment_tag": TAG,
        "container": CONTAINER,
        "model": MODEL,
        "endpoint": CHAT_URL,
        "method": "OpenAI-compatible streaming; client TTFT = first non-empty SSE delta; server metrics = Prometheus histogram delta before/after each sequential request.",
        "disable_thinking": DISABLE_THINKING,
        "tests": all_results,
    }
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# {TAG} 长上下文 TTFT/TPS",
        "",
        f"- time: {report['timestamp']}",
        f"- container: `{CONTAINER}`",
        f"- model: `{MODEL}`",
        f"- endpoint: `{CHAT_URL}`",
        "",
        "| Context | Prompt tokens | Client TTFT | Server TTFT | Client decode TPS | Server decode TPS | E2E | Finish | Correct |",
        "|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for r in all_results:
        if "error" in r:
            lines.append(f"| {r['label']} | {r.get('target_prompt_tokens','')} | ERROR | ERROR | ERROR | ERROR | ERROR | {r['error']} | — |")
            continue
        c, s = r["client"], r["server_metrics_delta"]
        lines.append(f"| {r['label']} | {r['actual_prompt_tokens_tokenize']:,} | {c['ttft_first_nonempty_s']:.2f}s | {s['ttft_s']:.2f}s | {c['avg_tps_completion_over_client_decode']:.1f} | {s['avg_tps_generation_over_decode']:.1f} | {s['e2e_latency_s']:.2f}s | {r['finish_reason']} | {'✅' if r['answer_contains_expected'] else '⚠️'} |")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    LOG_TXT.write_text("\n".join(f"\n===== {r.get('label')} =====\n{r.get('interesting_logs', r.get('error', ''))}" for r in all_results), encoding="utf-8")
    print("\nSAVED")
    print(OUT_JSON)
    print(OUT_MD)
    print(LOG_TXT)

if __name__ == "__main__":
    main()
