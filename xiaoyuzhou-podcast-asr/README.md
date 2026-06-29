# Xiaoyuzhou Podcast ASR to Static Site

End-to-end pipeline for turning a Xiaoyuzhou episode into GPU SenseVoice ASR artifacts, a local Qwen-generated structured Chinese summary, and a static website page.

## What it does

1. Resolve Xiaoyuzhou episode metadata and audio URL.
2. Download audio into a standard workspace under `PODCAST_ROOT`.
3. Convert audio to 16 kHz mono WAV.
4. Benchmark CPU vs CUDA SenseVoice on an identical slice.
5. Transcribe the full episode on GPU/CUDA with resumable chunks.
6. Generate `podcast_summary.json` and `podcast_summary.md` using a local OpenAI-compatible endpoint.
7. Publish per-episode report pages and an index under a static web root.
8. Export the final LLM summary into an LLM Wiki (`WIKI_PATH`) for long-term knowledge reuse.

## Files

| Path | Purpose |
|---|---|
| `scripts/xiaoyuzhou_asr_to_site.py` | End-to-end orchestrator. |
| `scripts/asr_pipeline_template.py` | Per-episode SenseVoice/FunASR pipeline template. |
| `scripts/generate_podcast_summary.py` | Structured Chinese summary generator using local Qwen/vLLM. |
| `scripts/export_podcast_summary_to_wiki.py` | Writes the final LLM summary into `WIKI_PATH` as raw source + curated wiki summary page. |
| `scripts/publish_podcast_asr_site.py` | Static site publisher and index builder. |
| `scripts/publish_podcast_asr_site_watchdog.sh` | Silent watchdog wrapper for cron/no-agent jobs. |
| `benchmarks/asr-eval-100/` | 100-sample dictation benchmark, baseline results, SenseVoice CUDA result, and reusable evaluation scripts. |
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

## Usage

```bash
export PODCAST_ROOT="$HOME/podcast"
python3.12 scripts/xiaoyuzhou_asr_to_site.py \
  'https://www.xiaoyuzhoufm.com/episode/<episode-id>'
```

The orchestrator is resumable. It skips completed ASR and summary outputs unless the corresponding `--force-*` flags are supplied. It exports the final summary into `WIKI_PATH` by default; pass `--skip-wiki-export` to disable that side effect.

## Outputs

A workspace is created under:

```text
$PODCAST_ROOT/xiaoyuzhou_<episode-id>/
```

Important outputs:

```text
output/transcription_cuda.json
output/transcript_cuda.md
output/transcript_cuda.txt
output/transcript_cuda.srt
output/benchmark_cpu_gpu_*.json
output/podcast_summary.json
output/podcast_summary.md
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

## ASR Benchmark

The `benchmarks/asr-eval-100/` directory contains a reusable 100-sample dictation benchmark for tracking ASR accuracy and latency across model/config updates. It includes the WAV samples, reference transcripts, baseline Nemotron results, the 2026-06-29 SenseVoiceSmall CUDA run, and scripts to re-run the benchmark and regenerate the comparison image.

```bash
cd benchmarks/asr-eval-100
ASR_EVAL_DEVICE=cuda python3.12 scripts/eval_sensevoice_asr100.py
python3.12 scripts/make_comparison_image.py
```

See `benchmarks/asr-eval-100/README.md` for metric definitions, environment overrides, and the checked-in benchmark summary.

## Verification

```bash
python3.12 -m py_compile scripts/*.py
curl -I http://127.0.0.1:8020/static/podcast-asr/index.html
```

The page should include LLM summary sections, transcript download links, CPU/GPU benchmark metrics, and full transcript links.

## Notes

- Do not commit raw podcast episode audio, generated WAV chunks, model weights, credentials, logs, or private `.env` files. Small curated benchmark audio sets under `benchmarks/` are allowed when they are part of a reproducible test fixture.
- The Xiaoyuzhou public page usually exposes a media URL; authenticated opencli fallback is optional and should not expose credentials.
- Qwen summary calls disable thinking so the final JSON lands in `message.content`.
