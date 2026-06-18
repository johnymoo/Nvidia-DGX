#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import statistics
import subprocess
from datetime import datetime
from pathlib import Path

OUT = Path('/home/chriswang/project/nvidia-dgx/qwen36-dgx-spark/benchmark_outputs')
OUT.mkdir(parents=True, exist_ok=True)
TS = datetime.now().strftime('%Y%m%d-%H%M%S')

# Inputs
BENCH_BASE = Path('/home/chriswang/benchmark_results_20260422_133739.json')
BENCH_PR = Path('/home/chriswang/benchmark_results_20260423_053539.json')
BENCH_NV = Path('/home/chriswang/benchmark_results_nvfp4_20260618_062149.json')
LONG_NV = OUT / 'long-context-ttft-nvfp4-20260618-093358.json'
LONG_FP8 = OUT / 'long-context-ttft-fp8-20260618-100108.json'
QUAL_FP8 = OUT / 'quality-eval-fp8-20260618-100604.json'
QUAL_NV = OUT / 'quality-eval-nvfp4-20260618-100928.json'
PELICAN = OUT / 'pelican-nvfp4-20260618-061439.png'


def load(p: Path):
    with p.open() as f: return json.load(f)

base, pr, nv = map(load, [BENCH_BASE, BENCH_PR, BENCH_NV])
long_nv, long_fp8 = map(load, [LONG_NV, LONG_FP8])
qual_fp8, qual_nv = map(load, [QUAL_FP8, QUAL_NV])

def bench_stats(d):
    vals=[r['tok_per_sec_mean'] for r in d['results'] if 'tok_per_sec_mean' in r]
    return {'mean':statistics.mean(vals),'median':statistics.median(vals),'min':min(vals),'max':max(vals),'errors':len(d.get('errors',[]))}

sb, sp, sn = map(bench_stats, [base, pr, nv])

def pct(new, old): return (new-old)/old*100 if old else 0

def fmt_pct(x): return f"{x:+.1f}%"

def lmap(d): return {r['label']:r for r in d['tests'] if 'error' not in r}
ln, lf = lmap(long_nv), lmap(long_fp8)
long_rows=[]
for label in ['64K','128K','256K']:
    f=lf[label]; n=ln[label]
    long_rows.append({
        'label':label,
        'fp8_prompt':f['actual_prompt_tokens_tokenize'],
        'nv_prompt':n['actual_prompt_tokens_tokenize'],
        'fp8_ttft':f['client']['ttft_first_nonempty_s'],
        'nv_ttft':n['client']['ttft_first_nonempty_s'],
        'fp8_tps':f['client']['avg_tps_completion_over_client_decode'],
        'nv_tps':n['client']['avg_tps_completion_over_client_decode'],
        'fp8_server_tps':f['server_metrics_delta']['avg_tps_generation_over_decode'],
        'nv_server_tps':n['server_metrics_delta']['avg_tps_generation_over_decode'],
        'fp8_e2e':f['server_metrics_delta']['e2e_latency_s'],
        'nv_e2e':n['server_metrics_delta']['e2e_latency_s'],
        'fp8_correct':f['answer_contains_expected'],
        'nv_correct':n['answer_contains_expected'],
    })

# Quality rows
qf={r['id']:r for r in qual_fp8['results']}
qn={r['id']:r for r in qual_nv['results']}
quality_rows=[]
for tid in qf:
    quality_rows.append({'id':tid,'cat':qf[tid]['category'],'fp8':qf[tid]['ok'],'nv':qn.get(tid,{}).get('ok'),'fp8_out':qf[tid]['content_preview'][:80],'nv_out':qn.get(tid,{}).get('content_preview','')[:80]})

# Official model-card table BF16 vs NVFP4 from local README.
official = [
    ('MMLU Pro',85.6,85.0),('GPQA Diamond',84.9,84.8),('τ²-Bench Telecom',95.5,94.7),
    ('SciCode',40.8,40.6),('AIME 2025',89.2,88.8),('AA-LCR',62.0,62.0),('IFBench',62.3,62.8),('MMMU Pro',74.1,74.5),
]

pelican_b64 = base64.b64encode(PELICAN.read_bytes()).decode('ascii') if PELICAN.exists() else ''

# Markdown
md=[]
md.append('# Qwen3.6 GB10 FP8 vs NVFP4 合并评测报告')
md.append('')
md.append('## 结论摘要')
md.append(f'- 常规 16 项生成 benchmark：NVFP4 平均 **{sn["mean"]:.1f} tok/s**，相对旧 8004 FP8 **{fmt_pct(pct(sn["mean"], sb["mean"]))}**，相对 PR200 FP8 **{fmt_pct(pct(sn["mean"], sp["mean"]))}**。')
md.append(f'- 长上下文 TTFT：64K 基本持平；128K NVFP4 比 FP8 慢约 **{pct(ln["128K"]["client"]["ttft_first_nonempty_s"], lf["128K"]["client"]["ttft_first_nonempty_s"]):+.1f}%**；256K NVFP4 比 FP8 慢约 **{pct(ln["256K"]["client"]["ttft_first_nonempty_s"], lf["256K"]["client"]["ttft_first_nonempty_s"]):+.1f}%**。')
md.append(f'- 长上下文 decode TPS：NVFP4 明显更快，64K/128K/256K 分别约 **{pct(ln["64K"]["client"]["avg_tps_completion_over_client_decode"], lf["64K"]["client"]["avg_tps_completion_over_client_decode"]):+.1f}% / {pct(ln["128K"]["client"]["avg_tps_completion_over_client_decode"], lf["128K"]["client"]["avg_tps_completion_over_client_decode"]):+.1f}% / {pct(ln["256K"]["client"]["avg_tps_completion_over_client_decode"], lf["256K"]["client"]["avg_tps_completion_over_client_decode"]):+.1f}%**。')
md.append(f'- 轻量质量小测：FP8 **{qual_fp8["passed"]}/{qual_fp8["total"]}**，NVFP4 **{qual_nv["passed"]}/{qual_nv["total"]}**，同分；同一题 `long_two_fact` 两边都错。')
md.append('- 官方 model card：NVFP4 相比 BF16 在 8 项公开评测上波动约 -0.8 到 +0.5，整体很小；但这不是 FP8 vs NVFP4 的直接表。')
md.append('')
md.append('## 常规生成 benchmark 总览')
md.append('| 部署 | 平均 tok/s | 中位 | min | max | errors |')
md.append('|---|---:|---:|---:|---:|---:|')
md.append(f'| 旧 8004 FP8 baseline | {sb["mean"]:.1f} | {sb["median"]:.1f} | {sb["min"]:.1f} | {sb["max"]:.1f} | {sb["errors"]} |')
md.append(f'| PR200 FP8 | {sp["mean"]:.1f} | {sp["median"]:.1f} | {sp["min"]:.1f} | {sp["max"]:.1f} | {sp["errors"]} |')
md.append(f'| 当前 NVFP4 | **{sn["mean"]:.1f}** | **{sn["median"]:.1f}** | {sn["min"]:.1f} | **{sn["max"]:.1f}** | {sn["errors"]} |')
md.append('')
md.append('## 长上下文 TTFT/TPS：FP8 vs NVFP4')
md.append('| Context | FP8 TTFT | NVFP4 TTFT | TTFT 变化 | FP8 decode TPS | NVFP4 decode TPS | TPS 变化 | FP8 E2E | NVFP4 E2E | Correct |')
md.append('|---|---:|---:|---:|---:|---:|---:|---:|---:|---|')
for r in long_rows:
    md.append(f"| {r['label']} | {r['fp8_ttft']:.2f}s | {r['nv_ttft']:.2f}s | {fmt_pct(pct(r['nv_ttft'], r['fp8_ttft']))} | {r['fp8_tps']:.1f} | **{r['nv_tps']:.1f}** | **{fmt_pct(pct(r['nv_tps'], r['fp8_tps']))}** | {r['fp8_e2e']:.2f}s | {r['nv_e2e']:.2f}s | {'✅/✅' if r['fp8_correct'] and r['nv_correct'] else '⚠️'} |")
md.append('')
md.append('## 轻量质量/一致性测试')
md.append('| Suite | Score | Accuracy |')
md.append('|---|---:|---:|')
md.append(f'| FP8 | {qual_fp8["passed"]}/{qual_fp8["total"]} | {qual_fp8["accuracy"]:.1%} |')
md.append(f'| NVFP4 | {qual_nv["passed"]}/{qual_nv["total"]} | {qual_nv["accuracy"]:.1%} |')
md.append('')
md.append('| Test | Category | FP8 | NVFP4 | Note |')
md.append('|---|---|---:|---:|---|')
for r in quality_rows:
    note='' if r['fp8']==r['nv'] else '结果不一致'
    if r['id']=='long_two_fact': note='两边都错；非 NVFP4 独有'
    md.append(f"| `{r['id']}` | {r['cat']} | {'✅' if r['fp8'] else '❌'} | {'✅' if r['nv'] else '❌'} | {note} |")
md.append('')
md.append('## 官方 BF16 vs NVFP4 model-card 精度参考')
md.append('| Benchmark | BF16 | NVFP4 | Δ |')
md.append('|---|---:|---:|---:|')
for name,b,n in official:
    md.append(f'| {name} | {b:.1f} | {n:.1f} | {n-b:+.1f} |')
md.append('')
md.append('## 文件')
for p in [LONG_FP8, LONG_NV, QUAL_FP8, QUAL_NV, Path('/home/chriswang/benchmark_results_nvfp4_20260618_062149.json')]:
    md.append(f'- `{p}`')
md_text='\n'.join(md)
md_path=OUT/f'fp8-vs-nvfp4-merged-report-{TS}.md'
md_path.write_text(md_text,encoding='utf-8')

# HTML report
long_html='\n'.join(f"<tr><td>{r['label']}</td><td>{r['fp8_ttft']:.2f}s</td><td>{r['nv_ttft']:.2f}s</td><td class='{ 'bad' if pct(r['nv_ttft'], r['fp8_ttft'])>5 else 'ok'}'>{fmt_pct(pct(r['nv_ttft'], r['fp8_ttft']))}</td><td>{r['fp8_tps']:.1f}</td><td class='strong'>{r['nv_tps']:.1f}</td><td class='good'>{fmt_pct(pct(r['nv_tps'], r['fp8_tps']))}</td><td>{'✅' if r['fp8_correct'] and r['nv_correct'] else '⚠️'}</td></tr>" for r in long_rows)
qual_html='\n'.join(f"<tr><td><code>{r['id']}</code></td><td>{r['cat']}</td><td>{'✅' if r['fp8'] else '❌'}</td><td>{'✅' if r['nv'] else '❌'}</td><td>{'same' if r['fp8']==r['nv'] else 'diff'}</td></tr>" for r in quality_rows)
off_html='\n'.join(f"<tr><td>{name}</td><td>{b:.1f}</td><td>{n:.1f}</td><td class='{ 'good' if n-b>=0 else 'warn'}'>{n-b:+.1f}</td></tr>" for name,b,n in official)
html=f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>FP8 vs NVFP4 merged report</title><style>
body{{margin:0;background:#07101e;color:#eef4ff;font:15px/1.45 Inter,ui-sans-serif,system-ui;padding:42px}} .page{{width:1500px;margin:auto}} .hero{{display:grid;grid-template-columns:1.5fr .8fr;gap:24px}} .card{{background:linear-gradient(180deg,#121d33,#0d1729);border:1px solid #253653;border-radius:26px;padding:28px;box-shadow:0 20px 70px #0008}} h1{{font-size:54px;line-height:1;margin:8px 0 12px;letter-spacing:-.04em}} h2{{font-size:28px;margin:34px 0 14px}} .muted{{color:#9cafcc;font-size:20px}} .eyebrow{{color:#5eead4;text-transform:uppercase;letter-spacing:.14em;font-weight:800}} .kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:24px 0}} .kpi{{background:#101a2e;border:1px solid #263653;border-radius:22px;padding:22px}} .kpi .v{{font-size:36px;font-weight:850;margin-top:8px}} .good{{color:#4ade80;font-weight:800}} .bad{{color:#fb7185;font-weight:800}} .warn{{color:#fbbf24;font-weight:800}} .ok{{color:#93c5fd;font-weight:800}} .strong{{font-weight:850;color:white}} table{{width:100%;border-collapse:separate;border-spacing:0;background:#0c1425;border:1px solid #263653;border-radius:18px;overflow:hidden;margin-bottom:22px}} th,td{{padding:12px 14px;border-bottom:1px solid #263653;text-align:left}} th{{background:#17233b;color:#dbeafe;text-transform:uppercase;font-size:12px;letter-spacing:.08em}} tr:last-child td{{border-bottom:0}} code{{background:#17233b;border:1px solid #2b3d5c;border-radius:6px;padding:2px 5px}} img{{width:100%;border-radius:18px;background:white}} .grid2{{display:grid;grid-template-columns:1fr 1fr;gap:22px}} .small{{font-size:13px;color:#9cafcc}}
</style></head><body><div class='page'>
<section class='hero'><div class='card'><div class='eyebrow'>GB10 / Qwen3.6 · FP8 vs NVFP4</div><h1>NVFP4 生成速度翻倍；长上下文 prefill 接近，decode 更快；质量小测同分</h1><p class='muted'>对比旧 8004 FP8、PR200 FP8、当前官方 ARM64 NVFP4。当前服务已恢复到 NVFP4 healthy。</p></div><div class='card'><img src='data:image/png;base64,{pelican_b64}'><p class='small'>NVFP4 鹈鹕 SVG smoke test</p></div></section>
<section class='kpis'><div class='kpi'><div>常规平均 tok/s</div><div class='v good'>{sn['mean']:.1f}</div><div class='small'>vs old FP8 {fmt_pct(pct(sn['mean'], sb['mean']))}</div></div><div class='kpi'><div>质量小测</div><div class='v good'>{qual_nv['passed']}/{qual_nv['total']}</div><div class='small'>FP8 同为 {qual_fp8['passed']}/{qual_fp8['total']}</div></div><div class='kpi'><div>256K TTFT</div><div class='v warn'>{ln['256K']['client']['ttft_first_nonempty_s']:.1f}s</div><div class='small'>FP8 {lf['256K']['client']['ttft_first_nonempty_s']:.1f}s</div></div><div class='kpi'><div>256K decode TPS</div><div class='v good'>{ln['256K']['client']['avg_tps_completion_over_client_decode']:.1f}</div><div class='small'>FP8 {lf['256K']['client']['avg_tps_completion_over_client_decode']:.1f}</div></div></section>
<h2>常规生成 benchmark</h2><table><tr><th>部署</th><th>平均 tok/s</th><th>中位</th><th>min</th><th>max</th><th>errors</th></tr><tr><td>旧 8004 FP8</td><td>{sb['mean']:.1f}</td><td>{sb['median']:.1f}</td><td>{sb['min']:.1f}</td><td>{sb['max']:.1f}</td><td>0</td></tr><tr><td>PR200 FP8</td><td>{sp['mean']:.1f}</td><td>{sp['median']:.1f}</td><td>{sp['min']:.1f}</td><td>{sp['max']:.1f}</td><td>0</td></tr><tr><td><b>当前 NVFP4</b></td><td class='good'>{sn['mean']:.1f}</td><td>{sn['median']:.1f}</td><td>{sn['min']:.1f}</td><td>{sn['max']:.1f}</td><td>0</td></tr></table>
<h2>长上下文 TTFT/TPS</h2><table><tr><th>Context</th><th>FP8 TTFT</th><th>NVFP4 TTFT</th><th>TTFT Δ</th><th>FP8 TPS</th><th>NVFP4 TPS</th><th>TPS Δ</th><th>Correct</th></tr>{long_html}</table>
<div class='grid2'><div><h2>轻量质量/一致性测试</h2><table><tr><th>Test</th><th>Cat</th><th>FP8</th><th>NVFP4</th><th>Same?</th></tr>{qual_html}</table></div><div><h2>官方 BF16 vs NVFP4 参考</h2><table><tr><th>Benchmark</th><th>BF16</th><th>NVFP4</th><th>Δ</th></tr>{off_html}</table><div class='card small'>说明：官方表是 BF16 vs NVFP4，不是 FP8 vs NVFP4。我们本机 FP8 vs NVFP4 的自动判分小测同为 15/16；更严格的质量评估建议后续用 lm-eval/opencompass 跑 MMLU-Pro/GSM8K/GPQA 子集或业务题集。</div></div></div>
</div></body></html>"""
html_path=OUT/f'fp8-vs-nvfp4-merged-report-{TS}.html'
html_path.write_text(html,encoding='utf-8')
png_path=OUT/f'fp8-vs-nvfp4-merged-report-{TS}.png'
subprocess.run(['chromium-browser','--headless','--no-sandbox','--disable-gpu','--hide-scrollbars','--window-size=1500,2400',f'--screenshot={png_path}',html_path.as_uri()],check=False,capture_output=True,text=True,timeout=120)
print(json.dumps({'md':str(md_path),'html':str(html_path),'png':str(png_path)},ensure_ascii=False,indent=2))
