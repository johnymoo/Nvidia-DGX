#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the completed Claude Code benchmark as a self-contained HTML report."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
from typing import Any


TREATMENTS = ("online_ds", "offline_ds", "qwen_local")
TREATMENT_META = {
    "online_ds": {
        "name": "Online DeepSeek Flash",
        "short": "Online DS",
        "route": "claude_ds",
        "model": "deepseek-v4-flash",
        "class": "online",
    },
    "offline_ds": {
        "name": "Private DeepSeek Patch4",
        "short": "Private DS",
        "route": "claude_local",
        "model": "deepseek-v4-flash-0731",
        "class": "offline",
    },
    "qwen_local": {
        "name": "Private Qwen 3.6 35B",
        "short": "Qwen Local",
        "route": "claude_local",
        "model": "qwen3.6-35b-fp8",
        "class": "qwen",
    },
}
CRITERIA = ("accuracy", "following", "clarity_style")


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def treatment_for_preference(preference: str, mapping: dict[str, str]) -> str:
    return "tie" if preference == "tie" else mapping[preference]


def score_triplet(scores: dict[str, int] | None) -> str:
    if scores is None:
        return "未评分"
    return " / ".join(str(scores[key]) for key in CRITERIA)


def render_report(project_root: Path, artifact_root: Path, output: Path) -> None:
    manifest = read_json(project_root / "execution" / "benchmarks" / "claude-code-sandbox-pilot-tasks.json")
    state = read_json(artifact_root / "benchmark-state.json")
    results_path = artifact_root / "review" / "private" / "baseline-results.json"
    if not results_path.is_file():
        results_path = artifact_root / "review" / "private" / "reveal.json"
    reveal = read_json(results_path)
    sealed = read_json(artifact_root / "review" / "sealed" / "mappings.json")
    ratings_path = artifact_root / "review" / "private" / "ratings.json"
    ratings = read_json(ratings_path)["ratings"] if ratings_path.is_file() else {}
    if reveal.get("status") not in {"completed", "revealed"}:
        raise ValueError("benchmark results must be complete before rendering")

    attempts = {(item["task_id"], item["treatment"]): item for item in state["attempts"]}
    revealed_tasks = {item["task_id"]: item for item in reveal["tasks"]}
    tasks = manifest["tasks"]
    if len(tasks) != reveal.get("benchmark_task_count") or len(attempts) != len(tasks) * len(TREATMENTS):
        raise ValueError("unexpected benchmark shape")
    task_count = len(tasks)

    summaries: dict[str, dict[str, Any]] = {}
    judge_wins = {treatment: 0 for treatment in TREATMENTS}
    human_wins = {treatment: 0 for treatment in TREATMENTS}
    judge_ties = 0
    human_ties = 0
    for task in tasks:
        row = revealed_tasks[task["task_id"]]
        judge_choice = treatment_for_preference(row["judge_preference"], row["judge_mapping"])
        if judge_choice == "tie":
            judge_ties += 1
        else:
            judge_wins[judge_choice] += 1
        if row["human_scored"]:
            human_choice = treatment_for_preference(row["human_preference"], row["human_mapping"])
            if human_choice == "tie":
                human_ties += 1
            else:
                human_wins[human_choice] += 1

    for treatment in TREATMENTS:
        rows = [attempts[(task["task_id"], treatment)] for task in tasks]
        aggregate = reveal["aggregates"][treatment]
        summaries[treatment] = {
            **aggregate,
            "passed": sum(item["task_status"] == "passed" for item in rows),
            "elapsed": sum(float(item["elapsed_seconds"]) for item in rows),
            "mean_elapsed": mean([float(item["elapsed_seconds"]) for item in rows]),
            "turns": sum(int(item.get("num_turns") or 0) for item in rows),
            "tools": sum(len(item.get("tool_calls") or []) for item in rows),
            "judge_wins": judge_wins[treatment],
            "human_wins": human_wins[treatment],
        }

    ranked = sorted(TREATMENTS, key=lambda treatment: summaries[treatment]["quality_mean"], reverse=True)
    ranking_rows = []
    for rank, treatment in enumerate(ranked, 1):
        meta = TREATMENT_META[treatment]
        item = summaries[treatment]
        width = item["quality_mean"] / 3 * 100
        human_mean = f"{item['human_mean']:.3f}" if item["human_mean"] is not None else "--"
        ranking_rows.append(
            f'''<tr>
              <td class="rank">{rank}</td>
              <td><span class="model-key {meta['class']}"></span><strong>{esc(meta['name'])}</strong><small>{esc(meta['route'])} · {esc(meta['model'])}</small></td>
              <td><div class="score"><strong>{item['quality_mean']:.3f}</strong><span><i class="{meta['class']}" style="width:{width:.1f}%"></i></span></div></td>
              <td>{item['passed']}/{task_count}</td>
              <td>{item['judge_mean']:.3f}</td>
              <td>{human_mean}</td>
              <td>{item['elapsed']:.3f}s</td>
            </tr>'''
        )

    nav = "".join(f'<a href="#{esc(task["task_id"])}">{index:02d}</a>' for index, task in enumerate(tasks, 1))
    task_sections = []
    for index, task in enumerate(tasks, 1):
        task_id = task["task_id"]
        revealed = revealed_tasks[task_id]
        judge = sealed["judges"][task_id]
        judge_mapping = revealed["judge_mapping"]
        judge_choice = treatment_for_preference(revealed["judge_preference"], judge_mapping)
        judge_choice_text = "平局" if judge_choice == "tie" else TREATMENT_META[judge_choice]["name"]
        human_choice_text = "仅 GPT 评分"
        if revealed["human_scored"]:
            human_choice = treatment_for_preference(revealed["human_preference"], revealed["human_mapping"])
            human_choice_text = "平局" if human_choice == "tie" else TREATMENT_META[human_choice]["name"]

        answers = []
        for treatment in TREATMENTS:
            meta = TREATMENT_META[treatment]
            attempt = attempts[(task_id, treatment)]
            judge_label = next(label for label, value in judge_mapping.items() if value == treatment)
            judge_scores = judge["candidates"][judge_label]
            human_scores = None
            if revealed["human_scored"] and task_id in ratings:
                human_label = next(label for label, value in revealed["human_mapping"].items() if value == treatment)
                human_scores = ratings[task_id]["scores"][human_label]
            hidden = attempt["hidden_grader"]
            quality = revealed["scores"][treatment]["quality"]
            task_status = "通过" if attempt["task_status"] == "passed" else "失败"
            answers.append(
                f'''<article class="answer {meta['class']}">
                  <header><span class="model-key {meta['class']}"></span><div><h3>{esc(meta['name'])}</h3><small>{esc(meta['route'])} · {esc(meta['model'])}</small></div><strong class="quality">{quality:.3f}</strong></header>
                  <dl>
                    <div><dt>隐藏测试</dt><dd>{esc(hidden['passed'])}/{esc(hidden['total'])} · {task_status}</dd></div>
                    <div><dt>GPT 准确/遵循/表达</dt><dd>{score_triplet(judge_scores)}</dd></div>
                    <div><dt>人工 准确/遵循/表达</dt><dd>{score_triplet(human_scores)}</dd></div>
                    <div><dt>耗时</dt><dd>{float(attempt['elapsed_seconds']):.3f}s</dd></div>
                  </dl>
                  <pre>{esc(attempt['review_artifact'])}</pre>
                </article>'''
            )

        task_sections.append(
            f'''<section class="task" id="{esc(task_id)}">
              <div class="task-head"><span>{index:02d}</span><div><p>{esc(task['category'])}</p><h2>{esc(task['title'])}</h2></div></div>
              <div class="prompt"><strong>题目要求</strong><p>{esc(task['instruction'])}</p></div>
              <div class="answers">{''.join(answers)}</div>
              <aside class="verdict"><div><strong>GPT 偏好</strong><p>{esc(judge_choice_text)}</p></div><div><strong>人工偏好</strong><p>{esc(human_choice_text)}</p></div><blockquote><strong>GPT 评审结论</strong><br>{esc(judge['rationale'])}</blockquote></aside>
            </section>'''
        )

    human_summary = []
    for task in tasks:
        row = revealed_tasks[task["task_id"]]
        if row["human_scored"]:
            choice = treatment_for_preference(row["human_preference"], row["human_mapping"])
            human_summary.append(f'{esc(task["title"])}: <strong>{esc(TREATMENT_META[choice]["name"] if choice != "tie" else "平局")}</strong>')

    domain_labels = {"legacy": "原有 R2", "terminal": "终端", "server_ops": "服务器运维", "writing": "文字处理", "programming": "编程"}
    domain_rows = []
    for domain in ("legacy", "terminal", "server_ops", "writing", "programming"):
        domain_tasks = [task for task in tasks if (task.get("r3_domain") or "legacy") == domain]
        if not domain_tasks:
            continue
        cells = []
        for treatment in TREATMENTS:
            value = mean([revealed_tasks[task["task_id"]]["scores"][treatment]["quality"] for task in domain_tasks])
            cells.append(f"<td>{value:.3f}</td>")
        domain_rows.append(f'<tr><td><strong>{domain_labels[domain]}</strong><small>{len(domain_tasks)} 题</small></td>{"".join(cells)}</tr>')

    claude_version = manifest["claude_code_version"]
    timeout_seconds = manifest["task_timeout_seconds"]
    document = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Claude Code 三模型评测 · 最终报告</title>
<style>
:root{{--bg:#f4f6f5;--surface:#fff;--surface-2:#eef2f0;--ink:#17211c;--muted:#5d6a63;--line:#cbd3cf;--online:#147d58;--offline:#356ea3;--qwen:#b66a13;--danger:#a63f43}}*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 Arial,"PingFang SC","Microsoft YaHei",sans-serif}}main{{max-width:1480px;margin:auto;padding:28px 22px 80px}}h1,h2,h3,p{{margin:0}}h1{{font-size:28px;font-weight:500}}h2{{font-size:19px;font-weight:500}}h3{{font-size:14px;font-weight:500}}small{{display:block;color:var(--muted)}}.eyebrow{{margin-bottom:5px;color:var(--muted);font-size:12px;text-transform:uppercase}}.intro{{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:24px;align-items:end;padding-bottom:22px;border-bottom:2px solid var(--ink)}}.intro .run{{text-align:right}}.intro .run strong{{display:block;font-size:16px}}.environment{{padding:24px 0;border-bottom:1px solid var(--line)}}.environment h2{{margin-bottom:12px}}.environment-lead{{display:flex;gap:14px;align-items:baseline;margin-bottom:14px}}.environment-lead strong{{font-size:18px;font-weight:500}}.environment-lead span{{color:var(--muted)}}.environment-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));border:1px solid var(--line);background:var(--surface)}}.environment-grid article{{padding:14px 16px}}.environment-grid article+article{{border-left:1px solid var(--line)}}.environment-grid h3{{margin-bottom:4px}}.environment-grid p{{color:var(--muted);font-size:12px}}.environment-note{{margin-top:12px;color:var(--muted);font-size:12px}}.summary{{padding:26px 0 30px}}.summary h2{{margin-bottom:14px}}table{{width:100%;border-collapse:collapse;background:var(--surface)}}th,td{{padding:12px 14px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}}th{{background:var(--surface-2);color:var(--muted);font-size:11px;font-weight:500;text-transform:uppercase}}td small{{margin-top:2px;font-size:11px}}.rank{{width:42px;font-size:18px}}.model-key{{display:inline-block;width:9px;height:9px;margin-right:8px;border-radius:50%}}.model-key.online,.score i.online{{background:var(--online)}}.model-key.offline,.score i.offline{{background:var(--offline)}}.model-key.qwen,.score i.qwen{{background:var(--qwen)}}.score{{display:grid;grid-template-columns:48px minmax(90px,150px);gap:8px;align-items:center}}.score span{{height:7px;background:var(--surface-2)}}.score i{{display:block;height:100%}}.preferences{{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:18px}}.preferences div{{padding:13px 15px;border-left:4px solid var(--line);background:var(--surface)}}.preferences strong{{font-weight:500}}.preferences p+p{{margin-top:4px}}.task-nav{{position:sticky;top:0;z-index:5;display:flex;gap:8px;align-items:center;padding:10px 0;background:var(--bg);border-top:1px solid var(--line);border-bottom:1px solid var(--line)}}.task-nav strong{{margin-right:8px;font-weight:500}}.task-nav a{{display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;border:1px solid var(--line);border-radius:4px;background:var(--surface);color:var(--ink);text-decoration:none}}.task{{scroll-margin-top:64px;padding:34px 0;border-bottom:2px solid var(--ink)}}.task-head{{display:flex;gap:12px;align-items:flex-start;margin-bottom:14px}}.task-head>span{{display:flex;align-items:center;justify-content:center;width:34px;height:34px;background:var(--ink);color:var(--surface);font-weight:500}}.task-head p{{color:var(--muted);font-size:11px;text-transform:uppercase}}.prompt{{display:grid;grid-template-columns:110px minmax(0,1fr);gap:16px;margin-bottom:18px;padding:14px 16px;background:var(--surface-2)}}.answers{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));border:1px solid var(--line);background:var(--surface)}}.answer{{min-width:0;padding:16px}}.answer+.answer{{border-left:1px solid var(--line)}}.answer header{{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;margin-bottom:13px}}.answer header small{{font-size:10px}}.quality{{font-size:17px;font-weight:500}}.answer.online .quality{{color:var(--online)}}.answer.offline .quality{{color:var(--offline)}}.answer.qwen .quality{{color:var(--qwen)}}dl{{display:grid;grid-template-columns:1fr 1fr;margin:0 0 14px;background:var(--surface-2)}}dl div{{padding:7px 9px;border-bottom:1px solid var(--line)}}dt{{color:var(--muted);font-size:10px;text-transform:uppercase}}dd{{margin:1px 0 0;font-size:12px}}pre{{min-height:180px;margin:0;padding:12px;background:#202723;color:#f1f5f2;white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}.verdict{{display:grid;grid-template-columns:170px 170px minmax(0,1fr);gap:0;margin-top:12px;border:1px solid var(--line);background:var(--surface)}}.verdict>div{{padding:12px 14px;border-right:1px solid var(--line)}}.verdict strong{{color:var(--muted);font-size:10px;text-transform:uppercase}}.verdict p{{margin-top:3px;font-weight:500}}blockquote{{margin:0;padding:12px 16px;color:var(--muted)}}.footnote{{margin-top:24px;color:var(--muted);font-size:12px}}@media(max-width:980px){{.environment-grid,.answers{{grid-template-columns:1fr}}.environment-grid article+article{{border-top:1px solid var(--line);border-left:0}}.answer+.answer{{border-top:1px solid var(--line);border-left:0}}pre{{min-height:0}}.verdict{{grid-template-columns:1fr 1fr}}blockquote{{grid-column:1/-1;border-top:1px solid var(--line)}}}}@media(max-width:700px){{main{{padding:18px 12px 60px}}h1{{font-size:23px}}.intro{{grid-template-columns:1fr}}.intro .run{{text-align:left}}.environment-lead{{display:block}}.table-wrap{{overflow-x:auto}}table{{min-width:760px}}.preferences{{grid-template-columns:1fr}}.task-nav{{overflow-x:auto}}.prompt{{grid-template-columns:1fr}}.verdict{{grid-template-columns:1fr}}.verdict>div{{border-right:0;border-bottom:1px solid var(--line)}}blockquote{{grid-column:auto}}}}
</style>
</head>
<body>
<main>
  <header class="intro"><div><p class="eyebrow">三组模型 · 最终结果</p><h1>Claude Code 三模型评测</h1></div><div class="run"><small>运行编号</small><strong>{esc(artifact_root.name)}</strong><small>{task_count * 3} 次候选执行 · {task_count} 次 GPT 评审 · {len(ratings)} 次可选人工写作评分</small></div></header>
  <section class="environment"><h2>测试环境</h2><div class="environment-lead"><strong>三组候选任务全部通过 Claude Code {esc(claude_version)} 执行</strong><span>相同的 {task_count} 道题、隔离 Git 沙盒、工具策略、{esc(timeout_seconds)} 秒任务上限；每组每题执行一次。</span></div><div class="environment-grid"><article><h3><span class="model-key online"></span>Online DeepSeek Flash</h3><p><code>claude_ds</code> → 在线 Flash 路由 <code>deepseek-v4-flash</code></p></article><article><h3><span class="model-key offline"></span>Private DeepSeek Patch4</h3><p><code>claude_local</code> → 双机 GB10 Patch4 服务 <code>deepseek-v4-flash-0731</code></p></article><article><h3><span class="model-key qwen"></span>Private Qwen 3.6 35B</h3><p><code>claude_local</code> → GB10 <code>:8004</code> 上的 <code>qwen3.6-35b-fp8</code></p></article></div><p class="environment-note">GPT <code>gpt-5.6-sol/xhigh</code> 只对保存后的匿名答案进行独立盲评，不参与完成候选任务。DeepSeek 与 Qwen 因 GB10 内存限制而串行运行。</p></section>
  <section class="summary"><h2>综合排名</h2><div class="table-wrap"><table><thead><tr><th>排名</th><th>模型</th><th>综合分 / 3</th><th>通过数</th><th>GPT 评分</th><th>可选人工写作</th><th>总耗时</th></tr></thead><tbody>{''.join(ranking_rows)}</tbody></table></div><h2>分领域得分</h2><div class="table-wrap"><table><thead><tr><th>领域</th><th>Online DS</th><th>Private DS</th><th>Qwen Local</th></tr></thead><tbody>{''.join(domain_rows)}</tbody></table></div><div class="preferences"><div><strong>GPT 偏好统计</strong><p>Online DS {judge_wins['online_ds']} · Private DS {judge_wins['offline_ds']} · Qwen {judge_wins['qwen_local']} · 平局 {judge_ties}</p></div><div><strong>可选人工写作偏好</strong><p>{(' · '.join(human_summary) + (f' · 平局 {human_ties}' if human_ties else '')) if human_summary else '尚未进行；不影响最终排名'}</p></div></div></section>
  <nav class="task-nav"><strong>题目</strong>{nav}</nav>
  {''.join(task_sections)}
  <p class="footnote">全部题目的综合分统一取确定性隐藏测试档位与 GPT 评审分的平均值；人工写作评分仅单独展示，不改变综合排名。不同路由的 token、缓存与成本口径不可直接比较。本次每组仅执行一次，不构成统计显著性结论。</p>
</main>
</body>
</html>'''
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    render_report(args.project_root.resolve(), args.artifact_root.resolve(), args.output.resolve())
    content = args.output.resolve().read_bytes()
    print(json.dumps({"status": "rendered", "output": str(args.output.resolve()), "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}))


if __name__ == "__main__":
    main()
