#!/usr/bin/env python3
"""Run the frozen Claude Code Flash pilot in isolated local Git sandboxes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
BENCHMARK_DIR = SCRIPT_PATH.parent
EXECUTION_DIR = BENCHMARK_DIR.parent
PROJECT_ROOT = EXECUTION_DIR.parent
MANIFEST_PATH = BENCHMARK_DIR / "claude-code-sandbox-pilot-tasks.json"
FIXTURE_ROOT = BENCHMARK_DIR / "fixtures"
GRADER_ROOT = BENCHMARK_DIR / "graders"
SOLUTION_ROOT = BENCHMARK_DIR / "solutions"
DEFAULT_TOOLCHAIN = Path("/Users/chris/project/Shili/workspaces/coding-agent-toolchain")
DEFAULT_CACHE = EXECUTION_DIR / "artifacts" / "claude-code-pilot" / "cache"


class InfrastructureError(RuntimeError):
    pass


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in tree_files(root):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def checked_path(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute():
        raise InfrastructureError(f"invalid relative path: {relative!r}")
    root = root.resolve()
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise InfrastructureError(f"path escapes benchmark root: {relative}")
    return candidate


def load_manifest() -> dict[str, Any]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 2:
        raise InfrastructureError("unsupported task manifest schema")
    tasks = manifest.get("tasks") or []
    if len(tasks) != 4 or len({task.get("task_id") for task in tasks}) != 4:
        raise InfrastructureError("task manifest must contain four unique tasks")
    for task in tasks:
        task_id = task.get("task_id") or "<missing>"
        if sorted(task.get("treatment_order") or []) != ["online", "private"]:
            raise InfrastructureError(f"invalid treatment order for {task_id}")
        fixture = checked_path(FIXTURE_ROOT, task.get("fixture", ""))
        grader = checked_path(GRADER_ROOT, task.get("grader", ""))
        solution = checked_path(SOLUTION_ROOT, task.get("solution", ""))
        if not fixture.is_dir() or not tree_files(fixture):
            raise InfrastructureError(f"fixture missing for {task_id}: {fixture}")
        if any(path.is_symlink() for path in fixture.rglob("*")):
            raise InfrastructureError(f"fixture contains a symlink: {task_id}")
        if not grader.is_file() or not solution.is_dir() or not tree_files(solution):
            raise InfrastructureError(f"grader or solution missing for {task_id}")
        if not task.get("instruction") or not task.get("visible_test_command"):
            raise InfrastructureError(f"task contract incomplete: {task_id}")
    return manifest


def run_command(
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise InfrastructureError(
            f"command timed out after {timeout}s: {' '.join(argv[:4])}"
        ) from exc
    if check and result.returncode != 0:
        raise InfrastructureError(
            f"command failed ({result.returncode}): {' '.join(argv[:4])}\n"
            f"{result.stdout[-4000:]}"
        )
    return result


def run_measured_command(
    argv: list[str], *, cwd: Path, timeout: int, log_path: Path
) -> dict[str, Any]:
    started = time.monotonic()
    timed_out = False
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        output = result.stdout
        return_code = result.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        output = (exc.stdout or "") + (exc.stderr or "")
        return_code = 124
    elapsed = round(time.monotonic() - started, 3)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(output, encoding="utf-8")
    return {
        "argv": argv,
        "exit_code": return_code,
        "timed_out": timed_out,
        "elapsed_seconds": elapsed,
        "log_path": str(log_path),
    }


def find_real_claude(expected_version: str) -> Path:
    configured = os.environ.get("CLAUDE_BENCH_REAL_BIN")
    candidate_text = configured or shutil.which("claude") or ""
    candidate = Path(candidate_text)
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise InfrastructureError("real Claude Code binary not found")
    resolved = candidate.resolve()
    version = run_command([str(resolved), "--version"]).stdout.strip().split()[0]
    if version != expected_version:
        raise InfrastructureError(
            f"Claude Code version mismatch: {version}, expected {expected_version}"
        )
    return resolved


def toolchain_contract(toolchain: Path) -> dict[str, str]:
    shim = toolchain / "bin" / "claude"
    if not shim.is_file() or not os.access(shim, os.X_OK):
        raise InfrastructureError(f"toolchain Claude shim missing: {shim}")
    commit = run_command(["git", "rev-parse", "HEAD"], cwd=toolchain).stdout.strip()
    return {
        "shim": str(shim.resolve()),
        "shim_sha256": sha256_file(shim),
        "commit": commit,
    }


def provider_spec(treatment: str) -> dict[str, str]:
    if treatment == "online":
        return {
            "route": "claude_ds",
            "provider": "ds",
            "model": "deepseek-v4-flash",
            "base_url": os.environ.get(
                "CLAUDE_DS_BASE_URL",
                os.environ.get("CLAUDE_BASE_URL", "https://coding.onlyservice.io"),
            ),
        }
    if treatment == "private":
        return {
            "route": "claude_local",
            "provider": "local",
            "model": "deepseek-v4-flash-0731",
            "base_url": "http://192.168.88.181:8890",
        }
    raise InfrastructureError(f"unknown treatment: {treatment}")


def claude_environment(
    treatment: str, toolchain: Path, real_claude: Path
) -> tuple[dict[str, str], dict[str, str]]:
    spec = provider_spec(treatment)
    env = os.environ.copy()
    env.update(
        {
            "CLAUDE_SHIM_REPO_DIR": str(toolchain),
            "CLAUDE_REAL_BIN": str(real_claude),
            "CLAUDE_DEFAULT_PROVIDER": spec["provider"],
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        }
    )
    if treatment == "online":
        env["CLAUDE_DS_MODEL"] = spec["model"]
        env["CLAUDE_DS_BASE_URL"] = spec["base_url"]
    else:
        env["CLAUDE_LOCAL_TOKEN"] = "no-key-required"
        env["CLAUDE_LOCAL_MODEL"] = spec["model"]
        env["CLAUDE_LOCAL_BASE_URL"] = spec["base_url"]
    return env, spec


def claude_argv(shim: Path, model: str, prompt: str, with_tools: bool) -> list[str]:
    tools = "Bash,Edit,Read,Glob,Grep,Write" if with_tools else ""
    return [
        str(shim),
        "-p",
        "--model",
        model,
        "--safe-mode",
        "--disable-slash-commands",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--no-session-persistence",
        "--no-chrome",
        "--dangerously-skip-permissions",
        "--tools",
        tools,
        "--output-format",
        "stream-json",
        "--verbose",
        prompt,
    ]


def parse_stream(output: str) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    init = next(
        (
            event
            for event in events
            if event.get("type") == "system" and event.get("subtype") == "init"
        ),
        None,
    )
    result = next(
        (event for event in reversed(events) if event.get("type") == "result"), None
    )
    tool_calls: list[str] = []
    for event in events:
        message = event.get("message") if event.get("type") == "assistant" else None
        for block in (message or {}).get("content") or []:
            if block.get("type") == "tool_use":
                tool_calls.append(str(block.get("name") or "unknown"))
    return {"events": events, "init": init, "result": result, "tool_calls": tool_calls}


def validate_identity(
    parsed: dict[str, Any], treatment: str, expected_version: str
) -> None:
    init = parsed.get("init")
    if not init:
        raise InfrastructureError(f"{treatment}: Claude Code init event missing")
    expected_model = provider_spec(treatment)["model"]
    if init.get("model") != expected_model:
        raise InfrastructureError(
            f"{treatment}: model mismatch {init.get('model')!r}, "
            f"expected {expected_model!r}"
        )
    if init.get("claude_code_version") != expected_version:
        raise InfrastructureError(
            f"{treatment}: Claude Code init version mismatch "
            f"{init.get('claude_code_version')!r}"
        )
    result = parsed.get("result")
    if result and result.get("api_error_status") is not None:
        raise InfrastructureError(
            f"{treatment}: provider API error {result.get('api_error_status')}"
        )
    if result:
        models = set((result.get("modelUsage") or {}).keys())
        if models and models != {expected_model}:
            raise InfrastructureError(
                f"{treatment}: modelUsage contains unexpected models: {sorted(models)}"
            )


def run_claude(
    *,
    treatment: str,
    prompt: str,
    cwd: Path,
    timeout_seconds: int,
    toolchain: Path,
    real_claude: Path,
    expected_version: str,
    output_path: Path,
    with_tools: bool,
) -> dict[str, Any]:
    env, spec = claude_environment(treatment, toolchain, real_claude)
    contract = toolchain_contract(toolchain)
    argv = claude_argv(Path(contract["shim"]), spec["model"], prompt, with_tools)
    started = time.monotonic()
    timed_out = False
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        output, _ = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGTERM)
        try:
            output, _ = process.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            output, _ = process.communicate()
    elapsed = round(time.monotonic() - started, 3)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output, encoding="utf-8")
    parsed = parse_stream(output)
    validate_identity(parsed, treatment, expected_version)
    result = parsed.get("result") or {}
    if timed_out:
        agent_status = "timeout"
    elif process.returncode == 0:
        agent_status = "completed"
    else:
        agent_status = "agent_exit_error"
    return {
        "treatment": treatment,
        "route": spec["route"],
        "model": spec["model"],
        "claude_code_version": parsed["init"]["claude_code_version"],
        "agent_status": agent_status,
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "elapsed_seconds": elapsed,
        "duration_ms": result.get("duration_ms"),
        "duration_api_ms": result.get("duration_api_ms"),
        "ttft_ms": result.get("ttft_ms"),
        "num_turns": result.get("num_turns"),
        "terminal_reason": "timeout" if timed_out else result.get("terminal_reason"),
        "usage": result.get("usage") or {},
        "model_usage": result.get("modelUsage") or {},
        "cost_usd": result.get("total_cost_usd"),
        "permission_denials": result.get("permission_denials") or [],
        "tool_calls": parsed["tool_calls"],
        "stream_path": str(output_path),
    }


def probe_provider(
    treatment: str,
    toolchain: Path,
    real_claude: Path,
    expected_version: str,
    artifact: Path,
) -> dict[str, Any]:
    artifact.mkdir(parents=True, exist_ok=True)
    return run_claude(
        treatment=treatment,
        prompt="Reply with exactly: flash-ready",
        cwd=artifact,
        timeout_seconds=120,
        toolchain=toolchain,
        real_claude=real_claude,
        expected_version=expected_version,
        output_path=artifact / f"probe-{treatment}.jsonl",
        with_tools=False,
    )


def prepare_workspace(fixture: Path, destination: Path) -> str:
    if destination.exists():
        raise InfrastructureError(f"workspace already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(fixture, destination)
    run_command(["git", "init", "-q"], cwd=destination)
    run_command(["git", "config", "user.name", "Claude Code Pilot"], cwd=destination)
    run_command(["git", "config", "user.email", "pilot@localhost"], cwd=destination)
    run_command(["git", "add", "."], cwd=destination)
    run_command(["git", "commit", "-qm", "benchmark fixture"], cwd=destination)
    return run_command(["git", "rev-parse", "HEAD"], cwd=destination).stdout.strip()


def overlay_solution(solution: Path, workspace: Path) -> None:
    for source in tree_files(solution):
        relative = source.relative_to(solution)
        destination = workspace / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def capture_patch(workspace: Path) -> str:
    untracked = run_command(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=workspace
    ).stdout
    files = [item for item in untracked.split("\0") if item and item != ".claude"]
    if files:
        run_command(["git", "add", "-N", "--", *files], cwd=workspace)
    return run_command(
        ["git", "diff", "--binary", "--", ".", ":(exclude).claude"], cwd=workspace
    ).stdout


def changed_files(workspace: Path) -> list[str]:
    output = run_command(["git", "status", "--porcelain=v1"], cwd=workspace).stdout
    return sorted(line[3:] for line in output.splitlines() if len(line) > 3)


def command_for_task(task: dict[str, Any]) -> list[str]:
    return [
        sys.executable if token == "{python}" else str(token)
        for token in task["visible_test_command"]
    ]


def run_visible_tests(
    task: dict[str, Any], workspace: Path, artifact: Path, timeout: int
) -> dict[str, Any]:
    outcome = run_measured_command(
        command_for_task(task),
        cwd=workspace,
        timeout=timeout,
        log_path=artifact / "visible-tests.log",
    )
    outcome["status"] = (
        "passed" if outcome["exit_code"] == 0 and not outcome["timed_out"] else "failed"
    )
    return outcome


def run_hidden_grader(
    task: dict[str, Any], workspace: Path, artifact: Path, timeout: int
) -> dict[str, Any]:
    grader = checked_path(GRADER_ROOT, task["grader"])
    outcome = run_measured_command(
        [sys.executable, str(grader), str(workspace)],
        cwd=workspace,
        timeout=timeout,
        log_path=artifact / "hidden-grader.log",
    )
    parsed: dict[str, Any] | None = None
    if not outcome["timed_out"]:
        text = Path(outcome["log_path"]).read_text(encoding="utf-8")
        for line in reversed(text.splitlines()):
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and candidate.get("schema_version") == 1:
                parsed = candidate
                break
    if parsed:
        outcome.update(parsed)
    else:
        outcome.update(
            {
                "status": "failed",
                "passed": 0,
                "total": 0,
                "failures": ["grader_timeout" if outcome["timed_out"] else "grader_error"],
            }
        )
    if outcome["exit_code"] != 0 or outcome["timed_out"]:
        outcome["status"] = "failed"
    return outcome


def task_prompt(task: dict[str, Any]) -> str:
    return (
        f"Task: {task['title']}\n\n"
        f"{task['instruction'].strip()}\n\n"
        "Work directly in the current repository. You may read and modify only this repository. "
        "Do not inspect parent or sibling directories, benchmark harness files, hidden tests, "
        "solution artifacts, or external resources. Do not use network access or subagents. "
        "Run the visible tests and leave the best complete implementation in the worktree. "
        "Do not ask questions; finish when no further useful local verification remains."
    )


def controlled_files(toolchain: Path) -> list[Path]:
    files = [
        SCRIPT_PATH,
        MANIFEST_PATH,
        PROJECT_ROOT / "execution" / "run-claude-code-flash-pilot.sh",
        PROJECT_ROOT / "execution" / "run-vllm-service.sh",
        toolchain / "bin" / "claude",
    ]
    for root in (FIXTURE_ROOT, GRADER_ROOT, SOLUTION_ROOT):
        files.extend(tree_files(root))
    return sorted(set(path.resolve() for path in files))


def expected_preflight_key(
    manifest: dict[str, Any], toolchain: Path, real_claude: Path
) -> str:
    digest = hashlib.sha256()
    for path in controlled_files(toolchain):
        digest.update(str(path).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    digest.update(manifest["claude_code_version"].encode())
    digest.update(str(real_claude).encode())
    digest.update(toolchain_contract(toolchain)["commit"].encode())
    return digest.hexdigest()


def calibrate_task(
    task: dict[str, Any], root: Path, visible_timeout: int, grade_timeout: int
) -> dict[str, Any]:
    fixture = checked_path(FIXTURE_ROOT, task["fixture"])
    solution = checked_path(SOLUTION_ROOT, task["solution"])
    workspace = root / task["task_id"]
    prepare_workspace(fixture, workspace)
    initial = run_hidden_grader(task, workspace, root / "initial" / task["task_id"], grade_timeout)
    if initial["status"] == "passed":
        raise InfrastructureError(f"fixture unexpectedly passes hidden grader: {task['task_id']}")
    overlay_solution(solution, workspace)
    visible = run_visible_tests(task, workspace, root / "gold" / task["task_id"], visible_timeout)
    hidden = run_hidden_grader(task, workspace, root / "gold" / task["task_id"], grade_timeout)
    if visible["status"] != "passed" or hidden["status"] != "passed":
        raise InfrastructureError(f"gold calibration failed: {task['task_id']}")
    return {
        "task_id": task["task_id"],
        "fixture_sha256": tree_sha256(fixture),
        "initial_status": initial["status"],
        "gold_visible_status": visible["status"],
        "gold_hidden_status": hidden["status"],
        "gold_hidden_tests": hidden.get("total"),
    }


def run_preflight(cache: Path, artifact_root: Path, toolchain: Path) -> dict[str, Any]:
    manifest = load_manifest()
    started = utc_now()
    real_claude = find_real_claude(manifest["claude_code_version"])
    contract = toolchain_contract(toolchain)
    calibration_root = artifact_root / "calibration"
    calibrations = [
        calibrate_task(
            task,
            calibration_root,
            int(manifest["visible_test_timeout_seconds"]),
            int(manifest["grade_timeout_seconds"]),
        )
        for task in manifest["tasks"]
    ]
    shutil.rmtree(calibration_root, ignore_errors=True)
    online_probe = probe_provider(
        "online",
        toolchain,
        real_claude,
        manifest["claude_code_version"],
        artifact_root / "protocol-probe",
    )
    key = expected_preflight_key(manifest, toolchain, real_claude)
    receipt = {
        "schema_version": 2,
        "status": "passed",
        "preflight_key": key,
        "started_at": started,
        "ended_at": utc_now(),
        "baseline_revision": manifest["baseline_revision"],
        "manifest_sha256": sha256_file(MANIFEST_PATH),
        "runner_sha256": sha256_file(SCRIPT_PATH),
        "toolchain": contract,
        "claude_real_bin": str(real_claude),
        "claude_code_version": manifest["claude_code_version"],
        "online_probe": online_probe,
        "calibrations": calibrations,
        "task_ids": [task["task_id"] for task in manifest["tasks"]],
        "local_docker_used": False,
    }
    cache.mkdir(parents=True, exist_ok=True)
    write_json(cache / "preflight-receipt.json", receipt)
    write_json(artifact_root / "preflight-receipt.json", receipt)
    return receipt


def require_fresh_preflight(
    cache: Path,
    manifest: dict[str, Any],
    toolchain: Path,
    real_claude: Path,
) -> dict[str, Any]:
    receipt_path = cache / "preflight-receipt.json"
    if not receipt_path.is_file():
        raise InfrastructureError("preflight receipt is missing")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "passed":
        raise InfrastructureError("preflight receipt is not passed")
    expected = expected_preflight_key(manifest, toolchain, real_claude)
    if receipt.get("preflight_key") != expected:
        raise InfrastructureError("preflight receipt is stale")
    return receipt


def run_pilot(cache: Path, artifact_root: Path, toolchain: Path) -> dict[str, Any]:
    manifest = load_manifest()
    started = utc_now()
    real_claude = find_real_claude(manifest["claude_code_version"])
    preflight = require_fresh_preflight(cache, manifest, toolchain, real_claude)
    contract = toolchain_contract(toolchain)
    if contract != preflight["toolchain"]:
        raise InfrastructureError("coding-agent-toolchain changed after preflight")
    private_probe = probe_provider(
        "private",
        toolchain,
        real_claude,
        manifest["claude_code_version"],
        artifact_root / "protocol-probe",
    )
    attempts: list[dict[str, Any]] = []
    for task in manifest["tasks"]:
        for treatment in task["treatment_order"]:
            task_id = task["task_id"]
            attempt_root = artifact_root / "attempts" / treatment / task_id
            workspace = artifact_root / "workspaces" / treatment / task_id
            base_commit = prepare_workspace(
                checked_path(FIXTURE_ROOT, task["fixture"]), workspace
            )
            attempt = run_claude(
                treatment=treatment,
                prompt=task_prompt(task),
                cwd=workspace,
                timeout_seconds=int(manifest["task_timeout_seconds"]),
                toolchain=toolchain,
                real_claude=real_claude,
                expected_version=manifest["claude_code_version"],
                output_path=attempt_root / "stream.jsonl",
                with_tools=True,
            )
            visible = run_visible_tests(
                task,
                workspace,
                attempt_root,
                int(manifest["visible_test_timeout_seconds"]),
            )
            hidden = run_hidden_grader(
                task,
                workspace,
                attempt_root,
                int(manifest["grade_timeout_seconds"]),
            )
            patch = capture_patch(workspace)
            patch_path = attempt_root / "changes.patch"
            patch_path.write_text(patch, encoding="utf-8")
            attempt.update(
                {
                    "task_id": task_id,
                    "title": task["title"],
                    "category": task["category"],
                    "difficulty": task["difficulty"],
                    "base_commit": base_commit,
                    "workspace": str(workspace),
                    "visible_tests": visible,
                    "hidden_grader": hidden,
                    "task_status": "passed" if hidden["status"] == "passed" else "failed",
                    "changed_files": changed_files(workspace),
                    "patch_path": str(patch_path),
                    "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
                    "patch_bytes": len(patch.encode()),
                }
            )
            attempts.append(attempt)
            write_json(artifact_root / "attempts.partial.json", attempts)
    passed = {
        treatment: sum(
            1
            for attempt in attempts
            if attempt["treatment"] == treatment and attempt["task_status"] == "passed"
        )
        for treatment in ("online", "private")
    }
    result = {
        "schema_version": 2,
        "status": "completed",
        "baseline_revision": manifest["baseline_revision"],
        "started_at": started,
        "ended_at": utc_now(),
        "started_from_preflight": preflight["preflight_key"],
        "claude_code_version": manifest["claude_code_version"],
        "toolchain": contract,
        "private_probe": private_probe,
        "attempts": attempts,
        "passed": passed,
        "total_tasks_per_treatment": len(manifest["tasks"]),
        "local_docker_used": False,
        "note": "Single-repetition pilot; no statistical superiority claim.",
    }
    write_json(artifact_root / "result.json", result)
    write_summary(artifact_root / "summary.md", result)
    return result


def write_summary(path: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Claude Code Flash Sandbox Pilot",
        "",
        f"- Status: `{result['status']}`",
        f"- Claude Code: `{result['claude_code_version']}`",
        f"- Online passed: `{result['passed']['online']}/4`",
        f"- Private passed: `{result['passed']['private']}/4`",
        "- Interpretation: single-repetition calibration only",
        "",
        "| Task | Treatment | Tests | Agent | Seconds | Turns | Cost USD | Tools |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for attempt in result["attempts"]:
        lines.append(
            "| {task_id} | {treatment} | {task_status} | {agent_status} | "
            "{seconds} | {turns} | {cost} | {tools} |".format(
                task_id=attempt["task_id"],
                treatment=attempt["treatment"],
                task_status=attempt["task_status"],
                agent_status=attempt["agent_status"],
                seconds=attempt["elapsed_seconds"],
                turns=attempt.get("num_turns")
                if attempt.get("num_turns") is not None
                else "-",
                cost=attempt.get("cost_usd")
                if attempt.get("cost_usd") is not None
                else "-",
                tools=len(attempt.get("tool_calls") or []),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--probe", choices=("online", "private"))
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path(os.environ.get("CLAUDE_PILOT_CACHE", DEFAULT_CACHE)),
    )
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument(
        "--toolchain",
        type=Path,
        default=Path(os.environ.get("CODING_AGENT_TOOLCHAIN", DEFAULT_TOOLCHAIN)),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.cache = args.cache.resolve()
    args.artifact_root = args.artifact_root.resolve()
    args.toolchain = args.toolchain.resolve()
    args.artifact_root.mkdir(parents=True, exist_ok=True)
    try:
        if args.preflight:
            output = run_preflight(args.cache, args.artifact_root, args.toolchain)
        elif args.run:
            output = run_pilot(args.cache, args.artifact_root, args.toolchain)
        else:
            manifest = load_manifest()
            real = find_real_claude(manifest["claude_code_version"])
            output = probe_provider(
                args.probe,
                args.toolchain,
                real,
                manifest["claude_code_version"],
                args.artifact_root,
            )
        print(json.dumps(output, ensure_ascii=False))
        return 0
    except InfrastructureError as exc:
        error = {
            "schema_version": 2,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "ended_at": utc_now(),
        }
        write_json(args.artifact_root / "error.json", error)
        print(json.dumps(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
