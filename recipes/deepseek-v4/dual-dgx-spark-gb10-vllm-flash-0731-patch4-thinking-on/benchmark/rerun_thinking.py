#!/usr/bin/env python3
"""Run and compare a five-task Private DeepSeek thinking treatment."""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import os
import secrets
import shutil
import sys
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
BENCHMARK_DIR = SCRIPT_PATH.parent
PROJECT_ROOT = BENCHMARK_DIR.parent.parent
PILOT_PATH = BENCHMARK_DIR / "run_benchmark.py"
MANIFEST_PATH = BENCHMARK_DIR / "tasks.json"
DEFAULT_SOURCE_RUN = Path(os.environ.get("THINKING_RERUN_SOURCE", BENCHMARK_DIR / "artifacts" / "source-run"))
DEFAULT_TOOLCHAIN = Path(os.environ.get("CODING_AGENT_TOOLCHAIN", BENCHMARK_DIR / ".missing-toolchain"))
SELECTED = (
    ("ndjson-stream-decoder", "SWE / debug"),
    ("terminal-log-frequency", "Terminal"),
    ("ops-oom-cgroup", "Server operations"),
    ("writing-zh-incident", "Chinese writing"),
    ("typescript-lru-ttl", "TypeScript programming"),
)
TREATMENTS = ("offline_ds_old", "offline_ds_thinking", "online_ds")
LABELS = {
    "offline_ds_old": "Private DS (thinking off, original)",
    "offline_ds_thinking": "Private DS (thinking on, rerun)",
    "online_ds": "Online DS Flash (original)",
}


def load_pilot() -> Any:
    spec = importlib.util.spec_from_file_location("claude_code_sandbox_pilot", PILOT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load benchmark runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_paths(source_run: Path) -> tuple[Path, Path]:
    baseline = source_run / "review/private/baseline-results.json"
    state = source_run / "benchmark-state.json"
    if not baseline.is_file() or not state.is_file():
        raise RuntimeError("source benchmark artifacts are incomplete")
    return baseline, state


def validate_selection(source_run: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    baseline_path, state_path = source_paths(source_run)
    baseline = read_json(baseline_path)
    baseline_tasks = {row["task_id"]: row for row in baseline["tasks"]}
    manifest_tasks = {task["task_id"]: task for task in manifest["tasks"]}
    rows = []
    for task_id, category in SELECTED:
        if task_id not in baseline_tasks or task_id not in manifest_tasks:
            raise RuntimeError(f"selected task is missing: {task_id}")
        old = baseline_tasks[task_id]
        online_quality = float(old["scores"]["online_ds"]["quality"])
        private_quality = float(old["scores"]["offline_ds"]["quality"])
        if private_quality >= online_quality:
            raise RuntimeError(f"selected task was not weaker for Private DS: {task_id}")
        rows.append({
            "task_id": task_id,
            "selection_category": category,
            "manifest_category": manifest_tasks[task_id]["category"],
            "old_online_quality": online_quality,
            "old_private_quality": private_quality,
            "old_gap": online_quality - private_quality,
        })
    return {
        "schema_version": 1,
        "source_run": str(source_run),
        "source_baseline_sha256": sha256_file(baseline_path),
        "source_state_sha256": sha256_file(state_path),
        "selected": rows,
    }


def count_thinking(stream_path: Path) -> dict[str, int]:
    blocks = token_events = 0
    for line in stream_path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "system" and event.get("subtype") == "thinking_tokens":
            token_events += 1
        if event.get("type") == "assistant":
            for block in (event.get("message") or {}).get("content") or []:
                if block.get("type") in {"thinking", "redacted_thinking"}:
                    blocks += 1
    return {"blocks": blocks, "token_events": token_events}


def selected_tasks(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    by_id = {task["task_id"]: task for task in manifest["tasks"]}
    return [by_id[task_id] for task_id, _ in SELECTED]


def run_candidates(args: argparse.Namespace, pilot: Any) -> dict[str, Any]:
    manifest = pilot.load_manifest()
    selection = validate_selection(args.source_run, manifest)
    selection["created_at"] = pilot.utc_now()
    selection["claude_code_version"] = manifest["claude_code_version"]
    write_json(args.artifact_root / "selection.json", selection)
    real_claude = pilot.find_real_claude(manifest["claude_code_version"])
    attempts = []
    for task in selected_tasks(manifest):
        task_id = task["task_id"]
        final = args.artifact_root / "attempts/offline_ds_thinking" / task_id
        if (final / "attempt.json").is_file():
            attempt = read_json(final / "attempt.json")
        else:
            scratch = args.artifact_root / "scratch" / f"{task_id}-{secrets.token_hex(6)}"
            temporary = final.with_name(f".{task_id}-{secrets.token_hex(4)}.tmp")
            base_commit = pilot.prepare_workspace(pilot.checked_path(pilot.FIXTURE_ROOT, task["fixture"]), scratch)
            attempt = pilot.run_claude(
                treatment="offline_ds",
                prompt=pilot.task_prompt(task),
                cwd=scratch,
                timeout_seconds=int(manifest["task_timeout_seconds"]),
                toolchain=args.toolchain,
                real_claude=real_claude,
                expected_version=manifest["claude_code_version"],
                output_path=temporary / "stream.jsonl",
                with_tools=True,
                manifest=manifest,
            )
            visible = pilot.run_visible_tests(task, scratch, temporary, int(manifest["visible_test_timeout_seconds"]))
            hidden = pilot.run_hidden_grader(task, scratch, temporary, int(manifest["grade_timeout_seconds"]))
            patch = pilot.capture_patch(scratch)
            (temporary / "changes.patch").write_text(patch, encoding="utf-8")
            review_artifact = pilot.review_artifact(task, scratch, patch)
            (temporary / "review-artifact.txt").write_text(review_artifact, encoding="utf-8")
            thinking = count_thinking(temporary / "stream.jsonl")
            if thinking["blocks"] < 1:
                raise RuntimeError(f"Private DS thinking was not observed for {task_id}")
            attempt.update({
                "task_id": task_id,
                "title": task["title"],
                "category": task["category"],
                "selection_category": dict(SELECTED)[task_id],
                "base_commit": base_commit,
                "visible_tests": visible,
                "hidden_grader": hidden,
                "thinking": thinking,
                "task_status": "passed" if hidden["status"] == "passed" and attempt["agent_status"] == "completed" else "failed",
                "changed_files": pilot.changed_files(scratch),
                "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
                "review_artifact": review_artifact,
                "treatment": "offline_ds_thinking",
                "thinking_enabled": True,
            })
            write_json(temporary / "attempt.json", attempt)
            final.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temporary, final)
            shutil.rmtree(scratch, ignore_errors=True)
        attempts.append(attempt)
    receipt = {
        "schema_version": 1,
        "status": "completed",
        "completed_at": pilot.utc_now(),
        "attempt_count": len(attempts),
        "thinking_block_count": sum(item["thinking"]["blocks"] for item in attempts),
        "thinking_token_event_count": sum(item["thinking"]["token_events"] for item in attempts),
        "tasks": [item["task_id"] for item in attempts],
    }
    write_json(args.artifact_root / "candidate-receipt.json", receipt)
    return receipt


def old_attempts(source_run: Path) -> dict[tuple[str, str], dict[str, Any]]:
    state = read_json(source_run / "benchmark-state.json")
    return {(item["task_id"], item["treatment"]): item for item in state["attempts"]}


def deterministic_tier(pilot: Any, attempt: dict[str, Any]) -> float:
    return float(pilot.deterministic_tier(attempt["hidden_grader"], attempt["agent_status"]))


def run_judges(args: argparse.Namespace, pilot: Any) -> dict[str, Any]:
    manifest = pilot.load_manifest()
    old = old_attempts(args.source_run)
    results = []
    for task in selected_tasks(manifest):
        task_id = task["task_id"]
        thinking = read_json(args.artifact_root / "attempts/offline_ds_thinking" / task_id / "attempt.json")
        candidates = {
            "offline_ds_old": old[(task_id, "offline_ds")],
            "offline_ds_thinking": thinking,
            "online_ds": old[(task_id, "online_ds")],
        }
        mapping_path = args.artifact_root / "judges" / task_id / "mapping.json"
        if mapping_path.is_file():
            mapping = read_json(mapping_path)
        else:
            shuffled = list(TREATMENTS)
            secrets.SystemRandom().shuffle(shuffled)
            mapping = dict(zip(pilot.LETTERS, shuffled))
            write_json(mapping_path, mapping)
        choices = {label: candidates[treatment]["review_artifact"] for label, treatment in mapping.items()}
        judge_root = args.artifact_root / "judges" / task_id
        if (judge_root / "judge.json").is_file() and (judge_root / "judge-runtime.json").is_file():
            payload = pilot.validate_judge_payload(read_json(judge_root / "judge.json"))
            runtime = read_json(judge_root / "judge-runtime.json")
        else:
            judged = pilot.run_judge(task, choices, judge_root, manifest)
            payload, runtime = judged["payload"], judged["runtime"]
        scores = {}
        for treatment in TREATMENTS:
            label = next(key for key, value in mapping.items() if value == treatment)
            layer = pilot.score_mean(payload["candidates"][label])
            tier = deterministic_tier(pilot, candidates[treatment])
            scores[treatment] = {
                "deterministic_tier": tier,
                "judge_layer": layer,
                "quality": (tier + layer) / 2,
            }
        preferred = "tie" if payload["preference"] == "tie" else mapping[payload["preference"]]
        results.append({
            "task_id": task_id,
            "title": task["title"],
            "selection_category": dict(SELECTED)[task_id],
            "judge_mapping": mapping,
            "judge_preference": preferred,
            "judge_rationale": payload["rationale"],
            "scores": scores,
            "answers": {treatment: candidates[treatment]["review_artifact"] for treatment in TREATMENTS},
            "hidden": {treatment: candidates[treatment]["hidden_grader"] for treatment in TREATMENTS},
            "runtime": runtime,
            "thinking": thinking["thinking"],
        })
    aggregates = {
        treatment: sum(row["scores"][treatment]["quality"] for row in results) / len(results)
        for treatment in TREATMENTS
    }
    payload = {
        "schema_version": 1,
        "status": "completed",
        "completed_at": pilot.utc_now(),
        "source_run": str(args.source_run),
        "task_count": len(results),
        "judge_contract": {"model": pilot.JUDGE_MODEL, "reasoning_effort": pilot.JUDGE_EFFORT, "fallback_configured": False},
        "aggregates": aggregates,
        "tasks": results,
        "note": "The original Online DS and Private DS answers are reused. Only Private DS thinking-on was rerun. One sample per task; no statistical significance claim.",
    }
    write_json(args.artifact_root / "comparison.json", payload)
    render_html(payload, args.artifact_root / "report/index.html")
    receipt = {
        "schema_version": 1,
        "status": "completed",
        "task_count": len(results),
        "judge_count": len(results),
        "judge_model": pilot.JUDGE_MODEL,
        "reasoning_effort": pilot.JUDGE_EFFORT,
        "comparison_sha256": sha256_file(args.artifact_root / "comparison.json"),
        "report_sha256": sha256_file(args.artifact_root / "report/index.html"),
    }
    write_json(args.artifact_root / "judge-receipt.json", receipt)
    return receipt


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def render_html(payload: dict[str, Any], output: Path) -> None:
    summary = "".join(
        f"<tr><td>{esc(LABELS[t])}</td><td>{payload['aggregates'][t]:.3f}</td></tr>" for t in TREATMENTS
    )
    sections = []
    for index, row in enumerate(payload["tasks"], 1):
        columns = []
        for treatment in TREATMENTS:
            score = row["scores"][treatment]
            hidden = row["hidden"][treatment]
            thinking_note = ""
            if treatment == "offline_ds_thinking":
                thinking_note = f"<li>Thinking blocks: {row['thinking']['blocks']}</li>"
            columns.append(
                f"<article><h3>{esc(LABELS[treatment])}</h3><strong>{score['quality']:.3f} / 3</strong>"
                f"<ul><li>Deterministic: {score['deterministic_tier']:.1f}</li><li>GPT: {score['judge_layer']:.3f}</li>"
                f"<li>Hidden checks: {hidden['passed']}/{hidden['total']}</li>{thinking_note}</ul><pre>{esc(row['answers'][treatment])}</pre></article>"
            )
        preference = "Tie" if row["judge_preference"] == "tie" else LABELS[row["judge_preference"]]
        sections.append(
            f"<section><header><span>{index:02d}</span><div><small>{esc(row['selection_category'])}</small><h2>{esc(row['title'])}</h2></div></header>"
            f"<div class='answers'>{''.join(columns)}</div><aside><strong>GPT preference: {esc(preference)}</strong><p>{esc(row['judge_rationale'])}</p></aside></section>"
        )
    document = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Private DS Thinking 重测</title><style>
:root{{--bg:#f4f6f5;--surface:#fff;--line:#cad2ce;--ink:#17211c;--muted:#5b6961;--accent:#176a4b}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 Arial,"PingFang SC",sans-serif}}main{{max-width:1460px;margin:auto;padding:26px 22px 70px}}h1,h2,h3,p{{margin:0}}h1{{font-size:27px;font-weight:500}}h2{{font-size:18px}}h3{{font-size:14px}}small{{color:var(--muted)}}.intro{{display:flex;justify-content:space-between;gap:20px;align-items:end;padding-bottom:18px;border-bottom:2px solid var(--ink)}}.intro p{{max-width:760px;color:var(--muted)}}table{{width:100%;margin:24px 0;border-collapse:collapse;background:var(--surface)}}th,td{{padding:11px 14px;border:1px solid var(--line);text-align:left}}th{{background:#e9eeeb}}section{{padding:32px 0;border-top:1px solid var(--line)}}section>header{{display:flex;gap:12px;align-items:center;margin-bottom:14px}}section>header>span{{display:grid;place-items:center;width:34px;height:34px;background:var(--ink);color:#fff}}.answers{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));border:1px solid var(--line);background:var(--surface)}}article{{min-width:0;padding:15px}}article+article{{border-left:1px solid var(--line)}}article>strong{{display:block;margin-top:5px;color:var(--accent);font-size:18px}}ul{{padding-left:18px;color:var(--muted)}}pre{{max-height:520px;overflow:auto;margin:0;padding:12px;background:#202723;color:#f3f5f4;white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.5 ui-monospace,monospace}}aside{{padding:13px 15px;border:1px solid var(--line);border-top:0;background:#e9eeeb}}aside p{{margin-top:4px;color:var(--muted)}}@media(max-width:900px){{.answers{{grid-template-columns:1fr}}article+article{{border-left:0;border-top:1px solid var(--line)}}.intro{{display:block}}.intro p{{margin-top:8px}}}}@media(max-width:600px){{main{{padding:18px 12px 50px}}h1{{font-size:22px}}}}
</style></head><body><main><header class="intro"><div><small>Claude Code 2.1.207 · 5-task focused rerun</small><h1>Private DS Thinking 重测</h1></div><p>只重跑 Private DS thinking-on；原 Private DS 与 Online DS 回答来自冻结的 R3 结果。GPT 使用 gpt-5.6-sol/xhigh 对三份匿名答案重新盲评。</p></header><table><thead><tr><th>Treatment</th><th>5 题均分 / 3</th></tr></thead><tbody>{summary}</tbody></table>{''.join(sections)}<p><small>单次重测用于定位 thinking 影响，不构成统计显著性结论。</small></p></main></body></html>"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")


def validate_artifact(args: argparse.Namespace, pilot: Any) -> dict[str, Any]:
    selection = read_json(args.artifact_root / "selection.json")
    candidates = read_json(args.artifact_root / "candidate-receipt.json")
    comparison = read_json(args.artifact_root / "comparison.json")
    if len(selection["selected"]) != 5 or any(row["old_private_quality"] >= row["old_online_quality"] for row in selection["selected"]):
        raise RuntimeError("selection contract failed")
    if candidates["attempt_count"] != 5 or candidates["thinking_block_count"] < 5:
        raise RuntimeError("thinking evidence contract failed")
    if comparison["task_count"] != 5 or comparison["judge_contract"] != {"model": pilot.JUDGE_MODEL, "reasoning_effort": pilot.JUDGE_EFFORT, "fallback_configured": False}:
        raise RuntimeError("judge contract failed")
    for row in comparison["tasks"]:
        if set(row["scores"]) != set(TREATMENTS) or row["thinking"]["blocks"] < 1:
            raise RuntimeError(f"task result contract failed: {row['task_id']}")
    result = {"status": "passed", "task_count": 5, "thinking_block_count": candidates["thinking_block_count"], "judge_count": 5}
    write_json(args.artifact_root / "validation.json", result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--source-run", type=Path, default=DEFAULT_SOURCE_RUN)
    parser.add_argument("--toolchain", type=Path, default=DEFAULT_TOOLCHAIN)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--select", action="store_true")
    mode.add_argument("--run-candidates", action="store_true")
    mode.add_argument("--judge", action="store_true")
    mode.add_argument("--validate", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.artifact_root = args.artifact_root.resolve()
    args.source_run = args.source_run.resolve()
    args.toolchain = args.toolchain.resolve()
    pilot = load_pilot()
    if args.select:
        output = validate_selection(args.source_run, pilot.load_manifest())
        write_json(args.artifact_root / "selection.json", output)
    elif args.run_candidates:
        output = run_candidates(args, pilot)
    elif args.judge:
        output = run_judges(args, pilot)
    else:
        output = validate_artifact(args, pilot)
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
