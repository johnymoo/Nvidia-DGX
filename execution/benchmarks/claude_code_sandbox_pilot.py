#!/usr/bin/env python3
"""Three-treatment Claude Code benchmark, scoring, and local blind review."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


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
DEFAULT_CODEX_BIN = os.environ.get("CODEX_BIN", "codex")
DEFAULT_CODEX_AUDIT_ROOT = Path(os.environ.get("CODEX_JUDGE_AUDIT_ROOT", Path.home() / ".codex" / "sessions"))
TREATMENTS = ("online_ds", "offline_ds", "qwen_local")
DEEPSEEK_TREATMENTS = ("online_ds", "offline_ds")
LETTERS = ("A", "B", "C")
CRITERIA = ("accuracy", "following", "clarity_style")
JUDGE_MODEL = "gpt-5.6-sol"
JUDGE_EFFORT = "xhigh"
FORBIDDEN_BLIND_TERMS = (
    "online_ds", "offline_ds", "qwen_local", "deepseek", "qwen", "provider",
    "route", "token", "cost", "latency", "elapsed", "model usage",
)


class InfrastructureError(RuntimeError):
    """A broken benchmark contract, rather than a measured candidate result."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory = os.open(path.parent, os.O_DIRECTORY)
        except (AttributeError, OSError):
            return
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_json(path: Path, value: Any) -> None:
    atomic_write(path, json_bytes(value))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def tree_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file() and "__pycache__" not in path.parts)


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
    resolved_root = root.resolve()
    candidate = (resolved_root / relative).resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise InfrastructureError(f"path escapes benchmark root: {relative}")
    return candidate


def load_manifest() -> dict[str, Any]:
    manifest = read_json(MANIFEST_PATH)
    if manifest.get("schema_version") != 3:
        raise InfrastructureError("unsupported task manifest schema")
    if manifest.get("baseline_revision") != "claude-ds-pilot-r2":
        raise InfrastructureError("task manifest baseline revision mismatch")
    treatments = manifest.get("treatments")
    if not isinstance(treatments, dict) or set(treatments) != set(TREATMENTS):
        raise InfrastructureError("manifest must contain exactly three treatment contracts")
    expected = {
        "online_ds": ("claude_ds", "ds", "deepseek-v4-flash"),
        "offline_ds": ("claude_local", "local", "deepseek-v4-flash-0731"),
        "qwen_local": ("claude_local", "local", "qwen3.6-35b-fp8"),
    }
    for treatment, (route, provider, model) in expected.items():
        contract = treatments[treatment]
        if not isinstance(contract, dict) or any("fallback" in str(key).lower() for key in contract):
            raise InfrastructureError(f"invalid fallback contract for {treatment}")
        if (contract.get("route"), contract.get("provider"), contract.get("model")) != (route, provider, model):
            raise InfrastructureError(f"treatment contract mismatch: {treatment}")
    if treatments["offline_ds"].get("base_url") != "http://192.168.88.181:8890":
        raise InfrastructureError("private DeepSeek base URL mismatch")
    if treatments["qwen_local"].get("base_url") != "http://192.168.88.181:8004":
        raise InfrastructureError("Qwen base URL mismatch")
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 7:
        raise InfrastructureError("task manifest must contain seven tasks")
    task_ids = [task.get("task_id") for task in tasks]
    if len(set(task_ids)) != 7 or any(not isinstance(value, str) or not value for value in task_ids):
        raise InfrastructureError("task manifest must contain seven unique task IDs")
    starts: list[str] = []
    for task in tasks:
        task_id = task["task_id"]
        if task.get("task_kind") not in {"code", "qa", "brief"}:
            raise InfrastructureError(f"invalid task kind for {task_id}")
        order = task.get("treatment_order")
        if not isinstance(order, list) or sorted(order) != sorted(DEEPSEEK_TREATMENTS):
            raise InfrastructureError(f"invalid DeepSeek order for {task_id}")
        starts.append(order[0])
        fixture = checked_path(FIXTURE_ROOT, str(task.get("fixture", "")))
        grader = checked_path(GRADER_ROOT, str(task.get("grader", "")))
        solution = checked_path(SOLUTION_ROOT, str(task.get("solution", "")))
        if not fixture.is_dir() or not tree_files(fixture) or any(path.is_symlink() for path in fixture.rglob("*")):
            raise InfrastructureError(f"fixture contract invalid for {task_id}")
        if not grader.is_file() or not solution.is_dir() or not tree_files(solution):
            raise InfrastructureError(f"grader or solution missing for {task_id}")
        if not isinstance(task.get("instruction"), str) or not task["instruction"].strip():
            raise InfrastructureError(f"task instruction missing for {task_id}")
        if not isinstance(task.get("visible_test_command"), list) or not task["visible_test_command"]:
            raise InfrastructureError(f"visible test command missing for {task_id}")
    if starts.count("online_ds") != 4 or starts.count("offline_ds") != 3:
        raise InfrastructureError("DeepSeek task ordering is not balanced 4/3")
    return manifest


def run_command(argv: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, timeout: int | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(argv, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise InfrastructureError(f"command timed out after {timeout}s: {' '.join(argv[:4])}") from exc
    if check and result.returncode != 0:
        raise InfrastructureError(f"command failed ({result.returncode}): {' '.join(argv[:4])}\n{result.stdout[-4000:]}")
    return result


def run_measured_command(argv: list[str], *, cwd: Path, timeout: int, log_path: Path) -> dict[str, Any]:
    started = time.monotonic()
    timed_out = False
    try:
        result = subprocess.run(argv, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False)
        output = result.stdout
        return_code = result.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        output = (exc.stdout or "") + (exc.stderr or "")
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return_code = 124
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(output, encoding="utf-8")
    return {"argv": argv, "exit_code": return_code, "timed_out": timed_out, "elapsed_seconds": round(time.monotonic() - started, 3), "log_path": str(log_path)}


def find_real_claude(expected_version: str) -> Path:
    configured = os.environ.get("CLAUDE_BENCH_REAL_BIN")
    candidate = Path(configured or shutil.which("claude") or "")
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise InfrastructureError("real Claude Code binary not found")
    resolved = candidate.resolve()
    version = run_command([str(resolved), "--version"]).stdout.strip().split()[0]
    if version != expected_version:
        raise InfrastructureError(f"Claude Code version mismatch: {version}, expected {expected_version}")
    return resolved


def toolchain_contract(toolchain: Path) -> dict[str, str]:
    shim = toolchain / "bin" / "claude"
    if not shim.is_file() or not os.access(shim, os.X_OK):
        raise InfrastructureError(f"toolchain Claude shim missing: {shim}")
    return {"shim": str(shim.resolve()), "shim_sha256": sha256_file(shim), "commit": run_command(["git", "rev-parse", "HEAD"], cwd=toolchain).stdout.strip()}


def provider_spec(treatment: str, manifest: dict[str, Any] | None = None) -> dict[str, str]:
    manifest = manifest or load_manifest()
    if treatment in TREATMENTS:
        contract = manifest["treatments"][treatment]
        base_url = contract.get("base_url")
        if treatment == "online_ds":
            base_url = os.environ.get(str(contract["base_url_env"]), os.environ.get("CLAUDE_BASE_URL", "https://coding.onlyservice.io"))
        return {"route": str(contract["route"]), "provider": str(contract["provider"]), "model": str(contract["model"]), "base_url": str(base_url)}
    raise InfrastructureError(f"unknown treatment: {treatment}")


def claude_environment(treatment: str, toolchain: Path, real_claude: Path, manifest: dict[str, Any] | None = None) -> tuple[dict[str, str], dict[str, str]]:
    spec = provider_spec(treatment, manifest)
    env = os.environ.copy()
    env.update({"CLAUDE_SHIM_REPO_DIR": str(toolchain), "CLAUDE_REAL_BIN": str(real_claude), "CLAUDE_DEFAULT_PROVIDER": spec["provider"], "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
    prefix = "CLAUDE_" + spec["provider"].upper()
    env[f"{prefix}_MODEL"] = spec["model"]
    env[f"{prefix}_BASE_URL"] = spec["base_url"]
    if treatment in {"offline_ds", "qwen_local"}:
        env["CLAUDE_LOCAL_TOKEN"] = "no-key-required"
    return env, spec


def claude_argv(shim: Path, model: str, prompt: str, with_tools: bool) -> list[str]:
    return [str(shim), "-p", "--model", model, "--safe-mode", "--disable-slash-commands", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--no-session-persistence", "--no-chrome", "--dangerously-skip-permissions", "--tools", "Bash,Edit,Read,Glob,Grep,Write" if with_tools else "", "--output-format", "stream-json", "--verbose", prompt]


def parse_stream(output: str) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    tool_calls: list[str] = []
    assistant_text: list[str] = []
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        events.append(event)
        message = event.get("message") if event.get("type") == "assistant" else None
        for block in (message or {}).get("content") or []:
            if block.get("type") == "tool_use":
                tool_calls.append(str(block.get("name") or "unknown"))
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                assistant_text.append(block["text"])
    init = next((event for event in events if event.get("type") == "system" and event.get("subtype") == "init"), None)
    result = next((event for event in reversed(events) if event.get("type") == "result"), None)
    return {"events": events, "init": init, "result": result, "tool_calls": tool_calls, "assistant_text": "\n".join(assistant_text)}


def validate_identity(parsed: dict[str, Any], treatment: str, expected_version: str, manifest: dict[str, Any] | None = None) -> None:
    init = parsed.get("init")
    if not init:
        raise InfrastructureError(f"{treatment}: Claude Code init event missing")
    spec = provider_spec(treatment, manifest)
    if init.get("model") != spec["model"]:
        raise InfrastructureError(f"{treatment}: model mismatch {init.get('model')!r}, expected {spec['model']!r}")
    if init.get("claude_code_version") != expected_version:
        raise InfrastructureError(f"{treatment}: Claude Code init version mismatch {init.get('claude_code_version')!r}")
    result = parsed.get("result")
    if result and result.get("api_error_status") is not None:
        raise InfrastructureError(f"{treatment}: provider API error {result.get('api_error_status')}")
    if result:
        models = set((result.get("modelUsage") or {}).keys())
        if models and models != {spec["model"]}:
            raise InfrastructureError(f"{treatment}: modelUsage contains unexpected models: {sorted(models)}")
    allowed = {"Bash", "Edit", "Read", "Glob", "Grep", "Write"}
    if any(call not in allowed for call in parsed["tool_calls"]):
        raise InfrastructureError(f"{treatment}: disallowed tool activity")


def run_claude(*, treatment: str, prompt: str, cwd: Path, timeout_seconds: int, toolchain: Path, real_claude: Path, expected_version: str, output_path: Path, with_tools: bool, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    env, spec = claude_environment(treatment, toolchain, real_claude, manifest)
    contract = toolchain_contract(toolchain)
    argv = claude_argv(Path(contract["shim"]), spec["model"], prompt, with_tools)
    started = time.monotonic()
    timed_out = False
    process = subprocess.Popen(argv, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
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
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output, encoding="utf-8")
    parsed = parse_stream(output)
    validate_identity(parsed, treatment, expected_version, manifest)
    result = parsed.get("result") or {}
    return {"treatment": treatment, "route": spec["route"], "model": spec["model"], "claude_code_version": parsed["init"]["claude_code_version"], "fallback_configured": "--fallback-model" in argv, "agent_status": "timeout" if timed_out else "completed" if process.returncode == 0 else "agent_exit_error", "exit_code": process.returncode, "timed_out": timed_out, "elapsed_seconds": round(time.monotonic() - started, 3), "duration_ms": result.get("duration_ms"), "duration_api_ms": result.get("duration_api_ms"), "ttft_ms": result.get("ttft_ms"), "num_turns": result.get("num_turns"), "terminal_reason": "timeout" if timed_out else result.get("terminal_reason"), "usage": result.get("usage") or {}, "model_usage": result.get("modelUsage") or {}, "cost_usd": result.get("total_cost_usd"), "permission_denials": result.get("permission_denials") or [], "tool_calls": parsed["tool_calls"], "stream_path": str(output_path), "assistant_text": parsed["assistant_text"]}


def probe_provider(treatment: str, toolchain: Path, real_claude: Path, expected_version: str, artifact: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    artifact.mkdir(parents=True, exist_ok=True)
    return run_claude(treatment=treatment, prompt="Reply with exactly: benchmark-ready", cwd=artifact, timeout_seconds=120, toolchain=toolchain, real_claude=real_claude, expected_version=expected_version, output_path=artifact / f"probe-{treatment}.jsonl", with_tools=False, manifest=manifest)


def codex_binary() -> Path:
    candidate = Path(os.environ.get("CODEX_BIN", DEFAULT_CODEX_BIN))
    if not candidate.is_absolute():
        resolved = shutil.which(str(candidate))
        candidate = Path(resolved or "")
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise InfrastructureError("Codex CLI binary not found")
    return candidate.resolve()


def codex_contract() -> dict[str, str]:
    binary = codex_binary()
    version = run_command([str(binary), "--version"]).stdout.strip()
    if not version.startswith("codex-cli "):
        raise InfrastructureError(f"unexpected Codex CLI version output: {version!r}")
    return {"binary": str(binary), "version": version, "sha256": sha256_file(binary), "model": JUDGE_MODEL, "reasoning_effort": JUDGE_EFFORT}


def codex_schema(mode: str) -> dict[str, Any]:
    if mode == "probe":
        return {"type": "object", "additionalProperties": False, "properties": {"ready": {"type": "boolean"}}, "required": ["ready"]}
    return {"type": "object", "additionalProperties": False, "properties": {"candidates": {"type": "object", "additionalProperties": False, "properties": {letter: {"type": "object", "additionalProperties": False, "properties": {criterion: {"type": "integer", "enum": [1, 2, 3]} for criterion in CRITERIA}, "required": list(CRITERIA)} for letter in LETTERS}, "required": list(LETTERS)}, "preference": {"type": "string", "enum": [*LETTERS, "tie"]}, "rationale": {"type": "string"}}, "required": ["candidates", "preference"]}


def codex_thread_id(events_path: Path) -> str:
    for line in events_path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
            return event["thread_id"]
    raise InfrastructureError("Codex JSONL stream did not report a thread ID")


def codex_turn_completed(events_path: Path) -> None:
    for line in events_path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.completed":
            return
    raise InfrastructureError("Codex JSONL stream did not report a completed turn")


def codex_runtime_context(thread_id: str) -> dict[str, Any]:
    audit_root = Path(os.environ.get("CODEX_JUDGE_AUDIT_ROOT", DEFAULT_CODEX_AUDIT_ROOT))
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        for path in audit_root.rglob(f"*{thread_id}.jsonl") if audit_root.is_dir() else []:
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "turn_context" and isinstance(event.get("payload"), dict):
                    return event["payload"]
        time.sleep(0.2)
    raise InfrastructureError("Codex runtime turn_context is unavailable for the returned thread ID")


def validate_codex_runtime(context: dict[str, Any]) -> dict[str, Any]:
    settings = (((context.get("collaboration_mode") or {}).get("settings") or {}))
    model = context.get("model")
    effort = context.get("effort")
    if model != JUDGE_MODEL or effort != JUDGE_EFFORT:
        raise InfrastructureError(f"Codex runtime identity mismatch: model={model!r}, effort={effort!r}")
    if settings.get("model") != JUDGE_MODEL or settings.get("reasoning_effort") != JUDGE_EFFORT:
        raise InfrastructureError("Codex runtime context does not confirm the requested model and reasoning effort")
    if context.get("approval_policy") != "never" or context.get("sandbox_policy", {}).get("type") != "read-only":
        raise InfrastructureError("Codex runtime sandbox or approval contract mismatch")
    return {"model": model, "reasoning_effort": effort, "approval_policy": "never", "sandbox": "read-only"}


def run_codex(prompt: str, artifact: Path, schema: dict[str, Any], timeout_seconds: int) -> tuple[str, dict[str, Any]]:
    artifact.mkdir(parents=True, exist_ok=True)
    schema_path = artifact / "codex-output-schema.json"
    final_path = artifact / "codex-final.json"
    events_path = artifact / "codex-events.jsonl"
    stderr_path = artifact / "codex.stderr.log"
    write_json(schema_path, schema)
    contract = codex_contract()
    argv = [contract["binary"], "exec", "--json", "--ignore-rules", "--skip-git-repo-check", "--sandbox", "read-only", "--model", JUDGE_MODEL, "--config", 'model_reasoning_effort="xhigh"', "--config", 'approval_policy="never"', "--config", "mcp_servers={}", "--output-schema", str(schema_path), "--output-last-message", str(final_path), prompt]
    if "--fallback-model" in argv:
        raise InfrastructureError("Codex judge fallback was configured")
    try:
        result = subprocess.run(argv, cwd=artifact, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_seconds, check=False)
    except subprocess.TimeoutExpired as exc:
        raise InfrastructureError(f"Codex judge timed out after {timeout_seconds}s") from exc
    events_path.write_text(result.stdout, encoding="utf-8")
    stderr_path.write_text(result.stderr, encoding="utf-8")
    if result.returncode != 0:
        raise InfrastructureError(f"Codex judge exited {result.returncode}")
    thread_id = codex_thread_id(events_path)
    codex_turn_completed(events_path)
    runtime = validate_codex_runtime(codex_runtime_context(thread_id))
    if not final_path.is_file():
        raise InfrastructureError("Codex judge did not write its final structured output")
    text = final_path.read_text(encoding="utf-8")
    evidence = {"thread_id": thread_id, "runtime": runtime, "fallback_configured": False, "codex": contract, "events_sha256": sha256_file(events_path), "final_sha256": sha256_file(final_path)}
    write_json(artifact / "codex-runtime-receipt.json", evidence)
    return text, evidence


def run_codex_probe(artifact: Path) -> dict[str, Any]:
    text, evidence = run_codex("Return the exact JSON object required by the schema.", artifact, codex_schema("probe"), 120)
    response = parse_json_object(text)
    if response != {"ready": True}:
        raise InfrastructureError("Codex judge preflight response did not satisfy the probe contract")
    return evidence


def prepare_workspace(fixture: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(fixture, destination)
    run_command(["git", "init", "-q"], cwd=destination)
    run_command(["git", "config", "user.name", "Claude Code Benchmark"], cwd=destination)
    run_command(["git", "config", "user.email", "benchmark@localhost"], cwd=destination)
    run_command(["git", "add", "."], cwd=destination)
    run_command(["git", "commit", "-qm", "benchmark fixture"], cwd=destination)
    return run_command(["git", "rev-parse", "HEAD"], cwd=destination).stdout.strip()


def overlay_solution(solution: Path, workspace: Path) -> None:
    for source in tree_files(solution):
        destination = workspace / source.relative_to(solution)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def capture_patch(workspace: Path) -> str:
    untracked = run_command(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=workspace).stdout
    files = [entry for entry in untracked.split("\0") if entry and entry != ".claude"]
    if files:
        run_command(["git", "add", "-N", "--", *files], cwd=workspace)
    return run_command(["git", "diff", "--binary", "--", ".", ":(exclude).claude"], cwd=workspace).stdout


def changed_files(workspace: Path) -> list[str]:
    output = run_command(["git", "status", "--porcelain=v1"], cwd=workspace).stdout
    return sorted(line[3:] for line in output.splitlines() if len(line) > 3)


def command_for_task(task: dict[str, Any]) -> list[str]:
    return [sys.executable if token == "{python}" else str(token) for token in task["visible_test_command"]]


def run_visible_tests(task: dict[str, Any], workspace: Path, artifact: Path, timeout: int) -> dict[str, Any]:
    outcome = run_measured_command(command_for_task(task), cwd=workspace, timeout=timeout, log_path=artifact / "visible-tests.log")
    outcome["status"] = "passed" if outcome["exit_code"] == 0 and not outcome["timed_out"] else "failed"
    return outcome


def run_hidden_grader(task: dict[str, Any], workspace: Path, artifact: Path, timeout: int) -> dict[str, Any]:
    grader = checked_path(GRADER_ROOT, task["grader"])
    outcome = run_measured_command([sys.executable, str(grader), str(workspace)], cwd=workspace, timeout=timeout, log_path=artifact / "hidden-grader.log")
    parsed: dict[str, Any] | None = None
    if not outcome["timed_out"]:
        for line in reversed(Path(outcome["log_path"]).read_text(encoding="utf-8").splitlines()):
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and candidate.get("schema_version") == 1:
                parsed = candidate
                break
    if parsed is None:
        raise InfrastructureError(f"grader protocol failure for {task['task_id']}")
    if not isinstance(parsed.get("passed"), int) or not isinstance(parsed.get("total"), int) or parsed["total"] <= 0 or not 0 <= parsed["passed"] <= parsed["total"]:
        raise InfrastructureError(f"grader score schema invalid for {task['task_id']}")
    if parsed.get("status") not in {"passed", "failed"}:
        raise InfrastructureError(f"grader status schema invalid for {task['task_id']}")
    if outcome["exit_code"] == 0 and parsed["status"] != "passed":
        raise InfrastructureError(f"grader exit/status disagreement for {task['task_id']}")
    if outcome["exit_code"] != 0 and parsed["status"] != "failed":
        raise InfrastructureError(f"grader exit/status disagreement for {task['task_id']}")
    outcome.update(parsed)
    return outcome


def task_prompt(task: dict[str, Any]) -> str:
    return f"Task: {task['title']}\n\n{task['instruction'].strip()}\n\nWork directly in the current repository. You may read and modify only this repository. Do not inspect parent or sibling directories, benchmark harness files, hidden tests, solution artifacts, or external resources. Do not use network access or subagents. Run the visible tests and leave the best complete implementation in the worktree. Do not ask questions; finish when no further useful local verification remains."


def prompt_contract_hash(task: dict[str, Any], manifest: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    for item in (task_prompt(task), json.dumps(claude_argv(Path("claude"), "MODEL", "PROMPT", True)), str(manifest["task_timeout_seconds"])):
        digest.update(item.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def deterministic_tier(hidden: dict[str, Any], agent_status: str) -> int:
    if agent_status == "timeout" or hidden["total"] <= 0:
        return 1
    if hidden["passed"] == hidden["total"]:
        return 3
    return 2 if hidden["passed"] * 2 >= hidden["total"] else 1


def review_artifact(task: dict[str, Any], workspace: Path, patch: str) -> str:
    kind = task["task_kind"]
    if kind == "code":
        normalized = patch.replace("a/", "").replace("b/", "")
        return "Changed implementation:\n" + (normalized.strip() or "No changes were produced.")
    if kind == "qa":
        answer = workspace / "answers.json"
        if not answer.is_file():
            return "No declared answers.json was produced."
        try:
            parsed = json.loads(answer.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return "answers.json is not valid JSON."
        return json.dumps(parsed, ensure_ascii=False, sort_keys=True, indent=2)
    answer = workspace / "answer.md"
    return answer.read_text(encoding="utf-8").strip() if answer.is_file() else "No declared answer.md was produced."


def controlled_files(toolchain: Path) -> list[Path]:
    files = [SCRIPT_PATH, MANIFEST_PATH, PROJECT_ROOT / "execution" / "run-claude-code-flash-pilot.sh", PROJECT_ROOT / "execution" / "run-vllm-service.sh", PROJECT_ROOT / "execution" / "run-vllm-acceptance.sh", toolchain / "bin" / "claude"]
    for root in (FIXTURE_ROOT, GRADER_ROOT, SOLUTION_ROOT):
        files.extend(tree_files(root))
    return sorted(set(path.resolve() for path in files))


def expected_preflight_key(manifest: dict[str, Any], toolchain: Path, real_claude: Path) -> str:
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


def calibrate_task(task: dict[str, Any], root: Path, visible_timeout: int, grade_timeout: int) -> dict[str, Any]:
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
    return {"task_id": task["task_id"], "fixture_sha256": tree_sha256(fixture), "initial_status": initial["status"], "gold_visible_status": visible["status"], "gold_hidden_status": hidden["status"], "gold_hidden_tests": hidden["total"]}


def run_preflight(cache: Path, artifact_root: Path, toolchain: Path) -> dict[str, Any]:
    manifest = load_manifest()
    started = utc_now()
    real_claude = find_real_claude(manifest["claude_code_version"])
    contract = toolchain_contract(toolchain)
    calibration_root = artifact_root / "calibration"
    calibrations = [calibrate_task(task, calibration_root, int(manifest["visible_test_timeout_seconds"]), int(manifest["grade_timeout_seconds"])) for task in manifest["tasks"]]
    shutil.rmtree(calibration_root, ignore_errors=True)
    online_probe = probe_provider("online_ds", toolchain, real_claude, manifest["claude_code_version"], artifact_root / "protocol-probe", manifest)
    judge_runtime_probe = run_codex_probe(artifact_root / "judge-probe")
    receipt = {"schema_version": 3, "status": "passed", "preflight_key": expected_preflight_key(manifest, toolchain, real_claude), "started_at": started, "ended_at": utc_now(), "baseline_revision": manifest["baseline_revision"], "manifest_sha256": sha256_file(MANIFEST_PATH), "runner_sha256": sha256_file(SCRIPT_PATH), "toolchain": contract, "claude_real_bin": str(real_claude), "claude_real_sha256": sha256_file(real_claude), "claude_code_version": manifest["claude_code_version"], "online_probe": online_probe, "judge_runtime_probe": judge_runtime_probe, "calibrations": calibrations, "task_ids": [task["task_id"] for task in manifest["tasks"]], "treatment_contracts": manifest["treatments"], "local_docker_used": False}
    cache.mkdir(parents=True, exist_ok=True)
    write_json(cache / "preflight-receipt.json", receipt)
    write_json(artifact_root / "preflight-receipt.json", receipt)
    return receipt


def require_fresh_preflight(cache: Path, manifest: dict[str, Any], toolchain: Path, real_claude: Path) -> dict[str, Any]:
    receipt_path = cache / "preflight-receipt.json"
    if not receipt_path.is_file():
        raise InfrastructureError("preflight receipt is missing")
    receipt = read_json(receipt_path)
    if receipt.get("status") != "passed" or receipt.get("preflight_key") != expected_preflight_key(manifest, toolchain, real_claude):
        raise InfrastructureError("preflight receipt is stale or not passed")
    return receipt


def state_path(root: Path) -> Path:
    return root / "benchmark-state.json"


def initial_state(manifest: dict[str, Any], preflight: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": 1, "status": "running", "baseline_revision": manifest["baseline_revision"], "preflight_key": preflight["preflight_key"], "created_at": utc_now(), "attempts": [], "phase_receipts": {}}


def load_state(root: Path, manifest: dict[str, Any], preflight: dict[str, Any]) -> dict[str, Any]:
    path = state_path(root)
    if not path.exists():
        state = initial_state(manifest, preflight)
        write_json(path, state)
        return state
    state = read_json(path)
    if state.get("preflight_key") != preflight["preflight_key"] or state.get("baseline_revision") != manifest["baseline_revision"]:
        raise InfrastructureError("benchmark state belongs to a different preflight contract")
    return state


def attempt_key(task_id: str, treatment: str) -> str:
    return f"{task_id}:{treatment}"


def run_attempt(task: dict[str, Any], treatment: str, root: Path, toolchain: Path, real_claude: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    nonce = secrets.token_hex(6)
    scratch = root / "scratch" / treatment / f"{task['task_id']}-{nonce}"
    attempt_tmp = root / "attempts" / treatment / f".{task['task_id']}-{nonce}.tmp"
    attempt_final = root / "attempts" / treatment / task["task_id"]
    if attempt_final.exists():
        raise InfrastructureError(f"attempt artifact already exists without state: {task['task_id']} {treatment}")
    base_commit = prepare_workspace(checked_path(FIXTURE_ROOT, task["fixture"]), scratch)
    attempt = run_claude(treatment=treatment, prompt=task_prompt(task), cwd=scratch, timeout_seconds=int(manifest["task_timeout_seconds"]), toolchain=toolchain, real_claude=real_claude, expected_version=manifest["claude_code_version"], output_path=attempt_tmp / "stream.jsonl", with_tools=True, manifest=manifest)
    visible = run_visible_tests(task, scratch, attempt_tmp, int(manifest["visible_test_timeout_seconds"]))
    hidden = run_hidden_grader(task, scratch, attempt_tmp, int(manifest["grade_timeout_seconds"]))
    patch = capture_patch(scratch)
    (attempt_tmp / "changes.patch").parent.mkdir(parents=True, exist_ok=True)
    (attempt_tmp / "changes.patch").write_text(patch, encoding="utf-8")
    artifact = review_artifact(task, scratch, patch)
    (attempt_tmp / "review-artifact.txt").write_text(artifact, encoding="utf-8")
    attempt.update({"task_id": task["task_id"], "title": task["title"], "category": task["category"], "task_kind": task["task_kind"], "base_commit": base_commit, "workspace": str(scratch), "visible_tests": visible, "hidden_grader": hidden, "task_status": "passed" if hidden["status"] == "passed" else "failed", "changed_files": changed_files(scratch), "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(), "patch_bytes": len(patch.encode()), "review_artifact": artifact, "prompt_contract_sha256": prompt_contract_hash(task, manifest)})
    write_json(attempt_tmp / "attempt.json", attempt)
    attempt_final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(attempt_tmp, attempt_final)
    attempt["artifact_dir"] = str(attempt_final)
    return attempt


def run_phase(phase: str, cache: Path, artifact_root: Path, toolchain: Path) -> dict[str, Any]:
    manifest = load_manifest()
    real_claude = find_real_claude(manifest["claude_code_version"])
    preflight = require_fresh_preflight(cache, manifest, toolchain, real_claude)
    if toolchain_contract(toolchain) != preflight["toolchain"]:
        raise InfrastructureError("coding-agent-toolchain changed after preflight")
    state = load_state(artifact_root, manifest, preflight)
    known = {attempt_key(item["task_id"], item["treatment"]) for item in state["attempts"]}
    selected: list[tuple[dict[str, Any], str]] = []
    if phase == "deepseek":
        selected = [(task, treatment) for task in manifest["tasks"] for treatment in task["treatment_order"]]
    elif phase == "qwen":
        if "qwen_probe" not in state["phase_receipts"]:
            qwen_probe = probe_provider("qwen_local", toolchain, real_claude, manifest["claude_code_version"], artifact_root / "protocol-probe", manifest)
            probe_receipt = {"schema_version": 1, "status": "passed", "phase": "qwen_probe", "completed_at": utc_now(), "model": qwen_probe["model"], "claude_code_version": qwen_probe["claude_code_version"], "fallback_configured": qwen_probe["fallback_configured"]}
            if probe_receipt["fallback_configured"]:
                raise InfrastructureError("Qwen probe configured a fallback")
            write_json(artifact_root / "phase-qwen-probe-receipt.json", probe_receipt)
            state["phase_receipts"]["qwen_probe"] = probe_receipt
            write_json(state_path(artifact_root), state)
        selected = [(task, "qwen_local") for task in manifest["tasks"]]
    else:
        raise InfrastructureError(f"unknown phase: {phase}")
    for task, treatment in selected:
        key = attempt_key(task["task_id"], treatment)
        if key in known:
            continue
        attempt = run_attempt(task, treatment, artifact_root, toolchain, real_claude, manifest)
        state["attempts"].append(attempt)
        write_json(state_path(artifact_root), state)
        known.add(key)
    expected = 14 if phase == "deepseek" else 7
    count = sum(1 for item in state["attempts"] if item["treatment"] in DEEPSEEK_TREATMENTS) if phase == "deepseek" else sum(1 for item in state["attempts"] if item["treatment"] == "qwen_local")
    if count != expected:
        raise InfrastructureError(f"{phase} phase attempt count mismatch: {count}/{expected}")
    receipt = {"schema_version": 1, "status": "completed", "phase": phase, "completed_at": utc_now(), "attempt_count": count, "measured_failures": sum(1 for item in state["attempts"] if item["treatment"] in (DEEPSEEK_TREATMENTS if phase == "deepseek" else ("qwen_local",)) and item["task_status"] != "passed")}
    write_json(artifact_root / f"phase-{phase}-receipt.json", receipt)
    state["phase_receipts"][phase] = receipt
    write_json(state_path(artifact_root), state)
    return receipt


def shuffled_mapping() -> dict[str, str]:
    values = list(TREATMENTS)
    secrets.SystemRandom().shuffle(values)
    return dict(zip(LETTERS, values))


def judge_prompt(task: dict[str, Any], choices: dict[str, str], retry: bool = False) -> str:
    correction = " Return JSON only and correct the schema exactly." if retry else ""
    rendered = "\n\n".join(f"Candidate {label}:\n{choices[label]}" for label in LETTERS)
    return f"Independently score three anonymous candidate responses. Do not infer identity, model, provider, route, timing, tooling, token, cost, hidden grading, or attempt order. Task title: {task['title']}.\n\nTask instruction:\n{task['instruction']}\n\n{rendered}\n\nReturn a JSON object with exactly candidates, preference, and optional rationale. candidates must map A, B, and C to accuracy, following, and clarity_style integer scores from 1 to 3. preference must be A, B, C, or tie.{correction}"


def parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.IGNORECASE)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise InfrastructureError("judge response is not JSON") from exc
    if not isinstance(parsed, dict):
        raise InfrastructureError("judge response is not an object")
    return parsed


def validate_judge_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if set(payload) - {"candidates", "preference", "rationale"} or not {"candidates", "preference"}.issubset(payload):
        raise InfrastructureError("judge response has invalid keys")
    candidates = payload["candidates"]
    if not isinstance(candidates, dict) or set(candidates) != set(LETTERS):
        raise InfrastructureError("judge candidates must be exactly A/B/C")
    for label, scores in candidates.items():
        if not isinstance(scores, dict) or set(scores) != set(CRITERIA):
            raise InfrastructureError(f"judge score shape invalid for {label}")
        if any(type(value) is not int or value not in {1, 2, 3} for value in scores.values()):
            raise InfrastructureError(f"judge score range invalid for {label}")
    if payload["preference"] not in {*LETTERS, "tie"}:
        raise InfrastructureError("judge preference invalid")
    forbidden = " ".join(str(value) for value in payload.values()).lower()
    if any(term in forbidden for term in FORBIDDEN_BLIND_TERMS):
        raise InfrastructureError("judge response contains identity speculation")
    return payload


def fake_judge_payload() -> dict[str, Any]:
    return {"candidates": {letter: {criterion: 3 for criterion in CRITERIA} for letter in LETTERS}, "preference": "tie", "rationale": "All candidates are evaluated only on the supplied content."}


def run_judge(task: dict[str, Any], choices: dict[str, str], artifact: Path, manifest: dict[str, Any], fake: bool = False) -> dict[str, Any]:
    artifact.mkdir(parents=True, exist_ok=True)
    if fake:
        payload = fake_judge_payload()
        write_json(artifact / "judge.json", payload)
        return {"payload": payload, "runtime": {"model": JUDGE_MODEL, "reasoning_effort": JUDGE_EFFORT, "approval_policy": "never", "sandbox": "read-only", "fallback_configured": False, "source": "fake"}}
    for attempt_number in range(2):
        attempt_root = artifact / f"attempt-{attempt_number + 1}"
        text, runtime = run_codex(judge_prompt(task, choices, retry=attempt_number == 1), attempt_root, codex_schema("judge"), int(manifest["task_timeout_seconds"]))
        try:
            payload = validate_judge_payload(parse_json_object(text))
        except InfrastructureError:
            if attempt_number == 0:
                continue
            raise
        write_json(artifact / "judge.json", payload)
        runtime["fallback_configured"] = False
        write_json(artifact / "judge-runtime.json", runtime)
        return {"payload": payload, "runtime": runtime}
    raise InfrastructureError("judge retry exhausted")


def score_mean(scores: dict[str, int]) -> float:
    return sum(scores[criterion] for criterion in CRITERIA) / len(CRITERIA)


def ratings_path(review_root: Path) -> Path:
    return review_root / "private" / "ratings.json"


def load_ratings(review_root: Path) -> dict[str, Any]:
    path = ratings_path(review_root)
    return read_json(path) if path.exists() else {"schema_version": 1, "ratings": {}}


def validate_rating(payload: dict[str, Any], task_ids: set[str]) -> tuple[str, dict[str, dict[str, int]], str]:
    if set(payload) != {"task_id", "scores", "preference"} or payload["task_id"] not in task_ids:
        raise ValueError("invalid rating payload")
    scores = payload["scores"]
    if not isinstance(scores, dict) or set(scores) != set(LETTERS):
        raise ValueError("invalid candidate scores")
    for label, candidate in scores.items():
        if not isinstance(candidate, dict) or set(candidate) != set(CRITERIA):
            raise ValueError(f"invalid score criteria for {label}")
        if any(type(value) is not int or value not in {1, 2, 3} for value in candidate.values()):
            raise ValueError(f"invalid score level for {label}")
    if payload["preference"] not in {*LETTERS, "tie"}:
        raise ValueError("invalid preference")
    return payload["task_id"], scores, payload["preference"]


def submit_rating(review_root: Path, public: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    task_id, scores, preference = validate_rating(payload, {task["task_id"] for task in public["tasks"]})
    ratings = load_ratings(review_root)
    if task_id in ratings["ratings"]:
        raise FileExistsError("rating already submitted")
    ratings["ratings"][task_id] = {"scores": scores, "preference": preference, "submitted_at": utc_now()}
    write_json(ratings_path(review_root), ratings)
    complete = len(ratings["ratings"]) == len(public["tasks"])
    return {"status": "accepted", "completed": complete, "completed_count": len(ratings["ratings"]), "total": len(public["tasks"])}


def aggregate_reveal(review_root: Path) -> dict[str, Any]:
    public = read_json(review_root / "public" / "review.json")
    sealed = read_json(review_root / "sealed" / "mappings.json")
    ratings = load_ratings(review_root)["ratings"]
    if len(ratings) != len(public["tasks"]):
        raise PermissionError("review is not complete")
    totals: dict[str, list[dict[str, float]]] = {treatment: [] for treatment in TREATMENTS}
    mappings: list[dict[str, Any]] = []
    for task in public["tasks"]:
        task_id = task["task_id"]
        human_mapping = sealed["tasks"][task_id]["human"]
        judge_mapping = sealed["tasks"][task_id]["judge"]
        judge = sealed["judges"][task_id]
        rating = ratings[task_id]
        by_treatment: dict[str, dict[str, float]] = {}
        for treatment in TREATMENTS:
            human_label = next(label for label, value in human_mapping.items() if value == treatment)
            judge_label = next(label for label, value in judge_mapping.items() if value == treatment)
            deterministic = float(sealed["deterministic"][task_id][treatment])
            judge_layer = score_mean(judge["candidates"][judge_label])
            human_layer = score_mean(rating["scores"][human_label])
            quality = (deterministic + judge_layer + human_layer) / 3
            by_treatment[treatment] = {"deterministic_tier": deterministic, "judge_layer": judge_layer, "human_layer": human_layer, "quality": quality}
            totals[treatment].append(by_treatment[treatment])
        mappings.append({"task_id": task_id, "human_mapping": human_mapping, "judge_mapping": judge_mapping, "scores": by_treatment, "human_preference": rating["preference"], "judge_preference": judge["preference"]})
    aggregates = {treatment: {"deterministic_mean": sum(row["deterministic_tier"] for row in rows) / len(rows), "judge_mean": sum(row["judge_layer"] for row in rows) / len(rows), "human_mean": sum(row["human_layer"] for row in rows) / len(rows), "quality_mean": sum(row["quality"] for row in rows) / len(rows)} for treatment, rows in totals.items()}
    payload = {"schema_version": 1, "status": "revealed", "revealed_at": utc_now(), "tasks": mappings, "aggregates": aggregates, "note": "Single-repetition benchmark; no statistical superiority claim."}
    write_json(review_root / "private" / "reveal.json", payload)
    return payload


REVIEW_HTML = r'''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Blind Benchmark Review</title>
<style>
:root{--bg:#f5f7f6;--panel:#fff;--bar:#edf1ee;--line:#ccd5d0;--text:#18231e;--muted:#52625a;--accent:#087a55}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 Arial,sans-serif}#app{max-width:1200px;margin:24px auto;padding:0 14px}.surface,.reveal{overflow:hidden;background:var(--panel);border:1px solid var(--line);border-radius:8px}.toolbar{display:grid;grid-template-columns:minmax(0,1fr) minmax(220px,320px);align-items:center;gap:20px;padding:14px 16px;background:var(--bar);border-bottom:1px solid var(--line)}h1,h2,h3,p{margin:0}h1{font-size:16px}h2{font-size:13px}small,.muted{color:var(--muted)}.progress-copy{display:flex;justify-content:space-between;gap:12px;margin-bottom:6px;font-size:12px}.track{height:5px;overflow:hidden;border-radius:3px;background:var(--line)}.track span{display:block;height:100%;background:var(--accent)}.context{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:20px;padding:16px;border-bottom:1px solid var(--line)}.context strong{display:block;margin-bottom:4px;font-size:11px;text-transform:uppercase}.answers{display:grid;grid-template-columns:repeat(3,minmax(0,1fr))}.answer{display:flex;flex-direction:column;padding:16px}.answer+.answer{border-left:1px solid var(--line)}.heading{display:flex;justify-content:space-between;gap:10px;margin-bottom:10px}.copy{flex:1;min-height:184px;margin:0 0 14px;white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace}.sheet{border-top:1px solid var(--line)}fieldset.row{display:grid;grid-template-columns:minmax(92px,1fr) auto;align-items:center;gap:8px;margin:0;padding:9px 0;border:0;border-bottom:1px solid var(--line)}legend{padding:0;color:var(--muted);font-size:11px}.scale,.prefs{display:flex;gap:10px;align-items:center}.scale label,.prefs label{display:inline-flex;gap:3px;align-items:center;font-size:12px;cursor:pointer}input{accent-color:var(--accent)}footer{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:16px;align-items:center;padding:14px 16px;background:var(--bar);border-top:1px solid var(--line)}button{border:0;border-radius:6px;padding:9px 13px;background:var(--accent);color:#fff;font:600 12px Arial;cursor:pointer}button:disabled{cursor:not-allowed;background:#8ca498}.reveal{display:grid;grid-template-columns:minmax(210px,.75fr) minmax(0,1.25fr);gap:20px;align-items:center;margin-top:14px;padding:14px 16px}.reveal-items{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));border-left:1px solid var(--line)}.reveal-item{padding:3px 16px}.reveal-item+.reveal-item{border-left:1px solid var(--line)}@media(max-width:860px){.answers,.context{grid-template-columns:1fr}.answer+.answer{border-top:1px solid var(--line);border-left:0}.copy{min-height:0}}@media(max-width:620px){.toolbar,footer,.reveal{grid-template-columns:1fr}.reveal-items{border-top:1px solid var(--line);border-left:0;padding-top:10px}button{width:100%}}@media(max-width:380px){fieldset.row{grid-template-columns:1fr}.scale{justify-content:space-between}.reveal-items{grid-template-columns:1fr}.reveal-item+.reveal-item{margin-top:8px;padding-top:8px;border-top:1px solid var(--line);border-left:0}}
</style><div id="app"></div><script>
let review,current;const criteria=[['accuracy','Accuracy'],['following','Instruction following'],['clarity_style','Clarity / style']];
const el=(tag,attrs={},text='')=>{const n=document.createElement(tag);Object.assign(n,attrs);n.textContent=text;return n};
function nextTask(){return review.tasks.find(t=>!review.completed_task_ids.includes(t.task_id))||review.tasks[review.tasks.length-1]}
function scoreRow(letter,key,label,chosen){const f=el('fieldset',{className:'row'}),l=el('legend',{},label),s=el('div',{className:'scale'});f.append(l,s);[1,2,3].forEach(v=>{const lab=el('label'),i=el('input',{type:'radio',name:`${letter}-${key}`,value:v});i.checked=chosen===v;i.onchange=updateButton;lab.append(i,document.createTextNode(String(v)));s.append(lab)});return f}
function updateButton(){const complete=letters=>letters.every(letter=>criteria.every(([key])=>document.querySelector(`input[name="${letter}-${key}"]:checked`)));const pref=document.querySelector('input[name="preference"]:checked');document.querySelector('button').disabled=!(complete(['A','B','C'])&&pref)}
function render(){current=nextTask();const done=review.completed_task_ids.length,app=document.querySelector('#app');app.replaceChildren();const surface=el('main',{className:'surface'}),bar=el('header',{className:'toolbar'}),title=el('div');title.append(el('h1',{},`Blind benchmark review · task ${String(review.tasks.indexOf(current)+1).padStart(2,'0')} / 07`),el('small',{},'Anonymous candidate order is sealed'));const prog=el('div'),copy=el('div',{className:'progress-copy'});copy.append(el('strong',{},`${done} / 7 submitted`),el('span',{className:'muted'},`Current task ${String(review.tasks.indexOf(current)+1).padStart(2,'0')}`));const track=el('div',{className:'track'}),fill=el('span');fill.style.width=`${done/7*100}%`;track.append(fill);prog.append(copy,track);bar.append(title,prog);surface.append(bar);const context=el('section',{className:'context'}),task=el('div'),instruction=el('div');task.append(el('strong',{},'Task'),el('p',{},current.title));instruction.append(el('strong',{},'Task instruction'),el('p',{className:'muted'},current.instruction));context.append(task,instruction);surface.append(context);const answers=el('div',{className:'answers'});for(const letter of ['A','B','C']){const item=el('section',{className:'answer'}),head=el('div',{className:'heading'});head.append(el('h2',{},`Answer ${letter}`),el('small',{},'Anonymous response'));item.append(head,el('pre',{className:'copy'},current.candidates[letter]));const sheet=el('div',{className:'sheet'});criteria.forEach(([key,label])=>sheet.append(scoreRow(letter,key,label)));item.append(sheet);answers.append(item)}surface.append(answers);const foot=el('footer'),pref=el('fieldset',{className:'prefs'});pref.append(el('legend',{},'Overall preference'));['A','B','C','tie'].forEach(value=>{const lab=el('label'),i=el('input',{type:'radio',name:'preference',value});i.onchange=updateButton;lab.append(i,document.createTextNode(value));pref.append(lab)});const submit=el('button',{type:'button',disabled:true},'Submit and next');submit.onclick=submitRating;foot.append(pref,submit);surface.append(foot);app.append(surface);const reveal=el('section',{className:'reveal'}),left=el('div');left.append(el('h3',{},'Reveal after 7 / 7'),el('p',{className:'muted'},'Identity mappings and aggregate scores remain sealed until every task is submitted.'));const items=el('div',{className:'reveal-items'});for(const [a,b] of [['A / B / C identity mapping','Await all 7 submissions'],['Score and preference summary','Await all 7 submissions']]){const i=el('div',{className:'reveal-item'});i.append(el('strong',{},a),el('small',{},b));items.append(i)}reveal.append(left,items);app.append(reveal)}
async function submitRating(){const scores={};for(const letter of ['A','B','C']){scores[letter]={};for(const [key] of criteria)scores[letter][key]=Number(document.querySelector(`input[name="${letter}-${key}"]:checked`).value)}const preference=document.querySelector('input[name="preference"]:checked').value;const response=await fetch('/api/submit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({task_id:current.task_id,scores,preference})});if(!response.ok){alert('Unable to save this rating. Refresh and retry.');return}review=await (await fetch('/api/review')).json();if(review.completed_task_ids.length===7){const reveal=await fetch('/api/reveal');if(reveal.ok){document.querySelector('#app').textContent=JSON.stringify(await reveal.json(),null,2);return}}render()}
fetch('/api/review').then(r=>r.json()).then(value=>{review=value;render()}).catch(()=>document.querySelector('#app').textContent='Review data is unavailable.');
</script>'''


def build_package(cache: Path, artifact_root: Path, toolchain: Path, fake_judge: bool = False) -> dict[str, Any]:
    manifest = load_manifest()
    state = read_json(state_path(artifact_root))
    attempts = state.get("attempts", [])
    if len(attempts) != 21 or {attempt_key(item["task_id"], item["treatment"]) for item in attempts} != {attempt_key(task["task_id"], treatment) for task in manifest["tasks"] for treatment in TREATMENTS}:
        raise InfrastructureError("cannot package an incomplete 21-attempt benchmark")
    review_root = artifact_root / "review"
    sealed_root = review_root / "sealed"
    public_root = review_root / "public"
    if (public_root / "review.json").exists() or (sealed_root / "mappings.json").exists():
        raise InfrastructureError("review package already exists and is immutable")
    by_key = {attempt_key(item["task_id"], item["treatment"]): item for item in attempts}
    public_tasks: list[dict[str, Any]] = []
    sealed_tasks: dict[str, Any] = {}
    deterministic: dict[str, dict[str, int]] = {}
    judges: dict[str, Any] = {}
    judge_runtime: dict[str, Any] = {}
    for task in manifest["tasks"]:
        task_id = task["task_id"]
        human_mapping = shuffled_mapping()
        judge_mapping = shuffled_mapping()
        human_candidates = {label: by_key[attempt_key(task_id, treatment)]["review_artifact"] for label, treatment in human_mapping.items()}
        judge_candidates = {label: by_key[attempt_key(task_id, treatment)]["review_artifact"] for label, treatment in judge_mapping.items()}
        judge_result = run_judge(task, judge_candidates, review_root / "private" / "judge" / task_id, manifest, fake=fake_judge)
        judge = judge_result["payload"]
        public_tasks.append({"task_id": task_id, "title": task["title"], "instruction": task["instruction"], "candidates": human_candidates})
        sealed_tasks[task_id] = {"human": human_mapping, "judge": judge_mapping}
        deterministic[task_id] = {treatment: deterministic_tier(by_key[attempt_key(task_id, treatment)]["hidden_grader"], by_key[attempt_key(task_id, treatment)]["agent_status"]) for treatment in TREATMENTS}
        judges[task_id] = judge
        judge_runtime[task_id] = judge_result["runtime"]
    public = {"schema_version": 1, "baseline_revision": manifest["baseline_revision"], "tasks": public_tasks, "score_levels": {"1": "Materially incorrect, incomplete, or unclear", "2": "Acceptable with limited errors or weaknesses", "3": "Correct, complete, and clear"}, "completed_task_ids": []}
    forbidden_public = json.dumps(public, ensure_ascii=False).lower()
    if any(term in forbidden_public for term in ("online_ds", "offline_ds", "qwen_local", "hidden_grader", "elapsed_seconds", "cost_usd", "tool_calls")):
        raise InfrastructureError("public review package leaks treatment telemetry")
    sealed = {"schema_version": 1, "tasks": sealed_tasks, "deterministic": deterministic, "judges": judges, "judge_runtime": judge_runtime, "attempts_sha256": hashlib.sha256(json.dumps(attempts, sort_keys=True, default=str).encode()).hexdigest()}
    write_json(sealed_root / "mappings.json", sealed)
    write_json(public_root / "review.json", public)
    atomic_write(public_root / "index.html", REVIEW_HTML.encode("utf-8"))
    package = {"schema_version": 1, "status": "ready_for_review", "review_root": str(review_root), "public_sha256": sha256_file(public_root / "review.json"), "sealed_sha256": sha256_file(sealed_root / "mappings.json"), "judge_count": len(judges), "task_count": len(public_tasks), "judge_runtime_contract": {"model": JUDGE_MODEL, "reasoning_effort": JUDGE_EFFORT, "fallback_configured": False, "validated_calls": len(judge_runtime)}}
    write_json(artifact_root / "phase-package-receipt.json", package)
    state["phase_receipts"]["package"] = package
    state["status"] = "review_pending"
    write_json(state_path(artifact_root), state)
    return package


def public_review_payload(review_root: Path) -> dict[str, Any]:
    public = read_json(review_root / "public" / "review.json")
    ratings = load_ratings(review_root)["ratings"]
    public["completed_task_ids"] = [task["task_id"] for task in public["tasks"] if task["task_id"] in ratings]
    return public


def make_review_handler(review_root: Path):
    class ReviewHandler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def send_json(self, code: HTTPStatus, payload: dict[str, Any]) -> None:
            content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in {"/", "/index.html"}:
                content = (review_root / "public" / "index.html").read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(content)
            elif path == "/api/review":
                self.send_json(HTTPStatus.OK, public_review_payload(review_root))
            elif path == "/api/reveal":
                try:
                    self.send_json(HTTPStatus.OK, aggregate_reveal(review_root))
                except PermissionError:
                    self.send_json(HTTPStatus.FORBIDDEN, {"error": "reveal is sealed until all ratings are submitted"})
            else:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/submit":
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 1024 * 1024:
                    raise ValueError("invalid body size")
                payload = json.loads(self.rfile.read(size))
                result = submit_rating(review_root, read_json(review_root / "public" / "review.json"), payload)
            except FileExistsError:
                self.send_json(HTTPStatus.CONFLICT, {"error": "rating already submitted"})
                return
            except (ValueError, json.JSONDecodeError):
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid rating payload"})
                return
            self.send_json(HTTPStatus.OK, result)

    return ReviewHandler


def serve_review(review_root: Path, host: str, port: int) -> None:
    if host != "127.0.0.1":
        raise InfrastructureError("review server may bind only to 127.0.0.1")
    if not (review_root / "public" / "review.json").is_file() or not (review_root / "sealed" / "mappings.json").is_file():
        raise InfrastructureError("review package is incomplete")
    server = ThreadingHTTPServer((host, port), make_review_handler(review_root))
    print(json.dumps({"status": "serving", "url": f"http://{host}:{server.server_port}/"}), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def fake_attempt(task: dict[str, Any], treatment: str, manifest: dict[str, Any]) -> dict[str, Any]:
    hidden = {"status": "passed", "passed": 9, "total": 9}
    return {"task_id": task["task_id"], "title": task["title"], "category": task["category"], "task_kind": task["task_kind"], "treatment": treatment, "route": manifest["treatments"][treatment]["route"], "model": manifest["treatments"][treatment]["model"], "claude_code_version": manifest["claude_code_version"], "agent_status": "completed", "hidden_grader": hidden, "visible_tests": {"status": "passed"}, "task_status": "passed", "review_artifact": f"Synthetic anonymous response for {task['task_id']}.", "prompt_contract_sha256": prompt_contract_hash(task, manifest)}


def run_fake_benchmark(artifact_root: Path) -> dict[str, Any]:
    manifest = load_manifest()
    preflight = {"preflight_key": "fake-r2-preflight"}
    state = initial_state(manifest, preflight)
    for task in manifest["tasks"]:
        for treatment in task["treatment_order"]:
            state["attempts"].append(fake_attempt(task, treatment, manifest))
    for task in manifest["tasks"]:
        state["attempts"].append(fake_attempt(task, "qwen_local", manifest))
    write_json(state_path(artifact_root), state)
    package = build_package(DEFAULT_CACHE, artifact_root, DEFAULT_TOOLCHAIN, fake_judge=True)
    return {"status": "completed", "attempt_count": len(state["attempts"]), "package": package}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--phase", choices=("deepseek", "qwen"))
    mode.add_argument("--package", action="store_true")
    mode.add_argument("--serve-review", action="store_true")
    mode.add_argument("--fake-run", action="store_true")
    parser.add_argument("--cache", type=Path, default=Path(os.environ.get("CLAUDE_PILOT_CACHE", DEFAULT_CACHE)))
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--review-root", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--toolchain", type=Path, default=Path(os.environ.get("CODING_AGENT_TOOLCHAIN", DEFAULT_TOOLCHAIN)))
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
        elif args.phase:
            output = run_phase(args.phase, args.cache, args.artifact_root, args.toolchain)
        elif args.package:
            output = build_package(args.cache, args.artifact_root, args.toolchain)
        elif args.fake_run:
            output = run_fake_benchmark(args.artifact_root)
        else:
            serve_review((args.review_root or args.artifact_root / "review").resolve(), args.host, args.port)
            return 0
        print(json.dumps(output, ensure_ascii=False))
        return 0
    except InfrastructureError as exc:
        error = {"schema_version": 3, "status": "failed", "error": f"{type(exc).__name__}: {exc}", "ended_at": utc_now()}
        write_json(args.artifact_root / "error.json", error)
        print(json.dumps(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
