#!/usr/bin/env python3
"""Publish completed podcast ASR workspaces to the SenseVoice static website.

Scans podcast workspaces for */output/transcription_*.json, copies lightweight
ASR artifacts, generates per-episode report/full-transcript pages, and updates a
site index at /static/podcast-asr/.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

PODCAST_ROOT = Path(os.environ.get("PODCAST_ROOT", "~/podcast")).expanduser()
STATIC_ROOT = Path(os.environ.get("SENSEVOICE_STATIC_ROOT", "~/deployments/sensevoice/static")).expanduser()
LIBRARY_SLUG = "podcast-asr"
LIBRARY_DIR = STATIC_ROOT / LIBRARY_SLUG
DEFAULT_PORT = int(os.environ.get("SENSEVOICE_WEB_PORT", "8020"))


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def slugify(text: str, fallback: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    # Keep URLs readable and bounded.
    if not text:
        text = fallback
    if re.fullmatch(r"[\u4e00-\u9fff-]+", text):
        text = fallback
    return text[:88].strip("-") or fallback


def fmt_ts(seconds: float) -> str:
    seconds = max(0, int(float(seconds or 0)))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def fmt_bytes(n: int | float | None) -> str:
    if not n:
        return "—"
    n = float(n)
    units = ["B", "KB", "MB", "GB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    return f"{n:.1f} {units[i]}" if i else f"{int(n)} B"


def get_lan_ip() -> str:
    try:
        out = subprocess.check_output(["hostname", "-I"], text=True, timeout=2)
        for item in out.split():
            if item and not item.startswith("127."):
                return item
    except Exception:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return "127.0.0.1"


def artifact_sig(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for path in sorted(paths, key=lambda p: str(p)):
        if not path.exists():
            continue
        st = path.stat()
        h.update(str(path).encode())
        h.update(str(st.st_size).encode())
        h.update(str(st.st_mtime_ns).encode())
    return h.hexdigest()


def coverage_from_chunks(trans: dict[str, Any]) -> tuple[float, list[list[float]]]:
    chunks = trans.get("chunks") or []
    intervals = sorted(
        (float(c.get("start", 0)), float(c.get("end", 0)))
        for c in chunks
        if not c.get("error") and c.get("end") is not None
    )
    merged: list[list[float]] = []
    for s, e in intervals:
        if not merged or s > merged[-1][1] + 0.1:
            merged.append([s, e])
        else:
            merged[-1][1] = max(merged[-1][1], e)
    covered = sum(e - s for s, e in merged)
    duration = float(trans.get("duration_seconds") or 0)
    pct = covered / duration * 100 if duration else 0.0
    return pct, merged


@dataclass
class Episode:
    work_dir: Path
    output_dir: Path
    trans_path: Path
    trans: dict[str, Any]
    benchmark_path: Path | None
    benchmark: dict[str, Any]
    manifest_path: Path | None
    site_meta: dict[str, Any]
    slug: str
    device: str
    artifacts: dict[str, Path] = field(default_factory=dict)
    signature: str = ""

    @property
    def dest_dir(self) -> Path:
        return LIBRARY_DIR / self.slug

    @property
    def legacy_dir(self) -> Path:
        return STATIC_ROOT / self.slug


def discover_episodes(root: Path = PODCAST_ROOT) -> list[Episode]:
    episodes: list[Episode] = []
    for output_dir in sorted(root.glob("*/output")):
        trans_candidates = sorted(output_dir.glob("transcription_*.json"))
        if not trans_candidates:
            continue
        trans_path = output_dir / "transcription_cuda.json" if (output_dir / "transcription_cuda.json").exists() else trans_candidates[-1]
        trans = read_json(trans_path, {}) or {}
        if not trans.get("chunks"):
            continue
        bench_candidates = sorted(output_dir.glob("benchmark_cpu_gpu_*.json"), key=lambda p: p.stat().st_mtime)
        benchmark_path = bench_candidates[-1] if bench_candidates else None
        benchmark = read_json(benchmark_path, {}) if benchmark_path else {}
        manifest_path = output_dir / "manifest.json" if (output_dir / "manifest.json").exists() else None
        site_meta = read_json(output_dir / "site_meta.json", {}) or {}
        episode_id = str(trans.get("episode_id") or output_dir.parent.name)
        fallback = f"xiaoyuzhou-{episode_id}" if "xiaoyuzhou" in output_dir.parent.name else episode_id
        slug = str(site_meta.get("slug") or slugify(trans.get("title") or episode_id, fallback))
        device = str(trans.get("device") or trans_path.stem.replace("transcription_", "") or "cuda")
        artifacts: dict[str, Path] = {
            f"transcription_{device}.json": trans_path,
        }
        for suffix in ["md", "txt", "srt"]:
            p = output_dir / f"transcript_{device}.{suffix}"
            if p.exists():
                artifacts[p.name] = p
        if manifest_path:
            artifacts["manifest.json"] = manifest_path
        if benchmark_path:
            artifacts[benchmark_path.name] = benchmark_path
        zip_candidates = sorted(output_dir.glob("*_asr_results.zip"), key=lambda p: p.stat().st_mtime)
        if zip_candidates:
            artifacts["asr_results.zip"] = zip_candidates[-1]
        for summary_name in ["podcast_summary.json", "podcast_summary.md"]:
            p = output_dir / summary_name
            if p.exists():
                artifacts[summary_name] = p
        if (output_dir / "site_meta.json").exists():
            artifacts["site_meta.json"] = output_dir / "site_meta.json"
        ep = Episode(
            work_dir=output_dir.parent,
            output_dir=output_dir,
            trans_path=trans_path,
            trans=trans,
            benchmark_path=benchmark_path,
            benchmark=benchmark,
            manifest_path=manifest_path,
            site_meta=site_meta,
            slug=slug,
            device=device,
            artifacts=artifacts,
        )
        ep.signature = artifact_sig(list(artifacts.values()))
        episodes.append(ep)
    return episodes


CSS = """
:root{--bg:#081018;--panel:#101a25;--panel2:#142130;--ink:#e8f1fb;--muted:#9db0c6;--line:rgba(190,214,242,.16);--accent:#66d9ff;--accent2:#b9f56b;--warn:#ffd166;color-scheme:dark}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;font-family:ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:radial-gradient(circle at 16% 0%,rgba(102,217,255,.18),transparent 32%),radial-gradient(circle at 86% 8%,rgba(185,245,107,.12),transparent 30%),var(--bg);color:var(--ink);line-height:1.72}a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}.shell{max-width:1180px;margin:0 auto;padding:32px 20px 72px}.hero,.section,.card{background:linear-gradient(180deg,rgba(255,255,255,.06),rgba(255,255,255,.025));border:1px solid var(--line);border-radius:28px;box-shadow:0 24px 70px rgba(0,0,0,.32);backdrop-filter:blur(10px)}.hero{padding:38px;margin-bottom:22px}.eyebrow{display:inline-flex;gap:8px;color:var(--accent2);text-transform:uppercase;letter-spacing:.12em;font-size:12px;font-weight:800}.dot{width:10px;height:10px;border-radius:999px;background:var(--accent2);box-shadow:0 0 20px var(--accent2);display:inline-block;margin-top:.35em}h1{font-size:clamp(34px,5vw,66px);line-height:1.04;margin:14px 0 16px;letter-spacing:-.05em;text-wrap:balance}h2{font-size:clamp(23px,3vw,36px);line-height:1.15;margin:0 0 16px;letter-spacing:-.035em}h3{margin:0}.lead{max-width:850px;color:#bfd0e2;font-size:18px;margin:0 0 24px}.actions,.downloads,.toolbar{display:flex;gap:12px;flex-wrap:wrap;align-items:center}.btn{display:inline-flex;align-items:center;gap:8px;min-height:42px;padding:10px 15px;border-radius:999px;border:1px solid var(--line);background:rgba(255,255,255,.06);color:var(--ink);font-weight:800}.btn.primary{color:#06111a;background:linear-gradient(135deg,var(--accent),var(--accent2));border:none}.metrics{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-bottom:22px}.metric{padding:18px;border-radius:20px;background:rgba(255,255,255,.045);border:1px solid var(--line);min-height:120px}.metric small,.muted{color:var(--muted)}.metric strong{display:block;font-size:clamp(24px,3vw,34px);letter-spacing:-.04em;margin:6px 0 2px}.section{padding:28px;margin-bottom:22px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:18px}table{width:100%;border-collapse:collapse;min-width:720px}th,td{padding:12px 14px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{color:#bed1e8;font-size:12px;text-transform:uppercase;letter-spacing:.08em;background:rgba(255,255,255,.035)}tr:last-child td{border-bottom:none}.summary{margin:0;padding:0;list-style:none;display:grid;gap:12px}.summary li{padding:14px;border:1px solid var(--line);border-radius:16px;background:rgba(255,255,255,.04)}.summary strong{display:block}.notice{border-left:3px solid var(--warn);padding-left:14px;color:#cad8e8}.pill{display:inline-flex;padding:4px 9px;border-radius:999px;background:rgba(102,217,255,.1);color:#cef3ff;border:1px solid rgba(102,217,255,.22);font-size:12px}.search{flex:1;min-width:240px;height:44px;border-radius:999px;border:1px solid var(--line);background:rgba(255,255,255,.06);color:var(--ink);padding:0 16px;outline:none}.chunk{padding:20px;border:1px solid var(--line);border-radius:20px;background:rgba(255,255,255,.035);margin-bottom:14px}.chunk-head{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:10px}.chunk p{margin:0;color:#d9e6f5}.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}.card{padding:22px}.card-title{font-size:18px;font-weight:850;margin:8px 0}.footer{text-align:center;color:var(--muted);font-size:13px;padding-top:20px}mark{background:rgba(255,209,102,.35);color:#fff;border-radius:4px;padding:0 2px}.topic-block{padding:16px;border-radius:18px;background:rgba(255,255,255,.035);border:1px solid var(--line);margin:12px 0}.quote{padding:14px 16px;border-left:3px solid var(--accent2);background:rgba(185,245,107,.06);border-radius:12px;margin:12px 0}.quote blockquote{margin:0 0 8px;font-size:18px;color:#f2ffe0}.summary-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:980px){.grid2,.summary-grid{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(2,1fr)}}@media(max-width:560px){.shell{padding:18px 12px 48px}.hero,.section,.card{border-radius:20px;padding:20px}.metrics{grid-template-columns:1fr}table{min-width:640px}}
""".strip()


def safe_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def render_summary_list(items: list[Any]) -> str:
    if not items:
        return ""
    return "<ul>" + "".join(f"<li>{esc(item)}</li>" for item in items) + "</ul>"


def render_llm_summary_html(summary_data: dict[str, Any]) -> str:
    if not summary_data:
        return '<section class="section"><h2>LLM 总结</h2><p class="muted">尚未生成总结。运行 <code>generate_podcast_summary.py</code> 后会自动显示在这里。</p></section>'
    guests = []
    for g in safe_list(summary_data.get("guests")):
        if isinstance(g, dict):
            guests.append(f"<li><strong>{esc(g.get('name', 'unknown'))}</strong>：{esc(g.get('role', 'unknown'))}<br><span class=\"muted\">依据：{esc(g.get('evidence', 'unknown'))}</span></li>")
        else:
            guests.append(f"<li>{esc(g)}</li>")
    topics = []
    for i, t in enumerate(safe_list(summary_data.get("topic_summary")), 1):
        if isinstance(t, dict):
            topics.append(f"<div class=\"topic-block\"><h3>{i}. {esc(t.get('topic', '未命名话题'))}</h3><p class=\"muted\">时间：{esc(t.get('timestamp_range', 'unknown'))}</p><p>{esc(t.get('summary', ''))}</p>{render_summary_list(safe_list(t.get('key_points')))}</div>")
        else:
            topics.append(f"<div class=\"topic-block\"><h3>{i}. {esc(t)}</h3></div>")
    quotes = []
    for q in safe_list(summary_data.get("golden_quotes")):
        if isinstance(q, dict):
            quotes.append(f"<div class=\"quote\"><blockquote>{esc(q.get('quote', ''))}</blockquote><div class=\"muted\">{esc(q.get('speaker_or_context', 'unknown'))} · {esc(q.get('why_it_matters', ''))}</div></div>")
        else:
            quotes.append(f"<div class=\"quote\"><blockquote>{esc(q)}</blockquote></div>")
    terms = []
    for term in safe_list(summary_data.get("entities_and_terms")):
        if isinstance(term, dict):
            terms.append(f"<li><strong>{esc(term.get('term', ''))}</strong>：{esc(term.get('explanation', ''))}</li>")
        else:
            terms.append(f"<li>{esc(term)}</li>")
    generated = summary_data.get("generated_at") or ""
    model = summary_data.get("summary_model") or ""
    return f'''<section class="section" id="llm-summary"><h2>LLM 总结</h2><p class="muted">模型：{esc(model)} · 生成时间：{esc(generated)}</p><div class="downloads"><a class="btn primary" href="podcast_summary.md" download>下载总结 Markdown</a><a class="btn" href="podcast_summary.json" download>下载总结 JSON</a></div><h3>主题</h3><p>{esc(summary_data.get('theme', ''))}</p><div class="summary-grid"><div><h3>嘉宾</h3><ul>{''.join(guests)}</ul></div><div><h3>背景</h3><p>{esc(summary_data.get('background', ''))}</p></div></div><h3>讨论的话题总结</h3>{''.join(topics)}<h3>金句</h3>{''.join(quotes)}<div class="summary-grid"><div><h3>关键洞察</h3>{render_summary_list(safe_list(summary_data.get('key_takeaways')))}</div><div><h3>专名与术语</h3><ul>{''.join(terms)}</ul></div></div><h3>注意事项 / ASR 不确定处</h3>{render_summary_list(safe_list(summary_data.get('caveats')))}<h3>TL;DR</h3><p>{esc(summary_data.get('tldr', ''))}</p></section>'''


def copy_artifacts(ep: Episode, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name, src in ep.artifacts.items():
        if src.exists():
            shutil.copy2(src, dest / name)


def render_episode(ep: Episode) -> tuple[str, str, dict[str, Any]]:
    trans = ep.trans
    bench = ep.benchmark or {}
    summary = trans.get("summary") or {}
    chunks = trans.get("chunks") or []
    ok_chunks = [c for c in chunks if not c.get("error")]
    failed_chunks = [c for c in chunks if c.get("error")]
    coverage, merged = coverage_from_chunks(trans)
    speedups = bench.get("speedups") or {}
    devices = bench.get("devices") or {}
    cpu = devices.get("cpu") or {}
    gpu = devices.get("cuda") or devices.get("gpu") or {}
    title = trans.get("title") or ep.slug
    source_url = trans.get("url") or ""
    duration_seconds = float(trans.get("duration_seconds") or summary.get("audio_seconds") or 0)
    transcript_md = f"transcript_{ep.device}.md"
    transcript_txt = f"transcript_{ep.device}.txt"
    transcript_srt = f"transcript_{ep.device}.srt"
    transcription_json = f"transcription_{ep.device}.json"
    bench_name = ep.benchmark_path.name if ep.benchmark_path else ""
    published_at = datetime.now().isoformat(timespec="seconds")
    llm_summary = read_json(ep.output_dir / "podcast_summary.json", {}) or {}
    llm_summary_html = render_llm_summary_html(llm_summary)
    llm_tldr = str(llm_summary.get("tldr") or "")

    cards = [
        ("音频时长", trans.get("duration_formatted") or fmt_ts(duration_seconds), f"{duration_seconds:,.1f}s"),
        ("覆盖率", f"{coverage:.1f}%", f"{len(ok_chunks)}/{len(chunks)} chunks OK"),
        ("GPU 总耗时", f"{float(summary.get('pipeline_wall_seconds') or summary.get('wall_seconds') or 0):.1f}s", f"{summary.get('x_realtime_wall', '—')}× realtime"),
        ("GPU RTF", f"{float(summary.get('pipeline_rtf') or summary.get('rtf_wall') or 0):.4f}", "越低越快"),
        ("转写文本", f"{int(summary.get('chars') or sum(int(c.get('chars') or 0) for c in chunks)):,}", "字符"),
        ("GPU vs CPU", f"{float(speedups.get('cuda_vs_cpu_inference') or 0):.2f}×", "inference speedup"),
    ]
    card_html = "\n".join(
        f'<div class="metric"><small>{esc(k)}</small><strong>{esc(v)}</strong><small>{esc(note)}</small></div>'
        for k, v, note in cards
    )
    chunk_rows = []
    transcript_sections = []
    for c in chunks:
        idx = int(c.get("chunk_index") or 0)
        text = c.get("text") or ""
        plain = re.sub(r"\s+", " ", text).strip()
        status = "OK" if not c.get("error") else str(c.get("error"))
        chunk_rows.append(
            f'<tr><td><a href="full.html#chunk-{idx:03d}">{idx+1:02d}</a></td><td>{esc(c.get("start_ts"))}–{esc(c.get("end_ts"))}</td><td>{float(c.get("duration_seconds") or 0):.1f}s</td><td>{int(c.get("chars") or 0):,}</td><td>{float(c.get("inference_seconds") or 0):.2f}s</td><td>{float(c.get("rtf_inference") or 0):.4f}</td><td>{esc(status)}</td></tr>'
        )
        transcript_sections.append(
            f'<article class="chunk" id="chunk-{idx:03d}" data-text="{esc(plain)}"><div class="chunk-head"><span class="pill">Chunk {idx+1:02d}</span><h3>{esc(c.get("start_ts"))} → {esc(c.get("end_ts"))}</h3><span class="pill">{int(c.get("chars") or 0):,} 字符</span></div><p>{esc(text)}</p></article>'
        )

    work_steps = [
        ("自动发现", "publisher 扫描 PODCAST_ROOT 下 */output/transcription_*.json，发现完成的 ASR 结果。"),
        ("复制轻量文件", "只发布 Markdown/TXT/SRT/JSON/ZIP/benchmark，不复制原始音频和切片 WAV。"),
        ("生成单集页面", "自动生成报告页、全文页、下载链接和可搜索分段转写。"),
        ("更新总索引", "自动更新 /static/podcast-asr/，把新播客加入网站列表。"),
        ("保留旧链接", "如果旧的 /static/<slug>/ 已存在，会同步镜像，避免旧链接失效。"),
    ]
    steps_html = "".join(f'<li><strong>{esc(a)}</strong><span class="muted">{esc(b)}</span></li>' for a, b in work_steps)

    source_link = f'<a class="btn" href="{esc(source_url)}" target="_blank" rel="noopener">小宇宙原链接</a>' if source_url else ""
    bench_button = f'<a class="btn" href="{esc(bench_name)}" download>Benchmark JSON</a>' if bench_name else ""
    report_html = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}｜播客 ASR 报告</title><style>{CSS}</style></head><body><main class="shell"><section class="hero"><span class="eyebrow"><span class="dot"></span>Podcast ASR · Auto Published</span><h1>小宇宙播客完整转写报告</h1><p class="lead">{esc(title)}</p><div class="actions"><a class="btn primary" href="full.html">打开全文网页</a><a class="btn" href="#{'transcript'}">页内全文</a>{source_link}<a class="btn" href="{esc(transcript_md)}" download>下载 Markdown</a><a class="btn" href="asr_results.zip" download>下载结果包</a></div></section><section class="metrics">{card_html}</section>{llm_summary_html}<section class="section"><h2>网站发布状态</h2><div class="table-wrap"><table><tbody><tr><th>Episode ID</th><td>{esc(trans.get('episode_id'))}</td></tr><tr><th>源链接</th><td>{f'<a href="{esc(source_url)}" target="_blank" rel="noopener">{esc(source_url)}</a>' if source_url else '—'}</td></tr><tr><th>全文网页</th><td><a href="full.html">full.html</a> · <a href="{esc(transcript_md)}">Markdown 全文</a> · <a href="{esc(transcript_txt)}">TXT 全文</a></td></tr><tr><th>自动发布</th><td>由 <code>scripts/publish_podcast_asr_site.py</code> 生成；发布时间 {esc(published_at)}</td></tr></tbody></table></div></section><section class="section"><h2>自动发布流程</h2><ol class="summary">{steps_html}</ol></section><section class="grid2"><div class="section"><h2>CPU / GPU 对比</h2><div class="table-wrap"><table><thead><tr><th>设备</th><th>Model load</th><th>Inference</th><th>Wall</th><th>RTF</th><th>字符</th></tr></thead><tbody><tr><td>CPU</td><td>{float(cpu.get('model_load_seconds') or 0):.2f}s</td><td>{float(cpu.get('inference_seconds') or 0):.2f}s</td><td>{float(cpu.get('wall_seconds') or 0):.2f}s</td><td>{float(cpu.get('rtf_inference') or 0):.4f}</td><td>{int(cpu.get('chars') or 0):,}</td></tr><tr><td>GPU / CUDA</td><td>{float(gpu.get('model_load_seconds') or 0):.2f}s</td><td>{float(gpu.get('inference_seconds') or 0):.2f}s</td><td>{float(gpu.get('wall_seconds') or 0):.2f}s</td><td>{float(gpu.get('rtf_inference') or 0):.4f}</td><td>{int(gpu.get('chars') or 0):,}</td></tr></tbody></table></div><p class="notice">同一 {float(bench.get('audio_seconds') or 0):.0f}s 片段：GPU 纯 inference 提速 {float(speedups.get('cuda_vs_cpu_inference') or 0):.2f}×，端到端 wall time 提速 {float(speedups.get('cuda_vs_cpu_wall') or 0):.2f}×。</p></div><div class="section"><h2>完整转写统计</h2><div class="table-wrap"><table><tbody><tr><th>原始 M4A</th><td>{fmt_bytes(trans.get('source_size_bytes'))}</td></tr><tr><th>16k WAV</th><td>{fmt_bytes(trans.get('wav_size_bytes'))}</td></tr><tr><th>音频时长</th><td>{esc(trans.get('duration_formatted') or fmt_ts(duration_seconds))} / {duration_seconds:,.1f}s</td></tr><tr><th>切片数</th><td>{len(chunks)} 段；成功 {len(ok_chunks)}，失败 {len(failed_chunks)}</td></tr><tr><th>覆盖区间</th><td>{fmt_ts(merged[0][0]) if merged else '—'} → {fmt_ts(merged[-1][1]) if merged else '—'}，{coverage:.1f}%</td></tr><tr><th>GPU pipeline wall</th><td>{float(summary.get('pipeline_wall_seconds') or summary.get('wall_seconds') or 0):.1f}s；RTF {float(summary.get('pipeline_rtf') or summary.get('rtf_wall') or 0):.4f}</td></tr><tr><th>实时倍速</th><td>{esc(summary.get('x_realtime_wall', '—'))}× realtime</td></tr></tbody></table></div></div></section><section class="section"><h2>下载与全文链接</h2><div class="downloads"><a class="btn primary" href="full.html">全文网页</a><a class="btn" href="{esc(transcript_md)}" download>Markdown 全文</a><a class="btn" href="{esc(transcript_txt)}" download>TXT 全文</a><a class="btn" href="{esc(transcript_srt)}" download>SRT 字幕</a><a class="btn" href="{esc(transcription_json)}" download>JSON</a>{bench_button}<a class="btn" href="asr_results.zip" download>结果包 ZIP</a></div></section><section class="section"><h2>分段性能明细</h2><div class="table-wrap"><table><thead><tr><th>#</th><th>时间</th><th>音频长</th><th>字符</th><th>GPU inference</th><th>RTF</th><th>状态</th></tr></thead><tbody>{''.join(chunk_rows)}</tbody></table></div></section><section class="section" id="transcript"><h2>完整转写稿</h2><p class="notice">原始 SenseVoice 输出已做标签清理，但未做专名纠错；英文、人名、公司名可能有音译误差。更适合知识库入库前再做一次纠错清洗。</p><div class="toolbar"><a class="btn primary" href="full.html">打开独立全文页</a><input id="searchBox" class="search" placeholder="搜索全文，例如 SpaceX / 马斯克 / IPO / 火箭"><button class="btn" id="clearSearch">清除</button><span class="pill" id="matchCount">{len(chunks)} 段</span></div><div id="chunks">{''.join(transcript_sections)}</div></section><div class="footer">Generated locally on GB10 · Auto Podcast ASR Publisher · {esc(published_at)}</div></main><script>{SEARCH_JS}</script></body></html>'''

    full_html = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}｜完整转写全文</title><style>{CSS}</style></head><body><main class="shell"><section class="hero"><span class="eyebrow"><span class="dot"></span>Full Transcript</span><h1>完整转写全文</h1><p class="lead">{esc(title)}</p><div class="actions"><a class="btn primary" href="index.html">返回报告</a>{source_link}<a class="btn" href="{esc(transcript_md)}" download>Markdown</a><a class="btn" href="{esc(transcript_txt)}" download>TXT</a></div></section><section class="section"><div class="toolbar"><input id="searchBox" class="search" placeholder="搜索全文"><button class="btn" id="clearSearch">清除</button><span class="pill" id="matchCount">{len(chunks)} 段</span></div><div id="chunks">{''.join(transcript_sections)}</div></section><div class="footer">全文网页链接：<code>full.html</code> · 原始播客：{f'<a href="{esc(source_url)}">小宇宙</a>' if source_url else '—'}</div></main><script>{SEARCH_JS}</script></body></html>'''

    episode_json = {
        "slug": ep.slug,
        "title": title,
        "episode_id": trans.get("episode_id"),
        "source_url": source_url,
        "report_path": f"{ep.slug}/index.html",
        "full_text_path": f"{ep.slug}/full.html",
        "markdown_path": f"{ep.slug}/{transcript_md}",
        "txt_path": f"{ep.slug}/{transcript_txt}",
        "summary_markdown_path": f"{ep.slug}/podcast_summary.md" if (ep.output_dir / "podcast_summary.md").exists() else "",
        "summary_json_path": f"{ep.slug}/podcast_summary.json" if (ep.output_dir / "podcast_summary.json").exists() else "",
        "llm_tldr": llm_tldr,
        "summary_model": llm_summary.get("summary_model") or "",
        "duration_seconds": duration_seconds,
        "duration_formatted": trans.get("duration_formatted") or fmt_ts(duration_seconds),
        "chars": int(summary.get("chars") or sum(int(c.get("chars") or 0) for c in chunks)),
        "chunks": len(chunks),
        "ok_chunks": len(ok_chunks),
        "failed_chunks": len(failed_chunks),
        "coverage_pct": round(coverage, 3),
        "gpu_pipeline_wall_seconds": summary.get("pipeline_wall_seconds") or summary.get("wall_seconds"),
        "gpu_x_realtime_wall": summary.get("x_realtime_wall"),
        "gpu_vs_cpu_inference": speedups.get("cuda_vs_cpu_inference"),
        "gpu_vs_cpu_wall": speedups.get("cuda_vs_cpu_wall"),
        "published_at": published_at,
        "signature": ep.signature,
    }
    return report_html, full_html, episode_json


SEARCH_JS = r"""
const searchBox=document.getElementById('searchBox');const clearSearch=document.getElementById('clearSearch');const matchCount=document.getElementById('matchCount');const chunks=[...document.querySelectorAll('.chunk')];const original=new Map(chunks.map(c=>[c.id,c.querySelector('p').textContent]));function escReg(s){return s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')}function applySearch(){const q=(searchBox?.value||'').trim();let shown=0;const re=q?new RegExp(escReg(q),'gi'):null;chunks.forEach(c=>{const text=original.get(c.id)||'';const hit=!q||text.toLowerCase().includes(q.toLowerCase());c.style.display=hit?'':'none';if(hit)shown++;const p=c.querySelector('p');p.innerHTML=re?text.replace(re,m=>`<mark>${m}</mark>`):text});if(matchCount)matchCount.textContent=q?`${shown} 段匹配`:`${chunks.length} 段`}if(searchBox){searchBox.addEventListener('input',applySearch)}if(clearSearch){clearSearch.addEventListener('click',()=>{searchBox.value='';applySearch();searchBox.focus()})}
""".strip()


def publish_episode(ep: Episode) -> dict[str, Any]:
    report_html, full_html, episode_json = render_episode(ep)
    for dest in [ep.dest_dir] + ([ep.legacy_dir] if ep.legacy_dir.exists() and ep.legacy_dir != ep.dest_dir else []):
        copy_artifacts(ep, dest)
        (dest / "index.html").write_text(report_html, encoding="utf-8")
        (dest / "full.html").write_text(full_html, encoding="utf-8")
        write_json(dest / "episode.json", episode_json)
    return episode_json


def render_site_index(episodes: list[dict[str, Any]]) -> str:
    cards = []
    for ep in sorted(episodes, key=lambda x: x.get("published_at") or "", reverse=True):
        source = ep.get("source_url") or ""
        cards.append(f'''<article class="card"><span class="eyebrow"><span class="dot"></span>{esc(ep.get('duration_formatted'))} · {int(ep.get('chars') or 0):,} 字</span><div class="card-title">{esc(ep.get('title'))}</div><p>{esc(ep.get('llm_tldr') or '')}</p><p class="muted">{esc(ep.get('episode_id'))} · {ep.get('ok_chunks')}/{ep.get('chunks')} chunks · 覆盖率 {float(ep.get('coverage_pct') or 0):.1f}% · 总结模型 {esc(ep.get('summary_model') or '—')}</p><div class="actions"><a class="btn primary" href="{esc(ep.get('report_path'))}">报告</a><a class="btn" href="{esc(ep.get('full_text_path'))}">完整转写全文</a><a class="btn" href="{esc(ep.get('summary_markdown_path') or ep.get('report_path'))}">总结</a><a class="btn" href="{esc(ep.get('markdown_path'))}">Markdown</a>{f'<a class="btn" href="{esc(source)}" target="_blank" rel="noopener">小宇宙原链接</a>' if source else ''}</div></article>''')
    updated = datetime.now().isoformat(timespec="seconds")
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>播客 ASR 全文库</title><style>{CSS}</style></head><body><main class="shell"><section class="hero"><span class="eyebrow"><span class="dot"></span>Auto Podcast ASR Library</span><h1>播客 ASR 全文库</h1><p class="lead">自动收录 PODCAST_ROOT 下已经完成的播客转写，包含报告、全文网页、原始播客链接和下载文件。</p><div class="actions"><a class="btn primary" href="../">返回转写首页</a><a class="btn" href="episodes.json">episodes.json</a></div></section><section class="cards">{''.join(cards)}</section><div class="footer">Updated {esc(updated)} · publisher: scripts/publish_podcast_asr_site.py</div></main></body></html>'''


def publish_all(only_if_changed: bool = False) -> dict[str, Any]:
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    state_path = LIBRARY_DIR / ".publish_state.json"
    old_state = read_json(state_path, {}) or {}
    old_sigs = old_state.get("signatures") or {}
    episodes = discover_episodes()
    published: list[dict[str, Any]] = []
    changed_slugs: list[str] = []
    existing_episode_jsons: dict[str, dict[str, Any]] = {}
    for ep_json_path in LIBRARY_DIR.glob("*/episode.json"):
        data = read_json(ep_json_path, {}) or {}
        if data.get("slug"):
            existing_episode_jsons[data["slug"]] = data

    for ep in episodes:
        must_publish = (
            old_sigs.get(ep.slug) != ep.signature
            or not (ep.dest_dir / "index.html").exists()
            or not (ep.dest_dir / "full.html").exists()
        )
        if must_publish or not only_if_changed:
            ep_json = publish_episode(ep)
            changed_slugs.append(ep.slug) if must_publish else None
        else:
            ep_json = read_json(ep.dest_dir / "episode.json", {}) or existing_episode_jsons.get(ep.slug, {})
        if ep_json:
            published.append(ep_json)

    # Always refresh the aggregate index when running manually; refresh on cron
    # only when something changed or the index is missing.
    index_missing = not (LIBRARY_DIR / "index.html").exists()
    if published and (changed_slugs or index_missing or not only_if_changed):
        episodes_sorted = sorted(published, key=lambda x: x.get("published_at") or "", reverse=True)
        write_json(LIBRARY_DIR / "episodes.json", episodes_sorted)
        (LIBRARY_DIR / "index.html").write_text(render_site_index(episodes_sorted), encoding="utf-8")

    new_sigs = {ep.slug: ep.signature for ep in episodes}
    write_json(state_path, {"updated_at": datetime.now().isoformat(timespec="seconds"), "signatures": new_sigs})
    lan = get_lan_ip()
    return {
        "library_path": str(LIBRARY_DIR / "index.html"),
        "library_url_local": f"http://127.0.0.1:{DEFAULT_PORT}/static/{LIBRARY_SLUG}/index.html",
        "library_url_lan": f"http://{lan}:{DEFAULT_PORT}/static/{LIBRARY_SLUG}/index.html",
        "episodes": len(published),
        "changed_slugs": changed_slugs,
        "episode_urls": [f"http://{lan}:{DEFAULT_PORT}/static/{LIBRARY_SLUG}/{ep['slug']}/index.html" for ep in published],
        "full_text_urls": [f"http://{lan}:{DEFAULT_PORT}/static/{LIBRARY_SLUG}/{ep['slug']}/full.html" for ep in published],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only-if-changed", action="store_true", help="Print nothing and avoid rewrite when no completed ASR output changed")
    parser.add_argument("--quiet", action="store_true", help="Suppress output unless --only-if-changed finds changes")
    args = parser.parse_args()
    result = publish_all(only_if_changed=args.only_if_changed)
    if args.only_if_changed and not result["changed_slugs"]:
        return 0
    if not args.quiet or result["changed_slugs"]:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
