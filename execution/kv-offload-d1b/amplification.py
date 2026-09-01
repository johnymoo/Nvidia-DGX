#!/usr/bin/env python3
"""D1b store-amplification snapshotter.

Usage:
  amplification.py snap                      print one JSON snapshot
  amplification.py ratio SNAP1.json SNAP2.json TOKENS_BETWEEN
      -> expected bytes = TOKENS * 13.9 KiB; ratio = actual/expected.
Gate: ratio <= 1.3 (A1 measured ~13x; kill-grade).

13.9 KiB/token = cluster KV bytes per token (2 ranks, 5 groups, page-padded;
calibrated from A1: 8,589,934,592 B pool / 605K tokens ≈ 13.7-14.2 KiB).
"""
import json
import sys
import time
import urllib.request

METRICS = "http://192.168.88.181:8890/metrics"
KIB_PER_TOKEN = 13.9 * 1024


def scrape():
    with urllib.request.urlopen(METRICS, timeout=15) as r:
        text = r.read().decode()
    out = {}
    for line in text.splitlines():
        if line.startswith("vllm:kv_offload_total_bytes") or line.startswith("vllm:kv_offload_total_bytes_total"):
            key, _, val = line.rpartition(" ")
            key = key.split("{")[0] + "{" + (key.split("{", 1)[1] if "{" in key else "")
            out[key.strip()] = float(val)
        elif line.startswith("vllm:prefix_cache_"):
            key, _, val = line.rpartition(" ")
            out[key.strip()] = float(val)
    return out


def main():
    if sys.argv[1] == "snap":
        print(json.dumps({"epoch": time.time(), "metrics": scrape()}, indent=1))
        return
    if sys.argv[1] == "ratio":
        a = json.load(open(sys.argv[2]))["metrics"]
        b = json.load(open(sys.argv[3]))["metrics"]
        tokens = float(sys.argv[4])
        keys = [k for k in b if "kv_offload_total_bytes" in k and ("GPU_to_CPU" in k or "gpu_to_cpu" in k)]
        deltas = {}
        for k in keys:
            deltas[k] = b[k] - a.get(k, 0.0)
        actual = max(deltas.values(), default=0.0)
        expected = tokens * KIB_PER_TOKEN
        ratio = actual / expected if expected else None
        print(json.dumps({
            "gpu_to_cpu_delta_bytes": deltas,
            "actual_gib": round(actual / 1024**3, 3),
            "expected_gib": round(expected / 1024**3, 3),
            "tokens": tokens,
            "ratio": round(ratio, 2) if ratio is not None else None,
            "gate_pass": ratio is not None and ratio <= 1.3,
        }, indent=1))
        sys.exit(0 if (ratio is not None and ratio <= 1.3) else 1)
    raise SystemExit("unknown subcommand")


if __name__ == "__main__":
    main()
