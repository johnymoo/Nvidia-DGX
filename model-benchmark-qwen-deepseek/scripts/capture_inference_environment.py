#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


LOCAL_MODELS = {
    "qwen38": {
        "container": "qwen38-vllm",
        "model_id": "Qwen/Qwen3.8-27B-FP8",
        "model_path": Path("/data/models/modelscope/Qwen3.8-27B-FP8"),
    },
    "qwen36": {
        "container": "qwen36-vllm",
        "model_id": "Qwen/Qwen3.6-35B-A3B-FP8",
        "model_path": Path("/data/models/modelscope/Qwen3.6-35B-A3B-FP8"),
    },
}


def command(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def docker_logs(container: str) -> str:
    result = subprocess.run(
        ["docker", "logs", "--timestamps", container],
        check=True,
        capture_output=True,
        text=True,
    )
    return "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)


def parse_timestamp(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    normalized = re.sub(r"(\.\d{6})\d+(?=[+-])", r"\1", normalized)
    return datetime.fromisoformat(normalized)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def startup_metrics(container: str, started_at: str) -> dict:
    started = parse_timestamp(started_at)
    logs = docker_logs(container).splitlines()
    ready_at = None
    model_load_seconds = None
    model_load_gib = None
    for line in logs:
        timestamp_text, _, message = line.partition(" ")
        try:
            timestamp = parse_timestamp(timestamp_text)
        except ValueError:
            continue
        if timestamp < started:
            continue
        load_match = re.search(r"Model loading took ([0-9.]+) GiB memory and ([0-9.]+) seconds", message)
        if load_match:
            model_load_gib = float(load_match.group(1))
            model_load_seconds = float(load_match.group(2))
        if "Application startup complete" in message:
            ready_at = timestamp
            break
    return {
        "definition": "Docker StartedAt to vLLM Application startup complete",
        "started_at": started_at,
        "ready_at": ready_at.isoformat() if ready_at else None,
        "service_startup_seconds": round((ready_at - started).total_seconds(), 3) if ready_at else None,
        "model_load_seconds": model_load_seconds,
        "model_load_gpu_memory_gib": model_load_gib,
        "host_page_cache_cleared": False,
        "qualification": "observed service restart; not a power-off cold boot",
    }


def local_model_snapshot(item: dict) -> dict:
    inspect = json.loads(command("docker", "inspect", item["container"]))[0]
    path: Path = item["model_path"]
    config_path = path / "config.json"
    config = json.loads(config_path.read_text())
    host = inspect["HostConfig"]
    state = inspect["State"]
    return {
        "model_id": item["model_id"],
        "model_source": "ModelScope",
        "model_path": str(path),
        "model_size_bytes": directory_size(path),
        "config_sha256": sha256(config_path),
        "architecture": (config.get("architectures") or [None])[0],
        "quantization": config.get("quantization_config", {}).get("quant_method"),
        "container": item["container"],
        "container_image": inspect["Config"]["Image"],
        "command": inspect["Config"]["Cmd"],
        "memory_limit_bytes": host.get("Memory"),
        "memory_swap_limit_bytes": host.get("MemorySwap"),
        "shm_size_bytes": host.get("ShmSize"),
        "restart_policy": host.get("RestartPolicy", {}).get("Name"),
        "running_after_benchmark": state.get("Running"),
        "startup": startup_metrics(item["container"], state["StartedAt"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os_release = {}
    for line in Path("/etc/os-release").read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            os_release[key] = value.strip('"')
    gpu_fields = command(
        "nvidia-smi",
        "--query-gpu=name,pci.bus_id,driver_version,memory.total,power.limit",
        "--format=csv,noheader,nounits",
    ).split(", ")
    memory = command("free", "-b").splitlines()
    mem_values = memory[1].split()
    swap_values = memory[2].split()
    record = {
        "schema_version": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "host": {
            "hostname": platform.node(),
            "os": os_release.get("PRETTY_NAME"),
            "kernel": platform.release(),
            "architecture": platform.machine(),
            "cpu": json.loads(command("lscpu", "-J"))["lscpu"],
            "logical_cpus": os.cpu_count(),
            "memory_total_bytes": int(mem_values[1]),
            "swap_total_bytes": int(swap_values[1]),
            "docker_version": command("docker", "version", "--format", "{{.Server.Version}}"),
            "python_version": platform.python_version(),
            "gpu": {
                "name": gpu_fields[0],
                "pci_bus_id": gpu_fields[1],
                "driver_version": gpu_fields[2],
                "memory_total_mib": int(gpu_fields[3]),
                "power_limit_w": float(gpu_fields[4]),
            },
        },
        "local_deployments": {name: local_model_snapshot(item) for name, item in LOCAL_MODELS.items()},
        "external_deployments": {
            "private-dgx-spark": {
                "model": "deepseek-v4-flash-0731",
                "hardware": "2 x NVIDIA GB10 / DGX Spark cluster",
                "runtime": "vLLM OpenAI-compatible API",
                "max_model_len": 1048576,
                "ownership": "private deployment",
                "cold_start": None,
                "cold_start_reason": "service lifecycle and startup logs are not exposed to this benchmark host",
            },
            "online-gateway": {
                "model": "deepseek-v4-flash (dynamic alias)",
                "hardware": "not disclosed",
                "runtime": "not disclosed behind managed API",
                "gateway": "Nginx 1.29.5 on NAS Ubuntu",
                "ownership": "online managed service",
                "cold_start": None,
                "cold_start_reason": "provider service lifecycle is not observable",
            },
        },
        "benchmark_conditions": {
            "quality_harness": "lakehouse-thinking-v1 with adjudication errata",
            "quality_seed": 42,
            "quality_execution": "single-stream, sequential within each endpoint",
            "latency_probe": "one warmup plus three measured SSE requests; endpoints run on independent hardware",
            "latency_max_tokens": 2048,
            "latency_prompt_language": "English",
            "pdf_font": "Noto Sans CJK SC",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
