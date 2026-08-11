#!/usr/bin/env python3
"""Run the frozen Claude Code Flash SWE-bench pilot without per-task agents."""

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
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pyarrow import parquet

SCRIPT_PATH = Path(__file__).resolve()
BENCHMARK_DIR = SCRIPT_PATH.parent
EXECUTION_DIR = BENCHMARK_DIR.parent
PROJECT_ROOT = EXECUTION_DIR.parent
MANIFEST_PATH = BENCHMARK_DIR / "claude-code-swe-pilot-tasks.json"
DEFAULT_TOOLCHAIN = Path("/Users/chris/project/Shili/workspaces/coding-agent-toolchain")
DEFAULT_CACHE = EXECUTION_DIR / "artifacts" / "claude-code-pilot" / "cache"
DATASET_URLS = (
    (
        "https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified/resolve/"
        "main/data/test-00000-of-00001.parquet"
    ),
    (
        "https://hf-mirror.com/datasets/princeton-nlp/SWE-bench_Verified/resolve/"
        "main/data/test-00000-of-00001.parquet"
    ),
)


class InfrastructureError(RuntimeError):
    pass


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def load_manifest() -> dict[str, Any]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise InfrastructureError("unsupported task manifest schema")
    tasks = manifest.get("tasks") or []
    if len(tasks) != 4 or len({task["instance_id"] for task in tasks}) != 4:
        raise InfrastructureError("task manifest must contain four unique tasks")
    for task in tasks:
        if sorted(task.get("treatment_order") or []) != ["online", "private"]:
            raise InfrastructureError(
                f"invalid treatment order for {task['instance_id']}"
            )
    return manifest


def run_command(
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
    log_path: Path | None = None,
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
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(result.stdout, encoding="utf-8")
    if check and result.returncode != 0:
        output = result.stdout[-4000:]
        raise InfrastructureError(
            f"command failed ({result.returncode}): {' '.join(argv[:4])}\n{output}"
        )
    return result


def download_dataset(cache: Path, manifest: dict[str, Any]) -> Path:
    destination = cache / "dataset" / "swe-bench-verified-test.parquet"
    expected = manifest["dataset"]["parquet_sha256"]
    if destination.exists() and sha256_file(destination) == expected:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for url in DATASET_URLS:
        temporary = destination.with_suffix(".download")
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "gb10-ds-pilot/1"}
            )
            with (
                urllib.request.urlopen(request, timeout=120) as response,
                temporary.open("wb") as out,
            ):
                shutil.copyfileobj(response, out)
            actual = sha256_file(temporary)
            if actual != expected:
                raise InfrastructureError(f"dataset SHA mismatch: {actual}")
            temporary.replace(destination)
            return destination
        except (
            InfrastructureError,
            OSError,
            TimeoutError,
            urllib.error.URLError,
        ) as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
            temporary.unlink(missing_ok=True)
    raise InfrastructureError("dataset download failed: " + " | ".join(errors))


def selected_dataset(
    cache: Path, manifest: dict[str, Any]
) -> tuple[Path, dict[str, dict[str, Any]]]:
    parquet_path = download_dataset(cache, manifest)
    rows = parquet.read_table(parquet_path).to_pylist()
    by_id = {row["instance_id"]: row for row in rows}
    selected: list[dict[str, Any]] = []
    selected_by_id: dict[str, dict[str, Any]] = {}
    for task in manifest["tasks"]:
        instance_id = task["instance_id"]
        row = by_id.get(instance_id)
        if row is None:
            raise InfrastructureError(f"task missing from dataset: {instance_id}")
        if row.get("difficulty") != task["difficulty"]:
            raise InfrastructureError(f"difficulty mismatch for {instance_id}")
        selected.append(row)
        selected_by_id[instance_id] = row
    json_path = cache / "dataset" / "selected-tasks.json"
    write_json(json_path, selected)
    return json_path, selected_by_id


def ensure_harness(cache: Path, manifest: dict[str, Any]) -> tuple[Path, Path]:
    repo = cache / "harness" / "SWE-bench"
    venv = cache / "harness" / "venv"
    marker = venv / ".installed-commit"
    expected = manifest["harness"]["commit"]
    if not (repo / ".git").exists():
        repo.parent.mkdir(parents=True, exist_ok=True)
        run_command(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                manifest["harness"]["repo"],
                str(repo),
            ],
            timeout=600,
        )
    run_command(
        ["git", "fetch", "--depth", "1", "origin", "tag", manifest["harness"]["tag"]],
        cwd=repo,
        timeout=600,
    )
    run_command(["git", "checkout", "--detach", manifest["harness"]["tag"]], cwd=repo)
    actual = run_command(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()
    if actual != expected:
        raise InfrastructureError(f"SWE-bench commit mismatch: {actual}")
    if not marker.exists() or marker.read_text(encoding="utf-8").strip() != expected:
        if not (venv / "bin" / "python").exists():
            run_command(["uv", "venv", "--python", "3.11", str(venv)], timeout=600)
        run_command(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(venv / "bin" / "python"),
                "-e",
                str(repo),
            ],
            timeout=1800,
        )
        marker.write_text(expected + "\n", encoding="utf-8")
    return repo, venv / "bin" / "python"


def expected_preflight_key(manifest: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    for path in (
        MANIFEST_PATH,
        SCRIPT_PATH,
        PROJECT_ROOT / "execution" / "run-vllm-service.sh",
        PROJECT_ROOT / "execution" / "run-claude-code-flash-pilot.sh",
    ):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    digest.update(manifest["harness"]["commit"].encode())
    digest.update(manifest["dataset"]["parquet_sha256"].encode())
    docker_arch = run_command(
        ["docker", "version", "--format", "{{.Server.Arch}}"], check=True
    ).stdout.strip()
    digest.update(docker_arch.encode())
    return digest.hexdigest()


def find_real_claude(expected_version: str) -> Path:
    configured = os.environ.get("CLAUDE_BENCH_REAL_BIN")
    candidate = Path(configured) if configured else Path(shutil.which("claude") or "")
    if not candidate or not candidate.is_file():
        raise InfrastructureError("real Claude Code binary not found")
    version = run_command([str(candidate), "--version"]).stdout.strip().split()[0]
    if version != expected_version:
        raise InfrastructureError(
            f"Claude Code version mismatch: {version}, expected {expected_version}"
        )
    return candidate.resolve()


def toolchain_contract(toolchain: Path) -> tuple[Path, str]:
    shim = toolchain / "bin" / "claude"
    if not shim.is_file():
        raise InfrastructureError(f"toolchain Claude shim missing: {shim}")
    commit = run_command(["git", "rev-parse", "HEAD"], cwd=toolchain).stdout.strip()
    return shim, commit


def provider_spec(treatment: str) -> dict[str, str]:
    if treatment == "online":
        return {
            "provider": "ds",
            "model": "deepseek-v4-flash",
            "base_url": os.environ.get(
                "CLAUDE_DS_BASE_URL",
                os.environ.get("CLAUDE_BASE_URL", "https://coding.onlyservice.io"),
            ),
        }
    if treatment == "private":
        return {
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
        }
    )
    if treatment == "online":
        if not env.get("CLAUDE_DS_TOKEN"):
            raise InfrastructureError("CLAUDE_DS_TOKEN is missing")
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
            f"{treatment}: model mismatch {init.get('model')!r}, expected {expected_model!r}"
        )
    if init.get("claude_code_version") != expected_version:
        raise InfrastructureError(
            f"{treatment}: Claude Code init version mismatch {init.get('claude_code_version')!r}"
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
    shim, _ = toolchain_contract(toolchain)
    argv = claude_argv(shim, spec["model"], prompt, with_tools)
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
    if not timed_out and process.returncode != 0:
        raise InfrastructureError(
            f"{treatment}: Claude Code exited {process.returncode} after valid init"
        )
    return {
        "treatment": treatment,
        "model": spec["model"],
        "claude_code_version": parsed["init"]["claude_code_version"],
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


def ensure_repo(cache: Path, row: dict[str, Any]) -> Path:
    repo_name = row["repo"].replace("/", "__")
    repo_cache = cache / "repositories" / repo_name
    url = f"https://github.com/{row['repo']}.git"
    if not (repo_cache / ".git").exists():
        repo_cache.parent.mkdir(parents=True, exist_ok=True)
        run_command(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                url,
                str(repo_cache),
            ],
            timeout=1800,
        )
    check = run_command(
        ["git", "cat-file", "-e", f"{row['base_commit']}^{{commit}}"],
        cwd=repo_cache,
        check=False,
    )
    if check.returncode != 0:
        run_command(
            ["git", "fetch", "--filter=blob:none", "origin", row["base_commit"]],
            cwd=repo_cache,
            timeout=1800,
        )
    run_command(
        ["git", "cat-file", "-e", f"{row['base_commit']}^{{commit}}"], cwd=repo_cache
    )
    return repo_cache


def prepare_workspace(repo_cache: Path, destination: Path, base_commit: str) -> None:
    if destination.exists():
        raise InfrastructureError(f"workspace already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            "git",
            "clone",
            "--shared",
            "--no-checkout",
            str(repo_cache),
            str(destination),
        ],
        timeout=600,
    )
    run_command(
        ["git", "checkout", "--detach", base_commit], cwd=destination, timeout=600
    )
    run_command(["git", "config", "user.name", "Claude Code Pilot"], cwd=destination)
    run_command(["git", "config", "user.email", "pilot@localhost"], cwd=destination)


def capture_patch(workspace: Path) -> str:
    untracked = run_command(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=workspace
    ).stdout
    files = [
        item
        for item in untracked.split("\0")
        if item and not item.startswith(".claude/")
    ]
    if files:
        run_command(["git", "add", "-N", "--", *files], cwd=workspace)
    return run_command(
        ["git", "diff", "--binary", "--", ".", ":(exclude).claude"], cwd=workspace
    ).stdout


def task_prompt(row: dict[str, Any], instance_id: str) -> str:
    return (
        f"You are solving SWE-bench Verified instance {instance_id}.\n\n"
        f"Issue:\n{row['problem_statement'].strip()}\n\n"
        "Work directly in the current repository. Inspect the code, implement the smallest complete fix, "
        "and run relevant tests when the environment permits. Do not use network access, do not inspect "
        "external solutions or hidden tests, and do not ask questions. Leave the best patch in the worktree "
        "and finish when no further useful local verification remains."
    )


def run_harness_evaluation(
    *,
    harness_python: Path,
    dataset_path: Path,
    predictions_path: Path | str,
    instance_ids: list[str],
    run_id: str,
    work_dir: Path,
    model_name: str,
    timeout: int,
) -> dict[str, Any]:
    report_dir = work_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    argv = [
        str(harness_python),
        "-m",
        "swebench.harness.run_evaluation",
        "--dataset_name",
        str(dataset_path),
        "--predictions_path",
        str(predictions_path),
        "--instance_ids",
        *instance_ids,
        "--max_workers",
        "1",
        "--timeout",
        str(timeout),
        "--cache_level",
        "env",
        "--clean",
        "false",
        "--run_id",
        run_id,
        "--namespace",
        "none",
        "--report_dir",
        str(report_dir),
    ]
    run_command(
        argv,
        cwd=work_dir,
        timeout=max(timeout * len(instance_ids) + 3600, 7200),
        log_path=work_dir / "evaluation.log",
    )
    report_name = f"{model_name.replace('/', '__')}.{run_id}.json"
    report_path = report_dir / report_name
    if not report_path.is_file():
        report_path = work_dir / report_name
    if not report_path.is_file():
        raise InfrastructureError(f"SWE-bench report missing: {report_path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["report_path"] = str(report_path)
    return report


def run_preflight(cache: Path, artifact_root: Path, toolchain: Path) -> dict[str, Any]:
    manifest = load_manifest()
    started = utc_now()
    dataset_path, rows = selected_dataset(cache, manifest)
    _, harness_python = ensure_harness(cache, manifest)
    real_claude = find_real_claude(manifest["claude_code_version"])
    _, toolchain_commit = toolchain_contract(toolchain)
    for row in rows.values():
        ensure_repo(cache, row)
    probe_dir = artifact_root / "protocol-probe"
    online_probe = probe_provider(
        "online", toolchain, real_claude, manifest["claude_code_version"], probe_dir
    )
    key = expected_preflight_key(manifest)
    gold_dir = cache / "gold" / key
    run_id = f"gold-{key[:12]}"
    report_name = f"gold.{run_id}.json"
    cached_report = next(
        (
            path
            for path in (gold_dir / "reports" / report_name, gold_dir / report_name)
            if path.is_file()
        ),
        None,
    )
    if cached_report:
        gold_report = json.loads(cached_report.read_text(encoding="utf-8"))
        gold_report["report_path"] = str(cached_report)
    else:
        gold_report = run_harness_evaluation(
            harness_python=harness_python,
            dataset_path=dataset_path,
            predictions_path="gold",
            instance_ids=[task["instance_id"] for task in manifest["tasks"]],
            run_id=run_id,
            work_dir=gold_dir,
            model_name="gold",
            timeout=1800,
        )
    expected_ids = {task["instance_id"] for task in manifest["tasks"]}
    if set(gold_report.get("resolved_ids") or []) != expected_ids:
        raise InfrastructureError(
            f"gold calibration did not resolve all tasks: {gold_report}"
        )
    receipt = {
        "schema_version": 1,
        "status": "passed",
        "preflight_key": key,
        "started_at": started,
        "ended_at": utc_now(),
        "manifest_sha256": sha256_file(MANIFEST_PATH),
        "runner_sha256": sha256_file(SCRIPT_PATH),
        "dataset_sha256": sha256_file(
            cache / "dataset" / "swe-bench-verified-test.parquet"
        ),
        "harness_commit": manifest["harness"]["commit"],
        "toolchain_commit": toolchain_commit,
        "claude_real_bin": str(real_claude),
        "claude_code_version": manifest["claude_code_version"],
        "online_probe": online_probe,
        "gold_report": gold_report,
        "task_ids": sorted(expected_ids),
    }
    receipt_path = cache / "preflight-receipt.json"
    write_json(receipt_path, receipt)
    write_json(artifact_root / "preflight-receipt.json", receipt)
    return receipt


def require_fresh_preflight(cache: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    receipt_path = cache / "preflight-receipt.json"
    if not receipt_path.is_file():
        raise InfrastructureError("preflight receipt is missing")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "passed":
        raise InfrastructureError("preflight receipt is not passed")
    expected = expected_preflight_key(manifest)
    if receipt.get("preflight_key") != expected:
        raise InfrastructureError("preflight receipt is stale")
    return receipt


def run_pilot(cache: Path, artifact_root: Path, toolchain: Path) -> dict[str, Any]:
    manifest = load_manifest()
    preflight = require_fresh_preflight(cache, manifest)
    dataset_path, rows = selected_dataset(cache, manifest)
    _, harness_python = ensure_harness(cache, manifest)
    real_claude = find_real_claude(manifest["claude_code_version"])
    _, toolchain_commit = toolchain_contract(toolchain)
    if toolchain_commit != preflight["toolchain_commit"]:
        raise InfrastructureError("coding-agent-toolchain changed after preflight")

    private_probe = probe_provider(
        "private",
        toolchain,
        real_claude,
        manifest["claude_code_version"],
        artifact_root / "protocol-probe",
    )
    attempts: list[dict[str, Any]] = []
    predictions: dict[str, list[dict[str, str]]] = {"online": [], "private": []}
    for task in manifest["tasks"]:
        instance_id = task["instance_id"]
        row = rows[instance_id]
        repo_cache = ensure_repo(cache, row)
        for treatment in task["treatment_order"]:
            workspace = artifact_root / "workspaces" / treatment / instance_id
            prepare_workspace(repo_cache, workspace, row["base_commit"])
            stream_path = artifact_root / "runs" / treatment / f"{instance_id}.jsonl"
            attempt = run_claude(
                treatment=treatment,
                prompt=task_prompt(row, instance_id),
                cwd=workspace,
                timeout_seconds=int(manifest["timeout_seconds"]),
                toolchain=toolchain,
                real_claude=real_claude,
                expected_version=manifest["claude_code_version"],
                output_path=stream_path,
                with_tools=True,
            )
            patch = capture_patch(workspace)
            patch_path = artifact_root / "patches" / treatment / f"{instance_id}.patch"
            patch_path.parent.mkdir(parents=True, exist_ok=True)
            patch_path.write_text(patch, encoding="utf-8")
            attempt.update(
                {
                    "instance_id": instance_id,
                    "difficulty": task["difficulty"],
                    "base_commit": row["base_commit"],
                    "workspace": str(workspace),
                    "patch_path": str(patch_path),
                    "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
                    "patch_bytes": len(patch.encode()),
                }
            )
            attempts.append(attempt)
            predictions[treatment].append(
                {
                    "instance_id": instance_id,
                    "model_name_or_path": provider_spec(treatment)["model"],
                    "model_patch": patch,
                }
            )
            write_json(artifact_root / "attempts.partial.json", attempts)

    reports: dict[str, Any] = {}
    for treatment in ("online", "private"):
        prediction_path = artifact_root / "predictions" / f"{treatment}.json"
        write_json(prediction_path, predictions[treatment])
        evaluation_dir = artifact_root / "evaluation" / treatment
        reports[treatment] = run_harness_evaluation(
            harness_python=harness_python,
            dataset_path=dataset_path,
            predictions_path=prediction_path,
            instance_ids=[task["instance_id"] for task in manifest["tasks"]],
            run_id=f"{artifact_root.name}-{treatment}",
            work_dir=evaluation_dir,
            model_name=provider_spec(treatment)["model"],
            timeout=1800,
        )

    for attempt in attempts:
        report = reports[attempt["treatment"]]
        instance_id = attempt["instance_id"]
        if instance_id in report.get("resolved_ids", []):
            attempt["official_status"] = "resolved"
        elif instance_id in report.get("unresolved_ids", []):
            attempt["official_status"] = "unresolved"
        elif instance_id in report.get("empty_patch_ids", []):
            attempt["official_status"] = "empty_patch"
        else:
            attempt["official_status"] = "evaluation_error"

    result = {
        "schema_version": 1,
        "status": "completed",
        "baseline_revision": "claude-ds-pilot-r1",
        "started_from_preflight": preflight["preflight_key"],
        "ended_at": utc_now(),
        "claude_code_version": manifest["claude_code_version"],
        "toolchain_commit": toolchain_commit,
        "private_probe": private_probe,
        "attempts": attempts,
        "reports": reports,
        "resolved": {
            treatment: reports[treatment].get("resolved_instances", 0)
            for treatment in ("online", "private")
        },
        "note": "Single-repetition pilot; no statistical superiority claim.",
    }
    write_json(artifact_root / "result.json", result)
    write_summary(artifact_root / "summary.md", result)
    return result


def write_summary(path: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Claude Code Flash Pilot",
        "",
        f"- Status: `{result['status']}`",
        f"- Claude Code: `{result['claude_code_version']}`",
        f"- Online resolved: `{result['resolved']['online']}/4`",
        f"- Private resolved: `{result['resolved']['private']}/4`",
        "- Interpretation: single-repetition calibration only",
        "",
        "| Task | Treatment | Official | Seconds | Turns | Cost USD | Tools |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for attempt in result["attempts"]:
        lines.append(
            "| {instance_id} | {treatment} | {official_status} | {elapsed_seconds} | {turns} | {cost} | {tools} |".format(
                instance_id=attempt["instance_id"],
                treatment=attempt["treatment"],
                official_status=attempt["official_status"],
                elapsed_seconds=attempt["elapsed_seconds"],
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
        default=Path(os.environ.get("SWE_PILOT_CACHE", DEFAULT_CACHE)),
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
            "schema_version": 1,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "ended_at": utc_now(),
        }
        write_json(args.artifact_root / "error.json", error)
        print(json.dumps(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
