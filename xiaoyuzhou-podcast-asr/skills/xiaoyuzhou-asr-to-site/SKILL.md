---
name: xiaoyuzhou-asr-to-site
description: "Use when the user sends a Xiaoyuzhou episode link and wants automatic GPU ASR transcription, LLM summary, and static website publishing on GB10."
platforms: [linux]
tags: [xiaoyuzhou, podcast, asr, sensevoice, gpu, qwen, website]
---

# Xiaoyuzhou ASR to Website

## When to use

Use when Spotty sends a 小宇宙 / Xiaoyuzhou episode URL and asks to transcribe it, summarize it, or import it into the local website.

Default expectation: do the full pipeline, not just a plan:

1. Resolve episode metadata and audio.
2. Download audio into a standard workspace.
3. Convert to 16 kHz mono WAV.
4. Benchmark CPU vs CUDA SenseVoice on the same 5-minute slice.
5. Transcribe the complete episode on GPU/CUDA.
6. Generate a structured Chinese summary with local vLLM on `localhost:8004`.
7. Publish report, full transcript, summary, and downloads to the SenseVoice static site.
8. Verify HTTP URLs and report the links.

## Primary command

Use the orchestrator:

```bash
python3.12 $PODCAST_ROOT/xiaoyuzhou_asr_to_site.py \
  'https://www.xiaoyuzhoufm.com/episode/<episode-id>'
```

For the known SpaceX episode, the existing slug is preserved:

```text
/static/podcast-asr/xiaoyuzhou-spacex-asr/
```

The script is resumable. If `output/transcription_cuda.json` already exists, it skips ASR unless `--force-asr` is supplied.

## Important paths

```text
$PODCAST_ROOT/xiaoyuzhou_asr_to_site.py       # end-to-end orchestrator
$PODCAST_ROOT/asr_pipeline_template.py        # per-episode SenseVoice pipeline template
$PODCAST_ROOT/generate_podcast_summary.py     # Qwen/vLLM summary generator
$PODCAST_ROOT/publish_podcast_asr_site.py     # static website publisher
$SENSEVOICE_STATIC_ROOT/podcast-asr/ # published site
```

Standard workspace:

```text
$PODCAST_ROOT/xiaoyuzhou_<episode-id>/
  input/episode.m4a
  audio/episode_16k.wav
  chunks/*.wav
  transcripts/chunk_*_cuda.{json,txt}
  output/transcription_cuda.json
  output/transcript_cuda.{md,txt,srt}
  output/benchmark_cpu_gpu_*.json
  output/podcast_summary.{json,md}
  output/site_meta.json
  logs/*.log
```

## Summary template

`generate_podcast_summary.py` calls:

```text
http://127.0.0.1:8004/v1/chat/completions
model: qwen3.6-35b-fp8
chat_template_kwargs: {"enable_thinking": false}
```

The output JSON must include:

- `theme` — 核心主题
- `guests` — 嘉宾/主持、身份、依据
- `background` — 讨论背景
- `topic_summary` — 分话题总结、时间范围、要点
- `golden_quotes` — 金句、上下文、价值
- `key_takeaways` — 关键洞察
- `entities_and_terms` — 专名术语解释
- `caveats` — ASR/专名不确定处
- `tldr` — 网站索引卡片摘要

## Website publication

Run or rely on the orchestrator:

```bash
python3.12 $PODCAST_ROOT/publish_podcast_asr_site.py
```

Published URLs:

```text
http://127.0.0.1:8020/static/podcast-asr/index.html
http://127.0.0.1:8020/static/podcast-asr/<slug>/index.html
http://127.0.0.1:8020/static/podcast-asr/<slug>/full.html
```

LAN URL uses:

```text
http://<LAN_IP>:8020/static/podcast-asr/...
```

The publisher also mirrors existing legacy `/static/<slug>/` directories so old links remain valid.

## Automatic watchdog

A no-agent cron job watches for changed/new completed outputs every 5 minutes:

```text
Job name: 自动发布播客 ASR 网站索引
Script: ~/.hermes/profiles/capital-avatar/scripts/publish_podcast_asr_site_watchdog.sh
```

The watchdog is silent when no new transcript changed.

## Repository packaging / public sharing

When asked to commit this pipeline into a public or team repository, package the reusable workflow rather than the live workspace:

- Put implementation under a project subdirectory such as `xiaoyuzhou-podcast-asr/`; do not add implementation files at the repo root.
- Copy reusable scripts and the class-level skill, but do **not** commit raw audio, WAV chunks, transcripts from private episodes unless explicitly requested, temporary logs, `__pycache__`, or generated large PNG/HTML artifacts.
- Sanitize host-specific defaults before staging:
  - replace absolute personal home paths with env-driven defaults such as `PODCAST_ROOT`, `SENSEVOICE_STATIC_ROOT`, `SENSEVOICE_MODEL_DIR`, `SENSEVOICE_PUNC_MODEL_DIR`, `SENSEVOICE_VAD_MODEL_DIR`, `SENSEVOICE_SITE_PACKAGES`;
  - replace private LAN URLs with `http://127.0.0.1...` defaults or documented `PODCAST_ASR_SITE_BASE` / `<LAN_IP>` placeholders;
  - keep `localhost` model endpoints acceptable as local examples, but never stage credentials, cookies, API keys, Telegram bot credentials, or authenticated Xiaoyuzhou config.
- Add a short README/config note explaining required env vars and the intended command sequence.
- Before commit: run `python3 -m py_compile` on copied `.py` files, `bash -n` on shell scripts, `git diff --cached`, and a staged secret scan for tokens/private URLs/absolute personal paths.

See `references/repo-packaging.md` for the concrete sanitization checklist.

## Verification checklist

After each run:

```bash
curl -I http://127.0.0.1:8020/static/podcast-asr/index.html
curl -I http://127.0.0.1:8020/static/podcast-asr/<slug>/index.html
curl -I http://127.0.0.1:8020/static/podcast-asr/<slug>/full.html
curl -I http://127.0.0.1:8020/static/podcast-asr/<slug>/podcast_summary.md
```

Check page content contains:

- `LLM 总结`
- `主题`
- `嘉宾`
- `背景`
- `讨论的话题总结`
- `金句`
- `完整转写稿`
- `CPU / GPU 对比`

Use headless Chromium screenshot for visual verification when practical.

## Pitfalls

- Do not paste full transcripts into Telegram. Send file attachments or website links.
- Do not copy raw M4A/WAV/chunk WAVs to the website unless asked.
- Public Xiaoyuzhou HTML may fail to expose audio. If that happens, pass `--audio-url` or use authenticated opencli credentials; never expose credentials in summaries.
- The SenseVoice upload page may still run CPU; this pipeline uses GPU via the generated per-episode script.
- Qwen 8004 may return reasoning-only output if thinking is enabled; keep `enable_thinking=false` for summary generation.
