#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parents[1]
HARNESS_DIR = REPO_DIR / "model-benchmark-qwen-deepseek" / "scripts"
sys.path.insert(0, str(HARNESS_DIR))

import lakehouse_thinking_benchmark as harness  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(value):
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items()}
    return value


def image_identity(image: str) -> dict:
    command = ["docker", "image", "inspect", image, "--format", "{{json .}}"]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    value = json.loads(completed.stdout)
    return {
        "requested": image,
        "id": value["Id"],
        "repo_digests": value.get("RepoDigests") or [],
        "architecture": value.get("Architecture"),
    }


def adjudicate(path: Path) -> dict:
    source = json.loads(path.read_text())
    cases = [dict(case) for case in source["cases"]]
    checks_by_id = {case_id: checks for case_id, _prompt, checks in harness.PYTHON_CASES}
    overrides = []
    for case in cases:
        if case["category"] != "python":
            continue
        passed, detail = harness.execute_python(case["id"], case["response"], checks_by_id[case["id"]])
        overrides.append(
            {
                "id": case["id"],
                "original_score": case["score"],
                "adjudicated_score": float(passed),
                "executor_tail": detail,
            }
        )
        case["score"] = float(passed)
        case["passed"] = passed

    categories = {name: harness.summarize(cases, name) for name in ("sql", "python", "incident")}
    return {
        "tag": source["tag"],
        "source_file": path.name,
        "source_sha256": sha256(path),
        "original_macro_score": source["macro_score"],
        "macro_score": statistics.fmean(value["score"] for value in categories.values()),
        "categories": categories,
        "case_overrides": overrides,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sandbox-image", required=True)
    args = parser.parse_args()
    os.environ["PYTHON_SANDBOX_IMAGE"] = args.sandbox_image
    paths = sorted(args.input_dir.glob("online-pro-*.json"))
    if len(paths) != 6:
        parser.error(f"expected 6 Pro matrix files, found {len(paths)}")
    result = {
        "schema_version": 1,
        "status": "passed",
        "source_harness": harness.HARNESS_ID,
        "adjudication": {
            "reason": "Raw Python scores were invalid because the pinned sandbox image was unavailable during generation; saved final responses were re-executed without model calls.",
            "executor_image": image_identity(args.sandbox_image),
        },
        "runs": [adjudicate(path) for path in paths],
    }
    args.output.write_text(json.dumps(normalize(result), indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"output": str(args.output), "runs": len(result["runs"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
