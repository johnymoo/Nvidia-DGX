#!/usr/bin/env python3
"""Generate a pelican-riding-bicycle SVG via the current vLLM endpoint and record timing."""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

OUT_DIR = Path("/home/YOUR_USERNAME/project/nvidia-dgx/qwen36-dgx-spark/benchmark_outputs")
OUT_DIR.mkdir(parents=True, exist_ok=True)
TS = time.strftime("%Y%m%d-%H%M%S")
BASE = OUT_DIR / f"pelican-nvfp4-{TS}"
API_URL = "http://localhost:8004/v1/chat/completions"
MODEL = "qwen3.6-35b-fp8"

PROMPT = """请生成一张完整、可直接保存为文件并渲染的 SVG 图片。
主题：一只鹈鹕正在骑自行车。
要求：
- 只输出 SVG 代码，从 <svg ...> 开始，到 </svg> 结束，不要 Markdown 代码块，不要解释。
- 画布 500x400，viewBox="0 0 500 400"。
- 画面必须清楚包含：鹈鹕的大喙、白/浅色羽毛、长脖子、眼睛、两条腿踩在自行车踏板上。
- 自行车必须清楚包含：两个轮子、车架、车把、座椅、踏板和辐条。
- 风格：简洁、可爱、彩色、线条清晰，适合做模型生成 SVG 的质量测试。
"""

payload = {
    "model": MODEL,
    "messages": [{"role": "user", "content": PROMPT}],
    "max_tokens": 4096,
    "temperature": 0.7,
    "chat_template_kwargs": {"enable_thinking": False},
}

start = time.perf_counter()
req = Request(API_URL, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
try:
    with urlopen(req, timeout=300) as resp:
        body = resp.read().decode("utf-8")
        status = resp.status
except (HTTPError, URLError) as exc:
    raise SystemExit(f"request failed: {exc}")
wall = time.perf_counter() - start

raw_path = BASE.with_suffix(".json")
raw_path.write_text(body, encoding="utf-8")

data = json.loads(body)
choice = data["choices"][0]
msg = choice["message"]
content = msg.get("content") or ""
usage = data.get("usage", {})
finish_reason = choice.get("finish_reason")

# Extract SVG robustly even if the model adds prose/code fences.
match = re.search(r"<svg\b[\s\S]*?</svg>", content, re.IGNORECASE)
if not match:
    text_path = BASE.with_suffix(".txt")
    text_path.write_text(content, encoding="utf-8")
    raise SystemExit(f"no SVG found in response; saved content to {text_path}")
svg = match.group(0)
svg_path = BASE.with_suffix(".svg")
svg_path.write_text(svg, encoding="utf-8")

png_path = BASE.with_suffix(".png")
# Render via Chromium headless. Window size matches requested SVG canvas.
cmd = [
    "chromium-browser",
    "--headless",
    "--no-sandbox",
    "--disable-gpu",
    "--hide-scrollbars",
    "--window-size=500,400",
    f"--screenshot={png_path}",
    svg_path.as_uri(),
]
render = subprocess.run(cmd, text=True, capture_output=True, timeout=120)

summary = {
    "timestamp": TS,
    "status": status,
    "api_url": API_URL,
    "model": MODEL,
    "wall_seconds": wall,
    "finish_reason": finish_reason,
    "usage": usage,
    "raw_path": str(raw_path),
    "svg_path": str(svg_path),
    "png_path": str(png_path),
    "render_returncode": render.returncode,
    "render_stdout": render.stdout[-2000:],
    "render_stderr": render.stderr[-2000:],
    "content_chars": len(content),
    "svg_chars": len(svg),
}
summary_path = BASE.with_suffix(".summary.json")
summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

print(json.dumps(summary, ensure_ascii=False, indent=2))
