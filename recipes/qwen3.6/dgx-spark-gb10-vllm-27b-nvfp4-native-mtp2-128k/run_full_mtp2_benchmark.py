#!/usr/bin/env python3
"""Run the 48-request MTP2 benchmark and persist speculative-decoding metrics."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "benchmark_outputs"
BENCHMARK = ROOT / "benchmark_vllm_qwen36_27b_unsloth_nvfp4_mtp2.py"
BENCH_URL = os.getenv("BENCH_URL", "http://127.0.0.1:8004/v1/chat/completions")
BASE_URL = BENCH_URL.removesuffix("/v1/chat/completions").rstrip("/")
METRICS_URL = os.getenv("METRICS_URL", f"{BASE_URL}/metrics")
METRICS_MODEL_NAME = "qwen3.6-35b-fp8"
RESULT_GLOB = "benchmark-results-qwen3.6-27b-unsloth-nvfp4-mtp2-*.json"
METRIC_NAMES = (
    "spec_decode_num_drafts_total",
    "spec_decode_num_draft_tokens_total",
    "spec_decode_num_accepted_tokens_total",
    "spec_decode_num_accepted_tokens_per_pos_total",
)


def metric_snapshot() -> dict[str, float]:
    text = urllib.request.urlopen(METRICS_URL, timeout=30).read().decode()
    values: dict[str, float] = {}
    found_names: set[str] = set()
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        for name in METRIC_NAMES:
            if f"vllm:{name}" not in line:
                continue
            if f'model_name="{METRICS_MODEL_NAME}"' not in line:
                continue
            position = re.search(r'position="(\d+)"', line)
            key = f"{name}_pos{position.group(1)}" if position else name
            values[key] = float(line.rsplit(" ", 1)[1])
            found_names.add(name)
    missing = sorted(set(METRIC_NAMES) - found_names)
    if missing:
        raise RuntimeError(
            f"Missing speculative metrics for model_name={METRICS_MODEL_NAME}: {missing!r}"
        )
    return values


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = OUTPUT_DIR / f"benchmark-run-qwen3.6-27b-unsloth-nvfp4-mtp2-{stamp}.log"
    summary_path = OUTPUT_DIR / f"benchmark-run-summary-qwen3.6-27b-unsloth-nvfp4-mtp2-{stamp}.json"
    before_files = set(OUTPUT_DIR.glob(RESULT_GLOB))
    before_metrics = metric_snapshot()
    started = datetime.now().astimezone()
    started_perf = time.perf_counter()

    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, str(BENCHMARK)],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
            log.flush()
        returncode = process.wait()

    duration = time.perf_counter() - started_perf
    ended = datetime.now().astimezone()
    after_metrics = metric_snapshot()
    delta = {
        key: after_metrics.get(key, 0.0) - before_metrics.get(key, 0.0)
        for key in set(before_metrics) | set(after_metrics)
    }
    new_results = sorted(set(OUTPUT_DIR.glob(RESULT_GLOB)) - before_files)
    result_path = new_results[-1] if new_results else None
    draft_tokens = delta.get("spec_decode_num_draft_tokens_total", 0.0)
    accepted_tokens = delta.get("spec_decode_num_accepted_tokens_total", 0.0)
    draft_steps = delta.get("spec_decode_num_drafts_total", 0.0)
    summary = {
        "started": started.isoformat(),
        "ended": ended.isoformat(),
        "duration_seconds": duration,
        "benchmark_exit_code": returncode,
        "benchmark_script": BENCHMARK.name,
        "benchmark_log": str(log_path.relative_to(ROOT)),
        "benchmark_result": str(result_path.relative_to(ROOT)) if result_path else None,
        "speculative_config": {"method": "mtp", "num_speculative_tokens": 2},
        "metrics_before": before_metrics,
        "metrics_after": after_metrics,
        "metrics_delta": delta,
        "acceptance_rate": accepted_tokens / draft_tokens if draft_tokens else None,
        "accepted_tokens_per_draft_step": accepted_tokens / draft_steps if draft_steps else None,
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print("\nWRAPPER_SUMMARY=" + json.dumps({**summary, "summary_path": str(summary_path)}, ensure_ascii=False))
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
