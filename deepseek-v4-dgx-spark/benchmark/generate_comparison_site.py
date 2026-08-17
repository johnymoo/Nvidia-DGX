#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.summary.read_text())
    quality = data["quality"]
    latency = data["latency"]
    telemetry = data["online_pro_telemetry"]
    bounded = data["private_bounded_4k_telemetry"]
    agent = data["agent_focus"]
    private_route = data["private_route"]
    route_labels = {
        "benchmark-client": "Benchmark client",
        "synology-reverse-proxy": "Synology reverse proxy",
        "llm-portal-edge": "LLM Portal edge",
        "litellm-compat": "LiteLLM / compat",
        "wireguard": "WireGuard",
        "private-vllm": "Private vLLM",
    }
    private_route_text = " → ".join(route_labels[item] for item in private_route["path"])

    treatments = [
        ("Private Flash", "High · 32K", quality["private_flash"]["high"], "private"),
        ("Private Flash", "High · bounded 4K", quality["private_flash_bounded_4k"]["high"], "private"),
        ("Private Flash", "Max · bounded 4K", quality["private_flash_bounded_4k"]["max"], "private"),
        ("Online Flash", "Low", quality["online_flash"]["low"], "flash"),
        ("Online Flash", "High", quality["online_flash"]["high"], "flash"),
        ("Online Flash", "Max", quality["online_flash"]["max"], "flash"),
        ("Online Pro", "Low", quality["online_pro"]["low"], "pro"),
        ("Online Pro", "High", quality["online_pro"]["high"], "pro"),
        ("Online Pro", "Max", quality["online_pro"]["max"], "pro"),
    ]
    quality_rows = []
    quality_bars = []
    for model, effort, row, kind in treatments:
        quality_rows.append(
            f"<tr><th>{esc(model)}<small>{esc(effort)}</small></th>"
            f"<td><strong>{pct(row['macro_score'])}</strong></td>"
            f"<td>{pct(row['categories']['sql'])}</td>"
            f"<td>{pct(row['categories']['python'])}</td>"
            f"<td>{pct(row['categories']['incident'])}</td>"
            f"<td>{row['stdev'] * 100:.1f}pp</td></tr>"
        )
        quality_bars.append(
            f"<div class='bar-row'><span>{esc(model)} · {esc(effort)}</span>"
            f"<div class='track'><i class='{kind}' style='width:{row['macro_score'] * 100:.1f}%'></i></div>"
            f"<b>{pct(row['macro_score'])}</b></div>"
        )

    latency_labels = {
        "private-high": "Private Flash · High",
        "private-max": "Private Flash · Max",
        "online-flash-low": "Online Flash · Low",
        "online-pro-low": "Online Pro · Low",
        "online-pro-high": "Online Pro · High",
        "online-pro-max": "Online Pro · Max",
    }
    latency_rows = []
    max_response = max(row["response_seconds"] for row in latency.values())
    for key in latency_labels:
        row = latency[key]
        latency_rows.append(
            f"<div class='latency-row'><div><strong>{esc(latency_labels[key])}</strong>"
            f"<small>TTFT {row['ttft_seconds']:.3f}s · {row['decode_tokens_per_second']:.1f} tok/s</small></div>"
            f"<div class='latency-track'><i style='width:{row['response_seconds'] / max_response * 100:.1f}%'></i></div>"
            f"<b>{row['response_seconds']:.3f}s</b></div>"
        )

    cost_rows = []
    for effort in ("low", "high", "max"):
        row = telemetry[effort]
        cost = row["estimated_api_cost_usd"]
        cost_rows.append(
            f"<article class='cost-item'><header><strong>Pro {effort.title()}</strong>"
            f"<span>{row['completion_tokens_mean'] / 1000:.1f}K output</span></header>"
            f"<div class='token-track'><i style='width:{row['completion_tokens_mean'] / telemetry['max']['completion_tokens_mean'] * 100:.1f}%'></i></div>"
            f"<p><b>${cost['off_peak_all_input_cache_miss']:.3f}</b> off-peak"
            f"<small>${cost['peak_all_input_cache_miss']:.3f} peak</small></p></article>"
        )

    agent_rows = []
    for row in agent["tasks"]:
        passed = row["hidden_passed"] == row["hidden_total"]
        agent_rows.append(
            f"<tr><th><code>{esc(row['task_id'])}</code></th>"
            f"<td><span class='status {'pass' if passed else 'fail'}'>{row['hidden_passed']}/{row['hidden_total']}</span></td>"
            f"<td><span class='status {row['historical_online_flash_status']}'>{esc(row['historical_online_flash_status'])}</span></td>"
            f"<td><span class='status {row['historical_private_flash_status']}'>{esc(row['historical_private_flash_status'])}</span></td></tr>"
        )

    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="DeepSeek V4 private Flash、online Flash 与 online Pro 性能和精度边界报告">
<title>DeepSeek V4 · Private / Online Benchmark</title>
<style>
:root{{--paper:#f5f6f2;--surface:#fff;--ink:#17201c;--muted:#627068;--line:#d4d9d4;--private:#15735b;--flash:#d7613c;--pro:#2f5ea8;--warning:#d9a62e;--soft:#e9ece8}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth;overflow-x:hidden}}body{{margin:0;min-width:0;overflow-x:hidden;background:var(--paper);color:var(--ink);font:15px/1.6 Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif;letter-spacing:0}}
a{{color:inherit}}button{{font:inherit}}.shell{{width:100%;max-width:1240px;margin:auto;padding:0 28px;min-width:0}}nav{{position:sticky;top:0;z-index:10;background:rgba(245,246,242,.96);border-bottom:1px solid var(--line);backdrop-filter:blur(12px)}}nav .shell{{height:58px;display:flex;align-items:center;justify-content:space-between;gap:20px}}.brand{{display:flex;align-items:center;gap:10px;font-weight:750;text-decoration:none}}.mark{{width:22px;height:22px;display:grid;grid-template-columns:1fr 1fr;gap:3px}}.mark i{{display:block;background:var(--ink)}}.mark i:nth-child(2){{background:var(--private)}}.mark i:nth-child(3){{background:var(--flash)}}.mark i:nth-child(4){{background:var(--pro)}}.nav-links{{display:flex;gap:18px;font-size:13px;color:var(--muted)}}.nav-links a{{text-decoration:none}}.nav-links a:hover{{color:var(--ink)}}
header.hero{{padding:68px 0 42px;border-bottom:1px solid var(--line)}}.eyebrow{{display:flex;align-items:center;gap:10px;color:var(--muted);font-size:13px}}.eyebrow i{{width:34px;height:2px;background:var(--private)}}h1{{max-width:850px;margin:16px 0 18px;font-size:48px;line-height:1.08;font-weight:720;letter-spacing:0}}.lead{{max-width:780px;color:var(--muted);font-size:18px}}.decision-strip{{display:grid;grid-template-columns:1.4fr 1fr 1fr;margin-top:44px;border-top:2px solid var(--ink);border-bottom:1px solid var(--line)}}.decision-strip article{{padding:20px 22px 22px 0}}.decision-strip article+article{{padding-left:22px;border-left:1px solid var(--line)}}.decision-strip small,.metric small{{display:block;color:var(--muted);font-size:12px}}.decision-strip strong{{display:block;margin-top:4px;font-size:22px;line-height:1.3}}.decision-strip .private strong{{color:var(--private)}}.decision-strip .pro strong{{color:var(--pro)}}
section{{padding:58px 0;border-bottom:1px solid var(--line)}}.section-head{{display:flex;justify-content:space-between;align-items:end;gap:28px;margin-bottom:26px}}.section-head div:first-child{{max-width:760px}}h2{{margin:0 0 7px;font-size:28px;line-height:1.2}}.section-head p,.note{{margin:0;color:var(--muted)}}.section-index{{font:700 13px ui-monospace,monospace;color:var(--muted)}}.quality-grid{{display:grid;grid-template-columns:1fr 1.05fr;gap:36px;align-items:start}}.chart{{background:var(--surface);border:1px solid var(--line);padding:24px;border-radius:6px}}.chart h3{{margin:0 0 20px;font-size:15px}}.bar-row{{display:grid;grid-template-columns:155px 1fr 50px;align-items:center;gap:12px;margin:13px 0;font-size:12px}}.bar-row b{{text-align:right}}.track,.latency-track,.token-track{{height:9px;background:var(--soft);overflow:hidden}}.track i,.latency-track i,.token-track i{{display:block;height:100%;background:var(--ink)}}.track i.private{{background:var(--private)}}.track i.flash{{background:var(--flash)}}.track i.pro{{background:var(--pro)}}
.table-wrap{{overflow:auto;border:1px solid var(--line);background:var(--surface)}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:12px 14px;border-bottom:1px solid var(--line);text-align:right;font-size:13px}}th:first-child{{text-align:left}}tbody tr:last-child th,tbody tr:last-child td{{border-bottom:0}}tbody th{{font-weight:650}}tbody th small{{display:block;color:var(--muted);font-weight:400}}td strong{{font-size:15px}}
.metric-band{{display:grid;grid-template-columns:repeat(3,1fr);border:1px solid var(--line);background:var(--surface);margin-bottom:28px}}.metric{{padding:18px 20px}}.metric+.metric{{border-left:1px solid var(--line)}}.metric b{{font-size:25px}}.metric.private b{{color:var(--private)}}.metric.pro b{{color:var(--pro)}}.latency-list{{display:grid;gap:14px}}.latency-row{{display:grid;grid-template-columns:205px 1fr 72px;align-items:center;gap:16px}}.latency-row strong,.latency-row small{{display:block}}.latency-row small{{color:var(--muted);font-size:11px}}.latency-row b{{text-align:right}}.latency-track{{height:13px}}.latency-track i{{background:var(--warning)}}
.route{{margin-bottom:28px;padding:16px 20px;border-left:3px solid var(--private);background:var(--surface)}}.route small{{display:block;color:var(--muted)}}.route strong{{display:block;margin-top:3px;overflow-wrap:anywhere}}
.cost-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}.cost-item{{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:20px}}.cost-item header{{display:flex;justify-content:space-between;gap:10px}}.cost-item header span{{color:var(--muted);font-size:12px}}.token-track{{height:7px;margin:18px 0 12px}}.token-track i{{background:var(--pro)}}.cost-item p{{margin:0}}.cost-item p b{{font-size:22px}}.cost-item p small{{display:block;color:var(--muted)}}
.status{{display:inline-flex;min-width:54px;justify-content:center;padding:2px 7px;border:1px solid var(--line);border-radius:3px;color:var(--muted)}}.status.pass,.status.passed{{color:var(--private);border-color:#9bc7b8;background:#edf7f3}}.status.fail,.status.failed{{color:#a63c2b;border-color:#e4afa5;background:#fff2ef}}code{{font:12px ui-monospace,SFMono-Regular,Menlo,monospace}}
.boundary{{display:grid;grid-template-columns:repeat(2,1fr);border-top:2px solid var(--ink)}}.boundary article{{padding:24px 28px 26px 0;border-bottom:1px solid var(--line)}}.boundary article:nth-child(even){{padding-left:28px;border-left:1px solid var(--line)}}.boundary h3{{margin:0 0 6px;font-size:17px}}.boundary p{{margin:0;color:var(--muted)}}.boundary b{{color:var(--private)}}.boundary .online b{{color:var(--pro)}}
.evidence{{display:grid;grid-template-columns:1fr 1fr;gap:30px}}.evidence ul{{margin:0;padding-left:18px;color:var(--muted)}}.evidence li+li{{margin-top:7px}}.links{{display:grid;border-top:1px solid var(--line)}}.links a{{padding:12px 0;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;text-decoration:none}}.links a:hover{{color:var(--pro)}}footer{{padding:34px 0 54px;color:var(--muted);font-size:12px}}
@media(max-width:900px){{h1{{font-size:38px}}.quality-grid{{grid-template-columns:1fr}}.decision-strip{{grid-template-columns:1fr}}.decision-strip article+article{{padding-left:0;border-left:0;border-top:1px solid var(--line)}}.metric-band,.cost-grid{{grid-template-columns:1fr}}.metric+.metric{{border-left:0;border-top:1px solid var(--line)}}.evidence{{grid-template-columns:1fr}}}}
@media(max-width:650px){{.shell{{padding:0 16px}}.nav-links{{display:none}}header.hero{{padding-top:44px}}h1,.lead,.decision-strip{{width:calc(100vw - 32px);max-width:calc(100vw - 32px)}}h1{{font-size:32px;overflow-wrap:anywhere}}.lead{{font-size:16px;overflow-wrap:anywhere}}.section-head{{display:block}}.section-index{{display:block;margin-bottom:8px}}.quality-grid>*{{min-width:0}}.bar-row{{grid-template-columns:112px minmax(0,1fr) 45px}}.latency-row{{grid-template-columns:minmax(0,1fr) 60px}}.latency-row .latency-track{{grid-row:2;grid-column:1/-1}}.boundary{{grid-template-columns:1fr}}.boundary article:nth-child(even){{padding-left:0;border-left:0}}}}
@media print{{nav{{position:static}}body{{background:#fff}}.shell{{max-width:none}}section{{break-inside:avoid}}}}
</style></head><body>
<nav><div class="shell"><a class="brand" href="#top"><span class="mark"><i></i><i></i><i></i><i></i></span>DeepSeek V4 Benchmark</a><div class="nav-links"><a href="#quality">精度</a><a href="#latency">性能</a><a href="#cost">成本</a><a href="#agent">Agent</a><a href="#coverage">覆盖</a><a href="#boundary">边界</a></div></div></nav>
<main id="top"><header class="hero"><div class="shell"><div class="eyebrow"><i></i>Dual DGX Spark · Online API · 2026-08-17</div><h1>Private 是默认线路，Pro High 是困难任务升级路径</h1><p class="lead">基于可执行湖仓题、串行 SSE 性能测量与 Claude Code 聚焦任务，界定经 LLM Portal 访问的双 GB10 私有部署和 online Flash / Pro 的质量、延迟与成本边界。</p>
<div class="decision-strip"><article class="private"><small>默认私有线路</small><strong>Private Flash · High</strong><span>{pct(quality['private_flash']['high']['macro_score'])} 宏平均 · {latency['private-high']['ttft_seconds']:.3f}s TTFT</span></article><article class="pro"><small>最高精度</small><strong>Online Pro · High</strong><span>{pct(quality['online_pro']['high']['macro_score'])} 宏平均</span></article><article><small>True Max · bounded 4K</small><strong>{pct(bounded['max']['final_coverage'])} final 覆盖</strong><span>{pct(bounded['max']['completed_final_score'])} 完整 final 得分</span></article></div></div></header>

<section id="quality"><div class="shell"><div class="section-head"><div><span class="section-index">01 / QUALITY</span><h2>精度对比</h2><p>每组 n=2；4K High/Max 使用相同输出上限，32K High 是能力基线。</p></div></div><div class="quality-grid"><div class="chart"><h3>全请求可执行宏平均</h3>{''.join(quality_bars)}</div><div class="table-wrap"><table><thead><tr><th>处理组</th><th>宏平均</th><th>SQL</th><th>Python</th><th>故障</th><th>波动</th></tr></thead><tbody>{''.join(quality_rows)}</tbody></table></div></div><div class="metric-band" style="margin-top:28px"><div class="metric private"><small>4K Max 全请求分</small><b>{pct(quality['private_flash_bounded_4k']['max']['macro_score'])}</b></div><div class="metric private"><small>4K Max final 覆盖率</small><b>{pct(bounded['max']['final_coverage'])}</b></div><div class="metric private"><small>4K Max 完整 final 得分</small><b>{pct(bounded['max']['completed_final_score'])}</b></div></div><p class="note">旧 Private Low/High/Max 的 `reasoning_effort` 被 LiteLLM 静默丢弃，原 87.5% 不是 Max。True Max 4K 共 10/36 length 截断；分数下降来自空 final，26 个完整 final 的得分没有低于 High。</p></div></section>

<section id="latency"><div class="shell"><div class="section-head"><div><span class="section-index">02 / PERFORMANCE</span><h2>短请求性能</h2><p>1 次预热、3 次串行 SSE。Private High/Max 固定相同 2048 输出上限，显式透传 effort。</p></div></div><div class="route"><small>Private 实测调用链</small><strong>{esc(private_route_text)}</strong></div><div class="metric-band"><div class="metric private"><small>Private High 经 Portal TTFT</small><b>{latency['private-high']['ttft_seconds']:.3f}s</b></div><div class="metric private"><small>Private Max 经 Portal TTFT</small><b>{latency['private-max']['ttft_seconds']:.3f}s</b></div><div class="metric pro"><small>Pro High 端到端</small><b>{latency['online-pro-high']['response_seconds']:.3f}s</b></div></div><div class="chart"><div class="latency-list">{''.join(latency_rows)}</div></div><p class="note" style="margin-top:14px">Private 指标包含反向代理、Portal、兼容层和 WireGuard，不代表裸 vLLM engine latency。短题 Max 未截断；全量质量题则出现超长生成。</p></div></section>

<section id="cost"><div class="shell"><div class="section-head"><div><span class="section-index">03 / TOKENS & COST</span><h2>Pro effort 的代价</h2><p>每轮 18 题均值。费用按全部输入 cache miss 的官方 Pro 单价保守估算。</p></div></div><div class="cost-grid">{''.join(cost_rows)}</div></div></section>

<section id="agent"><div class="shell"><div class="section-head"><div><span class="section-index">04 / AGENT</span><h2>Agent 工作流不是单调升级</h2><p>5 个历史差异题，Claude Code 2.1.207，Pro High；共观测 {agent['thinking_block_count']} 个 thinking block。</p></div><div><strong>Pro High {agent['passed']}/{agent['task_count']}</strong><p class="note">完整通过</p></div></div><div class="table-wrap"><table><thead><tr><th>任务</th><th>Pro High</th><th>历史 Online Flash</th><th>历史 Private</th></tr></thead><tbody>{''.join(agent_rows)}</tbody></table></div><p class="note" style="margin-top:14px">该集合刻意选择历史 private 弱项，不能外推总体胜率；它证明模型升级仍需工作流级验收。</p></div></section>

<section id="coverage"><div class="shell"><div class="section-head"><div><span class="section-index">05 / TEST COVERAGE</span><h2>本轮覆盖范围</h2><p>“未完成”表示没有可比证据，不以旧错误 treatment 代填。</p></div></div><div class="table-wrap"><table><thead><tr><th>维度</th><th>本轮纳入</th><th>未覆盖</th><th>状态</th></tr></thead><tbody><tr><th>可执行精度</th><td>Private High 32K；Private High/True Max 4K；Online Flash/Pro</td><td>True Private Max 32K</td><td><span class="status pass">主要边界完整</span></td></tr><tr><th>串行 SSE 性能</th><td>Verified Private High/Max；Online Flash Low；Online Pro Low/High/Max</td><td>Online Flash High/Max</td><td><span class="status pass">主要路径完整</span></td></tr><tr><th>Token 与 API 成本</th><td>Online Pro Low/High/Max</td><td>Private 无 API 账单；Flash 未统一计价</td><td><span class="status pass">范围内完整</span></td></tr><tr><th>Agent 聚焦任务</th><td>Online Pro High；Online/Private 历史基线</td><td>不是 effort 全矩阵</td><td><span class="status fail">部分</span></td></tr></tbody></table></div></div></section>

<section id="boundary"><div class="shell"><div class="section-head"><div><span class="section-index">06 / OPERATING BOUNDARY</span><h2>选型边界</h2></div></div><div class="boundary"><article><h3><b>Private Flash High</b></h3><p>私密代码、内网数据、稳定日常 SQL/Python/故障诊断。当前默认选择。</p></article><article><h3><b>Private Flash Max</b></h3><p>必须显式透传 effort；4K final 覆盖仅 {pct(bounded['max']['final_coverage'])}，需提高预算并显式处理空 final。</p></article><article class="online"><h3><b>Online Pro High</b></h3><p>复杂任务、private 首次失败、需要更高一次成功率。</p></article><article class="online"><h3><b>Pro Max · 按请求</b></h3><p>仅用于极难任务。没有超过 high，token 与分钟级尾延迟显著增加。</p></article></div></div></section>

<section id="evidence"><div class="shell"><div class="section-head"><div><span class="section-index">07 / EVIDENCE</span><h2>方法与证据</h2></div></div><div class="evidence"><ul><li>旧 Private Low/High/Max 均为 effective High；87.5% 不是 Max 精度。</li><li>LiteLLM 显式透传后，High/Max prompt tokens 为 11/90，Max 生效。</li><li>Private 请求通过 Synology 反代、LLM Portal/LiteLLM 与 WireGuard 到 vLLM，不是直连。</li><li>4K High/Max 各 36 请求、各两轮、配对总并发 6；0 HTTP/网络错误。</li><li>True Max 有 10/36 length 截断和空 final；High 为 0/36。</li><li>Python final 在不可变 ECR sandbox 中重评分，原始证据不覆盖。</li><li>快速决策 benchmark：精度 n=2，Agent n=1，不声明统计显著性。</li></ul><div class="links"><a href="BENCHMARK-COMPARISON-20260817.md">完整 Markdown 报告 <span>↗</span></a><a href="data/deepseek-private-online-comparison-20260817.json">机器可读汇总 <span>↗</span></a><a href="https://github.com/johnymoo/Nvidia-DGX/pull/32">GitHub PR 32 <span>↗</span></a><a href="https://github.com/shiliai/LLM-Portal/issues/46">LLM Portal Issue 46 <span>↗</span></a></div></div></div></section>
</main><footer><div class="shell">DeepSeek V4 private / online benchmark · Evidence dated 2026-08-17 · Generated from sanitized JSON</div></footer>
</body></html>"""
    args.output.write_text(document)
    print(json.dumps({"output": str(args.output), "bytes": len(document.encode())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
