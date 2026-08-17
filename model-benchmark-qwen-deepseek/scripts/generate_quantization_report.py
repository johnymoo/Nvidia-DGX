#!/usr/bin/env python3
from __future__ import annotations

import html
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "qwen38-quantization"
OUTPUT = ROOT / "report" / "qwen38-quantization.html"


def load(name: str) -> dict:
    return json.loads((DATA / name).read_text())


def metric_bar(label: str, value: float, maximum: float, color: str, suffix: str) -> str:
    width = max(2.0, value / maximum * 100)
    return (
        f'<div class="bar-row"><span>{html.escape(label)}</span><div class="track">'
        f'<i style="width:{width:.1f}%;background:{color}"></i></div><strong>{value:.2f}{suffix}</strong></div>'
    )


def main() -> int:
    keys = ("fp8", "q4", "q4_mtp2", "q6")
    quality_files = {
        "fp8": "fp8-quality-r1.json",
        "q4": "q4-quality-r1.json",
        "q4_mtp2": "q4-mtp2-quality-r1.json",
        "q6": "q6-quality-r1.json",
    }
    performance_files = {
        "fp8": "fp8-performance.json",
        "q4": "q4-performance.json",
        "q4_mtp2": "q4-mtp2-performance.json",
        "q6": "q6-performance.json",
    }
    vision_files = {
        "fp8": "fp8-vision.json",
        "q4": "q4-vision.json",
        "q4_mtp2": "q4-mtp2-vision.json",
        "q6": "q6-vision.json",
    }
    quality = {key: load(quality_files[key]) for key in keys}
    performance = {key: load(performance_files[key]) for key in keys}
    vision = {key: load(vision_files[key]) for key in keys}
    deployment = load("deployment-metrics.json")
    deployed_quality = quality["q4_mtp2"]
    deployed_performance = performance["q4_mtp2"]
    deployed_vision = vision["q4_mtp2"]
    short_baseline = load("q4-baseline-short-performance.json")
    short_mtp2 = load("q4-mtp2-short-performance.json")
    profiles = deployment["profiles"]
    context_profiles = deployment["context_profiles"]
    labels = {
        "fp8": "FP8 / vLLM",
        "q4": "UD-Q4 / llama.cpp",
        "q4_mtp2": "UD-Q4 + MTP2",
        "q6": "UD-Q6 / llama.cpp",
    }
    colors = {"fp8": "#4e9fd1", "q4": "#52b788", "q4_mtp2": "#c7e36b", "q6": "#ee9b46"}

    rows = []
    for key in keys:
        perf = performance[key]["summary"]
        runs = performance[key]["runs"]
        rows.append(
            {
                "key": key,
                "label": labels[key],
                "business_passed": round(quality[key]["macro_score"] * 18),
                "vision_passed": vision[key]["passed"],
                "tps": perf["decode_tokens_per_second"]["mean"],
                "ttft": perf["ttft_seconds"]["mean"],
                "response": perf["response_seconds"]["mean"],
                "completion_tokens": perf["completion_tokens_mean"],
                "final_answer": all(run["content_chars"] > 0 and run["finish_reason"] == "stop" for run in runs),
                "vram": profiles[key]["vram_used_mib"],
                "startup": profiles[key]["startup_seconds"],
                "model_bytes": profiles[key]["model_bytes"],
            }
        )

    summary = {
        "selected": "q4_mtp2",
        "profiles": rows,
        "quality_harness": "lakehouse-thinking-v2, 18 tasks, seed 42, thinking-low",
        "vision_harness": "qwen38-quantization-vision-v1, 6 deterministic synthetic images",
        "performance_harness": "1 warmup + 3 measured single-stream OpenAI SSE requests",
        "deployment_validation": {
            "context_size": context_profiles["256k"]["context"],
            "business_passed": round(deployed_quality["macro_score"] * 18),
            "vision_passed": deployed_vision["passed"],
            "decode_tokens_per_second": context_profiles["256k"]["decode_tokens_per_second"],
            "response_seconds": context_profiles["256k"]["response_seconds"],
            "long_prompt_tokens": context_profiles["256k"]["long_prompt_tokens"],
            "long_context_retrieval": context_profiles["256k"]["retrieval"],
        },
        "short_output_ab": {
            "max_tokens": 128,
            "baseline_tps": short_baseline["summary"]["decode_tokens_per_second"]["mean"],
            "mtp2_tps": short_mtp2["summary"]["decode_tokens_per_second"]["mean"],
            "baseline_response_seconds": short_baseline["summary"]["response_seconds"]["mean"],
            "mtp2_response_seconds": short_mtp2["summary"]["response_seconds"]["mean"],
        },
    }
    (DATA / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")

    max_tps = max(row["tps"] for row in rows)
    max_response = max(row["response"] for row in rows)
    max_vram = max(row["vram"] for row in rows)
    max_startup = max(row["startup"] for row in rows)
    speed_chart = "".join(metric_bar(row["label"], row["tps"], max_tps, colors[row["key"]], " tok/s") for row in rows)
    latency_chart = "".join(metric_bar(row["label"], row["response"], max_response, colors[row["key"]], " s") for row in rows)
    memory_chart = "".join(metric_bar(row["label"], row["vram"] / 1024, max_vram / 1024, colors[row["key"]], " GiB") for row in rows)
    startup_chart = "".join(metric_bar(row["label"], row["startup"], max_startup, colors[row["key"]], " s") for row in rows)

    categories = []
    for category, title in (("sql", "复杂 SQL"), ("python", "Python"), ("incident", "故障分析")):
        values = []
        for key in keys:
            item = quality[key]["categories"][category]
            values.append(f"{labels[key]} {item['passed']}/{item['total']}，均值 {item['mean_seconds']:.1f}s")
        categories.append(f"<tr><th>{title}</th>" + "".join(f"<td>{html.escape(value)}</td>" for value in values) + "</tr>")

    failed_cases = []
    for key in keys:
        failures = [case for case in quality[key]["cases"] if not case["passed"]]
        detail = "无" if not failures else "；".join(f"{case['id']}：{case['response'][:260]}" for case in failures)
        failed_cases.append(f"<tr><th>{labels[key]}</th><td>{html.escape(detail)}</td></tr>")

    table_rows = []
    for row in rows:
        table_rows.append(
            "<tr>"
            f"<th>{html.escape(row['label'])}</th>"
            f"<td>{row['business_passed']}/18</td><td>{row['vision_passed']}/6</td>"
            f"<td>{row['tps']:.2f}</td><td>{row['ttft'] * 1000:.0f} ms</td>"
            f"<td>{row['response']:.1f} s</td><td>{row['completion_tokens']:.0f}</td>"
            f"<td>{'有' if row['final_answer'] else '无（length）'}</td>"
            f"<td>{row['vram'] / 1024:.2f} GiB</td><td>{row['startup']:.1f} s</td>"
            f"<td>{row['model_bytes'] / 1e9:.2f} GB</td></tr>"
        )

    q4_types = " / ".join(f"{key} {value}" for key, value in profiles["q4"]["tensor_types"].items())
    q6_types = " / ".join(f"{key} {value}" for key, value in profiles["q6"]["tensor_types"].items())
    context_rows = []
    for key, label in (("65k", "65K"), ("128k", "128K"), ("256k", "256K")):
        item = context_profiles[key]
        if item.get("long_prompt_tokens"):
            long_result = (
                f"{item['long_prompt_tokens']:,} tokens / {item['long_response_seconds']:.1f}s / "
                f"prefill {item['prefill_tokens_per_second']:.1f} tok/s / {item['retrieval']}"
            )
        else:
            long_result = "本轮未填充"
        context_rows.append(
            f"<tr><th>{label}</th><td>{item['context']:,}</td>"
            f"<td>{item['vram_used_mib'] / 1024:.2f} GiB</td>"
            f"<td>{item['vram_headroom_mib'] / 1024:.2f} GiB</td>"
            f"<td>{item['decode_tokens_per_second']:.2f}</td>"
            f"<td>{item['response_seconds']:.2f}s</td><td>{long_result}</td></tr>"
        )
    source_hashes = []
    for path in sorted(DATA.glob("*.json")):
        if path.name == "summary.json":
            continue
        import hashlib

        source_hashes.append(f"<tr><td>{path.name}</td><td><code>{hashlib.sha256(path.read_bytes()).hexdigest()}</code></td></tr>")

    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Qwen3.8-27B FP8、Dynamic GGUF 与 MTP2 部署选型</title>
<style>
:root{{--bg:#0d1115;--surface:#151b20;--surface2:#1b2329;--line:#34414a;--text:#eef3f5;--muted:#a9b5bc;--blue:#4e9fd1;--green:#52b788;--orange:#ee9b46;--bad:#ef6f6c;color-scheme:dark}}
*{{box-sizing:border-box;min-width:0}}html{{scroll-behavior:smooth;overflow-x:hidden}}body{{margin:0;overflow-x:hidden;background:var(--bg);color:var(--text);font:15px/1.55 "Noto Sans CJK SC","Noto Sans SC","Microsoft YaHei",system-ui,sans-serif;letter-spacing:0}}main{{width:min(1240px,calc(100% - 32px));margin:auto;padding:28px 0 56px}}h1,h2,h3{{letter-spacing:0;line-height:1.25}}h1{{font-size:29px;margin:0 0 8px}}h2{{font-size:21px;margin:0 0 8px}}h3{{font-size:15px;margin:0 0 10px}}h1,h2,h3,p,li,span,strong,code,td,th{{overflow-wrap:anywhere;word-break:break-word;white-space:normal}}p{{margin:6px 0}}a{{color:#7bc4ee}}.muted,.meta{{color:var(--muted)}}header{{border-bottom:1px solid var(--line);padding-bottom:18px}}nav{{display:flex;gap:18px;flex-wrap:wrap;padding:12px 0;border-bottom:1px solid var(--line);position:sticky;top:0;background:#0d1115f2;z-index:2}}nav a{{text-decoration:none;color:var(--muted)}}section{{padding:24px 0;border-bottom:1px solid var(--line)}}.decision{{display:grid;grid-template-columns:1.25fr .75fr;gap:20px;align-items:start}}.callout{{border-left:4px solid var(--green);padding:14px 16px;background:var(--surface)}}.callout strong{{color:#79d5a5}}.kpis{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:16px}}.kpi{{background:var(--surface);padding:13px;border-radius:6px;min-width:0}}.kpi b{{display:block;font-size:22px;color:#fff}}.kpi span{{color:var(--muted);font-size:13px}}.grid2{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}}.panel{{background:var(--surface);padding:15px;border-radius:6px;min-width:0}}.bar-row{{display:grid;grid-template-columns:170px minmax(120px,1fr) 90px;gap:9px;align-items:center;margin:9px 0;font-size:13px}}.bar-row strong{{text-align:right}}.track{{height:10px;background:#29333a;border-radius:2px;overflow:hidden}}.track i{{display:block;height:100%}}.table-wrap{{max-width:100%;overflow-x:auto}}table{{width:100%;border-collapse:collapse;table-layout:fixed}}th,td{{border:1px solid var(--line);padding:8px;text-align:left;vertical-align:top}}th{{background:var(--surface2)}}thead th{{font-size:12px}}.matrix th:first-child{{width:15%}}.matrix td{{font-size:13px}}.selected{{color:#79d5a5}}.warning{{color:#f2c66d}}.bad{{color:#ff8984}}ul{{margin:8px 0;padding-left:20px}}li{{margin:4px 0}}.sources td:first-child{{width:34%}}footer{{padding-top:18px;color:var(--muted)}}
@media(max-width:800px){{.decision,.grid2{{grid-template-columns:1fr}}.kpis{{grid-template-columns:repeat(2,minmax(0,1fr))}}.bar-row{{grid-template-columns:115px minmax(80px,1fr) 75px}}}}
@page{{size:A4 landscape;margin:9mm}}@media print{{:root{{color-scheme:light;--bg:#fff;--surface:#f4f6f7;--surface2:#e9eef0;--line:#9aa5aa;--text:#111;--muted:#46545b}}body{{font-size:9pt;print-color-adjust:exact;-webkit-print-color-adjust:exact}}main{{width:100%;padding:0}}nav{{display:none}}header{{padding-bottom:4mm}}section{{padding:4mm 0;break-inside:auto}}#performance,.page-break{{break-before:page}}.panel,.kpi,.callout{{break-inside:avoid}}.kpi b{{color:#111}}h2,h3{{break-after:avoid}}table{{font-size:8pt}}th,td{{padding:4px}}thead{{display:table-header-group}}tr{{break-inside:avoid}}.bar-row{{grid-template-columns:35mm 1fr 22mm;margin:4px 0}}a{{color:#111;text-decoration:none}}footer{{font-size:8pt}}}}
</style></head><body><main>
<header><div class="meta">RTX 4090 48 GiB · 2026-08-17 · 同机实测</div><h1>Qwen3.8-27B FP8、Unsloth GGUF 与 MTP2 选型</h1><p class="muted">四种配置分维度比较：FP8/vLLM、UD-Q4_K_XL 基线、UD-Q4_K_XL + MTP2、UD-Q6_K_XL。</p></header>
<nav><a href="#decision">结论</a><a href="#performance">性能</a><a href="#context">上下文</a><a href="#quality">质量</a><a href="#method">方法</a><a href="#deployment">部署</a><a href="#evidence">证据</a></nav>

<section id="decision"><div class="decision"><div class="callout"><h2>选择 UD-Q4_K_XL + MTP2，默认 256K</h2><p><strong>作为 RTX 4090 默认推理配置。</strong> 在完全相同的模型、65K context、F16 KV、采样和单流请求下，仅启用内置 MTP head，decode 从 46.57 提升到 94.33 tok/s（+102.5%），E2E 从 23.19 降到 11.99 秒；业务准确率保持 17/18，视觉保持 6/6。</p><p>生产 context 提升到 262,144：245,034-token 首尾双校验码精确召回，短提示 TPS 比 65K 仅低 0.9%，仍保留 11.58 GiB 显存。128K 是需要与其他 GPU 服务共存时的保守档。</p></div><div class="panel"><h3>选择门槛</h3><ul><li>SQL、Python、故障分析不能出现系统性退化</li><li>图片识别必须保留</li><li>禁止 CPU weight offload</li><li>目标 context 下保留至少 4 GiB 显存余量</li><li>长上下文必须实际填充并验证首尾召回</li></ul></div></div>
<div class="kpis"><div class="kpi"><b>93.45 tok/s</b><span>256K 档短提示 decode</span></div><div class="kpi"><b>245,034</b><span>已验证输入 tokens</span></div><div class="kpi"><b>100%</b><span>首尾校验码召回</span></div><div class="kpi"><b>35.79 GiB</b><span>256K + F16 KV + MTP 空载显存</span></div></div></section>

<section id="performance"><h2>性能分维度对比</h2><p class="muted">响应时间受到实际生成 token 数影响，不能代替吞吐；因此 decode TPS、E2E、TTFT、完成 token 分列展示。</p><div class="grid2"><div class="panel"><h3>Decode 吞吐，越高越好</h3>{speed_chart}</div><div class="panel"><h3>端到端响应时间，越低越好</h3>{latency_chart}</div><div class="panel"><h3>空载显存，越低越好</h3>{memory_chart}</div><div class="panel"><h3>服务启动，越低越好</h3>{startup_chart}</div></div>
<div class="table-wrap"><table><thead><tr><th>配置</th><th>业务</th><th>视觉</th><th>TPS</th><th>TTFT</th><th>E2E</th><th>输出 token</th><th>最终答案</th><th>显存</th><th>启动</th><th>权重</th></tr></thead><tbody>{''.join(table_rows)}</tbody></table></div>
<p class="warning">FP8 的三次性能请求均生成 2,048 个 reasoning token 后以 length 结束，final content 为空；三种 llama.cpp 配置均正常 stop 并给出最终答案。MTP2 生成 1,111 token，基线为 1,069 token，因此选型以 TPS、质量和 E2E 联合判断。</p><p>短输出交叉验证（max 128）：基线 {short_baseline['summary']['decode_tokens_per_second']['mean']:.2f} tok/s、{short_baseline['summary']['response_seconds']['mean']:.2f}s；MTP2 {short_mtp2['summary']['decode_tokens_per_second']['mean']:.2f} tok/s、{short_mtp2['summary']['response_seconds']['mean']:.2f}s。本机没有复现社区在部分短输出上的退化。</p></section>

<section id="context" class="page-break"><h2>上下文档位实测</h2><p>三档都使用同一 Q4 + MTP2、F16 KV、parallel 1。短提示性能为同一 1,111-token 输出的 1 次预热 + 3 次实测；128K/256K 另实际填充长提示，在开头和末尾放置两个确定性校验码。</p><div class="table-wrap"><table><thead><tr><th>档位</th><th>分配 context</th><th>空载显存</th><th>显存余量</th><th>短提示 TPS</th><th>短提示 E2E</th><th>长上下文结果</th></tr></thead><tbody>{''.join(context_rows)}</tbody></table></div><div class="grid2"><div class="panel"><h3>默认：256K</h3><p>覆盖模型原生 262,144 context；245,034-token 首尾召回通过。适合大型代码库、湖仓元数据和故障资料的单用户分析。</p></div><div class="panel"><h3>保守：128K</h3><p>首尾召回同样通过，空载多保留约 8.75 GiB 显存。需要同卡临时运行其他 GPU 任务时切换到该档。</p></div></div><p class="warning">长提示延迟主要来自 prefill：120K 为 68.8s，245K 为 195.0s。256K 能运行不代表每个请求都应填满；客户端应按任务控制实际输入长度。</p></section>

<section id="quality" class="page-break"><h2>准确率与任务时延</h2><p>FP8 为 18/18；Q4 基线、Q4 + MTP2 与 Q6 均为 17/18。MTP2 与 Q4 基线失败的是同一个区间合并题；18 题样本只能证明本轮没有系统性退化，不能证明量化或推测解码在统计上等精度。</p><div class="table-wrap"><table class="matrix"><thead><tr><th>维度</th><th>FP8 / vLLM</th><th>UD-Q4 基线</th><th>UD-Q4 + MTP2</th><th>UD-Q6</th></tr></thead><tbody>{''.join(categories)}</tbody></table></div>
<h3>失败项原始结论</h3><table><tbody>{''.join(failed_cases)}</tbody></table>
<p>Q4 基线与 MTP2 都将整数区间相邻解释为 touching，使用了 <code>end + 1</code>；Q6 在 schema drift 中额外返回了变更类型，而 oracle 只要求路径。它们是需求解释偏差，不是 CUDA、截断或空回答。</p>
<h3>Dynamic GGUF 不是单一位宽</h3><table><thead><tr><th>文件</th><th>866 个 tensor 的类型分布</th></tr></thead><tbody><tr><th>UD-Q4_K_XL</th><td>{q4_types}</td></tr><tr><th>UD-Q6_K_XL</th><td>{q6_types}</td></tr></tbody></table><p class="muted">API 的概括 ftype 不能代表 Dynamic GGUF 的逐 tensor 配置，选型以文件身份和实际分布为准。</p></section>

<section id="method" class="page-break"><h2>测试环境与方法</h2><div class="grid2"><div><h3>固定环境</h3><ul><li>GPU：NVIDIA GeForce RTX 4090，49,140 MiB；driver 580.173.02</li><li>FP8：vLLM 0.19.0，65,536 context，CPU offload 0</li><li>首轮 GGUF：llama.cpp build 10459 / commit 4197155ad</li><li>MTP A/B：官方容器 build 10454 / commit 4df29be4f，同一 OCI digest</li><li>GGUF：65,536 context，parallel 1，F16 KV，Flash Attention，全 GPU layers</li><li>MTP arm 仅增加 draft-mtp、n-max 2、p-min 0</li><li>模型与 mmproj：ModelScope，revision f1bfb127…，本地 SHA-256 校验</li><li>采样：temperature 1.0、top_p 0.95、top_k 20、seed 42、reasoning_effort low</li></ul></div><div><h3>测量定义</h3><ul><li>质量：lakehouse-thinking-v2，SQL/Python/故障各 6 题</li><li>视觉：6 张确定性生成图，严格 exact-match</li><li>性能：1 次预热 + 3 次单流 SSE 实测</li><li>TTFT：请求发出至首个 reasoning/content delta</li><li>TPS：completion_tokens / (E2E - TTFT)</li><li>启动：进程或容器 start 至 health-ready；未清 Linux page cache</li><li>MTP 启动 20.43s 来自 warm page-cache，不参与冷启动排名</li></ul></div></div>
<h3>候选筛选</h3><table><thead><tr><th>候选</th><th>结论</th><th>原因</th></tr></thead><tbody><tr><td>Unsloth NVFP4</td><td>排除</td><td>vLLM/LLM Compressor 官方说明 NVFP4 需要 Blackwell compute capability 10.0；RTX 4090 是 Ada 8.9。</td></tr><tr><td>GGUF + vLLM</td><td>排除</td><td>vLLM 官方文档仍将 GGUF 标为 experimental、under-optimized，并要求 OOT plugin。</td></tr><tr><td>Dynamic GGUF + llama.cpp</td><td class="selected">采用</td><td>CUDA 支持成熟，Qwen3.8 文本与新视觉 projector 均在固定 commit 上验证。</td></tr></tbody></table>
<p>技术来源：<a href="https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/tree/f1bfb127c64f7072bdd2cad55f258b9c8b2910fe">Unsloth Qwen3.8 GGUF 固定 revision</a> · <a href="https://github.com/sudoingX/qwen38-mtp">Qwen3.8 MTP 社区 recipe</a> · <a href="https://github.com/ggml-org/llama.cpp/pull/22673">llama.cpp MTP 实现</a> · <a href="https://docs.vllm.ai/projects/llm-compressor/en/latest/steps/choosing-scheme/">vLLM quantization scheme</a> · <a href="https://docs.vllm.ai/en/stable/features/quantization/gguf/">vLLM GGUF documentation</a></p></section>

<section id="deployment" class="page-break"><h2>部署决策与运行边界</h2><div class="grid2"><div class="panel"><h3>默认服务</h3><ul><li>模型：<code>Qwen3.8-27B-UD-Q4_K_XL.gguf</code></li><li>API ID：<code>qwen3.8-27b</code></li><li>端口：<code>0.0.0.0:8005</code></li><li>上下文：262,144；parallel 1；F16 KV</li><li>MTP：draft-mtp；n-max 2；p-min 0</li><li>资源：全 GPU layers；容器内存上限 48 GiB</li><li>Embedding：BGE-M3 / CPU-only Ollama 保持独立运行</li></ul></div><div class="panel"><h3>生产建议</h3><ul><li>常规请求默认 non-thinking</li><li>复杂 SQL/Python/故障分析按请求启用 low</li><li>MTP 是单流优化；并发 2/4 未验收前不增加 parallel</li><li>监控 GPU headroom，低于 4 GiB 拒绝并发扩容</li><li>实际输入按任务裁剪，不因分配 256K 而默认填满</li><li>无认证 API 仅限受控 LAN，不直接暴露公网</li></ul></div></div>
<p>首轮量化选型使用 llama.cpp <code>b10459 / 4197155ad</code>；MTP 严格 A/B 与最终容器固定为官方 <code>b10454 / 4df29be4</code>。65K A/B 为 <strong>{round(deployed_quality['macro_score'] * 18)}/18、视觉 {deployed_vision['passed']}/6、{deployed_performance['summary']['decode_tokens_per_second']['mean']:.2f} tok/s</strong>；256K 生产档短提示为 <strong>{context_profiles['256k']['decode_tokens_per_second']:.2f} tok/s、{context_profiles['256k']['response_seconds']:.2f}s</strong>，长上下文召回通过。</p>
<p>部署脚本：<code>qwen38-rtx4090-llamacpp/</code>。Q6 与 FP8 不删除，作为离线回归和回滚资产；同一时刻只运行一个 27B 服务。</p></section>

<section id="evidence"><h2>原始证据身份</h2><div class="table-wrap"><table class="sources"><thead><tr><th>文件</th><th>SHA-256</th></tr></thead><tbody>{''.join(source_hashes)}</tbody></table></div></section>
<footer>结论只覆盖本页记录的 RTX 4090、模型 revision、运行时 commit、上下文与采样参数。并发 2/4、KV 量化替代方案与 48 小时压力测试仍待后续独立验证。</footer>
</main></body></html>"""
    OUTPUT.write_text(document)
    print(json.dumps({"output": str(OUTPUT), "selected": "UD-Q4_K_XL + MTP2", "profiles": rows}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
