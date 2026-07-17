# Unsloth Qwen3.6-27B NVFP4 MTP2 benchmark on DGX Spark

Validated: 2026-07-16 07:35 +08:00

## Result

**PASS:** checkpoint-native MTP is active with two speculative tokens and materially improves low-concurrency generation speed.

- Target checkpoint: `unsloth/Qwen3.6-27B-NVFP4`
- Native compute path: FlashInfer B12x W4A4 NVFP4 plus CUTLASS FP8 for the checkpoint's FP8 layers
- Speculative config: `{"method":"mtp","num_speculative_tokens":2}`
- vLLM: `0.23.1rc1.dev101+g4c6266331`
- Current Dockerfile base pin: `vllm/vllm-openai@sha256:1aef087aa5159bcb8f8cb91301ecdf2f6daa6aa41420706afe30b6a9a7001858`
- Endpoint: `http://127.0.0.1:8004/v1`
- Current compatibility served model: `qwen3.6-35b-fp8`
- Current deployment-marker alias: `qwen3.6-27b-unsloth-nvfp4`
- Benchmark-time temporary served model: `qwen3.6-27b-unsloth-nvfp4` (later corrected; see compatibility incident below)

The checkpoint contains one MTP layer (`mtp_num_hidden_layers=1`). For a speculative depth of two, this vLLM build runs that same MTP layer twice, as confirmed by its startup warning.

The current compose exposes both aliases. The 27B alias is a deployment marker that strengthens detection of accidentally targeting another service; it is **not** cryptographic checkpoint attestation. The pinned model revision and shard hashes in the native-FP4 report remain the stronger artifact identity evidence.

## Runtime evidence

Startup logs confirm all required paths:

```text
speculative_config=SpeculativeConfig(method='mtp', model='/models', num_spec_tokens=2)
Resolved architecture: Qwen3_5MTP
Detected MTP model. Sharing target model embedding weights with the draft model.
Detected MTP model. Sharing target model lm_head weights with the draft model.
Using FlashInferB12xNvFp4LinearKernel for NVFP4 GEMM
```

The MTP draft model loaded from the checkpoint itself; no separate draft checkpoint was used.

## Apples-to-apples single-stream result

Methodology: five serial deterministic requests, each forced to produce exactly 256 tokens, using the same prompt, sampling parameters, endpoint, checkpoint, native B12x image, and `MAX_MODEL_LEN=32768`. Both the no-MTP and MTP2 services were explicitly started at 32K; only the server's MTP setting changed.

| Variant | Runs | Weighted speed | Mean wall time / 256 tokens | 95% CI of mean speed |
|---|---:|---:|---:|---:|
| No MTP | 5 | 11.088 tok/s | 23.089 s | 11.082–11.093 tok/s |
| MTP, 2 speculative tokens | 5 | **25.681 tok/s** | **9.968 s** | 25.615–25.748 tok/s |

**Measured gain:**

- Speedup: **2.316×**
- Throughput increase: **+131.6%**
- Wall-latency reduction: **−56.8%**
- Draft-token acceptance: **100%** on this predictable deterministic sequence
- All ten requests completed successfully with exactly 256 output tokens

This is a clear and repeatable single-stream improvement; the confidence intervals do not overlap. The 100% acceptance rate is specific to the deliberately predictable counting workload and should not be generalized to normal prompts.

## Full 48-request benchmark

Methodology: the existing matrix of 4 prompts × 4 generation configurations × 3 serial runs.

| Metric | Result |
|---|---:|
| Cases | 16 / 16 |
| Requests | **48 / 48 successful** |
| API errors | **0** |
| Completion tokens | 27,142 |
| Sum of request wall times | 1,190.954 s |
| End-to-end benchmark wall time | 1,191.027 s (`00:19:51.03`) |
| Weighted wall throughput | **22.790 tok/s** |
| Mean request throughput | 22.576 tok/s |
| Median request throughput | 23.345 tok/s |
| Range | 12.620–24.936 tok/s |
| Finish reasons | 28 stop / 20 length |

The low end of the range comes from very short 8–9 token `reasoning_off` answers, where fixed request/TTFT overhead dominates the tokens-per-second calculation. Longer generations generally ran around 21–25 tok/s.

### By generation configuration

| Configuration | Requests | Tokens | Weighted wall throughput |
|---|---:|---:|---:|
| `greedy_fast` | 12 | 5,040 | **23.582 tok/s** |
| `default` | 12 | 5,034 | **23.080 tok/s** |
| `reasoning_on` | 12 | 13,719 | **22.572 tok/s** |
| `reasoning_off` | 12 | 3,349 | **22.128 tok/s** |

### By prompt group

| Prompt group | Requests | Tokens | Weighted wall throughput |
|---|---:|---:|---:|
| `long_reasoning` | 12 | 5,820 | **24.368 tok/s** |
| `code` | 12 | 9,458 | **23.654 tok/s** |
| `short` | 12 | 1,333 | **22.655 tok/s** |
| `medium` | 12 | 10,531 | **21.342 tok/s** |

## MTP acceptance over the full matrix

Metrics were snapshotted immediately before and after the 48-request run, so earlier smoke tests are excluded.

| MTP metric | Result |
|---|---:|
| Draft steps | 10,226 |
| Draft tokens proposed | 20,452 |
| Draft tokens accepted | 16,934 |
| Overall draft-token acceptance | **82.80%** |
| First speculative position | **89.33%** |
| Second speculative position | **76.27%** |
| Accepted speculative tokens per draft step | **1.656 / 2** |

The second speculative token is less reliable than the first, but the aggregate acceptance remains high enough to produce a strong single-stream result.

## Memory and stability

After startup, smoke testing, the five-run MTP single-stream test, and the complete 48-request matrix:

- Container: `running / healthy`
- Restart count: `0`
- Docker `OOMKilled`: `false`
- API health: HTTP 200
- Local port registry: `registered-active`
- Container traceback/CUDA/OOM/Marlin fallback matches: `0`
- Kernel NVRM/Xid/OOM events **during the 48-request benchmark**: `0`
- Current vLLM EngineCore unified-memory allocation: approximately 82,844 MiB
- Host memory available after the run: approximately 22 GiB
- KV cache capacity: 1,089,287 tokens; 33.24× theoretical concurrency at 32K

### Startup warning

Two non-fatal kernel messages occurred during startup memory profiling, before the API became healthy:

```text
NVRM: ... Out of memory [NV_ERR_NO_MEMORY] ... _memdescAllocInternal
```

They occurred at 07:10:58–07:10:59, immediately after KV/CUDA-graph memory profiling. The server continued initialization, became healthy, completed every benchmark request, emitted no container-side CUDA/OOM error, and produced no further kernel memory events during the 20-minute benchmark. This is therefore recorded as a startup allocation-probe warning rather than a benchmark failure, but it should be monitored on future restarts.

## Compatibility alias incident and correction

The real checkpoint remains `unsloth/Qwen3.6-27B-NVFP4`, but the API name is an intentional backward-compatibility contract. During the native-FP4/MTP deployment work it was mistakenly changed from `qwen3.6-35b-fp8` to `qwen3.6-27b-unsloth-nvfp4`. At 2026-07-16 09:46:49 +08:00, an existing client sent the required compatibility name and vLLM returned HTTP 404: `The model qwen3.6-35b-fp8 does not exist.`

The alias was restored at 09:55 +08:00 in both the MTP2 and no-MTP compose files. At correction time `/v1/models` reported `qwen3.6-35b-fp8`, a direct compatibility-name request returned HTTP 200, and a Hermes end-to-end call through `custom:local-vllm-qwen36` returned `HERMES-8004-OK`. The current hardened compose exposes that compatibility alias first and the 27B deployment marker second; benchmark request payloads still use `qwen3.6-35b-fp8`. Benchmark filenames and `actual_model` metadata continue to use the real 27B checkpoint identity.

## Post-benchmark 128K and multimodal deployment update

After the benchmark above, the live MTP2 service was raised from 32K to **128K** with `--max-model-len 131072`. The checkpoint's native text limit is 262,144 tokens.

The current compose parameterizes this setting with a 131,072-token default. That 128K default represents the post-benchmark deployment and must not be read as the exact benchmark-time setting; the apples-to-apples pair and full matrix were run at 32K.

Verification on the restarted service:

- `/v1/models` reports `max_model_len: 131072`.
- Engine logs report `max_seq_len=131072`, while retaining MTP2 and native FlashInfer B12x.
- A real request with **40,020 prompt tokens**—above the previous 32K limit—completed with HTTP 200 in 36.801 seconds.
- The KV cache reports 1,529,638 tokens and theoretical 11.67× concurrency at 131,072 tokens/request.
- The service remains healthy with zero restarts and `OOMKilled=false`.

The checkpoint is also natively multimodal: `language_model_only=false`, a 27-layer `qwen3_5_vision` tower, image/video token IDs, 333 visual weight entries, and `Qwen3VLProcessor` image/video processors. A live image request correctly identified a green circle on the left and yellow triangle on the right.

The same two non-fatal `NV_ERR_NO_MEMORY` profiling messages recurred during the 128K restart. No container-side CUDA/OOM error occurred, and no further kernel errors appeared during the 40K-token and vision requests.

## Interpretation

1. **Yes, MTP2 significantly improves the tested single stream:** 11.088 → 25.681 tok/s, or 2.316×.
2. The broader 48-request matrix sustains **22.790 tok/s weighted** with **82.80%** draft-token acceptance and no request failures.
3. The full 48-request run has no same-checkpoint/no-MTP matrix counterpart. Therefore, its 22.790 tok/s is an absolute MTP2 result; the strict apples-to-apples speedup claim is based on the controlled five-run single-stream pair.
4. The service is left running with MTP2 enabled on port 8004.

## Reproducible configuration and artifacts

Compose:

```text
docker-compose-vllm-qwen36-27b-unsloth-nvfp4-native-mtp2.yml
```

The current Dockerfile uses the digest pin shown above; the validated benchmark image reported vLLM `0.23.1rc1.dev101+g4c6266331`. To reproduce the historical 32K conditions with the hardened current files, use the exact relevant environment overrides below (the no-MTP service must be stopped before MTP2 starts):

```bash
MODEL_DIR="$HOME/models/unsloth-Qwen3.6-27B-NVFP4" \
VLLM_BIND_ADDRESS=127.0.0.1 \
MAX_MODEL_LEN=32768 \
  docker compose -f docker-compose-vllm-qwen36-27b-unsloth-nvfp4-native.yml up -d

MODEL_DIR="$HOME/models/unsloth-Qwen3.6-27B-NVFP4" \
VLLM_BIND_ADDRESS=127.0.0.1 \
MAX_MODEL_LEN=32768 \
  docker compose -f docker-compose-vllm-qwen36-27b-unsloth-nvfp4-native-mtp2.yml up -d

BENCH_URL=http://127.0.0.1:8004/v1/chat/completions \
METRICS_URL=http://127.0.0.1:8004/metrics \
EXPECTED_MAX_MODEL_LEN=32768 \
SERVED_MODEL_NAME=qwen3.6-35b-fp8 \
  python3 run_full_mtp2_benchmark.py
```

For the current 128K default deployment, omit `MAX_MODEL_LEN` and `EXPECTED_MAX_MODEL_LEN`; benchmark preflight defaults the latter to 131,072 and requires both aliases plus the compatibility-model speculative metrics.

Benchmark scripts:

```text
benchmark_vllm_qwen36_27b_unsloth_nvfp4_mtp2.py
run_full_mtp2_benchmark.py
```

Single-stream artifacts:

```text
benchmark_outputs/single-stream-nomtp-20260716-070601.json
benchmark_outputs/single-stream-mtp2-20260716-071424.json
benchmark_outputs/single-stream-nomtp-vs-mtp2-20260716-071424.json
```

Full benchmark artifacts:

```text
benchmark_outputs/benchmark-results-qwen3.6-27b-unsloth-nvfp4-mtp2-20260716-073507.json
benchmark_outputs/benchmark-run-summary-qwen3.6-27b-unsloth-nvfp4-mtp2-20260716-071516.json
benchmark_outputs/mtp2-benchmark-analysis-20260716-073507.json
```

The verbose console log is intentionally excluded from Git; the structured JSON files contain the submitted evidence.
