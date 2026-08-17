#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any


def load(path: Path) -> Any:
    return json.loads(path.read_text())


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


def mean(values: list[float]) -> float:
    return statistics.fmean(values)


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def source_group(tag: str) -> str | None:
    for prefix in ("private-low", "private-high", "private-max", "online-low", "online-high", "online-max"):
        if tag.startswith(prefix):
            return prefix
    return None


def pro_group(tag: str) -> str:
    return next(value for value in ("low", "high", "max") if f"-{value}-" in tag)


def verified_private_group(tag: str) -> str:
    return next(value for value in ("high", "max") if f"-verified-{value}-" in tag)


def aggregate_runs(runs: list[dict], group_function) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = {}
    for run in runs:
        group = group_function(run["tag"])
        if group is not None:
            grouped.setdefault(group, []).append(run)
    result = {}
    for group, rows in grouped.items():
        scores = [float(row["macro_score"]) for row in rows]
        result[group] = {
            "runs": len(rows),
            "macro_score": mean(scores),
            "stdev": statistics.stdev(scores) if len(scores) > 1 else 0.0,
            "categories": {
                name: mean([float(row["categories"][name]["score"]) for row in rows])
                for name in ("sql", "python", "incident")
            },
        }
    return result


def raw_telemetry(paths: list[Path]) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = {}
    for path in paths:
        value = load(path)
        group = pro_group(value["tag"])
        grouped.setdefault(group, []).append(value)
    result = {}
    for group, rows in grouped.items():
        prompt = [sum(int(case.get("usage", {}).get("prompt_tokens", 0)) for case in row["cases"]) for row in rows]
        completion = [sum(int(case.get("usage", {}).get("completion_tokens", 0)) for case in row["cases"]) for row in rows]
        result[group] = {
            "prompt_tokens_mean": mean(prompt),
            "completion_tokens_mean": mean(completion),
            "errors": sum(case.get("finish_reason") == "error" for row in rows for case in row["cases"]),
            "empty_finals": sum(not (case.get("response") or "") for row in rows for case in row["cases"]),
            "length_truncations": sum(case.get("finish_reason") == "length" for row in rows for case in row["cases"]),
        }
        output = result[group]["completion_tokens_mean"]
        input_tokens = result[group]["prompt_tokens_mean"]
        result[group]["estimated_api_cost_usd"] = {
            "off_peak_all_input_cache_miss": (input_tokens * 0.66 + output * 1.98) / 1_000_000,
            "peak_all_input_cache_miss": (input_tokens * 1.32 + output * 3.96) / 1_000_000,
        }
    return result


def adjudicated_source_paths(path: Path, raw_dir: Path, group_function, groups: set[str]) -> dict[str, list[Path]]:
    result = {group: [] for group in groups}
    for run in load(path)["runs"]:
        group = group_function(run["tag"])
        if group in result:
            source = raw_dir / run["source_file"]
            if not source.is_file():
                raise RuntimeError(f"Missing benchmark source: {source}")
            result[group].append(source)
    if any(not paths for paths in result.values()):
        raise RuntimeError(f"Missing completed benchmark group in {path}")
    return result


def nearest_rank(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def full_suite_telemetry(paths: list[Path]) -> dict:
    runs = [load(path) for path in paths]
    cases = []
    concurrency = set()
    stream_modes = set()
    for run in runs:
        if run.get("status") != "passed" or len(run.get("cases") or []) != 18:
            raise RuntimeError(f"Full-suite telemetry requires a completed 18-case run: {run.get('tag')}")
        cases.extend(run["cases"])
        request_config = run.get("request_config") or {}
        concurrency.add(int(run.get("concurrency") or request_config.get("concurrency") or 1))
        stream_modes.add(bool(request_config.get("stream")))
    seconds = [float(case["seconds"]) for case in cases]
    completion_tokens = [int(case.get("usage", {}).get("completion_tokens", 0)) for case in cases]
    if any(value <= 0 for value in seconds):
        raise RuntimeError("Full-suite response times must be positive")
    total_seconds = sum(seconds)
    return {
        "runs": len(runs),
        "requests": len(cases),
        "concurrency_per_run": sorted(concurrency),
        "stream_modes": sorted(stream_modes),
        "mean_response_seconds": mean(seconds),
        "p95_response_seconds": nearest_rank(seconds, 0.95),
        "max_response_seconds": max(seconds),
        "total_completion_tokens": sum(completion_tokens),
        "effective_e2e_completion_tokens_per_second": sum(completion_tokens) / total_seconds,
        "ttft_seconds": None,
        "ttft_collection": "not_recorded_by_quality_harness",
    }


def route_ab_summary(portal_path: Path, direct_path: Path) -> dict:
    portal = load(portal_path)
    direct = load(direct_path)
    portal_cases = {case["id"]: case for case in portal["cases"]}
    direct_cases = {case["id"]: case for case in direct["cases"]}
    if set(portal_cases) != set(direct_cases) or len(portal_cases) != 18:
        raise RuntimeError("Private route A/B must contain the same 18 cases")

    def route_metrics(run: dict) -> dict:
        cases = run["cases"]
        return {
            "endpoint_label": run["base_url"],
            "macro_score": run["macro_score"],
            "categories": {name: run["categories"][name]["score"] for name in ("sql", "python", "incident")},
            "completed_finals": sum(case.get("finish_reason") == "stop" and bool(case.get("response")) for case in cases),
            "length_truncations": sum(case.get("finish_reason") == "length" for case in cases),
            "errors": sum(case.get("finish_reason") == "error" for case in cases),
            "completion_tokens": sum(int(case.get("usage", {}).get("completion_tokens", 0)) for case in cases),
            "max_case_seconds": max(float(case["seconds"]) for case in cases),
            "max_case_completion_tokens": max(int(case.get("usage", {}).get("completion_tokens", 0)) for case in cases),
        }

    rows = []
    for case_id in portal_cases:
        portal_case = portal_cases[case_id]
        direct_case = direct_cases[case_id]
        rows.append({
            "id": case_id,
            "portal_score": portal_case["score"],
            "direct_score": direct_case["score"],
            "finish_equal": portal_case.get("finish_reason") == direct_case.get("finish_reason"),
            "prompt_tokens_equal": portal_case.get("usage", {}).get("prompt_tokens") == direct_case.get("usage", {}).get("prompt_tokens"),
            "final_hash_equal": portal_case["response_evidence"]["sha256"] == direct_case["response_evidence"]["sha256"],
            "reasoning_hash_equal": portal_case["reasoning_evidence"]["sha256"] == direct_case["reasoning_evidence"]["sha256"],
        })
    return {
        "max_tokens": portal["max_tokens"],
        "reasoning_effort": portal["request_config"]["deepseek_effort"],
        "stream": portal["request_config"]["stream"],
        "portal_per_request_passthrough_override": portal["request_config"]["force_reasoning_effort_passthrough"],
        "concurrency_per_route": portal["request_config"]["concurrency"],
        "runs_per_route": 1,
        "portal": route_metrics(portal),
        "direct_vllm": route_metrics(direct),
        "agreement": {
            "cases": len(rows),
            "finish_reason": sum(row["finish_equal"] for row in rows),
            "prompt_tokens": sum(row["prompt_tokens_equal"] for row in rows),
            "executable_score": sum(row["portal_score"] == row["direct_score"] for row in rows),
            "final_sha256": sum(row["final_hash_equal"] for row in rows),
            "reasoning_sha256": sum(row["reasoning_hash_equal"] for row in rows),
            "score_differences": [row for row in rows if row["portal_score"] != row["direct_score"]],
        },
    }


def incident_validation_summary(path: Path, prior_score: float) -> dict:
    run = load(path)
    cases = run.get("cases") or []
    request_config = run.get("request_config") or {}
    if (
        run.get("status") != "passed"
        or run.get("category_filter") != "incident"
        or len(cases) != 6
        or run.get("max_tokens") != 393216
        or request_config.get("deepseek_effort") != "max"
        or request_config.get("force_reasoning_effort_passthrough") is not False
        or request_config.get("stream") is not True
    ):
        raise RuntimeError("Private Max incident validation contract is incomplete")
    if any(case.get("finish_reason") != "stop" or not case.get("response") for case in cases):
        raise RuntimeError("Private Max incident validation must contain six completed finals")
    performance = run.get("performance") or {}
    if performance.get("ttft_available_requests") != 6:
        raise RuntimeError("Private Max incident validation must contain TTFT for all cases")
    score = float(run["categories"]["incident"]["score"])
    return {
        "route": "portal-lan-edge-to-litellm-to-wireguard-to-vllm",
        "public_ingress_included": False,
        "public_ingress_exclusion_reason": "public domain resolved to an address refusing TCP 443 during the rerun",
        "runs": 1,
        "requests": len(cases),
        "max_tokens": run["max_tokens"],
        "concurrency": run["concurrency"],
        "stream": request_config["stream"],
        "reasoning_effort": request_config["deepseek_effort"],
        "per_request_passthrough_override": request_config["force_reasoning_effort_passthrough"],
        "score": score,
        "prior_full_suite_incident_score": prior_score,
        "two_observation_mean_score": mean([prior_score, score]),
        "root_cause_correct": sum(bool(case["detail"]["cause"]) for case in cases),
        "exact_action_pair_correct": sum(case["score"] == 1.0 for case in cases),
        "completed_finals": sum(case.get("finish_reason") == "stop" and bool(case.get("response")) for case in cases),
        "length_truncations": sum(case.get("finish_reason") == "length" for case in cases),
        "errors": sum(case.get("finish_reason") == "error" for case in cases),
        "performance": performance,
        "cases": [
            {
                "id": case["id"],
                "score": case["score"],
                "root_cause_correct": bool(case["detail"]["cause"]),
                "correct_actions": case["detail"]["correct_actions"],
                "wrong_actions": case["detail"]["wrong_actions"],
                "ttft_seconds": case["ttft_seconds"],
                "response_seconds": case["response_seconds"],
                "decode_tokens_per_second": case["decode_tokens_per_second"],
                "effective_e2e_completion_tokens_per_second": case["effective_e2e_completion_tokens_per_second"],
                "completion_tokens": case["usage"]["completion_tokens"],
                "reasoning_tokens": case["usage"].get("completion_tokens_details", {}).get("reasoning_tokens"),
                "finish_reason": case["finish_reason"],
            }
            for case in cases
        ],
    }


def sanitize_agent(path: Path) -> dict:
    value = load(path)
    tasks = []
    for row in value["tasks"]:
        if "hidden_grader" not in row:
            tasks.append(dict(row))
            continue
        tasks.append(
            {
                "task_id": row["task_id"],
                "status": row["task_status"],
                "agent_status": row["agent_status"],
                "hidden_passed": row["hidden_grader"]["passed"],
                "hidden_total": row["hidden_grader"]["total"],
                "thinking_blocks": row["thinking_blocks"],
                "elapsed_seconds": row["elapsed_seconds"],
                "historical_online_flash_status": row["source_status"]["online_ds"],
                "historical_private_flash_status": row["source_status"]["offline_ds"],
            }
        )
    return {
        "model": value["model"],
        "reasoning_effort": value["reasoning_effort"],
        "claude_code_version": value["claude_code_version"],
        "parallelism": value["parallelism"],
        "passed": value["passed"],
        "task_count": value["task_count"],
        "thinking_block_count": value["thinking_block_count"],
        "tasks": tasks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--agent-result", type=Path, required=True)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    project = root / "deepseek-v4-dgx-spark"
    existing_path = root / "model-benchmark-qwen-deepseek/data/lakehouse-parameter-matrix-adjudicated.json"
    pro_path = project / "data/online-pro-matrix-adjudicated.json"
    pro_raw_paths = sorted((project / "data/online-pro-matrix").glob("online-pro-*.json"))
    existing = aggregate_runs(load(existing_path)["runs"], source_group)
    verified_path = root / "model-benchmark-qwen-deepseek/data/lakehouse-private-effort-verified-adjudicated.json"
    verified_private = aggregate_runs(load(verified_path)["runs"], verified_private_group)
    if set(verified_private) != {"high"} or verified_private["high"]["runs"] != 2:
        raise RuntimeError("verified private High matrix must contain two completed runs")
    route_ab_dir = root / "model-benchmark-qwen-deepseek/data/lakehouse-private-route-ab-384k"
    route_ab_portal_path = route_ab_dir / "portal-fixed-max-384k-r1.json"
    route_ab_direct_path = route_ab_dir / "direct-vllm-max-384k-r1.json"
    route_ab = route_ab_summary(route_ab_portal_path, route_ab_direct_path)
    incident_validation_path = route_ab_dir / "portal-fixed-max-384k-incident-r1.json"
    incident_validation = incident_validation_summary(
        incident_validation_path,
        float(route_ab["portal"]["categories"]["incident"]),
    )
    private_quality = dict(verified_private)
    private_quality["max"] = {
        "runs": 1,
        "macro_score": route_ab["portal"]["macro_score"],
        "stdev": None,
        "categories": route_ab["portal"]["categories"],
        "max_tokens": route_ab["max_tokens"],
        "completed_finals": route_ab["portal"]["completed_finals"],
        "length_truncations": route_ab["portal"]["length_truncations"],
        "errors": route_ab["portal"]["errors"],
    }
    pro = aggregate_runs(load(pro_path)["runs"], pro_group)
    telemetry = raw_telemetry(pro_raw_paths)
    existing_sources = adjudicated_source_paths(
        existing_path,
        existing_path.parent / "lakehouse-parameter-matrix",
        source_group,
        {"online-low", "online-high", "online-max"},
    )
    verified_sources = adjudicated_source_paths(
        verified_path,
        verified_path.parent / "lakehouse-private-effort-verified",
        verified_private_group,
        {"high"},
    )
    pro_sources = adjudicated_source_paths(pro_path, project / "data/online-pro-matrix", pro_group, {"low", "high", "max"})
    full_suite = {
        "private-high": full_suite_telemetry(verified_sources["high"]),
        "private-max": full_suite_telemetry([route_ab_portal_path]),
        "private-max-direct-vllm": full_suite_telemetry([route_ab_direct_path]),
        "online-flash-low": full_suite_telemetry(existing_sources["online-low"]),
        "online-flash-high": full_suite_telemetry(existing_sources["online-high"]),
        "online-flash-max": full_suite_telemetry(existing_sources["online-max"]),
        "online-pro-low": full_suite_telemetry(pro_sources["low"]),
        "online-pro-high": full_suite_telemetry(pro_sources["high"]),
        "online-pro-max": full_suite_telemetry(pro_sources["max"]),
    }
    agent_raw_path = args.agent_result.resolve()
    agent_raw_sha256 = sha256(agent_raw_path)
    agent = sanitize_agent(agent_raw_path)
    agent_path = project / "data/online-pro-agent-focus-20260817.json"
    agent_path.write_text(json.dumps(normalize(agent), indent=2, ensure_ascii=False) + "\n")

    latency_paths = {
        "private-high": root / "model-benchmark-qwen-deepseek/data/inference-performance/private-ds-high.json",
        "private-max": root / "model-benchmark-qwen-deepseek/data/inference-performance/private-ds-max.json",
        "online-flash-low": root / "model-benchmark-qwen-deepseek/data/inference-performance/online-ds-low.json",
        "online-pro-low": project / "data/online-pro-matrix/latency/online-pro-low.json",
        "online-pro-high": project / "data/online-pro-matrix/latency/online-pro-high.json",
        "online-pro-max": project / "data/online-pro-matrix/latency/online-pro-max.json",
    }
    latency = {}
    for name, path in latency_paths.items():
        summary = load(path)["summary"]
        latency[name] = {
            "ttft_seconds": summary["ttft_seconds"]["mean"],
            "response_seconds": summary["response_seconds"]["mean"],
            "decode_tokens_per_second": summary["decode_tokens_per_second"]["mean"],
            "completion_tokens": summary["completion_tokens_mean"],
        }

    summary = {
        "schema_version": 1,
        "status": "passed",
        "benchmark_date": "2026-08-17",
        "scope": "completed-result benchmark; Private High n=2, Private Max 384K full-suite n=1 plus one six-case incident rerun, online quality n=2, and five focused agent tasks",
        "quality": {
            "private_flash": private_quality,
            "online_flash": {key.removeprefix("online-"): value for key, value in existing.items() if key.startswith("online-")},
            "online_pro": pro,
        },
        "private_route_ab_384k": route_ab,
        "private_max_incident_validation": incident_validation,
        "online_pro_telemetry": telemetry,
        "full_suite_performance": {
            "task_count_per_run": 18,
            "ttft_available": False,
            "response_time_definition": "request dispatch to complete response",
            "effective_token_rate_definition": "sum(completion_tokens) / sum(response_seconds); not decode TPS",
            "comparison_limit": "quality runs used mixed stream modes and execution schedules; descriptive telemetry only",
            "treatments": full_suite,
        },
        "latency": latency,
        "agent_focus": agent,
        "agent_focus_provenance": {
            "raw_input_sha256": agent_raw_sha256,
            "raw_input_committed": False,
            "sanitizer": "sanitize_agent:v1",
            "qualification": "committed agent evidence is a sanitized derivative; raw sandbox artifacts are not published",
        },
        "private_route": {
            "direct_vllm": False,
            "endpoint_label": "private-llm-portal",
            "path": [
                "benchmark-client",
                "synology-reverse-proxy",
                "llm-portal-edge",
                "litellm-compat",
                "wireguard",
                "private-vllm",
            ],
            "latency_scope": "client-to-portal-to-vllm end-to-end",
            "verification": {
                "legacy_quality_requests_in_portal_access_log": 108,
                "legacy_latency_requests_in_portal_access_log": 4,
                "verified_high_quality_requests": 36,
                "verified_max_384k_quality_requests": 18,
                "verified_max_384k_incident_requests": incident_validation["requests"],
                "direct_vllm_max_384k_quality_requests": 18,
                "verified_high_max_latency_requests": 8,
                "latency_request_contract": "one warmup plus three measured requests",
            },
        },
        "private_effort_contract": {
            "portal_requires_allowed_openai_params": False,
            "portal_fix_verified_without_per_request_override": True,
            "legacy_requested_efforts_effective_effort": "high",
            "legacy_reason": "LiteLLM drop_params removed reasoning_effort for the generic OpenAI-compatible deployment",
            "verified_quality_configurations": {
                "high": {"max_tokens": 32768, "runs": 2, "completed_finals": 36},
                "max": {
                    "max_tokens": route_ab["max_tokens"],
                    "runs": 1,
                    "completed_finals": route_ab["portal"]["completed_finals"],
                    "length_truncations": route_ab["portal"]["length_truncations"],
                    "errors": route_ab["portal"]["errors"],
                },
            },
            "direct_tokenize_probe": {
                "high_prompt_tokens": 11,
                "max_prompt_tokens": 90,
                "high_token_sha256": "90e0facd84ffde0e1e47dbd7be797e53a0484f95254dcfe9fa513b7c2e047649",
                "max_token_sha256": "95763d174402e9db0be89de0dcbab745d838f4cc3fc382ad6a99b5e03f1201b8",
            },
        },
        "source_sha256": {
            "existing_adjudication": sha256(existing_path),
            "pro_adjudication": sha256(pro_path),
            "agent_evidence": sha256(agent_path),
            "verified_private_adjudication": sha256(verified_path),
            "route_ab_portal": sha256(route_ab_portal_path),
            "route_ab_direct_vllm": sha256(route_ab_direct_path),
            "private_max_incident_validation": sha256(incident_validation_path),
        },
    }
    summary_path = project / "data/deepseek-private-online-comparison-20260817.json"
    write = json.dumps(normalize(summary), indent=2, ensure_ascii=False) + "\n"
    summary_path.write_text(write)

    quality_rows = []
    labels = [
        ("private-high", "Private Flash high / 32K", verified_private["high"]),
        ("private-max", "Private Flash max / 384K", private_quality["max"]),
        ("online-low", "Online Flash low / 32K", existing["online-low"]),
        ("online-high", "Online Flash high / 256K", existing["online-high"]),
        ("online-max", "Online Flash max / 384K", existing["online-max"]),
        ("pro-low", "Online Pro low / 32K", pro["low"]),
        ("pro-high", "Online Pro high / 256K", pro["high"]),
        ("pro-max", "Online Pro max / 384K", pro["max"]),
    ]
    for _key, label, row in labels:
        stdev = f"{row['stdev'] * 100:.1f}pp" if row["stdev"] is not None else "N/A"
        quality_rows.append(
            f"| {label} | {pct(row['macro_score'])} | {pct(row['categories']['sql'])} | "
            f"{pct(row['categories']['python'])} | {pct(row['categories']['incident'])} | {row['runs']} | {stdev} |"
        )
    latency_rows = []
    for name, label in (
        ("private-high", "Private Flash high"),
        ("private-max", "Private Flash max"),
        ("online-flash-low", "Online Flash low"),
        ("online-pro-low", "Online Pro low"),
        ("online-pro-high", "Online Pro high"),
        ("online-pro-max", "Online Pro max"),
    ):
        row = latency[name]
        latency_rows.append(
            f"| {label} | {row['ttft_seconds']:.3f}s | {row['response_seconds']:.3f}s | "
            f"{row['decode_tokens_per_second']:.1f} | {row['completion_tokens']:.0f} |"
        )
    full_suite_rows = []
    for name, label in (
        ("private-high", "Private Flash high / 32K"),
        ("private-max", "Private Flash max / 384K · Portal"),
        ("private-max-direct-vllm", "Private Flash max / 384K · Direct vLLM"),
        ("online-flash-low", "Online Flash low / 32K"),
        ("online-flash-high", "Online Flash high / 256K"),
        ("online-flash-max", "Online Flash max / 384K"),
        ("online-pro-low", "Online Pro low / 32K"),
        ("online-pro-high", "Online Pro high / 256K"),
        ("online-pro-max", "Online Pro max / 384K"),
    ):
        row = full_suite[name]
        concurrency = "/".join(str(value) for value in row["concurrency_per_run"])
        full_suite_rows.append(
            f"| {label} | {row['requests']} | {concurrency} | {row['mean_response_seconds']:.1f}s | "
            f"{row['p95_response_seconds']:.1f}s | {row['max_response_seconds']:.1f}s | "
            f"{row['effective_e2e_completion_tokens_per_second']:.1f} | 未采集 |"
        )
    incident_rows = []
    for row in incident_validation["cases"]:
        incident_rows.append(
            f"| `{row['id']}` | {pct(row['score'])} | {'是' if row['root_cause_correct'] else '否'} | "
            f"{row['correct_actions']}/2 | {row['ttft_seconds']:.3f}s | {row['response_seconds']:.3f}s | "
            f"{row['decode_tokens_per_second']:.1f} | "
            f"{row['effective_e2e_completion_tokens_per_second']:.1f} | {row['completion_tokens']} |"
        )
    agent_rows = []
    for row in agent["tasks"]:
        agent_rows.append(
            f"| `{row['task_id']}` | {row['hidden_passed']}/{row['hidden_total']} | "
            f"{row['historical_online_flash_status']} | {row['historical_private_flash_status']} |"
        )
    cost_rows = []
    for effort in ("low", "high", "max"):
        row = telemetry[effort]
        cost = row["estimated_api_cost_usd"]
        cost_rows.append(
            f"| {effort} | {row['completion_tokens_mean'] / 1000:.1f}K | "
            f"${cost['off_peak_all_input_cache_miss']:.3f} | ${cost['peak_all_input_cache_miss']:.3f} |"
        )

    report = f"""# DeepSeek Private / Online 性能与精度边界（2026-08-17）

## 结论

- **双 GB10 private Flash 适合作为默认私有工程推理线路。** 在 18 道可执行湖仓题上，
  经 Portal 显式透传的 private high 平均 {pct(verified_private['high']['macro_score'])}，与 online Flash high 的
  {pct(existing['online-high']['macro_score'])} 接近；本轮通过 LLM Portal 转发至 private vLLM，
  客户端观测的端到端 TTFT 也明显更低。
- **需要最高成功率时升级到 online Pro high。** Pro high 平均
  {pct(pro['high']['macro_score'])}，比 private high 高
  {(pro['high']['macro_score'] - verified_private['high']['macro_score']) * 100:.1f}pp；本轮一轮 18/18，
  另一轮 {pct(pro['high']['macro_score'] * 2 - 1)}，没有空 final、截断或 HTTP 错误。
- **不要把 max 设为默认。** Pro max 平均 {pct(pro['max']['macro_score'])}，没有超过 high，
  平均输出 {telemetry['max']['completion_tokens_mean'] / 1000:.1f}K token，约为 low 的
  {telemetry['max']['completion_tokens_mean'] / telemetry['low']['completion_tokens_mean']:.1f} 倍，并出现分钟级尾延迟。
- **旧 Private max 质量分数无效。** LLM Portal 当时静默丢弃 `reasoning_effort`，所以旧
  87.5% 只是 effective-high 的重复波动，不是 Max 结果。Issue #46 修复后，无 per-request
  override 的 Portal Max 探针已与 direct vLLM 的 prompt usage、reasoning 和 final 哈希完全一致。
- **把 Private Max 上限提高到 384K 后，截断消失但尾延迟极高。** 修复后的 Portal 为
  {pct(route_ab['portal']['macro_score'])}，direct vLLM 为 {pct(route_ab['direct_vllm']['macro_score'])}；
  两边均 18/18 final、0 截断、0 错误，16/18 题可执行分一致。Portal 最慢题耗时
  {route_ab['portal']['max_case_seconds'] / 60:.1f} 分钟、输出 {route_ab['portal']['max_case_completion_tokens'] / 1000:.1f}K tokens，
  因此 384K 是能力验证配置，不适合作为默认产品预算。
- **Private Max 的故障低分不是稳定退化。** 完整 18 题轮的故障分为
  {pct(incident_validation['prior_full_suite_incident_score'])}，同配置 6 题专项复测为
  {pct(incident_validation['score'])}，两次观测均值 {pct(incident_validation['two_observation_mean_score'])}。
  两轮根因均 6/6 正确，失分来自精确 action-code 组合的采样波动。
- **Pro 不保证 Agent 工作流单调更好。** 在一个刻意聚焦历史 private 弱项的 5 题集合中，
  Pro high 只完整通过 1/5；历史 online Flash 为 4/5，private Flash 为 2/5。该集合有选择偏差，
  只能说明升级前仍需按真实 Agent workflow 验证。

## 精度

下表只保留已完整完成且 effort 契约已验证的处理组。Private High 与 online 各 effort 为 n=2；
Private Max 384K 为 n=1。Private 与 Pro 使用 v2 harness 的完整 18 题；Online Flash 保留 PR 32
的 v1 裁决结果。分数以可执行 grader 为主，不使用模型自评。

| 处理组 | 宏平均 | SQL | Python | 故障诊断 | 运行次数 | 标准差 |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(quality_rows)}

旧矩阵请求了 Private low/high/max，但 LiteLLM 将该 deployment 识别为 generic OpenAI-compatible，
`reasoning_effort` 不在支持参数列表且全局 `drop_params=true`，所以三组实际均为 vLLM 默认 High。
三组共六轮的宏平均为 87.0%，范围 80.6%–94.4%；108 个请求全部 `finish_reason=stop`，实际输出
远低于 32K/256K/384K 上限。因此旧 83.3%/90.3%/87.5% 差异既不是 Max 效果，也不是截断造成，
只能视为重复波动。

旧矩阵只用于解释历史契约错误，不进入上表或机器可读 `quality`。当前 Private 的正式质量配置
只有 High/32K（n=2）和 Max/384K（n=1），两者均为 18/18 完整 final。

## Private Max 384K 与路由一致性

Portal 修复后，不带 per-request `allowed_openai_params` override 的 Max 探针与 direct vLLM 均为
87 prompt tokens、10 completion tokens，reasoning/final SHA-1 完全一致。随后以 SSE、相同 18 题、
seed 42、`max_tokens=393216`，Portal 与 SSH tunnel direct vLLM 各并发 2 做一轮配对 A/B。

| 384K True Max 指标 | Portal | Direct vLLM |
|---|---:|---:|
| 可执行宏平均 | {pct(route_ab['portal']['macro_score'])} | {pct(route_ab['direct_vllm']['macro_score'])} |
| SQL / Python / 故障 | {pct(route_ab['portal']['categories']['sql'])} / {pct(route_ab['portal']['categories']['python'])} / {pct(route_ab['portal']['categories']['incident'])} | {pct(route_ab['direct_vllm']['categories']['sql'])} / {pct(route_ab['direct_vllm']['categories']['python'])} / {pct(route_ab['direct_vllm']['categories']['incident'])} |
| final / 截断 / 错误 | {route_ab['portal']['completed_finals']}/18 / {route_ab['portal']['length_truncations']} / {route_ab['portal']['errors']} | {route_ab['direct_vllm']['completed_finals']}/18 / {route_ab['direct_vllm']['length_truncations']} / {route_ab['direct_vllm']['errors']} |
| 总 completion tokens | {route_ab['portal']['completion_tokens'] / 1000:.1f}K | {route_ab['direct_vllm']['completion_tokens'] / 1000:.1f}K |
| 最慢单题 | {route_ab['portal']['max_case_seconds'] / 60:.1f} 分钟 / {route_ab['portal']['max_case_completion_tokens'] / 1000:.1f}K tokens | {route_ab['direct_vllm']['max_case_seconds'] / 60:.1f} 分钟 / {route_ab['direct_vllm']['max_case_completion_tokens'] / 1000:.1f}K tokens |

逐题 finish reason 与 prompt token 数均为 18/18 一致，可执行分 16/18 一致；final 与 reasoning
文本哈希均为 0/18 一致。结论是 **Portal 路由语义已经与 direct vLLM 对齐**，2.8pp 分差来自
True Max 单轮采样波动，不能解释为 Portal 改写答案。该 A/B 每条路径 n=1，不声明统计显著性。

## Private Max 故障专项复测

只重跑 6 个故障诊断 case，一轮、并发 2、SSE、`max_tokens=393216`，不带 per-request
`allowed_openai_params` override。公网域名当时解析到拒绝 TCP 443 的入口，因此本轮通过 LAN
直达同一个 LLM Portal edge，再经 LiteLLM、WireGuard 到 private vLLM；本轮时序不包含公网/NAS
入口，但模型、Portal 参数处理和后端均未绕过。

- 专项得分 {pct(incident_validation['score'])}（5/6），上一完整轮为
  {pct(incident_validation['prior_full_suite_incident_score'])}（4/6），两次故障观测均值
  {pct(incident_validation['two_observation_mean_score'])}。
- 两轮 root cause 都是 6/6 正确。本轮唯一失分题 `spark_shuffle_skew` 选对根因和一个动作，
  但第二动作选择 `repartition_by_distribution`，没有命中 rubric 指定的 `adaptive_skew_join`。
- 6/6 final、0 截断、0 错误；TTFT 平均
  {incident_validation['performance']['ttft_seconds']['mean']:.3f}s，P95
  {incident_validation['performance']['ttft_seconds']['p95']:.3f}s；response 平均
  {incident_validation['performance']['response_seconds']['mean']:.3f}s，P95
  {incident_validation['performance']['response_seconds']['p95']:.3f}s；平均 decode
  {incident_validation['performance']['decode_tokens_per_second']['mean']:.1f} tok/s，有效 E2E
  {incident_validation['performance']['effective_e2e_completion_tokens_per_second']:.1f} tok/s。

| 故障 case | 得分 | 根因正确 | 正确动作 | TTFT | response | decode tok/s | E2E tok/s | completion |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(incident_rows)}

因此主质量表继续保留完整 18 题轮的 83.3%，不把专项结果拼接成虚假的第二轮宏平均；但边界结论应按
两次故障观测理解：Private Max 没有稳定低于 High，动作代码的精确选择仍有波动。

## 18 题完整工作负载性能

质量 harness 为每题保存了从请求发出到完整响应结束的 wall time 和 completion tokens，但没有保存
首个 SSE delta 的时间戳；Private High 当时还是非流式请求。因此下表的 TTFT 无法事后恢复，
“有效 E2E tok/s”定义为 `sum(completion_tokens) / sum(response_seconds)`，不是扣除 TTFT 后的 decode TPS。

| 处理组 | 请求数 | 每轮并发 | 平均 response | P95 response | 最大 response | 有效 E2E tok/s | TTFT |
|---|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(full_suite_rows)}

这些是实际 18 题运行的描述性 telemetry，但各矩阵的 stream mode、执行时段和并行调度不完全相同，
不能当作严格的跨服务吞吐 A/B。下面的独立短请求实验才提供同一测量定义下的 TTFT 和 decode TPS。

## 短请求性能

每组 1 次预热、3 次串行 SSE 测量。Private 测量路径是 benchmark client → Synology 反向代理
→ LLM Portal edge/LiteLLM/compat → WireGuard → private vLLM，不是客户端直连 vLLM。
TTFT 是客户端收到首个 reasoning/content delta 的端到端时间；TPS 为 API
completion tokens 除以 TTFT 后生成时间。不同 effort 生成长度不同，因此响应时间不是固定
token 数吞吐 A/B。

| 处理组 | TTFT | 端到端 | 解码 tok/s | 平均输出 tokens |
|---|---:|---:|---:|---:|
{chr(10).join(latency_rows)}

Private high 经 LLM Portal 的端到端 TTFT 为 {latency['private-high']['ttft_seconds']:.3f}s，
True Max 为 {latency['private-max']['ttft_seconds']:.3f}s。两组都固定 `max_tokens=2048`，因此
差异来自 effort 与运行波动，不是输出上限。它们适合用于交互路径判断，但不能解释为裸 vLLM engine latency；
online Pro high 在本题上的端到端时间为 {latency['online-pro-high']['response_seconds']:.3f}s，
与 private high 的 {latency['private-high']['response_seconds']:.3f}s 接近，但其网络、调度和硬件
不可控。Pro 质量矩阵为缩短总时长采用并发执行，其中 `total_seconds` 不用于性能比较。

## Pro Token 与费用

以下为每轮 18 题的均值。费用按官方 Pro 单价估算，并保守地把全部输入视为 cache miss；
实际账单以服务端计费为准。

| Pro effort | 平均输出 tokens | 非高峰估算 | 高峰估算 |
|---|---:|---:|---:|
{chr(10).join(cost_rows)}

## Agent 聚焦题

Claude Code 2.1.207、Pro high、5 个并行隔离 Git sandbox；共观察到
{agent['thinking_block_count']} 个 thinking block。此集合专门选择历史 private 较弱或有差异的题，
不代表总体任务分布；并行耗时也不与历史顺序运行比较。

| 任务 | Pro high hidden checks | 历史 Online Flash | 历史 Private Flash |
|---|---:|---:|---:|
{chr(10).join(agent_rows)}

## 适用边界

| 场景 | 建议 |
|---|---|
| 私密代码、内网数据、稳定日常 SQL/Python/故障诊断 | private Flash high |
| Private max | 384K 为 18/18 final，但单题最长 {route_ab['portal']['max_case_seconds'] / 60:.1f} 分钟，仅按请求启用 |
| 简单低延迟请求且允许出网 | online Flash low |
| 复杂任务、private 首次失败、需要更高一次成功率 | online Pro high |
| 极难任务且能接受分钟级尾延迟和约 3 倍 low token | Pro max，仅按请求启用 |
| 终端脚本、长文约束、复杂 Agent 工具链 | 先跑工作流级验收，不按模型名直接升级 |

## 测试覆盖矩阵

| 维度 | 本轮纳入 | 未覆盖 | 状态 |
|---|---|---|---|
| 可执行精度 | Private High 32K；True Max 384K Portal/direct；Max 故障专项复测；Online Flash/Pro | Private Max 完整 18 题与 route A/B 仍仅 n=1 | 主要边界完整 |
| SSE 性能 | Private Max 故障 6 题逐题指标；短请求 Private high/max、Online Flash low、Online Pro | 其余完整质量轮未采集 TTFT | 采集边界已标明 |
| Token 与 API 成本 | Online Pro low/high/max | Private 无 API 账单；Flash 未统一计价 | 范围内完整 |
| Agent 聚焦任务 | Online Pro high；Online/Private 历史基线 | 不是九组 effort 全矩阵 | 部分 |

Private 还承担部署运维边界：两台 GB10 必须同时在线，当前 TP=2、最大并发序列 6；online
服务则引入数据出境、动态 alias、网络和供应商调度风险。两类线路应保留自动回退策略，不能
只看本轮宏平均。

## 方法与证据

- Online Flash alias：`deepseek-v4-flash` → `DeepSeek-V4-Flash-0731`。
- Online Pro alias：`deepseek-v4-pro` → `DeepSeek-V4-Pro-0813`。
- Private 请求经 LLM Portal 转发，不是客户端直连 vLLM。Portal access log 记录旧质量矩阵
  108 次请求和旧性能 4 次请求；正式完成配置另有 High 32K 质量 36 次、Max 384K Portal/direct
  各 18 次、Max 故障专项 6 次、High/Max 性能 8 次请求。
- LiteLLM 官方文档说明 `drop_params=true` 会丢弃不支持参数，`allowed_openai_params` 可显式透传；
  旧 Portal deployment 因此丢弃 `reasoning_effort`。Issue #46 修复后，不带 per-request override 的
  Portal/direct Max 探针 prompt usage 与输出哈希一致。
- 修正后 Private High/Max 性能均为 client → Portal → vLLM 的端到端指标，不是裸引擎延迟。
- 官方上下文 1M、最大输出 384K、effort 为 low/high/max；默认 high。
- Pro 六个质量 treatment 共 108 请求，0 HTTP/网络错误、0 空 final、0 length 截断。
- Private 384K route A/B 共 36 请求，Portal/direct 均 18/18 stop、0 截断、0 错误；逐题 score
  16/18 一致。Portal 最长请求 3031 秒，证明修复后的 SSE 路径跨过旧 600 秒网关边界。
- Private Max 故障专项复测通过 Portal LAN edge，6/6 root cause 正确、5/6 精确动作组合；公网
  入口当时拒绝 TCP 443，所以该轮 TTFT/response 不包含公网或 Synology 入口延迟。
- Agent 聚焦题的脱敏逐题证据见 `data/online-pro-agent-focus-20260817.json`；原始 sandbox、
  stream 和绝对路径不提交。
- Pro Python 原始评分时固定 sandbox 镜像不可用；保存的完整 final 随后在不可变 ECR Python
  digest 中重新执行。原始 JSON 未覆盖，裁决见
  `data/online-pro-matrix-adjudicated.json`。
- 本报告是快速决策 benchmark：Private Max 384K 完整轮、route A/B、故障专项和 Agent 每题 n=1，
  其余质量组 n=2，不宣称统计显著性。

官方资料：[Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode)、
[Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing)、
[V4 Pro GA](https://api-docs.deepseek.com/news/news260813)、
[LiteLLM Drop Unsupported Params](https://docs.litellm.ai/docs/completion/drop_params)。Portal 参数静默丢弃已记录在
[LLM-Portal #46](https://github.com/shiliai/LLM-Portal/issues/46)。机器可读汇总见
[`data/deepseek-private-online-comparison-20260817.json`](data/deepseek-private-online-comparison-20260817.json)。
"""
    (project / "BENCHMARK-COMPARISON-20260817.md").write_text(report)
    print(json.dumps({"report": str(project / "BENCHMARK-COMPARISON-20260817.md"), "summary": str(summary_path), "agent": str(agent_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
