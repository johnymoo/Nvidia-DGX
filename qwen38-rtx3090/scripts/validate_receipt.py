#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


SHA256 = re.compile(r"^[0-9a-f]{64}$")
MODEL_SHA256 = "0fc041075efd255732ce6de77617ac31520b35a8dbffc06ef56cb80e5c8762ca"
MMPROJ_SHA256 = "cbb841a9ee0636b2ec172f5bb8df2ea8dfeb01e90fe7c6126581d662a0b4e43e"
IMAGE_REF = "ghcr.io/ggml-org/llama.cpp@sha256:a50b12bb92de0253d2737824ca1887f410e07b4dd3e3028f74a5a0a67c789e4b"
REQUIRED_CASES = {
    "identity",
    "text",
    "vision",
    "structured",
    "tool",
    "concurrency_4",
    "concurrency_8",
    "long_context",
    "soak",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_data(data: dict) -> None:
    require(data["schema_version"] == 1, "unsupported schema")
    require(data["status"] == "passed", "receipt did not pass")
    require(data["hardware"]["gpu"] == "NVIDIA GeForce RTX 3090", "wrong GPU")
    require(data["hardware"]["gpu_memory_mib"] == 24576, "wrong GPU memory")
    require(data["artifacts"]["model_sha256"] == MODEL_SHA256, "wrong model identity")
    require(data["artifacts"]["mmproj_sha256"] == MMPROJ_SHA256, "wrong projector identity")
    require(data["artifacts"]["image_ref"] == IMAGE_REF, "wrong runtime image")
    require(data["runtime"]["ctx_size"] == 131072, "wrong context")
    require(data["runtime"]["parallel"] == 2, "wrong parallel count")
    require(data["runtime"]["flash_attention"] is True, "flash attention disabled")
    require(
        data["runtime"]["kv_cache"] == {"key": "q4_0", "value": "q4_0"},
        "wrong KV cache",
    )
    require(
        data["safety"]["minimum_free_gpu_mib"]
        >= data["safety"]["required_free_gpu_mib"],
        "GPU headroom below floor",
    )
    require(
        data["safety"]["fatal_log_patterns_found"] is False,
        "fatal log pattern found",
    )
    cases = data["acceptance"]["cases"]
    require(data["acceptance"]["status"] == "passed", "acceptance did not pass")
    require(REQUIRED_CASES == set(cases), "acceptance case set mismatch")
    require(
        all(case["status"] == "passed" for case in cases.values()),
        "acceptance case failed",
    )
    require(
        all(SHA256.fullmatch(value) for value in data["source_evidence"].values()),
        "invalid source evidence hash",
    )


def validate(path: Path) -> None:
    validate_data(json.loads(path.read_text()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    validate(args.receipt)
    print(f"PASS {args.receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
