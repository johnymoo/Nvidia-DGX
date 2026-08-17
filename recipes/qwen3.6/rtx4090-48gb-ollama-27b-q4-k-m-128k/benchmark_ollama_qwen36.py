#!/usr/bin/env python3
"""Single-stream inference benchmark for the local Ollama Qwen3.6 service."""

import argparse
import json
import statistics
import subprocess
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_URL = "http://127.0.0.1:8004/api/chat"
DEFAULT_MODEL = "qwen3.6:27b"


def repeated_context(target_words):
    unit = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
    return " ".join([unit] * ((target_words + 9) // 10))


def prefill_scenario(name, target_words):
    return {
        "name": name,
        "prompt": (
            "Read the following reference text. Reply with exactly the word ACK.\n\n"
            + repeated_context(target_words)
        ),
        "num_predict": 16,
        "think": False,
        "fresh_prefix": True,
        "target_words": target_words,
    }


def standard_scenarios():
    return [
        {
            "name": "decode_256",
            "prompt": (
                "Explain how a Python dictionary resolves a key lookup. "
                "Give a precise, self-contained technical explanation."
            ),
            "num_predict": 256,
            "think": False,
        },
        {
            "name": "code_256",
            "prompt": (
                "Write a Python function that reverses a singly linked list. "
                "Include type hints, edge cases, and a short explanation."
            ),
            "num_predict": 256,
            "think": False,
        },
        {
            "name": "reasoning_512",
            "prompt": (
                "Solve this step by step: A train travels 120 km in 2 hours. "
                "Then it travels 90 km in 1.5 hours. What is its average speed for the full trip?"
            ),
            "num_predict": 512,
            "think": True,
        },
        prefill_scenario("prefill_1k", 1000),
        prefill_scenario("prefill_8k", 8000),
        prefill_scenario("prefill_16k", 16000),
    ]


def long_context_scenarios():
    # Word counts are chosen to stay below the 128K allocation after tokenization.
    return [
        prefill_scenario("prefill_32k", 30000),
        prefill_scenario("prefill_64k", 58000),
        prefill_scenario("prefill_96k", 87000),
        prefill_scenario("prefill_124k", 112000),
    ]


def post_stream(url, payload, timeout):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    first_token_at = None
    final_event = None

    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw_line in response:
            line = raw_line.strip()
            if not line:
                continue
            event = json.loads(line)
            message = event.get("message", {})
            if first_token_at is None and (message.get("content") or message.get("thinking")):
                first_token_at = time.perf_counter()
            if event.get("done"):
                final_event = event

    completed = time.perf_counter()
    if final_event is None:
        raise RuntimeError("Ollama stream ended without a final event")
    if first_token_at is None:
        first_token_at = completed
    return {
        "client_wall_s": completed - started,
        "client_ttft_s": first_token_at - started,
        "final_event": final_event,
    }


def is_numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def numeric_value(record, key, default=None):
    value = record.get(key)
    return value if is_numeric(value) else default


def duration_seconds(event, name):
    duration = numeric_value(event, name)
    return duration / 1_000_000_000 if duration is not None else None


def format_metric(value, precision=1, width=None):
    formatted = f"{value:.{precision}f}" if is_numeric(value) else "N/A"
    return f"{formatted:>{width}}" if width is not None else formatted


def prompt_for_run(scenario, run_id):
    if not scenario.get("fresh_prefix"):
        return scenario["prompt"]
    marker = f"Noncached benchmark marker: {run_id}.\n"
    return marker + scenario["prompt"]


def measure(url, model, scenario, run_id, timeout):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt_for_run(scenario, run_id)}],
        "stream": True,
        "think": scenario["think"],
        "options": {"temperature": 0, "num_predict": scenario["num_predict"]},
    }
    streamed = post_stream(url, payload, timeout)
    event = streamed["final_event"]
    prompt_tokens = numeric_value(event, "prompt_eval_count", 0)
    completion_tokens = numeric_value(event, "eval_count", 0)
    prompt_eval_s = duration_seconds(event, "prompt_eval_duration")
    eval_s = duration_seconds(event, "eval_duration")
    total_s = duration_seconds(event, "total_duration")

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "prompt_eval_s": prompt_eval_s,
        "eval_s": eval_s,
        "load_s": duration_seconds(event, "load_duration"),
        "server_total_s": total_s,
        "client_ttft_s": streamed["client_ttft_s"],
        "client_wall_s": streamed["client_wall_s"],
        "prompt_tok_s": prompt_tokens / prompt_eval_s if prompt_eval_s else None,
        "decode_tok_s": completion_tokens / eval_s if eval_s else None,
        "end_to_end_tok_s": (
            completion_tokens / streamed["client_wall_s"] if streamed["client_wall_s"] else None
        ),
        "done_reason": event.get("done_reason"),
        "prompt_cache_mode": "fresh-prefix" if scenario.get("fresh_prefix") else "normal",
        "thinking": scenario["think"],
    }


def mean_metric(runs, key):
    values = [numeric_value(run, key) for run in runs]
    values = [value for value in values if value is not None]
    return statistics.mean(values) if values else None


def stdev_metric(runs, key):
    values = [numeric_value(run, key) for run in runs]
    values = [value for value in values if value is not None]
    if len(values) > 1:
        return statistics.stdev(values)
    return 0 if values else None


def milliseconds(value):
    return value * 1000 if is_numeric(value) else None


def summary(name, runs, scenario):
    return {
        "name": name,
        "target_words": scenario.get("target_words"),
        "thinking": runs[0]["thinking"] if runs else None,
        "runs": len(runs),
        "prompt_tokens_mean": mean_metric(runs, "prompt_tokens"),
        "completion_tokens_mean": mean_metric(runs, "completion_tokens"),
        "client_ttft_ms_mean": milliseconds(mean_metric(runs, "client_ttft_s")),
        "client_wall_ms_mean": milliseconds(mean_metric(runs, "client_wall_s")),
        "prompt_tok_s_mean": mean_metric(runs, "prompt_tok_s"),
        "decode_tok_s_mean": mean_metric(runs, "decode_tok_s"),
        "end_to_end_tok_s_mean": mean_metric(runs, "end_to_end_tok_s"),
        "decode_tok_s_std": stdev_metric(runs, "decode_tok_s"),
    }


def gpu_info():
    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            text=True,
        )
        return output.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument(
        "--long-context-only",
        action="store_true",
        help="run 32K, 64K, 96K, and approximately 124K fresh-prefix prefill scenarios only",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.runs < 1:
        parser.error("--runs must be at least 1")

    print(f"Warming model {args.model} at {args.url}...")
    warmup = {
        "model": args.model,
        "messages": [
            {
                "role": "user",
                "content": "Write a concise Python function and explanation for reversing a linked list.",
            }
        ],
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_predict": 256},
    }
    request = urllib.request.Request(
        args.url,
        data=json.dumps(warmup).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=args.timeout):
        pass

    selected_scenarios = long_context_scenarios() if args.long_context_only else standard_scenarios()
    all_runs = {}
    summaries = []
    benchmark_id = uuid.uuid4().hex
    for scenario in selected_scenarios:
        name = scenario["name"]
        print(f"\n{name}")
        runs = []
        for index in range(args.runs):
            run_id = f"{benchmark_id}-{name}-{index + 1}"
            result = measure(args.url, args.model, scenario, run_id, args.timeout)
            runs.append(result)
            print(
                f"  run {index + 1}: ttft={format_metric(milliseconds(result['client_ttft_s']), 0)} ms "
                f"prefill={format_metric(result['prompt_tok_s'])} tok/s "
                f"decode={format_metric(result['decode_tok_s'])} tok/s "
                f"e2e={format_metric(result['end_to_end_tok_s'])} tok/s"
            )
        all_runs[name] = runs
        summaries.append(summary(name, runs, scenario))

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "url": args.url,
        "runs_per_scenario": args.runs,
        "benchmark_id": benchmark_id,
        "scenario_set": "long-context-only" if args.long_context_only else "standard",
        "hardware": gpu_info(),
        "methodology": {
            "streaming": True,
            "temperature": 0,
            "thinking": "disabled except for the reasoning_512 scenario",
            "ttft": "client time from request send to first content or thinking token",
            "prefill": "prompt_eval_count / prompt_eval_duration from Ollama final event",
            "decode": "eval_count / eval_duration from Ollama final event",
            "end_to_end": "eval_count / client wall-clock duration",
        },
        "summaries": summaries,
        "runs": all_runs,
    }
    output = args.output or Path(
        f"benchmark_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print("\nSummary")
    print("scenario       ttft(ms)  prefill tok/s  decode tok/s  e2e tok/s")
    for item in summaries:
        print(
            f"{item['name']:<14} {format_metric(item['client_ttft_ms_mean'], 0, 8)} "
            f"{format_metric(item['prompt_tok_s_mean'], 1, 14)} "
            f"{format_metric(item['decode_tok_s_mean'], 1, 13)} "
            f"{format_metric(item['end_to_end_tok_s_mean'], 1, 10)}"
        )
    print(f"\nSaved: {output}")


if __name__ == "__main__":
    main()
