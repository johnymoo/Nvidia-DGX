# Qwen3.6 35B-A3B Q4_K_M on RTX 4090 48 GiB

This is a reproducible Ollama deployment and single-stream benchmark reference
for `qwen3.6:35b-a3b` on a 48 GiB RTX 4090 host. It is intentionally separate
from the DGX Spark references: the hardware, runtime, quantization, context
length, and benchmark method are different.

## Recorded Configuration

| Item | Value |
|---|---|
| Test date | 2026-07-22 |
| GPU reported by `nvidia-smi` | NVIDIA GeForce RTX 4090, 49,140 MiB |
| NVIDIA driver | 580.159.03 |
| Docker Engine | 29.1.3 |
| Docker Compose | 2.24.0 |
| Runtime | `ollama/ollama:0.20.2` |
| Model | `qwen3.6:35b-a3b`, 35B-A3B MoE |
| Quantization package | Official Ollama Q4_K_M, 23 GB download |
| Loaded model footprint | 27 GB, 100% GPU reported by Ollama |
| Context length | 32,768 tokens |
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

The text benchmark performs three runs per scenario. Its 1K, 8K, and 16K
prompts receive a unique prefix for every run so that prefix-cache hits do not
inflate prefill throughput. The visual benchmark generates a 640x360 image
with three blue squares, two yellow circles, and one red rectangle, then
requires exact JSON counts from every run.

## Results

All figures are arithmetic means of three runs. `N/A` means output throughput
is not meaningful for the two-token long-context acknowledgement response.

| Scenario | Input / output tokens | TTFT (ms) | Prefill (tok/s) | Decode (tok/s) | Result |
|---|---:|---:|---:|---:|---|
| Text decode | 32 / 256 | 163.6 | 901.1 | 132.8 | 114.5 end-to-end tok/s |
| Code generation | 36 / 251 | 168.1 | 947.5 | 132.4 | 113.8 end-to-end tok/s |
| Reasoning enabled | 54 / 512 | 173.5 | 1268.1 | 133.2 | 119.0 end-to-end tok/s |
| Fresh 1K prefill | 1,171 / 2 | 402.0 | 4406.0 | 144.1 | N/A |
| Fresh 8K prefill | 8,871 / 2 | 1934.9 | 4968.1 | 136.9 | N/A |
| Fresh 16K prefill | 17,672 / 2 | 3802.5 | 4864.3 | 129.0 | N/A |
| Multimodal counting | 304 / 38 | 268.9 | 3338.1 | 135.3 | 3 / 3 exact |

These numbers are not a direct comparison with DGX Spark FP8/NVFP4 vLLM
results. This reference uses a Q4_K_M Ollama package, a different GPU, a 32K
context limit, and one request at a time.

## Reproduce

```sh
python3 benchmark_ollama_qwen36.py --runs 3
python3 benchmark_multimodal_qwen36.py --runs 3
```

Each command writes a timestamped JSON record in the current directory. The
multimodal command exits nonzero if any exact-count check fails. The generated
PNG test card is intentionally ignored by Git.

## Files

| File | Purpose |
|---|---|
| `compose.yaml` | GPU-enabled Ollama deployment at port 8004 |
| `benchmark_ollama_qwen36.py` | Streaming text, reasoning, and fresh-prefix prefill benchmark |
| `benchmark_multimodal_qwen36.py` | Repeatable image-counting benchmark with correctness validation |
| `benchmark_results_20260722_171706.json` | Recorded text benchmark data |
| `benchmark_multimodal_results_20260722_172024.json` | Recorded multimodal benchmark data |

## Limitations

- Results are single-stream measurements, not a concurrent-load benchmark.
- Each reported result uses three runs, so it does not establish long-term
  variance or tail latency.
- The visual test checks a deterministic counting task. It is a smoke test for
  image input and structured output, not a broad multimodal quality evaluation.
