# GLM-5.3-Flash NVFP4 — dual DGX Spark (GB10) B12X stack

Production serving recipe for `local-inference-lab/GLM-5.3-Flash-NVFP4-Spark`
on 2× DGX Spark (GB10, TP=2 over ConnectX-7 RoCE), based on the
[eugr/spark-vllm-docker](https://github.com/eugr/spark-vllm-docker) B12X stack.

Validated 2026-09-21→09-23 on xFusion FusionXpark GB10 (firmware 01.53.05.01,
121.6 GiB visible after the 2 GiB OEM carveout was recovered via BIOS update).

## Fixed configuration

| Item | Value |
|---|---|
| Weights revision | `a608241037e4c2565356bff7ca293f2133888f88` (pinned via `--revision` + offline `refs/main`) |
| KV cache | 8 GiB pinned = **1,061,538 tokens (2.12× @500k)** |
| Context | 500,000 |
| Scheduling | MNBT 4096 · max_num_seqs 4 · chunked prefill · prefix caching |
| Speculative | native MTP k=5 (humming MoE draft) |
| Quantization | modelopt_mixed NVFP4 · KV fp8 · block 256 |
| Served name | `GLM-5.3-Flash-EXL3` (portal-compatible alias) |
| API port | 8890 |

Local deviations from the upstream recipe (all intentional):
1. `--served-model-name GLM-5.3-Flash-EXL3` — client compatibility.
2. `--enable-prompt-tokens-details` — surface `cached_tokens` in usage.
3. `--revision <sha>` — offline-safe pinned resolution (hub 1.32 cannot resolve
   `main` offline from a pinned-sha download; write `refs/main` too).
4. `HF_CACHE_DIR_WORKER` patch in `launch-cluster.sh` — per-node weight cache
   mount (head path `/home/chriswang/models/hf-nvfp4`, worker
   `/home/admin/models/hf-nvfp4`).

## Operations

`scripts/start.sh` (idempotent: verifies shard count + revision on both ranks,
stops old containers, relaunches), `scripts/status.sh`, `scripts/stop.sh`.
Ready when the log shows `Application startup complete` and
`GPU KV cache size: 1,061,538 tokens` (~2.5 min warm).

Known transient: `RoCE proxy failed: RDMA write to rank 1 … vendor_err 0x81`
with healthy links (both `enp1s0f0np0` UP, `rdma link` ACTIVE, ping clean) is a
rank-1 proxy readiness race — simply re-run `start.sh`.

Rollback: the previous EXL3 stack's containers (`glm53-exl3-head/-worker`) are
kept stopped on both hosts; `docker start` them and stop `vllm_node`.

Weights: 46 safetensors / 175 GiB, kept on both ranks plus an off-host copy
(sha256-verified). If `refs/main` is missing after a restore, write the pinned
revision into it.

## Benchmark

See [BENCHMARK-RESULTS.md](BENCHMARK-RESULTS.md) and the rendered comparisons
(`three-model-comparison.png`, `glm-nvfp4-window-comparison.png`).
