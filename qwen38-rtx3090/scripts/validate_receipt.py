#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


SHA256 = re.compile(r"^[0-9a-f]{64}$")
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


def validate(path: Path) -> None:
    data = json.loads(path.read_text())
    require(data["schema_version"] == 1, "unsupported schema")
    require(data["status"] == "passed", "receipt did not pass")
    require(data["hardware"]["gpu"] == "NVIDIA GeForce RTX 3090", "wrong GPU")
    require(data["hardware"]["gpu_memory_mib"] == 24576, "wrong GPU memory")
    for key in ("model_sha256", "mmproj_sha256"):
        require(bool(SHA256.fullmatch(data["artifacts"][key])), f"invalid {key}")
    require("@sha256:" in data["artifacts"]["image_ref"], "image is not digest-pinned")
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
    require(REQUIRED_CASES == set(cases), "acceptance case set mismatch")
    require(
        all(case["status"] == "passed" for case in cases.values()),
        "acceptance case failed",
    )
    require(
        all(SHA256.fullmatch(value) for value in data["source_evidence"].values()),
        "invalid source evidence hash",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    validate(args.receipt)
    print(f"PASS {args.receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
