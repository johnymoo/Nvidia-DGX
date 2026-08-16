#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def extrema(case):
    samples = case.get("resources", [])

    def values(key):
        observed = [row[key] for row in samples if row.get(key) is not None]
        if not observed:
            raise RuntimeError(
                f"resource samples are incomplete for case {case.get('id', 'unknown')}: "
                f"no {key} values")
        return observed

    available = values("available_memory_kib")
    rss = values("comfyui_rss_kib")
    gpu = values("gpu_utilization_percent")
    temperature = values("gpu_temperature_celsius")
    power = values("gpu_power_draw_watts")
    return {
        "samples": len(samples),
        "minimum_available_memory_gib": round(min(available) / 1048576, 3),
        "maximum_comfyui_rss_gib": round(max(rss) / 1048576, 3),
        "maximum_gpu_utilization_percent": max(gpu),
        "maximum_gpu_temperature_celsius": max(temperature),
        "maximum_gpu_power_draw_watts": max(power),
    }


def sanitize(source: Path):
    raw_bytes = source.read_bytes()
    data = json.loads(raw_bytes)
    if data.get("status") != "passed" or len(data.get("cases", [])) != 9:
        raise RuntimeError("source receipt is not the accepted nine-case run")
    cases = []
    for case in data["cases"]:
        if case.get("status") != "success":
            raise RuntimeError(f"case did not pass: {case.get('id')}")
        cases.append({
            "id": case["id"],
            "status": case["status"],
            "media_duration_seconds": float(case["video"]["ffprobe"]["format"]["duration"]),
            "execution_seconds": case["timing"]["comfyui_execution_seconds"],
            "bounded_wall_seconds": case["timing"]["bounded_wall_seconds"],
            "critical_generation_nodes_cached": case["timing"]["critical_generation_nodes_cached"],
            "video_sha256": case["video"]["sha256"],
            "decoded_rgb_sequence_sha256": case["video"]["decoded_rgb_sequence_sha256"],
            "png_sha256": case["image"]["sha256"],
            "resources": extrema(case),
        })
    deployment = data["deployment"]
    result = {
        "schema_version": 1,
        "status": data["status"],
        "provenance": {
            "run_id": data["run_id"],
            "started_at": data["started_at"],
            "completed_at": data["completed_at"],
            "raw_receipt_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "raw_receipt_committed": False,
        },
        "subject": {
            "hardware": "NVIDIA DGX Spark / GB10, 128 GB unified memory",
            "gitee_recipe_revision": deployment["gitee_revision"],
            "comfyui_revision": deployment["comfyui_revision"],
            "deployment_subject_sha256": deployment.get("subject_sha256"),
            "weight_files": 11,
            "weight_bytes": 176195310067,
        },
        "profile": data["selected_profile"],
        "summary": data["summary"] | {
            "reproducibility": data["reproducibility"],
            "fatal_scans": {
                name: scan["status"] for name, scan in data["fatal_scans"].items()
            },
        },
        "cases": cases,
        "interpretation": {
            "resources": "one-second polling extrema, not exact continuous peaks",
            "excluded": [
                "generated media", "raw logs and resource time series",
                "private host paths and network identities",
                "process and container identities",
            ],
        },
    }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = sanitize(args.input)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
