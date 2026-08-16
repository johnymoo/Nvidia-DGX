#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import statistics
from pathlib import Path


LABELS = {
    "image_recognition": "图片识别",
    "programming": "编程",
    "article_writing": "文章写作约束",
    "mathematical_reasoning": "数学推理",
}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:.1f}%"


def answer(case: dict) -> str:
    return str(case.get("response") or case.get("content") or case.get("actual") or "")


def verdict(case: dict) -> str:
    if "passed" in case:
        return "通过" if case["passed"] else "未通过"
    return f"{case['points']} / {case['max_points']}"


def validation_detail(case: dict) -> str:
    checks = (case.get("detail") or {}).get("checks") or {}
    if not checks:
        return ""
    return '<ul class="checks">' + "".join(
        f"<li>{esc(name)}: {'通过' if passed else '未通过'}</li>" for name, passed in checks.items()
    ) + "</ul>"


def model_answer(name: str, case: dict) -> str:
    reasoning = case.get("reasoning") or ""
    response = answer(case)
    answer_html = f"<pre>{esc(response)}</pre>" if response else '<div class="empty-answer">模型未返回 final content</div>'
    metadata_html = ""
    if not response:
        finish_reason = case.get("finish_reason")
        metadata_html = f'<div class="response-meta">finish_reason：{esc(finish_reason) if finish_reason is not None else "本次运行未记录"}</div>'
    reasoning_html = ""
    if reasoning:
        reasoning_html = f'<details class="reasoning"><summary>查看模型推理字段</summary><pre>{esc(reasoning)}</pre></details>'
    return f"""
    <section><h4>{esc(name)} 实际回答</h4>{answer_html}{metadata_html}
      <div class="validation">验证：{esc(verdict(case))}</div>{validation_detail(case)}{reasoning_html}
    </section>"""


def case_sections(q36: dict, q38: dict, deepseek: dict) -> str:
    sections = []
    for category in LABELS:
        left = q36["categories"][category]
        right = q38["categories"][category]
        right_cases = {case["id"]: case for case in right["cases"]}
        ds_category = deepseek["categories"].get(category)
        ds_cases = {case["id"]: case for case in ds_category["cases"]} if ds_category else {}
        rows = []
        for index, lcase in enumerate(left["cases"], 1):
            rcase = right_cases[lcase["id"]]
            dcase = ds_cases.get(lcase["id"])
            expected = lcase.get("expected")
            expected_html = (
                f'<div class="expected"><strong>期望/验证：</strong><pre>{esc(expected)}</pre></div>'
                if expected is not None
                else '<div class="expected"><strong>Rubric：</strong>见各模型逐项检查</div>'
            )
            scores = f"Qwen3.6 {verdict(lcase)} · Qwen3.8 {verdict(rcase)}"
            if dcase:
                scores += f" · DeepSeek {verdict(dcase)}"
            else:
                scores += " · DeepSeek N/A"
            answers = model_answer("Qwen3.6", lcase) + model_answer("Qwen3.8", rcase)
            if dcase:
                answers += model_answer("DeepSeek-V4-Flash-0731", dcase)
            rows.append(f"""
            <details class="case">
              <summary><span>{index}. {esc(lcase['id'])}</span><span class="case-score">{esc(scores)}</span></summary>
              <div class="question"><strong>题目：</strong>{esc(lcase.get('prompt', ''))}</div>
              {expected_html}<div class="answers {'three' if dcase else ''}">{answers}</div>
            </details>""")
        meta = f"Qwen3.6 {pct(left['score'])} · Qwen3.8 {pct(right['score'])}"
        meta += f" · DeepSeek {pct(ds_category['score'])}" if ds_category else " · DeepSeek N/A（非多模态）"
        sections.append(f"""
        <section id="cases-{category}" class="report-section">
          <h2>{LABELS[category]}逐题结果</h2><p class="section-meta">{meta} · {len(left['cases'])} 题</p>
          {''.join(rows)}
        </section>""")
    return "".join(sections)


def quality_bars(comparison: dict) -> str:
    rows = []
    for key, values in comparison["categories"].items():
        ds = values.get("deepseek")
        ds_line = (
            f'<div class="bar-line"><span class="series-name">DeepSeek</span><div class="bar-track"><div class="bar ds" style="width:{ds * 100:.1f}%"></div></div><span>{pct(ds)}</span></div>'
            if ds is not None
            else '<div class="bar-line"><span class="series-name">DeepSeek</span><div class="bar-track na">非多模态，不适用</div><span>N/A</span></div>'
        )
        rows.append(f"""
        <div class="bar-row"><div class="bar-label">{LABELS[key]}</div><div class="bar-pair">
          <div class="bar-line"><span class="series-name">Qwen3.6</span><div class="bar-track"><div class="bar q36" style="width:{values['qwen36'] * 100:.1f}%"></div></div><span>{pct(values['qwen36'])}</span></div>
          <div class="bar-line"><span class="series-name">Qwen3.8</span><div class="bar-track"><div class="bar q38" style="width:{values['qwen38'] * 100:.1f}%"></div></div><span>{pct(values['qwen38'])}</span></div>
          {ds_line}
        </div></div>""")
    return "".join(rows)


def summarize_deepseek_performance(raw: dict) -> dict:
    return {
        "single_stream": {row["label"]: row["best"]["tokens_per_second"] for row in raw["single_stream"]},
        "concurrency": {str(row["concurrency"]): row["aggregate_tokens_per_second"] for row in raw["concurrency"]},
        "prefill": {str(row["target_tokens"]): row["prefill_tokens_per_second"] for row in raw["prefill"]},
    }


def performance_rows(perf: dict, ds_perf: dict, section: str) -> str:
    rows = []
    for key, q36_value in perf["qwen36"][section].items():
        q38_value = perf["qwen38"][section][key]
        ds_value = ds_perf[section].get(key)
        rows.append(
            f"<tr><td>{esc(key)}</td><td>{q36_value:,.1f}</td><td>{q38_value:,.1f}</td>"
            f"<td>{ds_value:,.1f}</td><td>{pct(q38_value / q36_value)}</td><td>{pct(ds_value / q36_value)}</td></tr>"
        )
    return "".join(rows)


def quality_rows(quality: dict) -> str:
    rows = []
    for key, values in quality["categories"].items():
        rows.append(
            f"<tr><td>{LABELS[key]}</td><td>{pct(values['qwen36'])}</td><td>{pct(values['qwen38'])}</td>"
            f"<td>{pct(values.get('deepseek'))}</td><td>{values['total_cases']}</td></tr>"
        )
    return "".join(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--performance", type=Path, required=True)
    parser.add_argument("--deepseek-performance", type=Path, required=True)
    parser.add_argument("--qwen36-quality", type=Path, required=True)
    parser.add_argument("--qwen38-quality", type=Path, required=True)
    parser.add_argument("--deepseek-quality", type=Path, required=True)
    parser.add_argument("--quality-comparison", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--performance-receipt", default="benchmark-20260815T140326Z")
    parser.add_argument("--deepseek-performance-receipt", default="acceptance/20260811T002139Z/bench-full.json")
    parser.add_argument("--quality-receipt", default="quality-20260815T144141Z")
    parser.add_argument("--deepseek-quality-receipt", default="deepseek-quality-20260816")
    parser.add_argument("--deepseek-endpoint-label", default="http://localhost:8890/v1")
    parser.add_argument("--final-model", default="Qwen3.6")
    args = parser.parse_args()
    perf = json.loads(args.performance.read_text())
    ds_perf_raw = json.loads(args.deepseek_performance.read_text())
    q36 = json.loads(args.qwen36_quality.read_text())
    q38 = json.loads(args.qwen38_quality.read_text())
    deepseek = json.loads(args.deepseek_quality.read_text())
    quality = json.loads(args.quality_comparison.read_text())
    ds_perf = summarize_deepseek_performance(ds_perf_raw)
    q36_single = statistics.fmean(perf["qwen36"]["single_stream"].values())
    q38_single = statistics.fmean(perf["qwen38"]["single_stream"].values())
    ds_single = statistics.fmean(ds_perf["single_stream"].values())
    ds_cases = [case for category in deepseek["categories"].values() for case in category["cases"]]
    ds_final_answers = sum(bool(answer(case)) for case in ds_cases)
    ds_missing_final = len(ds_cases) - ds_final_answers

    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Qwen3.6、Qwen3.8 与 DeepSeek-V4-Flash-0731 完整评测</title>
<style>
:root{{--bg:#0c0f12;--surface:#14191e;--surface2:#1a2026;--text:#f2f5f7;--muted:#9ca8b2;--line:#303943;--q36:#55a7e8;--q38:#f28b48;--ds:#62c58b;--good:#58c58b;--warn:#f1c45b;color-scheme:dark}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;letter-spacing:0}}main{{width:min(1220px,calc(100% - 32px));margin:auto;padding:28px 0 64px}}h1,h2,h3,h4{{font-weight:600;letter-spacing:0}}h1{{font-size:30px;line-height:1.2;margin:0}}h2{{font-size:21px;margin:0 0 6px}}h3{{font-size:16px}}h4{{margin:0 0 8px;font-size:14px}}.eyebrow,.muted,.section-meta{{color:var(--muted)}}.eyebrow{{margin-bottom:8px}}.top{{display:flex;justify-content:space-between;gap:24px;align-items:flex-start;border-bottom:1px solid var(--line);padding-bottom:20px}}.state{{text-align:right}}.state strong{{color:var(--good)}}nav{{display:flex;gap:18px;flex-wrap:wrap;padding:14px 0;border-bottom:1px solid var(--line);position:sticky;top:0;background:rgba(12,15,18,.96);z-index:3}}nav a{{color:var(--muted);text-decoration:none}}nav a:hover{{color:var(--text)}}.summary{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:22px 0}}.stat{{background:var(--surface);border:1px solid var(--line);padding:14px;border-radius:6px}}.stat span{{display:block;color:var(--muted)}}.stat strong{{display:block;font-size:23px;margin:4px 0}}.report-section{{padding:28px 0;border-bottom:1px solid var(--line)}}.config-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}}.config{{background:var(--surface);border:1px solid var(--line);padding:16px;border-radius:6px}}table{{width:100%;border-collapse:collapse;margin-top:14px}}th,td{{text-align:right;padding:9px 10px;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}}th:first-child,td:first-child{{text-align:left}}th{{color:var(--muted);font-weight:500}}.legend{{display:flex;gap:18px;flex-wrap:wrap;margin:14px 0;color:var(--muted)}}.legend i{{display:inline-block;width:11px;height:11px;margin-right:6px}}.bar-row{{display:grid;grid-template-columns:150px 1fr;gap:14px;align-items:center;margin:16px 0}}.bar-pair{{display:grid;gap:6px}}.bar-line{{display:grid;grid-template-columns:76px 1fr 68px;gap:8px;align-items:center}}.series-name{{color:var(--muted);font-size:13px}}.bar-track{{height:18px;border:1px solid var(--line);overflow:hidden}}.bar-track.na{{font-size:11px;color:var(--muted);padding:0 6px;line-height:16px}}.bar{{height:100%}}.q36{{background:var(--q36)}}.q38{{background:var(--q38)}}.ds{{background:var(--ds)}}.case{{border-top:1px solid var(--line)}}.case summary{{cursor:pointer;display:flex;justify-content:space-between;gap:16px;padding:13px 4px}}.case-score{{color:var(--muted);text-align:right}}.question,.expected{{padding:8px 4px;color:var(--muted)}}.answers{{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:8px 0 18px}}.answers.three{{grid-template-columns:repeat(3,minmax(0,1fr))}}.answers>section{{min-width:0;background:var(--surface);border:1px solid var(--line);padding:12px;border-radius:5px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;max-height:460px;overflow:auto;background:var(--surface2);padding:11px;border-radius:4px;color:var(--text);font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}}.validation{{margin-top:8px;color:var(--good)}}.checks{{margin:8px 0 0;padding-left:18px;color:var(--muted)}}.reasoning{{margin-top:10px;color:var(--muted)}}.reasoning pre{{margin-top:8px}}.empty-answer{{border:1px solid var(--warn);padding:11px;color:var(--warn)}}.response-meta{{margin-top:6px;color:var(--muted);font-size:12px}}.setup li{{margin:6px 0}}code{{color:var(--text)}}.note{{border-left:3px solid var(--warn);padding:8px 12px;color:var(--muted)}}button{{background:transparent;color:var(--text);border:1px solid var(--line);border-radius:4px;padding:7px 10px;cursor:pointer}}
@media(max-width:900px){{.config-grid,.answers.three{{grid-template-columns:1fr}}}}@media(max-width:760px){{main{{width:min(100% - 20px,1220px);padding-top:18px}}h1{{font-size:24px}}.top{{display:block}}.state{{text-align:left;margin-top:12px}}.summary{{grid-template-columns:1fr 1fr}}.config-grid,.answers{{grid-template-columns:1fr}}.bar-row{{grid-template-columns:1fr;gap:5px}}.bar-line{{grid-template-columns:70px 1fr 54px}}.case summary{{display:block}}.case-score{{display:block;text-align:left;margin-top:5px}}.table-wrap{{overflow-x:auto}}th,td{{padding:7px 6px;font-size:12px;white-space:nowrap}}}}@media(max-width:430px){{.summary{{grid-template-columns:1fr}}}}
</style></head><body><main>
<header class="top"><div><div class="eyebrow">X570 RTX 3090 + 双 NVIDIA GB10 · 更新于 2026-08-16</div><h1>Qwen3.6、Qwen3.8 与 DeepSeek-V4-Flash-0731</h1><p class="muted">性能、图片、编程、写作与数学推理对比；DeepSeek 不参与图片识别</p></div><div class="state"><span>最终 Qwen 生产</span><strong>{esc(args.final_model)} 在线</strong><div>Qwen3.8 已停止 · DeepSeek 独立在线</div><div>OPF :8765 当前未监听（本次未触碰）</div></div></header>
<nav><a href="#summary">汇总</a><a href="#config">配置</a><a href="#setup">Setup</a><a href="#performance">性能</a><a href="#quality">精度</a><a href="#cases-image_recognition">逐题回答</a><button id="toggle">展开全部题目</button></nav>
<section id="summary" class="summary">
  <div class="stat"><span>质量宏平均（4 类）</span><strong>{pct(quality['qwen36_macro'])}</strong><small>Qwen3.6</small></div>
  <div class="stat"><span>质量宏平均（4 类）</span><strong>{pct(quality['qwen38_macro'])}</strong><small>Qwen3.8</small></div>
  <div class="stat"><span>质量宏平均（3 类）</span><strong>{pct(quality['deepseek_macro'])}</strong><small>DeepSeek，排除图片</small></div>
  <div class="stat"><span>单流生成均值</span><strong>{q36_single:.1f} tok/s</strong><small>Qwen3.6 · X570</small></div>
  <div class="stat"><span>单流生成均值</span><strong>{q38_single:.1f} tok/s</strong><small>Qwen3.8 · X570</small></div>
  <div class="stat"><span>单流生成均值</span><strong>{ds_single:.1f} tok/s</strong><small>DeepSeek · 双 GB10</small></div>
</section>
<section id="config" class="report-section"><h2>模型与运行配置</h2><div class="config-grid">
  <article class="config"><h3>Qwen3.6-35B-A3B</h3><table><tr><td>权重</td><td>UD-IQ3_S GGUF</td></tr><tr><td>结构</td><td>35B A3B MoE</td></tr><tr><td>硬件</td><td>X570 / RTX 3090</td></tr><tr><td>总 context</td><td>262,144</td></tr><tr><td>并行槽</td><td>4</td></tr><tr><td>每槽 context</td><td>65,536</td></tr></table></article>
  <article class="config"><h3>Qwen3.8-27B</h3><table><tr><td>权重</td><td>Q3_K_S GGUF</td></tr><tr><td>参数</td><td>27,320,697,856</td></tr><tr><td>硬件</td><td>X570 / RTX 3090</td></tr><tr><td>总 context</td><td>131,072</td></tr><tr><td>并行槽</td><td>2</td></tr><tr><td>每槽 context</td><td>65,536</td></tr></table></article>
  <article class="config"><h3>DeepSeek-V4-Flash-0731</h3><table><tr><td>运行时</td><td>vLLM f277b3d</td></tr><tr><td>硬件</td><td>2 × NVIDIA GB10</td></tr><tr><td>并行</td><td>TP=2</td></tr><tr><td>最大 context</td><td>1,048,576</td></tr><tr><td>KV cache</td><td>NVFP4 MLA</td></tr><tr><td>MTP</td><td>5</td></tr></table></article>
</div></section>
<section id="setup" class="report-section setup"><h2>Setup 与证据</h2><ol>
  <li>Qwen3.6 与 Qwen3.8 性能结果来自同一 X570 / RTX 3090 上串行运行的同一 harness；DeepSeek 性能来自双 GB10 官方验收中的同一 <code>bench_full.py</code>。</li>
  <li>DeepSeek 实时模型身份为 <code>deepseek-v4-flash-0731</code>，OpenAI API 为 <code>{esc(args.deepseek_endpoint_label)}</code>；评测未重启或修改服务。</li>
  <li>质量 harness 对三个模型使用相同的 5 道编程隐藏测试、4 道写作 rubric 和 12 道数学题。仅两个 Qwen 运行 6 道图片题，DeepSeek 显示 N/A。</li>
  <li>DeepSeek 共完成 21 次非视觉请求，保留 {ds_final_answers} 份 final content；{ds_missing_final} 份请求未返回 final content，报告按失败计分并单独标记，同时保留其 reasoning 字段。</li>
  <li>最终只读检查发现 X570 OPF <code>:8765</code> 未监听，原因未知；本次评测没有停止、启动、重启或修改 OPF，因此该状态不影响 DeepSeek <code>:8890</code>、Qwen <code>:8004</code> 与报告结果。</li>
  <li>编程代码在无网络、只读、128 MiB、非 root 的固定 digest Docker 沙箱执行。写作只评分题目明确声明的客观约束。</li>
  <li>Qwen 性能 receipt：<code>{esc(args.performance_receipt)}</code>；DeepSeek 性能 receipt：<code>{esc(args.deepseek_performance_receipt)}</code>（SHA-256 <code>670e0ac4…beb65</code>）。</li>
  <li>Qwen 质量 receipt：<code>{esc(args.quality_receipt)}</code>；DeepSeek 质量 receipt：<code>{esc(args.deepseek_quality_receipt)}</code>。</li>
</ol></section>
<section id="performance" class="report-section"><h2>性能汇总</h2><div class="legend"><span><i class="q36"></i>Qwen3.6 / X570</span><span><i class="q38"></i>Qwen3.8 / X570</span><span><i class="ds"></i>DeepSeek / 双 GB10</span></div>
<h3>单流生成 tok/s</h3><div class="table-wrap"><table><thead><tr><th>任务</th><th>Qwen3.6</th><th>Qwen3.8</th><th>DeepSeek</th><th>Qwen3.8 / 3.6</th><th>DeepSeek / 3.6</th></tr></thead><tbody>{performance_rows(perf, ds_perf, 'single_stream')}</tbody></table></div>
<h3>并发聚合 tok/s</h3><div class="table-wrap"><table><thead><tr><th>并发</th><th>Qwen3.6</th><th>Qwen3.8</th><th>DeepSeek</th><th>Qwen3.8 / 3.6</th><th>DeepSeek / 3.6</th></tr></thead><tbody>{performance_rows(perf, ds_perf, 'concurrency')}</tbody></table></div>
<h3>Prefill tok/s</h3><div class="table-wrap"><table><thead><tr><th>目标</th><th>Qwen3.6</th><th>Qwen3.8</th><th>DeepSeek</th><th>Qwen3.8 / 3.6</th><th>DeepSeek / 3.6</th></tr></thead><tbody>{performance_rows(perf, ds_perf, 'prefill')}</tbody></table></div>
<p class="note">Qwen3.6 与 Qwen3.8 是同机 A/B；DeepSeek 使用双 GB10，硬件、并行策略和模型规模不同，性能数字用于部署实测参考，不代表同硬件架构效率排名。DeepSeek 另通过 100K prefill；两个 Qwen 因每槽约 65K 上限排除该项。</p></section>
<section id="quality" class="report-section"><h2>精度与质量汇总</h2><div class="legend"><span><i class="q36"></i>Qwen3.6</span><span><i class="q38"></i>Qwen3.8</span><span><i class="ds"></i>DeepSeek</span></div>{quality_bars(quality)}
<div class="table-wrap"><table><thead><tr><th>类别</th><th>Qwen3.6</th><th>Qwen3.8</th><th>DeepSeek</th><th>题数</th></tr></thead><tbody>{quality_rows(quality)}</tbody></table></div>
<p class="note">图片、编程、数学按确定答案或隐藏测试计分；写作只衡量长度、结构和指定要点。DeepSeek 的宏平均只覆盖编程、写作和数学三类，不能与 Qwen 的四类宏平均直接等同。DeepSeek 的 <code>risk_memo</code> 未返回 final content，因此实际为 20 份 final 回答加 1 份明确标记的空回答。</p></section>
{case_sections(q36, q38, deepseek)}
</main><script>const b=document.getElementById('toggle');let open=false;b.addEventListener('click',()=>{{open=!open;document.querySelectorAll('details.case').forEach(d=>d.open=open);b.textContent=open?'收起全部题目':'展开全部题目';}});</script></body></html>"""
    document = "\n".join(line.rstrip() for line in document.splitlines()) + "\n"
    args.output.write_text(document)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
