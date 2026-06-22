# Xiaoyuzhou Podcast ASR to Static Site

End-to-end pipeline for turning a Xiaoyuzhou episode into GPU SenseVoice ASR artifacts, a local Qwen-generated structured Chinese summary, and a static website page.

## What it does

1. Resolve Xiaoyuzhou episode metadata and audio URL.
2. Download audio into a standard workspace under `PODCAST_ROOT`.
3. Convert audio to 16 kHz mono WAV.
4. Benchmark CPU vs CUDA SenseVoice on an identical slice.
5. Transcribe the full episode on GPU/CUDA with resumable chunks.
6. Generate `podcast_summary.json` and `podcast_summary.md` using a local OpenAI-compatible endpoint.
7. Generate a native GPT Image2 TLDR infographic directly from the structured summary.
8. Publish per-episode report pages and an index under a static web root.
9. Export the final LLM summary into an LLM Wiki (`WIKI_PATH`) for long-term knowledge reuse.
10. Optionally expose a FastAPI background-task API so the website import form keeps running after users leave the page.

## Files

| Path | Purpose |
|---|---|
| `scripts/xiaoyuzhou_asr_to_site.py` | End-to-end orchestrator. |
| `scripts/asr_pipeline_template.py` | Per-episode SenseVoice/FunASR pipeline template. |
| `scripts/generate_podcast_summary.py` | Structured Chinese summary generator using local Qwen/vLLM. |
| `scripts/generate_podcast_tldr_infographic.py` | Native GPT Image2 direct TLDR infographic generator. |
| `scripts/export_podcast_summary_to_wiki.py` | Writes the final LLM summary into `WIKI_PATH` as raw source + curated wiki summary page. |
| `scripts/publish_podcast_asr_site.py` | Static site publisher and index builder. |
| `scripts/podcast_asr_task_api.py` | FastAPI router for persistent background website import jobs. |
| `scripts/publish_podcast_asr_site_watchdog.sh` | Silent watchdog wrapper for cron/no-agent jobs. |
| `skills/xiaoyuzhou-asr-to-site/SKILL.md` | Hermes skill procedure used by the local agent. |

## Requirements

- Python 3.12
- `ffmpeg` / `ffprobe`
- `curl`
- SenseVoice/FunASR dependencies installed in a Python site-packages path
- Local model directories for SenseVoice, punctuation, and VAD
- Optional local vLLM/OpenAI-compatible endpoint for summary generation

## Configuration

The scripts default to local paths, but all environment-specific values are configurable:

| Variable | Default |
|---|---|
| `PODCAST_ROOT` | `~/podcast` |
| `SENSEVOICE_SITE_PACKAGES` | `~/deployments/sensevoice/venv/lib/python3.12/site-packages` |
| `SENSEVOICE_MODEL_DIR` | `~/deployments/sensevoice/models/SenseVoiceSmall` |
| `SENSEVOICE_PUNC_MODEL_DIR` | `~/deployments/sensevoice/models/punc-ct-transformer` |
| `SENSEVOICE_VAD_MODEL_DIR` | `~/deployments/sensevoice-docker/modelscope-cache/hub/models/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch` |
| `SENSEVOICE_STATIC_ROOT` | `~/deployments/sensevoice/static` |
| `SENSEVOICE_WEB_PORT` | `8020` |
| `PODCAST_ASR_SITE_BASE` | `http://127.0.0.1:8020/static/podcast-asr` |
| `WIKI_PATH` | `~/wiki` |
| `PODCAST_WIKI_EXPORT_SCRIPT` | `$PODCAST_ROOT/export_podcast_summary_to_wiki.py` |
| `PODCAST_TLDR_IMAGE_SCRIPT` | `$PODCAST_ROOT/generate_podcast_tldr_infographic.py` |
| `PODCAST_TASK_DIR` | `$PODCAST_ROOT/asr_tasks` |
| `PODCAST_PIPELINE` | `$PODCAST_ROOT/xiaoyuzhou_asr_to_site.py` |
| `PODCAST_LIBRARY_DIR` | `~/deployments/sensevoice/static/podcast-asr` |
| `IMAGE2_MODEL` | `gpt-image-2` |
| `IMAGE2_API_KEY` / `OPENAI_API_KEY` | required for native GPT Image2 TLDR image generation |
| `IMAGE2_BASE_URL` / `OPENAI_BASE_URL` | optional OpenAI-compatible image endpoint |

## Usage

```bash
export PODCAST_ROOT="$HOME/podcast"
python3.12 scripts/xiaoyuzhou_asr_to_site.py \
  'https://www.xiaoyuzhoufm.com/episode/<episode-id>'
```

The orchestrator is resumable. It skips completed ASR and summary outputs unless the corresponding `--force-*` flags are supplied. Use `--force-asr --force-summary --force-tldr-image` to recover a stale/partial run and regenerate all downstream artifacts. It exports the final summary into `WIKI_PATH` by default; pass `--skip-wiki-export` to disable that side effect.

## Website background import jobs

The import form in the published index calls `/api/podcast-asr/tasks`. The task API starts the pipeline with `subprocess.Popen(..., start_new_session=True)`, writes persistent JSON state under `PODCAST_TASK_DIR`, and exposes polling endpoints:

```text
POST /api/podcast-asr/tasks
GET  /api/podcast-asr/tasks
GET  /api/podcast-asr/tasks/{job_id}
GET  /api/podcast-asr/tasks/by-episode/{episode_id}
```

Because the job is server-side and state is persisted, users may leave or close the website after submitting a Xiaoyuzhou URL. When they return, the front-end restores the last active task from `localStorage`, polls the API, and shows a persistent task panel instead of relying on an auto-dismissing toast.

To mount the router in an existing FastAPI app:

```python
from scripts.podcast_asr_task_api import router as podcast_asr_router
app.include_router(podcast_asr_router)
```

## Outputs

A workspace is created under:

```text
$PODCAST_ROOT/xiaoyuzhou_<episode-id>/
```

Important outputs:

```text
output/transcription_<device>.json
output/transcript_<device>.md
output/transcript_<device>.txt
output/transcript_<device>.srt
output/benchmark_cpu_gpu_*.json
output/podcast_summary.json
output/podcast_summary.md
output/tldr_infographic.png
output/tldr_infographic_meta.json
output/episode_page_context.json
output/episode_page_context.md
output/site_meta.json
```

Wiki export paths:

```text
$WIKI_PATH/raw/podcast-summaries/podcast-<episode-slug>-llm-summary.md
$WIKI_PATH/queries/podcast-<episode-slug>.md
```

Published site paths:

```text
$SENSEVOICE_STATIC_ROOT/podcast-asr/index.html
$SENSEVOICE_STATIC_ROOT/podcast-asr/<episode-slug>/index.html
$SENSEVOICE_STATIC_ROOT/podcast-asr/<episode-slug>/full.html
```

## Verification

```bash
python3.12 -m py_compile scripts/*.py
curl -I http://127.0.0.1:8020/static/podcast-asr/index.html
```

The page should include LLM summary sections, transcript download links, CPU/GPU benchmark metrics, and full transcript links.

## Notes

- Do not commit raw audio, WAV chunks, model weights, credentials, logs, or private `.env` files.
- The Xiaoyuzhou public page usually exposes a media URL; authenticated opencli fallback is optional and should not expose credentials.
- Qwen summary calls disable thinking so the final JSON lands in `message.content`.
