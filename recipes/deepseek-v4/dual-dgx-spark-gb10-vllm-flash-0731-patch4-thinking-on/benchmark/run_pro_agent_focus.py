#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import importlib.util
import json
import os
import secrets
import shutil
import statistics
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
RUNNER_PATH = SCRIPT_DIR / "run_benchmark.py"
SELECTED = (
    "ndjson-stream-decoder",
    "terminal-log-frequency",
    "ops-oom-cgroup",
    "writing-zh-incident",
    "typescript-lru-ttl",
)


def load_runner() -> Any:
    spec = importlib.util.spec_from_file_location("pro_focus_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load benchmark runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def count_thinking(path: Path) -> int:
    count = 0
    for line in path.read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "assistant":
            continue
        for block in (event.get("message") or {}).get("content") or []:
            count += block.get("type") in {"thinking", "redacted_thinking"}
    return count


def source_comparison(path: Path) -> dict[str, dict[str, str]]:
    state = json.loads(path.read_text())
    rows: dict[str, dict[str, str]] = {task_id: {} for task_id in SELECTED}
    for attempt in state["attempts"]:
        if attempt["task_id"] in rows and attempt["treatment"] in {"online_ds", "offline_ds"}:
            rows[attempt["task_id"]][attempt["treatment"]] = attempt["hidden_grader"]["status"]
    if any(set(value) != {"online_ds", "offline_ds"} for value in rows.values()):
        raise RuntimeError("source comparison is incomplete")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--source-state", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--allow-external", action="store_true")
    parser.add_argument("--parallelism", type=int, default=5)
    args = parser.parse_args()
    args.toolchain = args.toolchain.resolve()
    args.source_state = args.source_state.resolve()
    args.artifact_root = args.artifact_root.resolve()
    if not args.allow_external:
        parser.error("--allow-external is required for the online benchmark")
    if not os.environ.get("CLAUDE_DS_TOKEN"):
        parser.error("CLAUDE_DS_TOKEN is required")
    if args.parallelism < 1:
        parser.error("--parallelism must be positive")

    pilot = load_runner()
    manifest = pilot.load_manifest()
    tasks = {task["task_id"]: task for task in manifest["tasks"]}
    real_claude = pilot.find_real_claude(manifest["claude_code_version"])
    original_provider_spec = pilot.provider_spec

    def provider_spec(treatment: str, selected_manifest: dict | None = None) -> dict[str, str]:
        if treatment == "online_pro":
            return {
                "route": "claude_ds",
                "provider": "ds",
                "model": "deepseek-v4-pro",
                "base_url": args.base_url,
            }
        return original_provider_spec(treatment, selected_manifest)

    pilot.provider_spec = provider_spec
    source = source_comparison(args.source_state)

    def run_task(task_id: str) -> dict[str, Any]:
        task = tasks[task_id]
        final = args.artifact_root / "attempts" / task_id
        if (final / "attempt.json").is_file():
            return json.loads((final / "attempt.json").read_text())
        scratch = args.artifact_root / "scratch" / f"{task_id}-{secrets.token_hex(6)}"
        temporary = final.with_name(f".{task_id}-{secrets.token_hex(4)}.tmp")
        base_commit = pilot.prepare_workspace(pilot.checked_path(pilot.FIXTURE_ROOT, task["fixture"]), scratch)
        try:
            stream = temporary / "stream.jsonl"
            attempt = pilot.run_claude(
                treatment="online_pro",
                prompt=pilot.task_prompt(task),
                cwd=scratch,
                timeout_seconds=int(manifest["task_timeout_seconds"]),
                toolchain=args.toolchain,
                real_claude=real_claude,
                expected_version=manifest["claude_code_version"],
                output_path=stream,
                with_tools=True,
                manifest=manifest,
            )
            visible = pilot.run_visible_tests(task, scratch, temporary, int(manifest["visible_test_timeout_seconds"]))
            hidden = pilot.run_hidden_grader(task, scratch, temporary, int(manifest["grade_timeout_seconds"]))
            patch = pilot.capture_patch(scratch)
            thinking_blocks = count_thinking(stream)
            attempt.update(
                {
                    "task_id": task_id,
                    "title": task["title"],
                    "base_commit": base_commit,
                    "visible_tests": visible,
                    "hidden_grader": hidden,
                    "thinking_blocks": thinking_blocks,
                    "task_status": "passed"
                    if hidden["status"] == "passed" and attempt["agent_status"] == "completed"
                    else "failed",
                    "changed_files": pilot.changed_files(scratch),
                    "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
                    "source_status": source[task_id],
                }
            )
            write_json(temporary / "attempt.json", attempt)
            final.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temporary, final)
            return attempt
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallelism) as executor:
        attempts = list(executor.map(run_task, SELECTED))
    result = {
        "schema_version": 1,
        "status": "passed" if all(item["task_status"] == "passed" for item in attempts) else "completed_with_failures",
        "model": "deepseek-v4-pro",
        "reasoning_effort": "high (official API default)",
        "claude_code_version": manifest["claude_code_version"],
        "parallelism": args.parallelism,
        "task_count": len(attempts),
        "passed": sum(item["task_status"] == "passed" for item in attempts),
        "thinking_block_count": sum(item["thinking_blocks"] for item in attempts),
        "elapsed_seconds_mean": statistics.fmean(item["elapsed_seconds"] for item in attempts),
        "tasks": attempts,
    }
    write_json(args.artifact_root / "result.json", result)
    print(json.dumps({"output": str(args.artifact_root / "result.json"), "passed": result["passed"]}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
