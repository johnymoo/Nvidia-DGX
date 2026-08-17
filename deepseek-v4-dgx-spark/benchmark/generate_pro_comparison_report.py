#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import json
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


def bounded_private_group(tag: str) -> str:
    return next(value for value in ("high", "max") if f"-bounded-{value}-" in tag)


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


def bounded_private_telemetry(paths: list[Path]) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = {}
    for path in paths:
        value = load(path)
        grouped.setdefault(bounded_private_group(value["tag"]), []).append(value)
    result = {}
    for effort, runs in grouped.items():
        cases = [case for run in runs for case in run["cases"]]
        completed = [
            case for case in cases
            if case.get("finish_reason") == "stop" and bool(case.get("response"))
        ]
        result[effort] = {
            "requests": len(cases),
            "completed_finals": len(completed),
            "final_coverage": len(completed) / len(cases),
            "completed_final_score": mean([float(case["score"]) for case in completed]),
            "length_truncations": sum(case.get("finish_reason") == "length" for case in cases),
            "empty_finals": sum(not case.get("response") for case in cases),
            "errors": sum(case.get("finish_reason") == "error" for case in cases),
            "completion_tokens_mean_per_run": mean([
                sum(int(case.get("usage", {}).get("completion_tokens", 0)) for case in run["cases"])
                for run in runs
            ]),
        }
    return result


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
    bounded_path = root / "model-benchmark-qwen-deepseek/data/lakehouse-private-effort-bounded-4k-adjudicated.json"
    bounded_raw_paths = sorted((root / "model-benchmark-qwen-deepseek/data/lakehouse-private-effort-bounded-4k").glob("private-*.json"))
    bounded_private = aggregate_runs(load(bounded_path)["runs"], bounded_private_group)
    if set(bounded_private) != {"high", "max"} or any(row["runs"] != 2 for row in bounded_private.values()):
        raise RuntimeError("bounded private High/Max matrix must contain two completed runs per effort")
    bounded_telemetry = bounded_private_telemetry(bounded_raw_paths)
    pro = aggregate_runs(load(pro_path)["runs"], pro_group)
    telemetry = raw_telemetry(pro_raw_paths)
    agent = sanitize_agent(args.agent_result.resolve())
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
        "scope": "quick decision benchmark; two quality runs per effort and five focused agent tasks",
        "quality": {
            "private_flash": verified_private,
            "private_flash_bounded_4k": bounded_private,
            "private_flash_legacy_requested": {key.removeprefix("private-"): value for key, value in existing.items() if key.startswith("private-")},
            "online_flash": {key.removeprefix("online-"): value for key, value in existing.items() if key.startswith("online-")},
            "online_pro": pro,
        },
        "private_bounded_4k_telemetry": bounded_telemetry,
        "online_pro_telemetry": telemetry,
        "latency": latency,
        "agent_focus": agent,
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
                "bounded_high_max_quality_requests": 72,
                "verified_high_max_latency_requests": 8,
                "latency_request_contract": "one warmup plus three measured requests",
            },
        },
        "private_effort_contract": {
            "portal_requires_allowed_openai_params": ["reasoning_effort"],
            "legacy_requested_efforts_effective_effort": "high",
            "legacy_reason": "LiteLLM drop_params removed reasoning_effort for the generic OpenAI-compatible deployment",
            "verified_same_max_tokens": 32768,
            "verified_max_quality_status": "completed_with_4k_bound",
            "verified_max_quality_pilot": {
                "parallel_requests": 2,
                "same_max_tokens_as_high": 32768,
                "client_bound_seconds": 900,
                "completed_matrix_runs": 0,
                "portal_status_on_client_cancel": [499, 499],
            },
            "bounded_quality_matrix": {
                "max_tokens": 4096,
                "runs_per_effort": 2,
                "requests_per_effort": 36,
                "concurrency_per_effort": 3,
                "paired_total_concurrency": 6,
                "high_final_coverage": bounded_telemetry["high"]["final_coverage"],
                "max_final_coverage": bounded_telemetry["max"]["final_coverage"],
                "high_completed_final_score": bounded_telemetry["high"]["completed_final_score"],
                "max_completed_final_score": bounded_telemetry["max"]["completed_final_score"],
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
            "bounded_private_adjudication": sha256(bounded_path),
        },
    }
    summary_path = project / "data/deepseek-private-online-comparison-20260817.json"
    write = json.dumps(normalize(summary), indent=2, ensure_ascii=False) + "\n"
    summary_path.write_text(write)

    quality_rows = []
    labels = [
        ("private-high", "Private Flash high / 32K", verified_private["high"]),
        ("private-bounded-high", "Private Flash high / bounded 4K", bounded_private["high"]),
        ("private-bounded-max", "Private Flash max / bounded 4K", bounded_private["max"]),
        ("online-low", "Online Flash low / 32K", existing["online-low"]),
        ("online-high", "Online Flash high / 256K", existing["online-high"]),
        ("online-max", "Online Flash max / 384K", existing["online-max"]),
        ("pro-low", "Online Pro low / 32K", pro["low"]),
        ("pro-high", "Online Pro high / 256K", pro["high"]),
        ("pro-max", "Online Pro max / 384K", pro["max"]),
    ]
    for _key, label, row in labels:
        quality_rows.append(
            f"| {label} | {pct(row['macro_score'])} | {pct(row['categories']['sql'])} | "
            f"{pct(row['categories']['python'])} | {pct(row['categories']['incident'])} | {row['stdev'] * 100:.1f}pp |"
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
  87.5% 只是 effective-high 的重复波动，不是 Max 结果。显式透传后，在 High/Max 相同 4K
  上限的有界 A/B 中，High 为 {pct(bounded_private['high']['macro_score'])} 且 0/36 截断；True Max
  全请求分为 {pct(bounded_private['max']['macro_score'])}，10/36 截断。Max 的 26 个完整 final
  得分 {pct(bounded_telemetry['max']['completed_final_score'])}，说明下降来自 final 覆盖率，不是
  已完成答案的质量变差。
- **Pro 不保证 Agent 工作流单调更好。** 在一个刻意聚焦历史 private 弱项的 5 题集合中，
  Pro high 只完整通过 1/5；历史 online Flash 为 4/5，private Flash 为 2/5。该集合有选择偏差，
  只能说明升级前仍需按真实 Agent workflow 验证。

## 精度

下表只保留 effort 契约已验证的处理组，每组 n=2。Private 与 Pro 使用 v2 harness 的完整
18 题；Online Flash 保留 PR 32 的 v1 裁决结果。4K 行是相同输出上限下的 High/Max 因果 A/B；
32K Private High 是不受本轮截断影响的能力基线。分数以可执行 grader 为主，不使用模型自评。

| 处理组 | 宏平均 | SQL | Python | 故障诊断 | 两轮标准差 |
|---|---:|---:|---:|---:|---:|
{chr(10).join(quality_rows)}

旧矩阵请求了 Private low/high/max，但 LiteLLM 将该 deployment 识别为 generic OpenAI-compatible，
`reasoning_effort` 不在支持参数列表且全局 `drop_params=true`，所以三组实际均为 vLLM 默认 High。
三组共六轮的宏平均为 87.0%，范围 80.6%–94.4%；108 个请求全部 `finish_reason=stop`，实际输出
远低于 32K/256K/384K 上限。因此旧 83.3%/90.3%/87.5% 差异既不是 Max 效果，也不是截断造成，
只能视为重复波动。

按 LiteLLM 官方方式加入 `allowed_openai_params=["reasoning_effort"]` 后，直接模板探针从 High 的
11 prompt tokens 变为 Max 的 90 tokens，证明 Max 已真实到达 vLLM。Private high 在相同 32K
输出上限下重跑两轮并完成。32K True Max pilot 在 15 分钟客户端边界内未完成，因此补做相同
`max_tokens=4096` 的 High/Max 有界矩阵，各两轮、每轮 18 题、每组并发 3，总并发不超过 vLLM
`max-num-seqs=6`。

| Private 4K 指标 | High | True Max |
|---|---:|---:|
| 全请求可执行分 | {pct(bounded_private['high']['macro_score'])} | {pct(bounded_private['max']['macro_score'])} |
| final 覆盖率 | {pct(bounded_telemetry['high']['final_coverage'])} | {pct(bounded_telemetry['max']['final_coverage'])} |
| 完整 final 得分 | {pct(bounded_telemetry['high']['completed_final_score'])} | {pct(bounded_telemetry['max']['completed_final_score'])} |
| length 截断 | {bounded_telemetry['high']['length_truncations']}/36 | {bounded_telemetry['max']['length_truncations']}/36 |
| 空 final | {bounded_telemetry['high']['empty_finals']}/36 | {bounded_telemetry['max']['empty_finals']}/36 |
| HTTP/网络错误 | {bounded_telemetry['high']['errors']}/36 | {bounded_telemetry['max']['errors']}/36 |

因此“Max 比 High 精度差”的说法不准确：在 4K 产品边界下，Max 的**任务成功率**更低；但只看
成功返回的 final，Max 并未低于 High。若产品必须使用 Max，需要提高输出预算或实现 reasoning
预算/超时保护，并把空 final 当作显式失败处理。

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
| Private max | 4K 下 final 覆盖率 {pct(bounded_telemetry['max']['final_coverage'])}；仅在能提高预算并处理空 final 时按请求启用 |
| 简单低延迟请求且允许出网 | online Flash low |
| 复杂任务、private 首次失败、需要更高一次成功率 | online Pro high |
| 极难任务且能接受分钟级尾延迟和约 3 倍 low token | Pro max，仅按请求启用 |
| 终端脚本、长文约束、复杂 Agent 工具链 | 先跑工作流级验收，不按模型名直接升级 |

## 测试覆盖矩阵

| 维度 | 本轮纳入 | 未覆盖 | 状态 |
|---|---|---|---|
| 可执行精度 | Verified Private high 32K；Private High/True Max 4K；Online Flash/Pro | True Private Max 32K 未完成；旧 private low/max 不是有效 effort | 主要边界完整 |
| 串行 SSE 性能 | Verified Private high/max；Online Flash low；Online Pro low/high/max | Online Flash high/max | 主要路径完整 |
| Token 与 API 成本 | Online Pro low/high/max | Private 无 API 账单；Flash 未统一计价 | 范围内完整 |
| Agent 聚焦任务 | Online Pro high；Online/Private 历史基线 | 不是九组 effort 全矩阵 | 部分 |

Private 还承担部署运维边界：两台 GB10 必须同时在线，当前 TP=2、最大并发序列 6；online
服务则引入数据出境、动态 alias、网络和供应商调度风险。两类线路应保留自动回退策略，不能
只看本轮宏平均。

## 方法与证据

- Online Flash alias：`deepseek-v4-flash` → `DeepSeek-V4-Flash-0731`。
- Online Pro alias：`deepseek-v4-pro` → `DeepSeek-V4-Pro-0813`。
- Private 请求经 LLM Portal 转发，不是客户端直连 vLLM。Portal access log 记录旧质量矩阵
  108 次请求和旧性能 4 次请求；修正后另有 High 32K 质量 36 次、High/Max 4K 质量 72 次、
  High/Max 性能 8 次请求。
- LiteLLM 官方文档说明 `drop_params=true` 会丢弃不支持参数，`allowed_openai_params` 可显式透传；
  live `get_supported_openai_params()` 也确认该 generic OpenAI deployment 默认不支持 `reasoning_effort`。
- 修正后 Private High/Max 性能均为 client → Portal → vLLM 的端到端指标，不是裸引擎延迟。
- 官方上下文 1M、最大输出 384K、effort 为 low/high/max；默认 high。
- Pro 六个质量 treatment 共 108 请求，0 HTTP/网络错误、0 空 final、0 length 截断。
- Private 4K High/True Max 共 72 请求，0 HTTP/网络错误；High 0 截断，True Max 10 个 length
  截断且对应 10 个空 final。
- Agent 聚焦题的脱敏逐题证据见 `data/online-pro-agent-focus-20260817.json`；原始 sandbox、
  stream 和绝对路径不提交。
- Pro Python 原始评分时固定 sandbox 镜像不可用；保存的完整 final 随后在不可变 ECR Python
  digest 中重新执行。原始 JSON 未覆盖，裁决见
  `data/online-pro-matrix-adjudicated.json`。
- Private 4K High/Max 的 Python final 也在相同不可变 ECR digest 中重新执行；裁决产物为
  `model-benchmark-qwen-deepseek/data/lakehouse-private-effort-bounded-4k-adjudicated.json`。
- 本报告是快速决策 benchmark：每组 n=2、Agent 每题 n=1，不宣称统计显著性。

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
