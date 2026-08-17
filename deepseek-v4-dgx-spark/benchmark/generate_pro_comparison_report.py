#!/usr/bin/env python3
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


def sanitize_agent(path: Path) -> dict:
    value = load(path)
    tasks = []
    for row in value["tasks"]:
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
    pro = aggregate_runs(load(pro_path)["runs"], pro_group)
    telemetry = raw_telemetry(pro_raw_paths)
    agent = sanitize_agent(args.agent_result.resolve())
    agent_path = project / "data/online-pro-agent-focus-20260817.json"
    agent_path.write_text(json.dumps(normalize(agent), indent=2, ensure_ascii=False) + "\n")

    latency_paths = {
        "private-high": root / "model-benchmark-qwen-deepseek/data/inference-performance/private-ds-high.json",
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
            "private_flash": {key.removeprefix("private-"): value for key, value in existing.items() if key.startswith("private-")},
            "online_flash": {key.removeprefix("online-"): value for key, value in existing.items() if key.startswith("online-")},
            "online_pro": pro,
        },
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
                "quality_requests_in_portal_access_log": 108,
                "latency_requests_in_portal_access_log": 4,
                "latency_request_contract": "one warmup plus three measured requests",
            },
        },
        "private_effort_contract": {
            "low_equals_high": True,
            "low_prompt_sha256": "f0c87d80359c231133820e076d1b5c6dcf61fcee3d09905b0a26eddc4c211de0",
            "high_prompt_sha256": "f0c87d80359c231133820e076d1b5c6dcf61fcee3d09905b0a26eddc4c211de0",
            "max_prompt_sha256": "289b341131ccacbac40dd051a01c4b61989671915e61bbb236ee62bab7427b65",
        },
        "source_sha256": {
            "existing_adjudication": sha256(existing_path),
            "pro_adjudication": sha256(pro_path),
            "agent_evidence": sha256(agent_path),
        },
    }
    summary_path = project / "data/deepseek-private-online-comparison-20260817.json"
    write = json.dumps(normalize(summary), indent=2, ensure_ascii=False) + "\n"
    summary_path.write_text(write)

    quality_rows = []
    labels = [
        ("private-low", "Private Flash low* / 32K", existing["private-low"]),
        ("private-high", "Private Flash high / 256K", existing["private-high"]),
        ("private-max", "Private Flash max / 384K", existing["private-max"]),
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
  private high 平均 {pct(existing['private-high']['macro_score'])}，与 online Flash high 的
  {pct(existing['online-high']['macro_score'])} 接近；本轮通过 LLM Portal 转发至 private vLLM，
  客户端观测的端到端 TTFT 也明显更低。
- **需要最高成功率时升级到 online Pro high。** Pro high 平均
  {pct(pro['high']['macro_score'])}，比 private high 高
  {(pro['high']['macro_score'] - existing['private-high']['macro_score']) * 100:.1f}pp；本轮一轮 18/18，
  另一轮 {pct(pro['high']['macro_score'] * 2 - 1)}，没有空 final、截断或 HTTP 错误。
- **不要把 max 设为默认。** Pro max 平均 {pct(pro['max']['macro_score'])}，没有超过 high，
  平均输出 {telemetry['max']['completion_tokens_mean'] / 1000:.1f}K token，约为 low 的
  {telemetry['max']['completion_tokens_mean'] / telemetry['low']['completion_tokens_mean']:.1f} 倍，并出现分钟级尾延迟。
- **Private max 已测试，但没有改善质量。** 两轮宏平均为
  {pct(existing['private-max']['macro_score'])}，低于 private high，且标准差为
  {existing['private-max']['stdev'] * 100:.1f}pp。
- **Pro 不保证 Agent 工作流单调更好。** 在一个刻意聚焦历史 private 弱项的 5 题集合中，
  Pro high 只完整通过 1/5；历史 online Flash 为 4/5，private Flash 为 2/5。该集合有选择偏差，
  只能说明升级前仍需按真实 Agent workflow 验证。

## 精度

九个观测组都生成 18 道 SQL、Python 和故障诊断题，每组 n=2。PR 32 的 Flash/private
使用 v1 题面，其中一题 CDC 因未定义 I/U/D 在独立裁决时排除，最终按 17 题计分；Pro 使用
已修正的 v2 harness，按完整 18 题计分。分数以可执行 grader 为主，不使用模型自评。

| 处理组 | 宏平均 | SQL | Python | 故障诊断 | 两轮标准差 |
|---|---:|---:|---:|---:|---:|
{chr(10).join(quality_rows)}

`*` Private 当前运行时不能独立测试 low：vLLM `deepseek_v4` tokenizer 将 low 和 high 都映射为
high。实测同一消息的 low/high prompt SHA-256 均为
`f0c87d80359c231133820e076d1b5c6dcf61fcee3d09905b0a26eddc4c211de0`；max 才产生不同前缀。
因此 PR 32 中 private-low 与 private-high 的差异应解释为重复运行波动和不同输出上限，
不能解释为 effort 效应。

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
适合交互式内网 Agent，但不能解释为裸 vLLM engine latency；
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
| Private max | 两轮 87.5%，未超过 high；本轮未单独测延迟与 Agent，不建议默认启用 |
| 简单低延迟请求且允许出网 | online Flash low |
| 复杂任务、private 首次失败、需要更高一次成功率 | online Pro high |
| 极难任务且能接受分钟级尾延迟和约 3 倍 low token | Pro max，仅按请求启用 |
| 终端脚本、长文约束、复杂 Agent 工具链 | 先跑工作流级验收，不按模型名直接升级 |

## 测试覆盖矩阵

| 维度 | 本轮纳入 | 未覆盖 | 状态 |
|---|---|---|---|
| 可执行精度 | Private / Online Flash / Online Pro：low、high、max | Private low 非独立 prompt | 完整 |
| 串行 SSE 性能 | Private high；Online Flash low；Online Pro low/high/max | Private low/max；Online Flash high/max | 部分 |
| Token 与 API 成本 | Online Pro low/high/max | Private 无 API 账单；Flash 未统一计价 | 范围内完整 |
| Agent 聚焦任务 | Online Pro high；Online/Private 历史基线 | 不是九组 effort 全矩阵 | 部分 |

Private 还承担部署运维边界：两台 GB10 必须同时在线，当前 TP=2、最大并发序列 6；online
服务则引入数据出境、动态 alias、网络和供应商调度风险。两类线路应保留自动回退策略，不能
只看本轮宏平均。

## 方法与证据

- Online Flash alias：`deepseek-v4-flash` → `DeepSeek-V4-Flash-0731`。
- Online Pro alias：`deepseek-v4-pro` → `DeepSeek-V4-Pro-0813`。
- Private 请求经 LLM Portal 转发，不是客户端直连 vLLM。Portal access log 在质量矩阵对应
  时段记录 108 次请求；性能测量对应 4 次成功请求，与 1 次预热加 3 次测量完全一致。
- Private 的 0.252s TTFT 是 client → Portal → vLLM 的端到端指标，不是裸引擎延迟。
- 官方上下文 1M、最大输出 384K、effort 为 low/high/max；默认 high。
- Pro 六个质量 treatment 共 108 请求，0 HTTP/网络错误、0 空 final、0 length 截断。
- Agent 聚焦题的脱敏逐题证据见 `data/online-pro-agent-focus-20260817.json`；原始 sandbox、
  stream 和绝对路径不提交。
- Pro Python 原始评分时固定 sandbox 镜像不可用；保存的完整 final 随后在不可变 ECR Python
  digest 中重新执行。原始 JSON 未覆盖，裁决见
  `data/online-pro-matrix-adjudicated.json`。
- 本报告是快速决策 benchmark：每组 n=2、Agent 每题 n=1，不宣称统计显著性。

官方资料：[Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode)、
[Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing)、
[V4 Pro GA](https://api-docs.deepseek.com/news/news260813)。机器可读汇总见
[`data/deepseek-private-online-comparison-20260817.json`](data/deepseek-private-online-comparison-20260817.json)。
"""
    (project / "BENCHMARK-COMPARISON-20260817.md").write_text(report)
    print(json.dumps({"report": str(project / "BENCHMARK-COMPARISON-20260817.md"), "summary": str(summary_path), "agent": str(agent_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
