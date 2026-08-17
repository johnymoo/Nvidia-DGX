# Unsloth Qwen3.6-27B NVFP4 native FP4 validation on DGX Spark

Validated: 2026-07-15 23:17 +08:00

## Result

**PASS:** the mixed-precision `unsloth/Qwen3.6-27B-NVFP4` checkpoint loads on GB10/SM121 and vLLM selects FlashInfer B12x native FP4 GEMM for its W4A4 MLP layers.

This is a mixed deployment, not an all-FP4 model:

| Layer group | Checkpoint operands | Selected vLLM kernel | Native FP4? |
|---|---|---|---|
| Attention / linear-attention projections | FP8 weights + FP8 activations | `CutlassFP8ScaledMMLinearKernel` | No; native FP8 path |
| Most MLP projections | FP4 weights + dynamically quantized FP4 activations | `FlashInferB12xNvFp4LinearKernel` | **Yes** |
| Final 8 MLP layers (56-63) | FP8 weights + FP8 activations | `CutlassFP8ScaledMMLinearKernel` | No; native FP8 path |
| Vision layers | excluded from checkpoint quantization | default dtype/path | No |

## Model artifact

- Repository: `unsloth/Qwen3.6-27B-NVFP4`
- Hugging Face revision: `ccdaab7e68af2409599b8949a8f2685703c9bae5`
- Download source: ModelScope mirror
- Local path: `~/models/unsloth-Qwen3.6-27B-NVFP4`
- Indexed tensors: 1,968
- Shards: 5
- Safetensors payload: 23.42 GB (decimal)
- Quantization: compressed-tensors mixed precision
- W4A4 group format: `nvfp4-pack-quantized`, group size 16
- KV cache metadata: FP8

All five shard sizes and SHA-256 hashes match the Hugging Face revision:

| Shard | Size | SHA-256 |
|---|---:|---|
| `model-00001-of-00005.safetensors` | 4,987,125,100 | `7425311be1926ae8db13449c86ff7a03e4465ccb7c6b599457b1392603c44867` |
| `model-00002-of-00005.safetensors` | 4,958,199,472 | `15bff3d0a9ebae8d876a17a102666b46460120a9639a84058595f2c2e7ff43d0` |
| `model-00003-of-00005.safetensors` | 4,962,827,364 | `bee4902f307e256fa70bee641ba531a527420c779b22148134484c7295f34afc` |
| `model-00004-of-00005.safetensors` | 4,925,632,304 | `74cd7aa7eb60a064d103b75e57297960fc90b6db1750662970b8ff93b29e7283` |
| `model-00005-of-00005.safetensors` | 3,583,802,696 | `b1b368fe53d8a68ca0c68891895e043087deda4ad1d5880fcd48c69d78058da1` |

Safetensors headers also parsed successfully for all five shards.

## Runtime

- Host GPU: NVIDIA GB10, compute capability 12.1
- Image: `local/vllm-openai:sm121-native-fp4`
- Image ID: `sha256:4522f7791b8658c033618013c779448698abd42c8428d76b30a519b162b29290`
- Benchmark-time base source was the mutable `vllm/vllm-openai:nightly-aarch64` tag
- Current Dockerfile base pin: `vllm/vllm-openai@sha256:1aef087aa5159bcb8f8cb91301ecdf2f6daa6aa41420706afe30b6a9a7001858`
- vLLM: `0.23.1rc1.dev101+g4c6266331`
- PyTorch: `2.11.0+cu130`
- CUDA runtime: 13.0
- FlashInfer: 0.6.12
- Container: `vllm-qwen36-27b-unsloth-nvfp4-native`
- Endpoint: `http://127.0.0.1:8004/v1`
- Current compatibility served model: `qwen3.6-35b-fp8`
- Current deployment-marker alias: `qwen3.6-27b-unsloth-nvfp4`
- Initial validation temporarily reported: `qwen3.6-27b-unsloth-nvfp4` (corrected after a compatibility regression)
- Max model length for this first validation: 32,768
- GPU memory utilization target: 0.60
- KV cache dtype: FP8
- MTP: not enabled in this first isolated kernel validation
- Restart policy: `no`

Compose file:

`docker-compose-vllm-qwen36-27b-unsloth-nvfp4-native.yml`

## Positive backend and kernel evidence

The model startup log contains:

```text
Selected CutlassFP8ScaledMMLinearKernel for CompressedTensorsW8A8Fp8
Using FlashInferB12xNvFp4LinearKernel for NVFP4 GEMM
```

It subsequently executed FlashInfer's `fp4_gemm` autotuner during engine warmup.

A standalone GPU profiler call through the exact vLLM B12x wrapper on this image and GB10 reported:

```text
vllm::flashinfer_mm_fp4
kernel_cutlass_kernel_flashinfergemmkernelsdense_blockscaled_gemm_sm120_b12xDenseGemmKernel_...
```

The profiled operation returned finite BF16 output with shape `(32, 256)`. This proves that the image's B12x backend executes the SM120+ block-scaled FP4 GEMM kernel successfully on SM121; the model startup log proves that its W4A4 layers dispatch to that backend.

No Marlin NVFP4 or weight-only FP4 fallback was found in the model log.

## API validation

- `GET /health`: HTTP 200
- `GET /v1/models`: HTTP 200
- Initial validation model ID: `qwen3.6-27b-unsloth-nvfp4` (temporary; subsequently restored to the compatibility alias)
- Current model ID: `qwen3.6-35b-fp8`
- Current second alias: `qwen3.6-27b-unsloth-nvfp4` (deployment marker only, not cryptographic checkpoint attestation)
- Reported max model length: 32,768
- Deterministic non-thinking chat request: HTTP 200
- Required response: `OK-UNSLOTH`
- Actual response: `OK-UNSLOTH`
- First smoke request wall time: 1.584 seconds

## Initial throughput sample

This is a focused smoke benchmark, not directly comparable with the earlier full 16-case benchmark.

### One request at a time

Three deterministic 256-token requests:

| Run | Wall time | Wall throughput |
|---:|---:|---:|
| 1 | 23.082 s | 11.091 tok/s |
| 2 | 23.096 s | 11.084 tok/s |
| 3 | 23.086 s | 11.089 tok/s |

Weighted throughput: **11.088 tok/s**.

### Four concurrent requests

Four simultaneous 256-token requests:

- Total completion tokens: 1,024
- Batch wall time: 24.983 s
- Aggregate throughput: **40.988 tok/s**
- Per-request throughput: approximately 10.25 tok/s

The initial result suggests that this kernel/model combination benefits primarily in aggregate throughput at concurrency. A full apples-to-apples benchmark and an MTP test are still required before comparing it with previous deployments.

## Memory and capacity

- Model load allocation reported by vLLM: 21.31 GiB
- Available KV cache memory: 44.63 GiB
- GPU KV cache capacity: 1,131,102 tokens
- Maximum concurrency at 32,768 tokens: 34.52x
- Host memory after benchmark: 83 GiB used, 36 GiB available

## Stability

After startup, API smoke tests, three serial generations, and four concurrent generations:

- Container: running and healthy
- Restart count: 0
- Docker OOM flag: false
- API health: HTTP 200
- Local port registry: `registered-active`
- Container traceback/CUDA/OOM/Marlin fallback matches: 0
- Kernel NVRM/Xid/NV_ERR/OOM events since launch: 0

Non-fatal warnings:

- fastsafetensors reports that GDS is unavailable and uses the non-GDS path.
- Transformers reports a deprecated `use_fast` parameter.
- Torch Inductor reports insufficient SM count for `max_autotune_gemm`; this did not prevent startup or inference.

## Operations

Start:

```bash
docker compose -f docker-compose-vllm-qwen36-27b-unsloth-nvfp4-native.yml up -d
```

Status:

```bash
docker inspect vllm-qwen36-27b-unsloth-nvfp4-native \
  --format 'status={{.State.Status}} health={{.State.Health.Status}} restart_count={{.RestartCount}}'
curl http://127.0.0.1:8004/health
curl http://127.0.0.1:8004/v1/models
```

Logs:

```bash
docker logs -f vllm-qwen36-27b-unsloth-nvfp4-native
```

Stop:

```bash
docker compose -f docker-compose-vllm-qwen36-27b-unsloth-nvfp4-native.yml down
```

## MTP2 follow-up completed

Checkpoint-native MTP with two speculative tokens was enabled and the full 16-case/48-request matrix completed successfully. See:

`UNSLOTH-QWEN36-27B-NVFP4-MTP2-BENCHMARK-RESULTS.md`

Key follow-up results:

- Controlled single stream: 11.088 → 25.681 tok/s (**2.316×**)
- Full matrix: 48/48 requests, 0 errors, 22.790 weighted wall tok/s
- Full-matrix draft-token acceptance: 82.80%

## 128K and multimodal follow-up completed

The live MTP2 service now uses `--max-model-len 131072`. `/v1/models` reports 131,072, and an actual 40,020-token prompt completed successfully. The checkpoint is natively multimodal and a live image request was also verified. Detailed evidence is in `UNSLOTH-QWEN36-27B-NVFP4-MTP2-BENCHMARK-RESULTS.md`.

## Remaining optional work

1. Replace the local selection patch with a pinned upstream image once stock vLLM includes SM121 B12x auto-selection.
