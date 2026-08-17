#!/usr/bin/env python3
"""Generate a native GPT Image2 TL;DR infographic for a podcast summary.

This script follows the updated TLDR infographic workflow: ask GPT Image2 to
produce the complete final Chinese infographic directly, including layout,
illustrations, tables, labels, and readable text. It deliberately avoids the old
"Image2 visual base + deterministic PIL overlay" path unless a future operator
adds an explicit fallback script.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

W, H = 2048, 1152
CONFIG_ENV = os.environ.get("HERMES_CONFIG", "").strip()
CONFIG_PATH = Path(CONFIG_ENV).expanduser() if CONFIG_ENV else None
DEFAULT_PROVIDER = os.environ.get("IMAGE2_PROVIDER", "openai")
DEFAULT_MODEL = os.environ.get("IMAGE2_MODEL", "gpt-image-2")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else ([] if value in (None, "") else [value])


def one_line(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def trim(text: Any, n: int) -> str:
    s = one_line(text)
    return s if len(s) <= n else s[: max(0, n - 1)].rstrip("，。；、 ") + "…"


def item_text(item: Any, max_chars: int = 90) -> str:
    if isinstance(item, dict):
        if item.get("term"):
            return trim(f"{item.get('term')}：{item.get('explanation', '')}", max_chars)
        if item.get("topic"):
            return trim(f"{item.get('topic')}：{item.get('summary', '')}", max_chars)
        if item.get("quote"):
            return trim(item.get("quote"), max_chars)
        for key in ["summary", "takeaway", "point", "value", "explanation", "text"]:
            if item.get(key):
                return trim(item[key], max_chars)
    return trim(item, max_chars)


def extract_payload(summary: dict[str, Any]) -> dict[str, Any]:
    topics = []
    for t in safe_list(summary.get("topic_summary"))[:6]:
        if isinstance(t, dict):
            title = trim(t.get("topic") or "未命名话题", 20)
            body = trim(t.get("summary") or "；".join(item_text(x, 36) for x in safe_list(t.get("key_points"))[:2]), 56)
            ts = trim(t.get("timestamp_range") or "", 16)
            topics.append({"title": title, "body": body, "time": ts})
        else:
            topics.append({"title": trim(t, 20), "body": "", "time": ""})

    quotes = []
    for q in safe_list(summary.get("golden_quotes"))[:2]:
        if isinstance(q, dict):
            quotes.append({
                "quote": trim(q.get("quote"), 42),
                "why": trim(q.get("why_it_matters") or q.get("speaker_or_context"), 28),
            })
        else:
            quotes.append({"quote": trim(q, 42), "why": ""})

    terms = []
    for t in safe_list(summary.get("entities_and_terms"))[:4]:
        if isinstance(t, dict):
            terms.append(trim(f"{t.get('term', '')}：{t.get('explanation', '')}", 36))
        else:
            terms.append(trim(t, 36))

    takeaways = [item_text(x, 48) for x in safe_list(summary.get("key_takeaways"))[:5]]
    guests = []
    for g in safe_list(summary.get("guests"))[:3]:
        if isinstance(g, dict):
            guests.append(trim(f"{g.get('name','')}｜{g.get('role','')}", 28))
        else:
            guests.append(trim(g, 28))

    return {
        "title": trim(summary.get("title") or "播客 TL;DR", 42),
        "podcast": trim(summary.get("podcast") or "Podcast", 22),
        "published_time": trim(summary.get("published_time") or "", 18),
        "theme": trim(summary.get("theme"), 78),
        "background": trim(summary.get("background"), 58),
        "tldr": trim(summary.get("tldr") or summary.get("theme"), 92),
        "takeaways": takeaways,
        "topics": topics,
        "quotes": quotes,
        "terms": terms,
        "guests": guests,
        "summary_model": trim(summary.get("summary_model"), 24),
    }


def build_direct_prompt(payload: dict[str, Any], attempt: int = 1) -> str:
    topic_lines = "\n".join(
        f"{i+1}. {t['title']}｜{t.get('time','')}｜{t.get('body','')}"
        for i, t in enumerate(payload["topics"][:6])
    ) or "1. 核心主题｜unknown｜围绕节目主要观点展开"
    takeaway_lines = "\n".join(f"- {x}" for x in payload["takeaways"][:5]) or "- 提炼节目中的关键判断"
    quote_lines = "\n".join(f"- “{q['quote']}” {q.get('why','')}" for q in payload["quotes"][:2]) or "- 保留节目中最有代表性的表达"
    term_lines = "\n".join(f"- {x}" for x in payload["terms"][:4]) or "- 解释关键术语"
    guest_line = "；".join(payload["guests"]) or "嘉宾/主持：见节目说明"
    attempt_note = {
        1: "baseline complete finished asset, direct Image2 output",
        2: "reinforce polished ChatGPT website visual summary style",
        3: "compress text budget for legibility",
        4: "strengthen 2×3 grid, no crop, high hierarchy",
        5: "final correction: readable Chinese text and exact title",
    }.get(attempt, "direct complete asset")

    return f"""Create a complete finished Chinese TL;DR infographic in one image, including all readable text. Native GPT Image2 direct generation only; do not leave blank text boxes.

Canvas: horizontal 16:9, 2048×1152. Language: Simplified Chinese. Style: polished ChatGPT website visual summary, dense lecture handout, modern macro-research dashboard, clean vector cards, soft shadows, navy/ivory background, orange/cyan/green accents. Attempt focus: {attempt_note}.

Main title (must appear exactly): {payload['title']}
Subtitle: {payload['podcast']} · {payload['published_time']} · 播客 TL;DR
People: {guest_line}

Readable content plan:
1) Top title banner: title + subtitle.
2) Left large card titled「核心结论」with this short TL;DR:
{payload['tldr']}
3) Small card titled「主题」:
{payload['theme']}
4) Center 2×3 module grid titled「讨论地图」with these numbered modules:
{topic_lines}
5) Right column titled「关键洞察」:
{takeaway_lines}
6) Bottom band titled「金句 / 术语」:
{quote_lines}
{term_lines}
7) Footer:「ASR + LLM 总结，原生 GPT Image2 直接生成」

Design requirements:
- This must look like a final production infographic, not a draft poster.
- Use crisp, readable Chinese text; concise labels are better than tiny paragraphs.
- Strong hierarchy: title readable first, then TL;DR, then modules.
- Integrate mini charts/icons/arrows/timeline chips; avoid generic clipart.
- No pseudo-Chinese, no fake random English, no lorem ipsum, no cropped text, no wrong title.
- Keep safe margins on all edges; no text cut off.
"""


def normalize_base_url(base_url: str) -> str:
    normalized = (base_url or "").strip().rstrip("/")
    if not normalized:
        return "https://api.openai.com/v1"
    if normalized.endswith("/v1"):
        return normalized
    return f"{normalized}/v1"


def _yaml_scalar(raw: str) -> str:
    s = raw.strip()
    if s.startswith(("'", '"')) and s.endswith(("'", '"')) and len(s) >= 2:
        return s[1:-1]
    return s


def load_provider_from_config(provider: str) -> tuple[str, str]:
    """Resolve image generation base_url/api_key without logging secrets.

    Preferred generic configuration is OPENAI_API_KEY plus optional
    OPENAI_BASE_URL/IMAGE2_BASE_URL. If HERMES_CONFIG is explicitly supplied,
    the named IMAGE2_PROVIDER can be read from that Hermes config file.
    """
    env_base_url = os.environ.get("IMAGE2_BASE_URL") or os.environ.get("OPENAI_BASE_URL", "")
    env_api_key = os.environ.get("IMAGE2_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    if env_api_key:
        return normalize_base_url(env_base_url), env_api_key
    if not CONFIG_PATH or not CONFIG_PATH.exists():
        raise RuntimeError("No Image2 API key found. Set IMAGE2_API_KEY/OPENAI_API_KEY or HERMES_CONFIG + IMAGE2_PROVIDER.")
    text = CONFIG_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()
    start = None
    provider_indent = None
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)" + re.escape(provider) + r":\s*$", line)
        if m:
            start = i + 1
            provider_indent = len(m.group(1))
            break
    if start is None or provider_indent is None:
        raise RuntimeError(f"provider {provider!r} not found in {CONFIG_PATH}")
    fields: dict[str, str] = {}
    for line in lines[start:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= provider_indent:
            break
        m = re.match(r"^\s+([A-Za-z0-9_.-]+):\s*(.*)$", line)
        if m and m.group(1) in {"base_url", "api_key"}:
            fields[m.group(1)] = _yaml_scalar(m.group(2))
    base_url = fields.get("base_url") or env_base_url
    api_key = fields.get("api_key") or env_api_key
    if not api_key:
        raise RuntimeError("No Image2 API key found in Hermes config or IMAGE2_API_KEY/OPENAI_API_KEY")
    return normalize_base_url(base_url), api_key


def find_b64(obj: Any) -> str | None:
    found: list[tuple[str, str]] = []

    def walk(x: Any, path: str = "") -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                kp = f"{path}.{k}" if path else k
                if isinstance(v, str) and len(v) > 1000 and ("b64" in k.lower() or "image" in k.lower()):
                    found.append((kp, v))
                walk(v, kp)
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, f"{path}[{i}]")

    walk(obj)
    found.sort(key=lambda kv: (0 if "b64_json" in kv[0] else 1, -len(kv[1])))
    return found[0][1] if found else None


def generate_image2(prompt: str, out_path: Path, *, provider: str, model: str, size: str, quality: str, timeout: int, partial_images: int) -> dict[str, Any]:
    base_url, api_key = load_provider_from_config(provider)
    url = base_url.rstrip("/") + "/images/generations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    payload = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "n": 1,
        "output_format": "png",
        "stream": True,
        "partial_images": partial_images,
    }
    started = time.time()
    last_b64: str | None = None
    events: list[str] = []
    errors: list[str] = []

    print(f"[image2-direct] provider={provider} model={model} size={size} quality={quality} prompt_chars={len(prompt)}")
    with requests.post(url, headers=headers, json=payload, stream=True, timeout=timeout) as r:
        if r.status_code >= 400:
            raise RuntimeError(f"Image2 HTTP {r.status_code}: {r.text[:800]}")
        for raw in r.iter_lines(decode_unicode=True):
            if not raw:
                continue
            line = raw.strip()
            if line.startswith("data:"):
                data = line[5:].strip()
                if data == "[DONE]":
                    events.append("done")
                    break
                try:
                    ev = json.loads(data)
                except Exception:
                    events.append("non_json")
                    continue
                etype = str(ev.get("type") or ev.get("event") or ev.get("object") or "event")
                events.append(etype)
                if "error" in ev:
                    errors.append(json.dumps(ev.get("error"), ensure_ascii=False)[:500])
                b64 = find_b64(ev)
                if b64:
                    last_b64 = b64
                    print(f"[image2-direct] event={etype} image_b64_chars={len(b64)} elapsed={time.time()-started:.1f}s", flush=True)
                else:
                    print(f"[image2-direct] event={etype} elapsed={time.time()-started:.1f}s", flush=True)
            else:
                # Some OpenAI-compatible gateways return a normal JSON line even when stream=True.
                try:
                    ev = json.loads(line)
                    b64 = find_b64(ev)
                    if b64:
                        last_b64 = b64
                except Exception:
                    pass

    if not last_b64:
        detail = "; ".join(errors) if errors else f"events={events[-10:]}"
        raise RuntimeError(f"No image b64 returned from Image2 stream: {detail}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(base64.b64decode(last_b64))
    return {
        "provider": provider,
        "model": model,
        "base_url_host": re.sub(r"^https?://", "", base_url).split("/")[0],
        "size": size,
        "quality": quality,
        "stream": True,
        "events": events[-20:],
        "bytes": out_path.stat().st_size,
        "wall_seconds": round(time.time() - started, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary_json", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--size", default=f"{W}x{H}")
    parser.add_argument("--quality", default="medium", choices=["low", "medium", "high", "auto"])
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--partial-images", type=int, default=2)
    parser.add_argument("--attempt", type=int, default=1, help="Prompt attempt profile 1-5 from the Image2 workflow")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    summary = read_json(args.summary_json, {}) or {}
    if not summary:
        raise SystemExit(f"Cannot read summary JSON: {args.summary_json}")

    out_dir = args.summary_json.parent
    out_path = args.output or (out_dir / "tldr_infographic.png")
    prompt_path = out_dir / "tldr_infographic_prompt.txt"
    meta_path = out_dir / "tldr_infographic_meta.json"
    if out_path.exists() and not args.force:
        print(json.dumps({"ok": True, "skipped": True, "output": str(out_path)}, ensure_ascii=False))
        return 0

    payload = extract_payload(summary)
    prompt = build_direct_prompt(payload, attempt=args.attempt)
    prompt_path.write_text(prompt, encoding="utf-8")

    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "prompt": str(prompt_path), "prompt_chars": len(prompt)}, ensure_ascii=False, indent=2))
        return 0

    gen_meta = generate_image2(
        prompt,
        out_path,
        provider=args.provider,
        model=args.model,
        size=args.size,
        quality=args.quality,
        timeout=args.timeout,
        partial_images=args.partial_images,
    )
    meta = {
        "ok": True,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary_json": str(args.summary_json),
        "output": str(out_path),
        "prompt": str(prompt_path),
        "mode": "native_gpt_image2_direct_complete_image",
        "image2_attempted": True,
        "image2_ok": True,
        "fallback_used": False,
        "title": payload["title"],
        **gen_meta,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
