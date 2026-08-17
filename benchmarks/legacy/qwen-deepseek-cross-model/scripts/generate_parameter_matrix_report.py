#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import html
import json
import statistics
from collections import defaultdict
from pathlib import Path


CATEGORIES = ("sql", "python", "incident")
EFFORT_ORDER = {"low": 0, "high": 1, "max": 2, None: 3}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def mean(values: list[float]) -> float:
    return statistics.fmean(values)


def deviation(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) > 1 else 0.0


def record_key(record: dict) -> tuple:
    config = record.get("request_config") or {}
    return (
        record.get("treatment") or record["tag"],
        record.get("base_url"),
        record.get("model"),
        record.get("mode"),
        config.get("deepseek_effort"),
        record.get("max_tokens"),
        record.get("sampling"),
        bool(config.get("stream")),
        config.get("request_timeout_seconds"),
        record.get("seed"),
    )


def validate_raw_summary(record: dict, path: Path) -> None:
    cases = record.get("cases") or []
    if len(cases) != 18:
        return
    for category in CATEGORIES:
        selected = [case for case in cases if case["category"] == category]
        computed = mean([float(case["score"]) for case in selected])
        if abs(computed - record["categories"][category]["score"]) > 1e-9:
            raise RuntimeError(f"category summary mismatch in {path}: {category}")
    computed_macro = mean([record["categories"][name]["score"] for name in CATEGORIES])
    if abs(computed_macro - record["macro_score"]) > 1e-9:
        raise RuntimeError(f"macro summary mismatch in {path}")


def read_runs(input_dir: Path, max_deepseek_repeat: int | None = None, adjudication_file: Path | None = None) -> list[dict]:
    adjudication = {}
    if adjudication_file:
        payload = json.loads(adjudication_file.read_text())
        adjudication = {item["tag"]: item for item in payload["runs"]}
    runs = []
    for path in sorted(input_dir.glob("*.json")):
        record = json.loads(path.read_text())
        if record.get("harness_id") != "lakehouse-thinking-v1" or record.get("status") != "passed":
            continue
        validate_raw_summary(record, path)
        if (
            max_deepseek_repeat is not None
            and record.get("mode") == "deepseek-thinking"
            and record.get("repeat", 1) > max_deepseek_repeat
        ):
            continue
        record["_path"] = path.name
        if record["tag"] in adjudication:
            adjusted = adjudication[record["tag"]]
            record["_original_macro_score"] = record["macro_score"]
            record["macro_score"] = adjusted["macro_score"]
            for category in CATEGORIES:
                record["categories"][category].update(adjusted["categories"][category])
        runs.append(record)
    if not runs:
        raise RuntimeError(f"No completed lakehouse matrix JSON files in {input_dir}")
    identities = [[(case["id"], case["category"]) for case in run["cases"]] for run in runs]
    if any(identity != identities[0] for identity in identities[1:]):
        raise RuntimeError("case identity mismatch across matrix runs")
    return runs


def groups(runs: list[dict], expected_deepseek_runs: int | None = None) -> list[tuple[tuple, list[dict]]]:
    bucket: dict[tuple, list[dict]] = defaultdict(list)
    for run in runs:
        bucket[record_key(run)].append(run)
    ordered = []
    for key, values in bucket.items():
        values.sort(key=lambda run: run["repeat"])
        expected = values[0].get("expected_runs", 1)
        if expected_deepseek_runs is not None and values[0].get("mode") == "deepseek-thinking":
            expected = expected_deepseek_runs
        repeats = [run["repeat"] for run in values]
        if len(values) != expected or repeats != list(range(1, expected + 1)):
            raise RuntimeError(f"incomplete repeats for {key[0]}: expected 1..{expected}, got {repeats}")
        for run in values:
            run["_display_expected_runs"] = expected
        ordered.append((key, values))
    return sorted(ordered, key=lambda item: (item[0][0], EFFORT_ORDER.get(item[0][4], 9), item[0][1] or ""))


def group_metrics(runs: list[dict]) -> dict:
    categories = {
        category: mean([run["categories"][category]["score"] for run in runs])
        for category in CATEGORIES
    }
    macros = [run["macro_score"] for run in runs]
    tokens = [sum(row["completion_tokens"] for row in run["categories"].values()) for run in runs]
    truncations = [sum(row["length_truncations"] for row in run["categories"].values()) for run in runs]
    empty = [sum(row["empty_finals"] for row in run["categories"].values()) for run in runs]
    errors = [sum(row.get("errors", 0) for row in run["categories"].values()) for run in runs]
    return {
        "categories": categories,
        "macro": mean(macros),
        "macro_stddev": deviation(macros),
        "seconds": mean([run["total_seconds"] for run in runs]),
        "tokens": mean(tokens),
        "truncations": mean(truncations),
        "empty": mean(empty),
        "errors": mean(errors),
    }


def summary_rows(grouped: list[tuple[tuple, list[dict]]]) -> str:
    rows = []
    for key, runs in grouped:
        treatment, endpoint, model, _mode, effort, max_tokens, sampling = key[:7]
        metrics = group_metrics(runs)
        effort_label = effort or "-"
        rows.append(
            "<tr>"
            f"<td>{esc(treatment)}</td><td>{esc(endpoint)}</td><td>{esc(model)}</td>"
            f"<td>{esc(effort_label)} / {max_tokens:,}</td>"
            f"<td>{len(runs)}</td><td>{pct(metrics['categories']['sql'])}</td>"
            f"<td>{pct(metrics['categories']['python'])}</td><td>{pct(metrics['categories']['incident'])}</td>"
            f"<td><strong>{pct(metrics['macro'])}</strong> <small>+/- {metrics['macro_stddev'] * 100:.1f}pp</small></td>"
            f"<td>{metrics['seconds']:.1f}s</td><td>{metrics['tokens']:,.0f}</td>"
            f"<td>{metrics['truncations']:.1f}</td><td>{metrics['empty']:.1f}</td><td>{metrics['errors']:.1f}</td>"
            "</tr>"
        )
    return "".join(rows)


def run_rows(grouped: list[tuple[tuple, list[dict]]]) -> str:
    rows = []
    for key, runs in grouped:
        for run in runs:
            tokens = sum(row["completion_tokens"] for row in run["categories"].values())
            truncations = sum(row["length_truncations"] for row in run["categories"].values())
            empty = sum(row["empty_finals"] for row in run["categories"].values())
            rows.append(
                "<tr>"
                f"<td>{esc(run['treatment'])}</td><td>{run['repeat']}/{run['_display_expected_runs']}</td>"
                f"<td>{pct(run['macro_score'])}</td><td>{pct(run.get('_original_macro_score', run['macro_score']))}</td><td>{run['total_seconds']:.1f}s</td>"
            f"<td>{tokens:,}</td><td>{truncations}</td><td>{empty}</td><td>{sum(row.get('errors', 0) for row in run['categories'].values())}</td><td><code>{esc(run['_path'])}</code></td>"
                "</tr>"
            )
    return "".join(rows)


def config_rows(grouped: list[tuple[tuple, list[dict]]]) -> str:
    rows = []
    for key, runs in grouped:
        treatment, endpoint, model, mode, effort, max_tokens, sampling = key[:7]
        config = runs[0].get("request_config") or {}
        rows.append(
            "<tr>"
            f"<td>{esc(treatment)}</td><td>{esc(endpoint)}</td><td>{esc(model)}</td><td>{esc(mode)}</td>"
            f"<td>{esc(effort or '-')}</td><td>{max_tokens:,}</td><td>{esc(sampling)}</td>"
            f"<td>final {config.get('max_response_chars', 0)} chars; reasoning {config.get('max_reasoning_chars', 0)} chars</td>"
            "</tr>"
        )
    return "".join(rows)


def group_name(key: tuple) -> str:
    return str(key[0])


def effort_name(key: tuple) -> str:
    return str(key[4] or "thinking")


def compact_time(seconds: float) -> str:
    minutes, remainder = divmod(round(seconds), 60)
    return f"{minutes}m {remainder:02d}s" if minutes else f"{remainder}s"


def bar(value: float, maximum: float, flavor: str, label: str) -> str:
    width = 0 if maximum <= 0 else min(100, value / maximum * 100)
    return f"<div class='measure {flavor}'><span style='width:{width:.2f}%'></span></div><b>{esc(label)}</b>"


def qwen_section(grouped: list[tuple[tuple, list[dict]]]) -> str:
    qwen = [(key, runs, group_metrics(runs)) for key, runs in grouped if key[3] != "deepseek-thinking"]
    if not qwen:
        return ""
    qwen.sort(key=lambda item: item[2]["macro"], reverse=True)
    max_seconds = max(item[2]["seconds"] for item in qwen)
    rows = []
    for key, _runs, metrics in qwen:
        categories = "".join(
            f"<div class='category'><span>{name.upper()}</span>{bar(metrics['categories'][name], 1, 'score', pct(metrics['categories'][name]))}</div>"
            for name in CATEGORIES
        )
        rows.append(
            "<article class='model-row'>"
            f"<div class='model-title'><h3>{esc(key[2])}</h3><p>{esc(group_name(key))}</p></div>"
            f"<div class='macro'>{pct(metrics['macro'])}<small>宏平均</small></div>"
            f"<div class='category-set'>{categories}</div>"
            f"<div class='cost-cell'>{bar(metrics['seconds'], max_seconds, 'time', compact_time(metrics['seconds']))}<small>18 题串行总耗时</small></div>"
            "</article>"
        )
    return "".join(rows)


def deepseek_score_section(grouped: list[tuple[tuple, list[dict]]]) -> str:
    deepseek = [(key, runs, group_metrics(runs)) for key, runs in grouped if key[3] == "deepseek-thinking"]
    buckets: dict[str, list[tuple[tuple, list[dict], dict]]] = defaultdict(list)
    for item in deepseek:
        buckets[str(item[0][1])].append(item)
    panels = []
    for endpoint, items in sorted(buckets.items()):
        items.sort(key=lambda item: EFFORT_ORDER.get(item[0][4], 9))
        rows = []
        for key, runs, metrics in items:
            rows.append(
                "<tr>"
                f"<th scope='row'>{esc(effort_name(key))}<small>{key[5] // 1024}K cap · n={len(runs)}</small></th>"
                f"<td>{bar(metrics['categories']['sql'], 1, 'score', pct(metrics['categories']['sql']))}</td>"
                f"<td>{bar(metrics['categories']['python'], 1, 'score', pct(metrics['categories']['python']))}</td>"
                f"<td>{bar(metrics['categories']['incident'], 1, 'score', pct(metrics['categories']['incident']))}</td>"
                f"<td class='strong'>{pct(metrics['macro'])}<small>+/- {metrics['macro_stddev'] * 100:.1f}pp</small></td>"
                "</tr>"
            )
        panels.append(
            "<div class='endpoint-panel'>"
            f"<header><p>endpoint</p><h3>{esc(endpoint)}</h3><span>{esc(items[0][0][2])}</span></header>"
            "<div class='table-wrap'><table class='score-table'><thead><tr><th>思考档位</th><th>SQL</th><th>Python</th><th>故障分析</th><th>宏平均</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div></div>"
        )
    return "".join(panels)


def deepseek_cost_rows(grouped: list[tuple[tuple, list[dict]]]) -> str:
    deepseek = [(key, runs, group_metrics(runs)) for key, runs in grouped if key[3] == "deepseek-thinking"]
    if not deepseek:
        return ""
    max_seconds = max(item[2]["seconds"] for item in deepseek)
    max_tokens = max(item[2]["tokens"] for item in deepseek)
    rows = []
    for key, runs, metrics in sorted(deepseek, key=lambda item: (item[0][1], EFFORT_ORDER.get(item[0][4], 9))):
        errors = metrics["errors"]
        token_label = f"{metrics['tokens']:,.0f}"
        rows.append(
            "<tr>"
            f"<th scope='row'>{esc(key[1])}<small>{esc(effort_name(key))} · {key[5] // 1024}K · n={len(runs)}</small></th>"
            f"<td>{bar(metrics['seconds'], max_seconds, 'time', compact_time(metrics['seconds']))}</td>"
            f"<td>{bar(metrics['tokens'], max_tokens, 'token', token_label)}</td>"
            f"<td>{metrics['truncations']:.1f}</td><td>{metrics['empty']:.1f}</td><td>{errors:.1f}</td>"
            "</tr>"
        )
    return "".join(rows)


def run_stability_rows(grouped: list[tuple[tuple, list[dict]]]) -> str:
    rows = []
    for key, runs in grouped:
        if key[3] != "deepseek-thinking":
            continue
        dots = "".join(
            f"<span class='run-dot' style='--dot:{run['macro_score'] * 100:.1f}' title='r{run['repeat']}: {pct(run['macro_score'])}'></span>"
            for run in runs
        )
        metrics = group_metrics(runs)
        rows.append(
            "<tr>"
            f"<th scope='row'>{esc(key[1])}<small>{esc(effort_name(key))} · {key[5] // 1024}K</small></th>"
            f"<td><div class='dot-track'>{dots}</div></td>"
            f"<td>{pct(metrics['macro'])}</td><td>+/- {metrics['macro_stddev'] * 100:.1f}pp</td>"
            "</tr>"
        )
    return "".join(rows)


def load_performance(directory: Path | None) -> list[dict]:
    if not directory:
        return []
    records = [json.loads(path.read_text()) for path in sorted(directory.glob("*.json"))]
    if not records:
        raise RuntimeError(f"No inference performance JSON files in {directory}")
    return records


def performance_rows(records: list[dict]) -> str:
    rows = []
    for record in records:
        summary = record["summary"]
        rows.append(
            "<tr>"
            f"<th>{esc(record['endpoint'])}<small>{esc(record['model'])} · {esc(record['profile'])}</small></th>"
            f"<td>{summary['ttft_seconds']['mean']:.3f}s<small>{summary['ttft_seconds']['min']:.3f}–{summary['ttft_seconds']['max']:.3f}s</small></td>"
            f"<td>{summary['response_seconds']['mean']:.3f}s<small>{summary['response_seconds']['min']:.3f}–{summary['response_seconds']['max']:.3f}s</small></td>"
            f"<td>{summary['decode_tokens_per_second']['mean']:.1f}<small>tokens/s</small></td>"
            f"<td>{summary['completion_tokens_mean']:.0f}</td>"
            f"<td>{summary['successful_runs']}/{summary['runs']}<small>错误 {summary['errors']}</small></td>"
            "</tr>"
        )
    return "".join(rows)


def cpu_value(environment: dict, field: str) -> str:
    for item in environment["host"]["cpu"]:
        if item["field"] == field:
            return str(item["data"])
    return "-"


def gib(value: int | float | None) -> str:
    return "-" if value is None else f"{value / 1024 ** 3:.1f} GiB"


def environment_section(environment: dict | None, performance: list[dict]) -> str:
    if not environment:
        return ""
    host = environment["host"]
    gpu = host["gpu"]
    local_rows = []
    startup_rows = []
    for name, item in environment["local_deployments"].items():
        command = " ".join(item["command"] or [])
        local_rows.append(
            "<tr>"
            f"<th>{esc(name)}<small>{esc(item['model_id'])}</small></th>"
            f"<td>ModelScope<small>{gib(item['model_size_bytes'])} · {esc(item['quantization'])}</small></td>"
            f"<td>{esc(item['container_image'])}</td><td>{gib(item['memory_limit_bytes'])} / {gib(item['memory_swap_limit_bytes'])}</td>"
            f"<td><code>{esc(command)}</code></td></tr>"
        )
        startup = item["startup"]
        startup_rows.append(
            "<tr>"
            f"<th>{esc(item['model_id'])}</th><td>{startup['service_startup_seconds']:.3f}s</td>"
            f"<td>{startup['model_load_seconds']:.3f}s</td><td>{startup['model_load_gpu_memory_gib']:.2f} GiB</td>"
            f"<td>{esc(startup['started_at'])}</td></tr>"
        )
    external_rows = "".join(
        f"<tr><th>{esc(name)}</th><td>{esc(item['model'])}</td><td>{esc(item['hardware'])}</td><td>{esc(item['runtime'])}</td><td>{esc(item['cold_start_reason'])}</td></tr>"
        for name, item in environment["external_deployments"].items()
    )
    return f"""
<section id='performance'><h2>推理性能：首 token、端到端响应与解码吞吐分开看</h2><p>统一短任务，1 次预热 + 3 次计量，SSE 单请求。TTFT 从请求发出到首个 reasoning/content delta；TPS 为 completion tokens /（响应时间 − TTFT）。输出长度不同，因此响应时间不能脱离 tokens 与 TPS 单独排名。</p><div class='table-wrap'><table><thead><tr><th>endpoint / 配置</th><th>TTFT 均值</th><th>响应时间均值</th><th>解码 TPS</th><th>输出 tokens</th><th>成功</th></tr></thead><tbody>{performance_rows(performance)}</tbody></table></div></section>
<section id='startup'><h2>模型冷启动：服务重启到 API ready</h2><p>这是 Docker StartedAt 到 vLLM Application startup complete 的实测；未清 Linux page cache，不等同于断电冷启动。外部 DeepSeek 服务生命周期不可观测。</p><div class='table-wrap'><table><thead><tr><th>模型</th><th>服务启动</th><th>模型加载</th><th>加载显存</th><th>开始时间 UTC</th></tr></thead><tbody>{''.join(startup_rows)}</tbody></table></div></section>
<section id='environment'><h2>完整测试环境与部署配置</h2><p>快照时间 {esc(environment['timestamp'])}。敏感环境变量与 API 密钥未采集。</p><div class='facts'><div><small>操作系统 / 内核</small><strong>{esc(host['os'])}<br>{esc(host['kernel'])}</strong></div><div><small>CPU</small><strong>{esc(cpu_value(environment, 'Model name:'))}<br>{esc(cpu_value(environment, 'Socket(s):'))} socket · {esc(cpu_value(environment, 'Core(s) per socket:'))} cores/socket</strong></div><div><small>内存 / Swap</small><strong>{gib(host['memory_total_bytes'])} / {gib(host['swap_total_bytes'])}</strong></div><div><small>GPU</small><strong>{esc(gpu['name'])} · {gpu['memory_total_mib']} MiB<br>driver {esc(gpu['driver_version'])} · {gpu['power_limit_w']:.0f} W</strong></div><div><small>运行时</small><strong>Docker {esc(host['docker_version'])}<br>Python {esc(host['python_version'])}</strong></div></div><h3 class='subhead'>本机模型容器</h3><div class='table-wrap'><table><thead><tr><th>部署</th><th>来源 / 量化</th><th>镜像</th><th>内存 / swap 限制</th><th>完整启动命令</th></tr></thead><tbody>{''.join(local_rows)}</tbody></table></div><h3 class='subhead'>外部 DeepSeek endpoint</h3><div class='table-wrap'><table><thead><tr><th>endpoint</th><th>模型</th><th>硬件</th><th>运行时</th><th>冷启动不可用原因</th></tr></thead><tbody>{external_rows}</tbody></table></div></section>
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--recommendation", required=True)
    parser.add_argument("--expected-deepseek-runs", type=int, help="Override the recorded DS repeat target for a completed preview")
    parser.add_argument("--max-deepseek-repeat", type=int, help="Exclude later DS repeats when rendering a completed preview")
    parser.add_argument("--adjudication-file", type=Path)
    parser.add_argument("--performance-dir", type=Path)
    parser.add_argument("--environment-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.expected_deepseek_runs is not None and args.expected_deepseek_runs < 1:
        parser.error("--expected-deepseek-runs must be at least 1")
    if args.max_deepseek_repeat is not None and args.max_deepseek_repeat < 1:
        parser.error("--max-deepseek-repeat must be at least 1")
    grouped = groups(read_runs(args.input_dir, args.max_deepseek_repeat, args.adjudication_file), args.expected_deepseek_runs)
    performance = load_performance(args.performance_dir)
    environment = json.loads(args.environment_file.read_text()) if args.environment_file else None
    operational_sections = environment_section(environment, performance)
    document = f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>湖仓推理参数矩阵 Benchmark</title><style>
:root{{--ink:#151816;--paper:#f5f3ed;--surface:#fffdf8;--line:#c8c5b9;--muted:#6a6c66;--score:#117a65;--time:#c46a1b;--token:#3c6db0;--danger:#b73c38;color-scheme:light}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 "Noto Sans CJK SC","Noto Sans CJK",system-ui,"Segoe UI",sans-serif;letter-spacing:0}}main{{width:min(1440px,calc(100% - 36px));margin:auto;padding:30px 0 72px}}h1,h2,h3,p{{margin:0}}h1{{font-size:32px;line-height:1.15}}h2{{font-size:22px;line-height:1.2}}h3{{font-size:16px;line-height:1.25}}small{{display:block;color:var(--muted);font-size:12px;font-weight:400}}header{{border-bottom:2px solid var(--ink);padding-bottom:20px}}header>p{{color:var(--muted);font-size:13px;margin-bottom:8px}}header>div{{max-width:900px;color:var(--muted);margin-top:9px}}nav{{display:flex;gap:20px;flex-wrap:wrap;position:sticky;top:0;background:rgba(245,243,237,.96);z-index:2;padding:13px 0;border-bottom:1px solid var(--line)}}nav a{{color:var(--ink);text-decoration:none;font-size:13px}}.decision{{margin:24px 0 0;border-left:4px solid var(--score);padding:14px 18px;background:#e8f2ed}}.decision strong{{display:block;margin-bottom:4px}}section{{padding:34px 0;border-bottom:1px solid var(--line)}}section>p{{color:var(--muted);margin:6px 0 18px}}.subhead{{margin:24px 0 8px}}.facts{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin-bottom:20px}}.facts>div{{background:var(--surface);padding:13px;min-width:0}}.facts strong{{font-size:13px;overflow-wrap:anywhere}}.model-list{{border-top:1px solid var(--line)}}.model-row{{display:grid;grid-template-columns:minmax(190px,1.1fr) 105px minmax(330px,2.1fr) minmax(180px,1fr);gap:22px;align-items:center;padding:18px 0;border-bottom:1px solid var(--line)}}.model-title p{{margin-top:4px;color:var(--muted);font-size:13px}}.macro{{font-size:30px;font-variant-numeric:tabular-nums;color:var(--score);font-weight:700}}.macro small{{margin-top:-2px}}.category-set{{display:grid;gap:7px}}.category{{display:grid;grid-template-columns:66px minmax(80px,1fr) 48px;gap:8px;align-items:center;font-size:12px}}.measure{{height:8px;background:#dedbd1;position:relative;overflow:hidden}}.measure span{{position:absolute;inset:0 auto 0 0}}.measure.score span{{background:var(--score)}}.measure.time span{{background:var(--time)}}.measure.token span{{background:var(--token)}}.cost-cell{{display:grid;grid-template-columns:minmax(90px,1fr) auto;gap:8px;align-items:center}}.cost-cell small{{grid-column:1 / -1}}.endpoint-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:28px}}.endpoint-panel{{min-width:0;border-top:3px solid var(--ink);padding-top:12px}}.endpoint-panel header{{padding:0 0 12px;border-bottom:1px solid var(--line)}}.endpoint-panel header p{{font-size:12px;color:var(--muted);margin-bottom:2px}}.endpoint-panel header span{{display:block;color:var(--muted);font-size:13px;margin-top:4px;overflow-wrap:anywhere}}.table-wrap{{max-width:100%;min-width:0;overflow-x:auto}}table{{width:100%;border-collapse:collapse}}th,td{{padding:11px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle;white-space:nowrap}}th{{font-weight:600}}td code{{display:block;max-width:560px;white-space:normal;overflow-wrap:anywhere}}.score-table th:first-child{{width:105px}}.score-table td{{min-width:120px}}.score-table .measure,.cost-table .measure{{display:inline-block;width:calc(100% - 52px);margin-right:8px;vertical-align:middle}}.strong{{font-weight:700;color:var(--score)}}.cost-table th{{min-width:160px}}.cost-table td{{min-width:170px}}.cost-table td:nth-last-child(-n+3){{min-width:62px;text-align:center;font-variant-numeric:tabular-nums}}.stability-table{{max-width:760px}}.dot-track{{height:22px;position:relative;border-bottom:1px solid var(--line);min-width:220px;background:linear-gradient(to right,transparent 49.5%,#d5d1c5 50%,transparent 50.5%)}}.run-dot{{position:absolute;left:calc(var(--dot) * 1%);top:6px;width:10px;height:10px;background:var(--score);border:1px solid var(--surface);border-radius:50%;transform:translateX(-50%)}}.audit details{{border-top:1px solid var(--line)}}.audit summary{{cursor:pointer;padding:12px 0;color:var(--ink)}}.audit table{{margin-bottom:12px}}code{{font:12px ui-monospace,monospace;color:#34484f}}ul{{padding-left:20px;margin:0}}li+li{{margin-top:6px}}@media(max-width:980px){{.model-row{{grid-template-columns:1fr 105px;gap:16px}}.category-set,.cost-cell{{grid-column:1 / -1}}.endpoint-grid{{grid-template-columns:1fr}}.facts{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:620px){{main{{width:calc(100% - 20px);padding-top:20px}}h1{{font-size:26px}}section{{padding:25px 0}}.model-row{{grid-template-columns:1fr}}.macro{{grid-row:1;grid-column:1;text-align:right}}.model-title{{grid-row:1}}.endpoint-grid{{gap:22px}}.score-table td{{min-width:150px}}.facts{{grid-template-columns:1fr}}}}
@media print{{@page{{size:A4 landscape;margin:9mm}}html,body{{background:#fff}}body{{font-size:9.5px;line-height:1.3}}main{{width:100%;padding:0}}nav{{display:none}}header{{padding-bottom:9px}}h1{{font-size:24px}}h2{{font-size:17px;break-after:avoid;page-break-after:avoid}}h3{{font-size:13px}}section{{padding:13px 0}}section>p{{margin:4px 0 8px;break-after:avoid;page-break-after:avoid}}.decision{{margin-top:10px;padding:8px 11px}}.model-row{{grid-template-columns:minmax(160px,1fr) 80px minmax(300px,2.2fr) minmax(150px,1fr);gap:13px;padding:8px 0;break-inside:avoid;page-break-inside:avoid}}.macro{{font-size:23px}}.endpoint-grid{{gap:14px}}.endpoint-panel,.facts,.cost-table tr,.stability-table tr,table tr{{break-inside:avoid;page-break-inside:avoid}}thead{{display:table-header-group}}tfoot{{display:table-footer-group}}table{{font-size:8.3px;table-layout:auto}}th,td{{padding:4px 5px;white-space:normal;overflow-wrap:anywhere;word-break:break-word}}th small,td small{{font-size:7.3px}}td code{{max-width:none;font-size:6.8px;line-height:1.2}}.score-table td,.cost-table td,.cost-table th{{min-width:0}}.cost-table .measure,.score-table .measure{{width:calc(100% - 42px)}}.facts{{grid-template-columns:repeat(5,minmax(0,1fr));margin-bottom:9px}}.facts>div{{padding:6px}}.subhead{{margin:10px 0 4px}}details{{display:none}}.audit ul{{font-size:8.5px}}.audit li+li{{margin-top:3px}}}}
</style></head><body><main><header><p>2026-08-17 · 固定 18 题 · 每 endpoint 单流 · 所有耗时为 18 题串行墙钟时间</p><h1>湖仓推理参数矩阵</h1><div>将模型选择、DeepSeek 质量、成本、稳定性和审计证据拆开比较。SQL 为可执行验证，Python 使用隐藏测试，故障分析以编码化根因与动作评分。</div></header>
<nav><a href='#qwen'>Qwen 选型</a><a href='#quality'>DeepSeek 质量</a><a href='#cost'>DeepSeek 成本</a><a href='#performance'>推理性能</a><a href='#startup'>冷启动</a><a href='#environment'>环境</a><a href='#audit'>审计</a></nav>
<div class='decision'><strong>当前结论</strong><div>{esc(args.recommendation)}</div></div>
<section id='qwen'><h2>Qwen 选型：同一 RTX 4090，质量与耗时并列</h2><p>仅比较同机、CPU offload=0 的两组推荐 thinking 配置。DeepSeek 不进入此处的延迟比较。</p><div class='model-list'>{qwen_section(grouped)}</div></section>
<section id='quality'><h2>DeepSeek 质量：先分 endpoint，再比较思考档位</h2><p>每格为对应能力的平均通过率；宏平均是三类能力等权平均。online 的动态 alias 与 private 固定 revision 不能解释为同模型 A/B。</p><div class='endpoint-grid'>{deepseek_score_section(grouped)}</div></section>
<section id='cost'><h2>DeepSeek 成本：耗时与输出 tokens 独立刻度</h2><p>条形长度仅在同一指标内比较，不把时延、token 或正确率折叠成单一分数。</p><div class='table-wrap'><table class='cost-table'><thead><tr><th>endpoint / 档位</th><th>18 题总耗时</th><th>输出 tokens</th><th>截断</th><th>空 final</th><th>HTTP/网络错误</th></tr></thead><tbody>{deepseek_cost_rows(grouped)}</tbody></table></div></section>
<section id='stability'><h2>重复稳定性：每个圆点是一轮宏平均</h2><p>横轴为 0% 到 100%；这里显示随机采样的实际波动，而不是只显示均值。</p><div class='table-wrap'><table class='stability-table'><thead><tr><th>endpoint / 档位</th><th>轮次位置</th><th>均值</th><th>标准差</th></tr></thead><tbody>{run_stability_rows(grouped)}</tbody></table></div></section>
{operational_sections}
<section id='audit' class='audit'><h2>审计与方法边界</h2><p><strong>评分勘误：</strong><code>cdc_latest_live</code> 因 v1 题面未解释 I/U/D 被剔除；<code>stable_toposort</code> 按字典插入顺序修正预期并执行异常检查。原始证据不改写，表内同时保留原始宏平均。</p><details><summary>显示每次运行、证据文件与原始汇总</summary><div class='table-wrap'><table><thead><tr><th>处理组</th><th>重复</th><th>裁决后宏平均</th><th>原始宏平均</th><th>耗时</th><th>输出 tokens</th><th>截断</th><th>空 final</th><th>错误</th><th>证据文件</th></tr></thead><tbody>{run_rows(grouped)}</tbody></table></div><div class='table-wrap'><table><thead><tr><th>处理组</th><th>endpoint</th><th>模型</th><th>模式</th><th>effort</th><th>输出上限</th><th>采样/协议</th><th>提交的响应证据</th></tr></thead><tbody>{config_rows(grouped)}</tbody></table></div></details><ul><li>DeepSeek 每组只完成 n=2；标准差只描述这两轮观测，不足以证明稳定性优势。high 是风险保守默认，不是统计显著结论。</li><li>online 使用官方 <code>thinking</code> 与 <code>reasoning_effort</code> 请求字段并开启 SSE；private DSpark 使用已验证的 chat-template thinking 开关并传相同 effort。</li><li>online-high-r2 出现 1 个空 final；错误、空 final 与 length 截断分别统计。</li><li>GB10 private max/384K 的 504 目前是 Nginx read-timeout 的高置信假设，仍需 NAS 上 <code>nginx -T</code>、error log/request-id 及 SSE/non-stream A/B 证实，不能写成已确认根因。</li><li>每题在评分后只提交 final/reasoning 前缀、完整字符数和 SHA-256；评分发生在截断存储之前。</li><li>online 仅提供动态 alias <code>deepseek-v4-flash</code>；private 使用固定 <code>deepseek-v4-flash-0731</code>。硬件、服务 revision 与网络路径不同。</li></ul></section>
</main></body></html>"""
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(line.rstrip() for line in document.splitlines()) + "\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
