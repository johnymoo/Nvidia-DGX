# Qwen3.6 Q4_K_M on RTX 4090 48 GiB

This is a reproducible Ollama deployment and single-stream benchmark reference
for Qwen3.6 models on a 48 GiB RTX 4090 host. `qwen3.6:27b` is the deployment
and benchmark default; the earlier `qwen3.6:35b-a3b` measurements remain as a
same-host comparison. This is intentionally separate from the DGX Spark
references: the hardware, runtime, quantization, context length, and benchmark
method are different.

## Recorded Configuration

| Item | Value |
|---|---|
| Test dates | 2026-07-22 (35B-A3B); 2026-07-23 (27B) |
| GPU reported by `nvidia-smi` | NVIDIA GeForce RTX 4090, 49,140 MiB |
| NVIDIA driver | 580.159.03 |
| Docker Engine | 29.1.3 |
| Docker Compose | 2.24.0 |
| Runtime | `ollama/ollama:0.20.2` |
| Default model | `qwen3.6:27b`, dense 27B |
| Comparison model | `qwen3.6:35b-a3b`, 35B-A3B MoE |
| Quantization package | Official Ollama Q4_K_M (27B: 17 GB download; 35B-A3B: 23 GB download) |
| Loaded model footprint | 27B: 32.4 GB reported by Ollama; 35B-A3B: 30 GB reported by Ollama, including a 4.0 GiB GPU KV cache allocation |
| Context length | 131,072 tokens |
| Service address | `0.0.0.0:8004` |
| Concurrency | One request (`OLLAMA_NUM_PARALLEL=1`) |

The host was provided as a "4090D 48G" configuration. `nvidia-smi` reported
the device name above; the VRAM capacity is the authoritative value used for
this reference.

## Architecture

`client -> 0.0.0.0:8004 -> Ollama 0.20.2 -> Qwen3.6 Q4_K_M -> RTX 4090 GPU`

The Compose deployment keeps the model in a Docker named volume. Its bootstrap
service pulls the model once, and the API service is then available through the
native Ollama and OpenAI-compatible endpoints.

## Deployment

Requirements: Docker Engine with Docker Compose v2, an NVIDIA driver, and the
NVIDIA Container Toolkit. The benchmark scripts use only the Python standard
library; no package installation is required.

```sh
docker-compose -f compose.yaml up -d
docker-compose -f compose.yaml ps
curl http://127.0.0.1:8004/api/tags
```

The compose file intentionally binds an unauthenticated API to all interfaces.
Use a firewall or an authenticated reverse proxy before allowing untrusted
network access to TCP port 8004.

## Method

Both benchmarks use the Ollama native streaming `/api/chat` endpoint with
temperature zero. Client TTFT is measured from request dispatch to the first
content or thinking token. Prefill and decode speeds use Ollama's final-event
token counts and durations; they are not estimated from wall-clock fractions.

The text benchmark performs three runs per scenario. Its standard 1K, 8K, and
16K prompts and its long-context 32K, 64K, 96K, and approximately 124K prompts
receive a unique prefix for every run so that prefix-cache hits do not inflate
prefill throughput. The visual benchmark generates a 640x360 image with three
blue squares, two yellow circles, and one red rectangle, then requires exact
JSON counts from every run.

## Results

All figures are arithmetic means of three runs. `N/A` means output throughput
is not meaningful for the two-token acknowledgement response. The standard
text benchmark measures serving speed only; it is not a model-quality or
coding-task-success benchmark.

### Default: Qwen3.6 27B

| Scenario | Input / output tokens | TTFT (ms) | Prefill (tok/s) | Decode (tok/s) | Result |
|---|---:|---:|---:|---:|---|
| Text decode | 32 / 256 | 202.8 | 597.3 | 42.9 | 40.5 end-to-end tok/s |
| Code generation | 36 / 233 | 205.0 | 668.2 | 42.7 | 40.2 end-to-end tok/s |
| Reasoning enabled | 54 / 512 | 187.3 | 928.7 | 42.6 | 41.0 end-to-end tok/s |
| Fresh 1K prefill | 1,170 / 2 | 703.3 | 2054.5 | 66.4 | N/A |
| Fresh 8K prefill | 8,870 / 2 | 4328.9 | 2123.6 | 62.5 | N/A |
| Fresh 16K prefill | 17,671 / 2 | 8697.8 | 2072.3 | 61.3 | N/A |

### Comparison: Qwen3.6 35B-A3B

| Scenario | Input / output tokens | TTFT (ms) | Prefill (tok/s) | Decode (tok/s) | Result |
|---|---:|---:|---:|---:|---|
| Text decode | 32 / 256 | 188.2 | 859.3 | 132.6 | 113.2 end-to-end tok/s |
| Code generation | 36 / 251 | 168.6 | 971.6 | 133.3 | 114.9 end-to-end tok/s |
| Reasoning enabled | 54 / 512 | 175.8 | 1251.6 | 132.8 | 118.5 end-to-end tok/s |
| Fresh 1K prefill | 1,167 / 2 | 405.5 | 4375.4 | 142.4 | N/A |
| Fresh 8K prefill | 8,867 / 2 | 1951.4 | 4921.7 | 138.6 | N/A |
| Fresh 16K prefill | 17,668 / 2 | 3803.5 | 4864.3 | 133.8 | N/A |
| Multimodal counting | 303 / 38 | 270.1 | 3295.4 | 134.8 | 3 / 3 exact |

The 35B-A3B dedicated long-context suite also used three fresh-prefix runs per
row:

| Actual prompt tokens | TTFT (s) | Prefill (tok/s) | Result |
|---:|---:|---:|---|
| 33,073 | 7.31 | 4651.7 | 3 / 3 success |
| 63,873 | 15.85 | 4106.1 | 3 / 3 success |
| 95,773 | 29.29 | 3308.0 | 3 / 3 success |
| 123,274 | 45.65 | 2725.4 | 3 / 3 success |

These numbers are not a direct comparison with DGX Spark FP8/NVFP4 vLLM
results. This reference uses a Q4_K_M Ollama package, a different GPU, a 128K
context allocation, and one request at a time.

## Reproduce

```sh
python3 benchmark_ollama_qwen36.py --runs 3
python3 benchmark_ollama_qwen36.py --long-context-only --runs 3
python3 benchmark_multimodal_qwen36.py --runs 3
```

Pass `--model qwen3.6:35b-a3b` to run the comparison model explicitly.

Each command writes a timestamped JSON record in the current directory. The
multimodal command exits nonzero if any exact-count check fails. The generated
PNG test card is intentionally ignored by Git.

## Files

| File | Purpose |
|---|---|
| `compose.yaml` | GPU-enabled Ollama deployment at port 8004 |
| `benchmark_ollama_qwen36.py` | Streaming text, reasoning, and fresh-prefix prefill benchmark |
| `benchmark_multimodal_qwen36.py` | Repeatable image-counting benchmark with correctness validation |
| `benchmark_results_20260722_171706.json` | Initial 32K text benchmark baseline |
| `benchmark_multimodal_results_20260722_172024.json` | Initial 32K multimodal benchmark baseline |
| `benchmark_results_128k_20260722_144200.json` | Recorded 35B-A3B 128K standard text benchmark data |
| `benchmark_results_27b_q4_128k_20260723_235741.json` | Recorded 27B 128K standard text benchmark data |
| `benchmark_long_context_128k_20260722_144500.json` | Recorded 128K long-context benchmark data |
| `benchmark_multimodal_results_128k_20260722_144900.json` | Recorded 128K multimodal benchmark data |

## Limitations

- Results are single-stream measurements, not a concurrent-load benchmark.
- Each reported result uses three runs, so it does not establish long-term
  variance or tail latency.
- The largest successful request contained 123,274 input tokens and a
  two-token acknowledgement; full 131,072-token user content is not tested.
- The visual test checks a deterministic counting task. It is a smoke test for
  image input and structured output, not a broad multimodal quality evaluation.
