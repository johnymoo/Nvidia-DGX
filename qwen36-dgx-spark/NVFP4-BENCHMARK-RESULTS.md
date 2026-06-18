# Qwen3.6-35B-A3B NVFP4 on DGX Spark (GB10) - Benchmark Results

## Test Environment

- **Date**: 2026-06-18
- **Hardware**: NVIDIA DGX Spark / GB10 / Blackwell / ARM64 (`aarch64`)
- **Runtime**: vLLM OpenAI-compatible API
- **Image**: `vllm/vllm-openai:nightly-aarch64`
- **vLLM version**: `0.23.1rc1.dev101+g4c6266331`
- **Container**: `vllm-qwen36-nvfp4-nightly-aarch64`
- **Endpoint**: `http://localhost:8004/v1/chat/completions`
- **Served model name**: `qwen3.6-35b-fp8` (kept for client compatibility)
- **Underlying model**: `Qwen3.6-35B-A3B-NVFP4`
- **Max context**: `262144`

## Deployment Files

| File | Purpose |
|---|---|
| [`docker-compose-vllm-nvfp4-nightly-aarch64.yml`](./docker-compose-vllm-nvfp4-nightly-aarch64.yml) | Known-good DGX Spark / ARM64 NVFP4 vLLM deployment. |
| [`benchmark_vllm_qwen36_nvfp4.py`](./benchmark_vllm_qwen36_nvfp4.py) | 16-case generation benchmark compatible with earlier FP8 benchmark methodology. |
| [`long_context_ttft_benchmark_generic.py`](./long_context_ttft_benchmark_generic.py) | Streaming TTFT/TPS benchmark with vLLM Prometheus metrics deltas. |
| [`quality_eval_api.py`](./quality_eval_api.py) | Lightweight deterministic FP8 vs NVFP4 quality sanity suite. |
| [`make_merged_fp8_nvfp4_report.py`](./make_merged_fp8_nvfp4_report.py) | Generates the merged Markdown/HTML/PNG report from raw benchmark artifacts. |
| [`run_pelican_nvfp4.py`](./run_pelican_nvfp4.py) | Visual SVG smoke test for generation quality. |

## Summary

### Regular 16-case generation benchmark

| Deployment | Avg tok/s | Median tok/s | Min tok/s | Max tok/s | Errors |
|---|---:|---:|---:|---:|---:|
| Old 8004 FP8 baseline | 70.2 | 70.0 | 69.1 | 71.7 | 0 |
| PR200 FP8 | 72.5 | 72.5 | 71.1 | 73.7 | 0 |
| Current NVFP4 | **152.1** | **159.2** | 66.0 | **179.0** | 0 |

NVFP4 improves average generation throughput by **+116.7%** vs the old 8004 FP8 baseline and **+109.8%** vs the PR200 FP8 run.

### Long-context streaming TTFT/TPS

The long-context benchmark uses OpenAI-compatible streaming. Client TTFT is measured as the first non-empty SSE delta. Server-side TTFT/prefill/decode/e2e metrics are collected from vLLM Prometheus metric deltas before/after each sequential request.

| Context | FP8 TTFT | NVFP4 TTFT | TTFT Δ | FP8 decode TPS | NVFP4 decode TPS | TPS Δ | Correct |
|---|---:|---:|---:|---:|---:|---:|---|
| 64K | 16.56s | 16.25s | -1.9% | 46.7 | **104.2** | **+123.2%** | ✅ / ✅ |
| 128K | 45.37s | 47.58s | +4.9% | 41.0 | **89.7** | **+118.9%** | ✅ / ✅ |
| 256K | 141.33s | 150.34s | +6.4% | 34.3 | **70.4** | **+105.4%** | ✅ / ✅ |

Observations:

- 64K TTFT is effectively tied.
- 128K/256K NVFP4 TTFT is slightly slower than FP8 in this single-request test.
- NVFP4 decode throughput is consistently about **2x** FP8.
- Both FP8 and NVFP4 answered the long-context retrieval/math checks correctly.

### Lightweight quality sanity suite

| Suite | Score | Accuracy |
|---|---:|---:|
| FP8 | 15/16 | 93.8% |
| NVFP4 | 15/16 | 93.8% |

Both deployments failed the same `long_two_fact` prompt, so the failure is not unique to NVFP4.

## Official model-card accuracy reference

The NVIDIA NVFP4 model card reports BF16 vs NVFP4, not FP8 vs NVFP4. It is still a useful quantization-risk reference:

| Benchmark | BF16 | NVFP4 | Δ |
|---|---:|---:|---:|
| MMLU Pro | 85.6 | 85.0 | -0.6 |
| GPQA Diamond | 84.9 | 84.8 | -0.1 |
| τ²-Bench Telecom | 95.5 | 94.7 | -0.8 |
| SciCode | 40.8 | 40.6 | -0.2 |
| AIME 2025 | 89.2 | 88.8 | -0.4 |
| AA-LCR | 62.0 | 62.0 | +0.0 |
| IFBench | 62.3 | 62.8 | +0.5 |
| MMMU Pro | 74.1 | 74.5 | +0.4 |

## Raw Results

| Artifact | Description |
|---|---|
| [`benchmark_outputs/benchmark-results-nvfp4-20260618-062149.json`](./benchmark_outputs/benchmark-results-nvfp4-20260618-062149.json) | Regular 16-case NVFP4 benchmark raw results. |
| [`benchmark_outputs/long-context-ttft-nvfp4-20260618-093358.json`](./benchmark_outputs/long-context-ttft-nvfp4-20260618-093358.json) | NVFP4 long-context streaming TTFT/TPS raw results. |
| [`benchmark_outputs/long-context-ttft-fp8-20260618-100108.json`](./benchmark_outputs/long-context-ttft-fp8-20260618-100108.json) | FP8 long-context streaming TTFT/TPS raw results. |
| [`benchmark_outputs/quality-eval-nvfp4-20260618-100928.json`](./benchmark_outputs/quality-eval-nvfp4-20260618-100928.json) | NVFP4 quality sanity raw results. |
| [`benchmark_outputs/quality-eval-fp8-20260618-100604.json`](./benchmark_outputs/quality-eval-fp8-20260618-100604.json) | FP8 quality sanity raw results. |
| [`benchmark_outputs/fp8-vs-nvfp4-merged-report-20260618-101205.md`](./benchmark_outputs/fp8-vs-nvfp4-merged-report-20260618-101205.md) | Human-readable merged report. |
| [`benchmark_outputs/fp8-vs-nvfp4-merged-report-20260618-101205.png`](./benchmark_outputs/fp8-vs-nvfp4-merged-report-20260618-101205.png) | Rendered report image. |

## Reproduction

Start the NVFP4 service:

```bash
cd ~/project/nvidia-dgx/qwen36-dgx-spark
docker compose -f docker-compose-vllm-nvfp4-nightly-aarch64.yml up -d
curl http://localhost:8004/health
curl http://localhost:8004/v1/models
```

Run the regular benchmark:

```bash
python3 benchmark_vllm_qwen36_nvfp4.py
```

Run long-context TTFT/TPS for the current endpoint:

```bash
BASE_URL=http://localhost:8004 \
MODEL=qwen3.6-35b-fp8 \
BENCH_TAG=nvfp4 \
VLLM_CONTAINER=vllm-qwen36-nvfp4-nightly-aarch64 \
python3 long_context_ttft_benchmark_generic.py
```

Run the lightweight quality suite:

```bash
BASE_URL=http://localhost:8004 \
MODEL=qwen3.6-35b-fp8 \
EVAL_TAG=nvfp4 \
python3 quality_eval_api.py
```

Generate the merged report after all referenced raw artifacts exist:

```bash
python3 make_merged_fp8_nvfp4_report.py
```

## Notes

- The external served model name remains `qwen3.6-35b-fp8` for compatibility with existing clients; the underlying model in the NVFP4 compose is `Qwen3.6-35B-A3B-NVFP4`.
- On DGX Spark / GB10, use the ARM64 image `vllm/vllm-openai:nightly-aarch64` for NVFP4. Older/local vLLM images may fail loading the ModelOpt NVFP4 checkpoint.
- If Docker Hub direct pull stalls, pull the same upstream image through a mirror and tag it back to `vllm/vllm-openai:nightly-aarch64`, then verify `Architecture=arm64` before deployment.
