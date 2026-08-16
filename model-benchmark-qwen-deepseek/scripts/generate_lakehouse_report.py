#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


LABELS = {
    "q36_off": "Qwen3.6 FP8 · non-thinking",
    "q36_thinking": "Qwen3.6 FP8 · thinking",
    "q38_off": "Qwen3.8 FP8 · non-thinking",
    "q38_thinking": "Qwen3.8 FP8 · thinking-low",
}
CATEGORIES = {"sql": "复杂 SQL", "python": "Python", "incident": "故障分析"}
COLORS = {"q36_off": "#3c8fc9", "q36_thinking": "#65c7a2", "q38_off": "#e78a45", "q38_thinking": "#d26bd3"}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def load_inputs(paths: dict[str, Path]) -> dict[str, dict]:
    values = {key: json.loads(path.read_text()) for key, path in paths.items()}
    harnesses = {value.get("harness_id") for value in values.values()}
    if harnesses != {"lakehouse-thinking-v1"}:
        raise RuntimeError(f"harness identity mismatch: {sorted(str(item) for item in harnesses)}")
    identities = [[(case["id"], case["category"]) for case in value["cases"]] for value in values.values()]
    if any(identity != identities[0] for identity in identities[1:]):
        raise RuntimeError("case identity mismatch")
    return values


def summary_rows(values: dict[str, dict]) -> str:
    rows = []
    for key, value in values.items():
        categories = value["categories"]
        tokens = sum(item["completion_tokens"] for item in categories.values())
        truncations = sum(item["length_truncations"] for item in categories.values())
        empty = sum(item["empty_finals"] for item in categories.values())
        rows.append(
            f"<tr><td><span class='dot' style='background:{COLORS[key]}'></span>{LABELS[key]}</td>"
            f"<td>{pct(categories['sql']['score'])}</td><td>{pct(categories['python']['score'])}</td>"
            f"<td>{pct(categories['incident']['score'])}</td><td><strong>{pct(value['macro_score'])}</strong></td>"
            f"<td>{value['total_seconds']:.1f}s</td><td>{tokens:,}</td><td>{truncations}</td><td>{empty}</td></tr>"
        )
    return "".join(rows)


def category_bars(values: dict[str, dict]) -> str:
    groups = []
    for category, category_label in CATEGORIES.items():
        bars = []
        for key, value in values.items():
            score = value["categories"][category]["score"]
            bars.append(
                f"<div class='bar-line'><span>{esc(LABELS[key])}</span><div class='track'><i style='width:{score*100:.1f}%;background:{COLORS[key]}'></i></div><strong>{pct(score)}</strong></div>"
            )
        groups.append(f"<section class='bar-group'><h3>{category_label}</h3>{''.join(bars)}</section>")
    return "".join(groups)


def case_sections(values: dict[str, dict]) -> str:
    indexes = {key: {case["id"]: case for case in value["cases"]} for key, value in values.items()}
    baseline = next(iter(values.values()))["cases"]
    sections = []
    for category, category_label in CATEGORIES.items():
        details = []
        for case in (item for item in baseline if item["category"] == category):
            scores = " · ".join(f"{LABELS[key]} {pct(indexes[key][case['id']]['score'])}" for key in values)
            answers = []
            for key in values:
                item = indexes[key][case["id"]]
                response = item.get("response") or ""
                reasoning = item.get("reasoning") or ""
                detail = json.dumps(item.get("detail"), ensure_ascii=False, indent=2)
                final = f"<pre>{esc(response)}</pre>" if response else "<div class='empty'>未返回 final content</div>"
                thought = f"<details class='nested'><summary>reasoning</summary><pre>{esc(reasoning)}</pre></details>" if reasoning else ""
                answers.append(
                    f"<article><h4>{LABELS[key]}</h4><div class='metrics'>{pct(item['score'])} · {item['seconds']:.1f}s · {esc(item.get('finish_reason'))}</div>{final}{thought}<details class='nested'><summary>评分细节</summary><pre>{esc(detail)}</pre></details></article>"
                )
            details.append(
                f"<details class='case'><summary><span>{esc(case['id'])}</span><span>{esc(scores)}</span></summary><div class='prompt'>{esc(case['prompt'])}</div><div class='answers'>{''.join(answers)}</div></details>"
            )
        sections.append(f"<section class='report-section' id='{category}'><h2>{category_label}逐题证据</h2>{''.join(details)}</section>")
    return "".join(sections)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--q36-off", type=Path, required=True)
    parser.add_argument("--q36-thinking", type=Path, required=True)
    parser.add_argument("--q38-off", type=Path, required=True)
    parser.add_argument("--q38-thinking", type=Path, required=True)
    parser.add_argument("--recommendation", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = {key: getattr(args, key) for key in LABELS}
    values = load_inputs(paths)
    document = f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Qwen3.6 vs Qwen3.8 湖仓推理 Benchmark</title><style>
:root{{--bg:#0b1013;--panel:#141b20;--panel2:#1b242b;--line:#33414b;--text:#f4f7f8;--muted:#9cabb5;--ok:#65c7a2;--warn:#f0bb58;color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 system-ui,"Segoe UI",sans-serif;letter-spacing:0}}main{{width:min(1240px,calc(100% - 28px));margin:auto;padding:28px 0 60px}}h1{{font-size:30px;line-height:1.2;margin:4px 0 8px}}h2{{font-size:21px;margin:0 0 10px}}h3{{font-size:16px}}h4{{font-size:14px;margin:0}}.muted,.metrics{{color:var(--muted)}}header{{border-bottom:1px solid var(--line);padding-bottom:20px}}nav{{display:flex;gap:18px;flex-wrap:wrap;position:sticky;top:0;background:rgba(11,16,19,.96);z-index:3;padding:13px 0;border-bottom:1px solid var(--line)}}nav a{{color:var(--muted);text-decoration:none}}.decision{{border-left:3px solid var(--ok);padding:14px 16px;background:var(--panel);margin:22px 0}}.report-section{{padding:26px 0;border-bottom:1px solid var(--line)}}.table-wrap{{overflow-x:auto}}table{{border-collapse:collapse;width:100%}}th,td{{padding:9px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}th:first-child,td:first-child{{text-align:left}}th{{color:var(--muted);font-weight:500}}.dot{{display:inline-block;width:10px;height:10px;margin-right:7px}}.bars{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}}.bar-group{{background:var(--panel);border:1px solid var(--line);padding:14px;border-radius:6px}}.bar-line{{display:grid;grid-template-columns:140px 1fr 52px;align-items:center;gap:8px;margin:9px 0;font-size:12px}}.track{{height:15px;border:1px solid var(--line)}}.track i{{display:block;height:100%}}.case{{border-top:1px solid var(--line)}}.case>summary{{display:flex;justify-content:space-between;gap:18px;padding:13px 3px;cursor:pointer}}.case>summary span:last-child{{color:var(--muted);text-align:right;font-size:12px}}.prompt{{color:var(--muted);padding:8px 3px}}.answers{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;padding:8px 0 18px}}article{{min-width:0;background:var(--panel);border:1px solid var(--line);padding:12px;border-radius:5px}}.metrics{{margin:4px 0 8px;font-size:12px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;max-height:420px;overflow:auto;background:var(--panel2);padding:10px;margin:0;font:12px/1.5 ui-monospace,monospace}}.nested{{margin-top:8px;color:var(--muted)}}.nested pre{{margin-top:6px}}.empty{{border:1px solid var(--warn);color:var(--warn);padding:10px}}
@media(max-width:900px){{.bars{{grid-template-columns:1fr}}}}@media(max-width:680px){{main{{width:calc(100% - 18px);padding-top:18px}}h1{{font-size:24px}}.answers{{grid-template-columns:1fr}}.case>summary{{display:block}}.case>summary span{{display:block;text-align:left!important;margin-top:4px}}.bar-line{{grid-template-columns:110px 1fr 48px}}}}
</style></head><body><main><header><div class='muted'>RTX 4090 48 GiB · FP8 · vLLM 0.19.0 · 2026-08-17</div><h1>Qwen3.6 vs Qwen3.8 湖仓推理 Benchmark</h1><div class='muted'>18 道固定题：可执行 SQL、隐藏测试 Python、编码化故障诊断；四组原生 thinking/non-thinking 对比</div></header>
<nav><a href='#summary'>汇总</a><a href='#scores'>分类</a><a href='#method'>方法</a><a href='#sql'>SQL</a><a href='#python'>Python</a><a href='#incident'>故障</a></nav>
<div class='decision'><strong>选型结论</strong><div>{esc(args.recommendation)}</div></div>
<section id='summary' class='report-section'><h2>结果汇总</h2><div class='table-wrap'><table><thead><tr><th>处理组</th><th>SQL</th><th>Python</th><th>故障</th><th>宏平均</th><th>总耗时</th><th>输出 tokens</th><th>截断</th><th>空 final</th></tr></thead><tbody>{summary_rows(values)}</tbody></table></div></section>
<section id='scores' class='report-section'><h2>分类对比</h2><div class='bars'>{category_bars(values)}</div></section>
<section id='method' class='report-section'><h2>方法与边界</h2><ul><li>两模型均使用 ModelScope 官方 FP8、同一 RTX 4090、同一固定 digest vLLM 0.19.0，CPU offload 为 0。</li><li>每组使用相同题目、最大 4096 输出 tokens 和 seed=42；non-thinking 与 thinking 分别使用官方推荐采样参数。</li><li>Qwen3.6 只有 thinking 开关；Qwen3.8 使用 reasoning_effort=low，两者不是相同强度的隐藏推理预算。</li><li>SQL 在 SQLite 内存库执行并精确比较结果；Python 在无网络、只读、非 root、128 MiB 容器执行；故障分析从固定 cause/action codes 选择并惩罚错误操作。</li><li>本集合用于本服务器湖仓工程选型，不替代大型公开 benchmark 或 48 小时压力测试。</li></ul></section>
{case_sections(values)}</main></body></html>"""
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(line.rstrip() for line in document.splitlines()) + "\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
