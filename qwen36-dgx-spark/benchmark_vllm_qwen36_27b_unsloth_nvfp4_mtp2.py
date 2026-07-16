#!/usr/bin/env python3
"""Unsloth Qwen3.6-27B-NVFP4 MTP2 benchmark using the prior 35B matrix."""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

URL = os.getenv("BENCH_URL", "http://127.0.0.1:8004/v1/chat/completions")
BASE_URL = URL.removesuffix("/v1/chat/completions").rstrip("/")
METRICS_URL = os.getenv("METRICS_URL", f"{BASE_URL}/metrics")
SERVED_MODEL_NAME = os.getenv("SERVED_MODEL_NAME", "qwen3.6-35b-fp8")
DEPLOYMENT_MARKER = "qwen3.6-27b-unsloth-nvfp4"
REQUIRED_MODEL_ALIASES = ("qwen3.6-35b-fp8", DEPLOYMENT_MARKER)
EXPECTED_MAX_MODEL_LEN = int(os.getenv("EXPECTED_MAX_MODEL_LEN", "131072"))
ACTUAL_MODEL_NAME = "unsloth/Qwen3.6-27B-NVFP4"
ACTUAL_MODEL_SLUG = "qwen3.6-27b-unsloth-nvfp4-mtp2"
LABEL = "Unsloth Qwen3.6-27B NVFP4 native B12x + MTP2 on 8004"
GPU_MEMORY_UTILIZATION = 0.60
SPECULATIVE_CONFIG = {"method": "mtp", "num_speculative_tokens": 2}
SPECULATIVE_METRIC_NAMES = (
    "spec_decode_num_drafts_total",
    "spec_decode_num_draft_tokens_total",
    "spec_decode_num_accepted_tokens_total",
    "spec_decode_num_accepted_tokens_per_pos_total",
)
OUTPUT_DIR = Path(__file__).resolve().parent / "benchmark_outputs"

# Same prompts and generation configurations as the prior 35B benchmark.
PROMPTS = {
    "short": "What is 2+2?",
    "medium": "Explain quantum computing in simple terms.",
    "long_reasoning": "Solve this step by step: A train travels 120 km in 2 hours. What's the average speed?",
    "code": "Write a Python function to reverse a linked list.",
}

CONFIGS = [
    {"name": "default", "temp": 0.7, "max_tokens": 512, "reasoning": None},
    {"name": "greedy_fast", "temp": 0.0, "max_tokens": 512, "reasoning": None},
    {"name": "reasoning_on", "temp": 0.7, "max_tokens": 2048, "reasoning": True},
    {"name": "reasoning_off", "temp": 0.7, "max_tokens": 2048, "reasoning": False},
]


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.load(response)


def validate_endpoint() -> dict:
    version = get_json(f"{BASE_URL}/version")
    models = get_json(f"{BASE_URL}/v1/models")
    if not isinstance(version, dict) or not isinstance(models, dict):
        raise RuntimeError("Endpoint version/models responses must be JSON objects")
    model_data = models.get("data")
    if not isinstance(model_data, list):
        raise RuntimeError("Endpoint models response is missing a data list")
    model_entries = {
        item.get("id"): item for item in model_data if isinstance(item, dict)
    }
    exposed = list(model_entries)
    missing_aliases = [alias for alias in REQUIRED_MODEL_ALIASES if alias not in model_entries]
    if missing_aliases:
        raise RuntimeError(
            f"Missing required served aliases {missing_aliases!r}; endpoint exposes {exposed!r}"
        )
    wrong_lengths = {
        alias: model_entries[alias].get("max_model_len")
        for alias in REQUIRED_MODEL_ALIASES
        if model_entries[alias].get("max_model_len") != EXPECTED_MAX_MODEL_LEN
    }
    if wrong_lengths:
        raise RuntimeError(
            f"Expected max_model_len={EXPECTED_MAX_MODEL_LEN} for both aliases; "
            f"observed {wrong_lengths!r}"
        )

    with urllib.request.urlopen(METRICS_URL, timeout=10) as response:
        metrics_text = response.read().decode()
    target_label = 'model_name="qwen3.6-35b-fp8"'
    found_metrics = {
        name
        for line in metrics_text.splitlines()
        for name in SPECULATIVE_METRIC_NAMES
        if not line.startswith("#")
        and f"vllm:{name}" in line
        and target_label in line
    }
    missing_metrics = sorted(set(SPECULATIVE_METRIC_NAMES) - found_metrics)
    if missing_metrics:
        raise RuntimeError(
            f"Missing speculative-decoding metrics for {target_label}: {missing_metrics!r}"
        )
    return {
        "vllm_version": version.get("version"),
        "exposed_models": exposed,
        "max_model_len": EXPECTED_MAX_MODEL_LEN,
        "speculative_metrics": sorted(found_metrics),
    }


def run_test(name: str, prompt: str, config: dict, num_runs: int = 3) -> tuple[dict, list[str]]:
    print(f"\n{'=' * 72}", flush=True)
    print(f"Test: {name} | config={config['name']}", flush=True)
    print(f"Prompt: {prompt[:68]}...", flush=True)
    print("=" * 72, flush=True)

    results: list[dict] = []
    errors: list[str] = []

    for i in range(num_runs):
        payload = {
            "model": SERVED_MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": config["max_tokens"],
            "temperature": config["temp"],
            "stream": False,
        }
        if config["reasoning"] is not None:
            payload["chat_template_kwargs"] = {"enable_thinking": config["reasoning"]}

        started = time.perf_counter()
        try:
            proc = subprocess.run(
                [
                    "curl",
                    "-sS",
                    "-X",
                    "POST",
                    URL,
                    "-H",
                    "Content-Type: application/json",
                    "-d",
                    json.dumps(payload, ensure_ascii=False),
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )
            wall_ms = (time.perf_counter() - started) * 1000
            if proc.returncode != 0:
                errors.append(f"Run {i + 1}: curl failed: {proc.stderr[-500:]}")
                continue

            try:
                response = json.loads(proc.stdout)
            except json.JSONDecodeError:
                errors.append(f"Run {i + 1}: invalid JSON: {proc.stdout[:500]}")
                continue
            if not isinstance(response, dict):
                errors.append(f"Run {i + 1}: schema error: response must be an object")
                continue
            if "error" in response:
                errors.append(f"Run {i + 1}: API error: {response['error']}")
                continue

            usage = response.get("usage")
            if not isinstance(usage, dict):
                errors.append(f"Run {i + 1}: schema error: usage must be an object")
                continue
            completion_tokens = usage.get("completion_tokens")
            if (
                not isinstance(completion_tokens, int)
                or isinstance(completion_tokens, bool)
                or completion_tokens <= 0
            ):
                errors.append(
                    f"Run {i + 1}: schema error: completion_tokens must be a positive integer"
                )
                continue
            choices = response.get("choices")
            if not isinstance(choices, list) or not choices:
                errors.append(f"Run {i + 1}: schema error: choices must be a non-empty list")
                continue
            choice = choices[0]
            if not isinstance(choice, dict):
                errors.append(f"Run {i + 1}: schema error: first choice must be an object")
                continue
            message = choice.get("message")
            if not isinstance(message, dict):
                errors.append(f"Run {i + 1}: schema error: choice.message must be an object")
                continue
            prompt_tokens = usage.get("prompt_tokens", 0)

            # Preserve the historical script's estimate for direct comparison.
            legacy_ttft_ms = wall_ms * 0.3
            legacy_decode_ms = wall_ms - legacy_ttft_ms
            legacy_tok_per_sec = (
                completion_tokens / (legacy_decode_ms / 1000) if legacy_decode_ms > 0 else 0
            )
            # Also record the directly observed client wall-clock throughput.
            wall_tok_per_sec = completion_tokens / (wall_ms / 1000) if wall_ms > 0 else 0

            result = {
                "run": i + 1,
                "wall_ms": wall_ms,
                "wall_tok_per_sec": wall_tok_per_sec,
                "legacy_estimated_ttft_ms": legacy_ttft_ms,
                "legacy_estimated_decode_ms": legacy_decode_ms,
                "legacy_tok_per_sec": legacy_tok_per_sec,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "finish_reason": choice.get("finish_reason", "unknown"),
                "content_preview": (message.get("content") or "")[:100] or "(empty)",
                "reasoning_preview": (
                    message.get("reasoning") or message.get("reasoning_content") or ""
                )[:100]
                or "(empty)",
            }
            results.append(result)
            print(
                f"  Run {i + 1}: wall={wall_tok_per_sec:.1f} tok/s | "
                f"legacy={legacy_tok_per_sec:.1f} tok/s | "
                f"tokens={completion_tokens} | {wall_ms:.0f}ms | "
                f"finish={result['finish_reason']}",
                flush=True,
            )
        except subprocess.TimeoutExpired:
            errors.append(f"Run {i + 1}: timeout after 300s")
        except Exception as exc:  # keep the full suite running and record failures
            errors.append(f"Run {i + 1}: {type(exc).__name__}: {exc}")

    if not results:
        return {
            "test_name": name,
            "config": config["name"],
            "num_runs": 0,
            "errors": len(errors),
            "error_details": errors,
        }, errors

    wall_values = [item["wall_tok_per_sec"] for item in results]
    legacy_values = [item["legacy_tok_per_sec"] for item in results]
    wall_ms_values = [item["wall_ms"] for item in results]
    return {
        "test_name": name,
        "config": config["name"],
        "num_runs": len(results),
        "errors": len(errors),
        "wall_tok_per_sec_mean": statistics.mean(wall_values),
        "wall_tok_per_sec_std": statistics.stdev(wall_values) if len(wall_values) > 1 else 0,
        "wall_tok_per_sec_min": min(wall_values),
        "wall_tok_per_sec_max": max(wall_values),
        "legacy_tok_per_sec_mean": statistics.mean(legacy_values),
        "legacy_tok_per_sec_std": statistics.stdev(legacy_values) if len(legacy_values) > 1 else 0,
        # Historical key retained so existing comparison tooling can consume this run.
        "tok_per_sec_mean": statistics.mean(legacy_values),
        "tok_per_sec_std": statistics.stdev(legacy_values) if len(legacy_values) > 1 else 0,
        "tok_per_sec_min": min(legacy_values),
        "tok_per_sec_max": max(legacy_values),
        "wall_ms_mean": statistics.mean(wall_ms_values),
        "wall_ms_std": statistics.stdev(wall_ms_values) if len(wall_ms_values) > 1 else 0,
        "total_tokens_mean": statistics.mean(
            [item["completion_tokens"] for item in results]
        ),
        "runs": results,
        "error_details": errors,
    }, errors


def main() -> int:
    endpoint = validate_endpoint()
    started_at = datetime.now().astimezone()
    print("#" * 72)
    print("# vLLM Unsloth Qwen3.6-27B-NVFP4 native B12x + MTP2 benchmark")
    print(f"# Actual model: {ACTUAL_MODEL_NAME}")
    print(f"# Served model: {SERVED_MODEL_NAME}")
    print(f"# Speculative config: {SPECULATIVE_CONFIG}")
    print(f"# URL: {URL}")
    print(f"# vLLM: {endpoint['vllm_version']}")
    print(f"# Required aliases: {', '.join(REQUIRED_MODEL_ALIASES)}")
    print(f"# Expected max model length: {EXPECTED_MAX_MODEL_LEN}")
    print(f"# gpu-memory-utilization: {GPU_MEMORY_UTILIZATION:.2f}")
    print(f"# Started: {started_at.isoformat()}")
    print("#" * 72)

    all_results: list[dict] = []
    all_errors: list[str] = []
    for prompt_name, prompt_text in PROMPTS.items():
        for config in CONFIGS:
            stats, errors = run_test(
                f"{prompt_name}_{config['name']}", prompt_text, config, num_runs=3
            )
            all_results.append(stats)
            all_errors.extend(errors)

    print(f"\n{'#' * 72}\n# SUMMARY\n{'#' * 72}")
    print(f"{'Test':<40} {'Wall tok/s':>11} {'Legacy':>9} {'Tokens':>8} {'Errors':>7}")
    print("-" * 82)
    for result in all_results:
        if "wall_tok_per_sec_mean" not in result:
            print(f"{result['test_name']:<40} {'FAILED':>11} {'':>9} {'':>8} {result['errors']:>6}")
            continue
        print(
            f"{result['test_name']:<40} "
            f"{result['wall_tok_per_sec_mean']:>10.1f} "
            f"{result['legacy_tok_per_sec_mean']:>8.1f} "
            f"{result['total_tokens_mean']:>7.0f} "
            f"{result['errors']:>6}"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_file = OUTPUT_DIR / f"benchmark-results-{ACTUAL_MODEL_SLUG}-{timestamp}.json"
    output = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "benchmark_source": Path(__file__).name,
        "methodology": "same 4 prompts x 4 configs x 3 serial runs as prior 35B benchmark",
        "label": LABEL,
        "actual_model": ACTUAL_MODEL_NAME,
        "served_model_name": SERVED_MODEL_NAME,
        "url": URL,
        "vllm_version": endpoint["vllm_version"],
        "gpu_memory_utilization": GPU_MEMORY_UTILIZATION,
        "speculative_config": SPECULATIVE_CONFIG,
        "results": all_results,
        "errors": all_errors,
    }
    output_file.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    print(f"\nResults saved to: {output_file}")
    if all_errors:
        print(f"\nErrors encountered ({len(all_errors)}):")
        for error in all_errors[:10]:
            print(f"  - {error}")
    return 0 if not all_errors else 1


if __name__ == "__main__":
    sys.exit(main())
