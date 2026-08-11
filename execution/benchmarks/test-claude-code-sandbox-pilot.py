#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("claude_code_sandbox_pilot.py")
SPEC = importlib.util.spec_from_file_location("claude_code_sandbox_pilot", MODULE_PATH)
assert SPEC and SPEC.loader
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)
REPORTER_PATH = Path(__file__).with_name("render_benchmark_report.py")
REPORTER_SPEC = importlib.util.spec_from_file_location("render_benchmark_report", REPORTER_PATH)
assert REPORTER_SPEC and REPORTER_SPEC.loader
reporter = importlib.util.module_from_spec(REPORTER_SPEC)
REPORTER_SPEC.loader.exec_module(reporter)


def make_fake_toolchain(root: Path) -> tuple[Path, Path]:
    toolchain = root / "toolchain"
    shim = toolchain / "bin" / "claude"
    shim.parent.mkdir(parents=True)
    shim.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
model="${FAKE_MODEL:-${CLAUDE_DS_MODEL:-${CLAUDE_LOCAL_MODEL:-missing}}}"
version="${FAKE_VERSION:-2.1.207}"
tools=""
previous=""
for argument in "$@"; do
  if [ "$previous" = "--tools" ]; then tools="$argument"; fi
  previous="$argument"
done
printf '{"type":"system","subtype":"init","model":"%s","claude_code_version":"%s"}\\n' "$model" "$version"
if [ -n "${FAKE_SLEEP:-}" ]; then sleep "$FAKE_SLEEP"; fi
if [ -n "$tools" ]; then printf '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"%s"}]}}\\n' "${FAKE_TOOL_NAME:-Read}"; fi
printf '{"type":"result","subtype":"success","duration_ms":5,"num_turns":1,"total_cost_usd":0.01,"modelUsage":{"%s":{"inputTokens":1,"outputTokens":1}},"usage":{"input_tokens":1,"output_tokens":1},"permission_denials":[],"terminal_reason":"completed"}\\n' "$model"
""",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    subprocess.run(["git", "init", "-q", str(toolchain)], check=True)
    subprocess.run(["git", "-C", str(toolchain), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(toolchain), "config", "user.email", "test@localhost"], check=True)
    subprocess.run(["git", "-C", str(toolchain), "add", "bin/claude"], check=True)
    subprocess.run(["git", "-C", str(toolchain), "commit", "-qm", "fake"], check=True)
    real = root / "claude-real"
    real.write_text("#!/usr/bin/env bash\necho '2.1.207 (Claude Code)'\n", encoding="utf-8")
    real.chmod(0o755)
    return toolchain, real


def make_fake_codex(root: Path) -> tuple[Path, Path]:
    binary = root / "codex"
    audit_root = root / "codex-audit"
    binary.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "--version" ]; then echo 'codex-cli 0.144.5'; exit 0; fi
model=""; effort=""; approval=""; output=""; prompt=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --model) model="$2"; shift 2 ;;
    --config) case "$2" in *model_reasoning_effort*) effort="$2";; *approval_policy*) approval="$2";; esac; shift 2 ;;
    --output-last-message) output="$2"; shift 2 ;;
    *) prompt="$1"; shift ;;
  esac
done
[ "$model" = "gpt-5.6-sol" ]
[ "$effort" = 'model_reasoning_effort="xhigh"' ]
[ "$approval" = 'approval_policy="never"' ]
if [ -n "${FAKE_CODEX_FAIL_ONCE:-}" ] && [ ! -e "$FAKE_CODEX_FAIL_ONCE" ]; then touch "$FAKE_CODEX_FAIL_ONCE"; exit 1; fi
thread="fake-codex-thread"
mkdir -p "$CODEX_JUDGE_AUDIT_ROOT/2026/08/11"
printf '{"type":"thread.started","thread_id":"%s"}\\n' "$thread"
printf '%s\\n' '{"type":"turn.completed"}'
printf '%s\\n' '{"type":"turn_context","payload":{"model":"gpt-5.6-sol","effort":"xhigh","approval_policy":"never","sandbox_policy":{"type":"read-only"},"collaboration_mode":{"settings":{"model":"gpt-5.6-sol","reasoning_effort":"xhigh"}}}}' >"$CODEX_JUDGE_AUDIT_ROOT/2026/08/11/rollout-$thread.jsonl"
if [[ "$prompt" == *"exact JSON object"* ]]; then
  printf '%s\\n' '{"ready":true}' >"$output"
else
  printf '%s\\n' '{"candidates":{"A":{"accuracy":3,"following":3,"clarity_style":3},"B":{"accuracy":2,"following":2,"clarity_style":2},"C":{"accuracy":1,"following":1,"clarity_style":1}},"preference":"A","rationale":"Content-only assessment."}' >"$output"
fi
""",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    return binary, audit_root


def rating(task_id: str) -> dict[str, object]:
    return {"task_id": task_id, "scores": {letter: {criterion: 2 for criterion in pilot.CRITERIA} for letter in pilot.LETTERS}, "preference": "tie"}


def assert_http_status(url: str, expected: int) -> None:
    try:
        urllib.request.urlopen(url, timeout=3)
    except urllib.error.HTTPError as exc:
        assert exc.code == expected, (url, exc.code)
    else:
        raise AssertionError(f"{url} unexpectedly succeeded")


def main() -> None:
    manifest = pilot.load_manifest()
    task_count = len(manifest["tasks"])
    human_count = sum(task["category"] == pilot.HUMAN_REVIEW_CATEGORY for task in manifest["tasks"])
    assert task_count == 47
    assert human_count == 12
    assert manifest["corpus_contract"]["new_domain_counts"] == {"terminal": 10, "server_ops": 10, "writing": 10, "programming": 10}
    assert set(manifest["treatments"]) == set(pilot.TREATMENTS)
    assert [task["treatment_order"][0] for task in manifest["tasks"]].count("online_ds") == 24
    assert all("fallback" not in json.dumps(contract).lower() for contract in manifest["treatments"].values())
    judge_schema = pilot.codex_schema("judge")
    assert set(judge_schema["required"]) == set(judge_schema["properties"])
    candidate_schema = judge_schema["properties"]["candidates"]
    assert set(candidate_schema["required"]) == set(candidate_schema["properties"])
    assert all(set(item["required"]) == set(item["properties"]) for item in candidate_schema["properties"].values())

    with tempfile.TemporaryDirectory(prefix="claude-pilot-test-") as raw:
        root = Path(raw)
        toolchain, real = make_fake_toolchain(root)
        codex, audit_root = make_fake_codex(root)
        os.environ["CODEX_BIN"] = str(codex)
        os.environ["CODEX_JUDGE_AUDIT_ROOT"] = str(audit_root)
        candidate_env, _ = pilot.claude_environment("offline_ds", toolchain, real, manifest)
        assert candidate_env["BASH_DEFAULT_TIMEOUT_MS"] == "1200000"
        assert candidate_env["BASH_MAX_TIMEOUT_MS"] == "1200000"
        run = pilot.run_claude(treatment="online_ds", prompt="test", cwd=root, timeout_seconds=5, toolchain=toolchain, real_claude=real, expected_version="2.1.207", output_path=root / "online.jsonl", with_tools=True, manifest=manifest)
        assert run["model"] == "deepseek-v4-flash" and run["route"] == "claude_ds" and run["tool_calls"] == ["Read"]
        qwen = pilot.run_claude(treatment="qwen_local", prompt="test", cwd=root, timeout_seconds=5, toolchain=toolchain, real_claude=real, expected_version="2.1.207", output_path=root / "qwen.jsonl", with_tools=False, manifest=manifest)
        assert qwen["model"] == "qwen3.6-35b-fp8" and qwen["route"] == "claude_local" and qwen["tool_calls"] == []

        os.environ["FAKE_TOOL_NAME"] = "shell"
        invalid_tool = pilot.run_claude(treatment="qwen_local", prompt="test", cwd=root, timeout_seconds=5, toolchain=toolchain, real_claude=real, expected_version="2.1.207", output_path=root / "invalid-tool.jsonl", with_tools=True, manifest=manifest)
        assert invalid_tool["agent_status"] == "invalid_tool_activity"
        assert invalid_tool["disallowed_tool_calls"] == ["shell"]
        assert pilot.deterministic_tier({"passed": 8, "total": 8}, invalid_tool["agent_status"]) == 1
        os.environ.pop("FAKE_TOOL_NAME")

        os.environ["FAKE_MODEL"] = "deepseek-v4-pro"
        try:
            pilot.run_claude(treatment="online_ds", prompt="test", cwd=root, timeout_seconds=5, toolchain=toolchain, real_claude=real, expected_version="2.1.207", output_path=root / "mismatch.jsonl", with_tools=False, manifest=manifest)
        except pilot.InfrastructureError as exc:
            assert "model mismatch" in str(exc)
        else:
            raise AssertionError("model mismatch did not fail")
        os.environ.pop("FAKE_MODEL")

        os.environ["FAKE_SLEEP"] = "3"
        timeout = pilot.run_claude(treatment="offline_ds", prompt="test", cwd=root, timeout_seconds=1, toolchain=toolchain, real_claude=real, expected_version="2.1.207", output_path=root / "timeout.jsonl", with_tools=True, manifest=manifest)
        assert timeout["timed_out"] is True and timeout["terminal_reason"] == "timeout"
        os.environ.pop("FAKE_SLEEP")

        for task in manifest["tasks"]:
            workspace = root / "sandboxes" / task["task_id"]
            fixture = pilot.checked_path(pilot.FIXTURE_ROOT, task["fixture"])
            solution = pilot.checked_path(pilot.SOLUTION_ROOT, task["solution"])
            assert len(pilot.prepare_workspace(fixture, workspace)) == 40
            initial = pilot.run_hidden_grader(task, workspace, root / "grades" / "initial" / task["task_id"], 30)
            assert initial["status"] == "failed", task["task_id"]
            pilot.overlay_solution(solution, workspace)
            visible = pilot.run_visible_tests(task, workspace, root / "grades" / "gold" / task["task_id"], 30)
            hidden = pilot.run_hidden_grader(task, workspace, root / "grades" / "gold" / task["task_id"], 30)
            assert visible["status"] == "passed" and hidden["status"] == "passed", task["task_id"]

        argv = pilot.claude_argv(toolchain / "bin" / "claude", "model", "p", True)
        assert "Agent" not in argv[argv.index("--tools") + 1] and "--fallback-model" not in argv
        assert "--strict-mcp-config" in argv and "--safe-mode" in argv
        assert [pilot.deterministic_tier({"passed": passed, "total": 8}, "completed") for passed in (8, 4, 3)] == [3, 2, 1]

        try:
            pilot.validate_judge_payload({"candidates": {}, "preference": "A"})
        except pilot.InfrastructureError:
            pass
        else:
            raise AssertionError("invalid judge schema did not fail")
        try:
            pilot.validate_judge_payload({"candidates": {letter: {criterion: 3 for criterion in pilot.CRITERIA} for letter in pilot.LETTERS}, "preference": "A", "rationale": "The online route wins."})
        except pilot.InfrastructureError:
            pass
        else:
            raise AssertionError("identity speculation did not fail")

        probe = pilot.run_codex_probe(root / "judge-probe")
        assert probe["runtime"]["model"] == "gpt-5.6-sol"
        assert probe["runtime"]["reasoning_effort"] == "xhigh"
        judged = pilot.run_judge(manifest["tasks"][0], {"A": "one", "B": "two", "C": "three"}, root / "judge", manifest)
        assert judged["payload"]["preference"] == "A"
        assert judged["runtime"]["fallback_configured"] is False

        os.environ["FAKE_CODEX_FAIL_ONCE"] = str(root / "codex-failed-once")
        retried = pilot.run_judge(manifest["tasks"][0], {"A": "one", "B": "two", "C": "three"}, root / "judge-retry", manifest)
        assert retried["payload"]["preference"] == "A"
        assert (root / "judge-retry" / "attempt-2" / "codex-runtime-receipt.json").is_file()
        os.environ.pop("FAKE_CODEX_FAIL_ONCE")

        fake_root = root / "fake-run"
        result = pilot.run_fake_benchmark(fake_root)
        assert result["attempt_count"] == task_count * len(pilot.TREATMENTS)
        assert result["package"]["status"] == "completed"
        assert result["package"]["task_count"] == task_count
        assert result["package"]["attempt_count"] == task_count * len(pilot.TREATMENTS)
        assert result["package"]["judge_count"] == task_count
        assert result["package"]["human_task_count"] == human_count
        assert result["package"]["human_review_required"] is False
        assert (fake_root / "review" / "private" / "baseline-results.json").is_file()
        review_root = fake_root / "review"
        public = pilot.public_review_payload(review_root)
        assert len(public["tasks"]) == human_count
        assert {task["task_id"] for task in public["tasks"]} == {task["task_id"] for task in manifest["tasks"] if task["category"] == pilot.HUMAN_REVIEW_CATEGORY}
        assert all(term not in json.dumps(public).lower() for term in ("online_ds", "offline_ds", "qwen_local", "hidden_grader", "cost_usd"))
        assert not (review_root / "public" / "mappings.json").exists() and (review_root / "sealed" / "mappings.json").is_file()
        baseline = pilot.aggregate_baseline(review_root)
        assert baseline["status"] == "completed" and baseline["human_ratings_completed"] == 0
        assert len(baseline["tasks"]) == task_count
        assert all(value["quality_mean"] == 3 for value in baseline["aggregates"].values())
        report_path = review_root / "public" / "final-report.html"
        reporter.render_report(pilot.PROJECT_ROOT, fake_root, report_path)
        report = report_path.read_text(encoding="utf-8")
        assert report.count('<section class="task"') == task_count
        assert report.count('<article class="answer') == task_count * len(pilot.TREATMENTS)
        assert report.count("<blockquote>") == task_count

        server = pilot.ThreadingHTTPServer(("127.0.0.1", 0), pilot.make_review_handler(review_root))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        assert_http_status(base + "/sealed/mappings.json", 404)
        assert_http_status(base + "/api/reveal", 403)
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()

        for task in public["tasks"]:
            accepted = pilot.submit_rating(review_root, public, rating(task["task_id"]))
        assert accepted["completed"] is True
        try:
            pilot.submit_rating(review_root, public, rating(public["tasks"][0]["task_id"]))
        except FileExistsError:
            pass
        else:
            raise AssertionError("atomic resume allowed a duplicate rating")
        reveal = pilot.aggregate_reveal(review_root)
        assert reveal["status"] == "revealed" and set(reveal["aggregates"]) == set(pilot.TREATMENTS)
        assert len(reveal["tasks"]) == task_count and sum(task["human_scored"] for task in reveal["tasks"]) == human_count
        assert all(value["quality_mean"] == 3 for value in reveal["aggregates"].values())

        os.environ.pop("CODEX_BIN")
        os.environ.pop("CODEX_JUDGE_AUDIT_ROOT")

    print(json.dumps({"status": "passed", "tests": 12}))


if __name__ == "__main__":
    main()
