# GB10 Cluster Audit — 2026-09-04 (read-only)

Scope: `<head>` (node-rank 0, API port 8890) and `<worker>` (node-rank 1, headless) running
`vllm serve deepseek-ai/DeepSeek-V4-Flash-Vision-Exp` via docker compose from `~/dspark-vision/`,
container `deepseek-v4-flash-vllm-dspark-1`, image `ghcr.io/anemll/dspark-vllm-gx10:0.1.1`,
TP=2 over a direct 200G RoCE link. Snapshot taken ~08:53 local, both containers `Up 9 hours (healthy)`.
Both hosts reachable on first attempt; all commands read-only.

## Current effective launch (identical on both ranks except rank/headless flag)

| Flag | Value |
|---|---|
| model / served-name | deepseek-ai/DeepSeek-V4-Flash-Vision-Exp @ 86f746b (rev pinned) / deepseek-v4-flash-0731 |
| tensor/pipeline parallel | TP=2, PP=1, nnodes=2 (rank0=`<head>`, rank1=`<worker>` `--headless`) |
| kv-cache-dtype / block-size | nvfp4_ds_mla / 256 |
| max-model-len | 1,048,576 |
| max-num-seqs / max-num-batched-tokens | 6 / 8192 |
| max-cudagraph-capture-size | 48 (capture sizes actually used: 1,2,4,8,16,24,32,40,48 — no truncation observed) |
| gpu-memory-utilization | 0.835 |
| speculative-config | method=dspark, num_speculative_tokens=6, draft_sample_method=probabilistic |
| moe-backend | flashinfer_b12x (B12X_MXFP4) |
| scheduling | async-scheduling, enable-chunked-prefill, long-prefill-token-threshold=1024, enable-prefix-caching |
| tool/reasoning parsers | deepseek_v4 / deepseek_v4, reasoning tags `<think>`/`</think>`, default thinking=true, reasoning_effort=low |
| tokenizer-mode | deepseek_v4 |
| limit-mm-per-prompt | image: 8 |
| distributed-executor-backend | mp |
| enable-flashinfer-autotune | true |

Key env (secrets filtered): `NCCL_NET=IB`, `NCCL_IB_HCA=rocep1s0f0`, `NCCL_SOCKET_IFNAME=enp1s0f0np0`,
`NCCL_IB_ADDR_FAMILY=AF_INET`, `NCCL_CROSS_NIC=1`, `NCCL_NVLS_ENABLE=0`, `NCCL_CUMEM_ENABLE=0`,
`NCCL_IGNORE_CPU_AFFINITY=1`, `TORCH_NCCL_ENABLE_MONITORING=1`, `TORCH_NCCL_DUMP_ON_TIMEOUT=1`,
`PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`, `CUTE_DSL_ARCH=sm_121a`, `TORCH_CUDA_ARCH_LIST=12.1a`,
`FLASHINFER_CUDA_ARCH_LIST=12.1a`, `VLLM_USE_B12X_MOE=1`, `VLLM_USE_FLASHINFER_SAMPLER=1`,
`VLLM_ALLOW_LONG_MAX_MODEL_LEN=1`, `VLLM_PREFIX_CACHE_RETENTION_INTERVAL=4096`,
`DSPARK_MAX_INFLIGHT_PREFILLS=2`, `DSPARK_SUPPRESS_STOPS_IN_REASONING=1` (the only DSPARK feature-flag
set to `1`; all other `DSPARK_ENABLE_*`/`DSPARK_SKIP_*` flags are `0`, i.e. code-level hotfixes are baked
in and applied unconditionally at container start rather than gated by these env vars).
`VLLM_HOST_IP` correctly per-node (`<head-ip>` / `<worker-ip>`, same /24 subnet as the RoCE NIC).
Four custom `VLLM_BUILD_*`/`VLLM_IMAGE_TAG` vars are unrecognized by vLLM (see Anomalies).

## Boot facts

| Metric | `<head>` (rank 0) | `<worker>` (rank 1) |
|---|---|---|
| Weight load time | 151.96 s (main) + 32.18 s (DSpark draft) | 102.70 s (main) + 24.29 s (draft) |
| Model loading took (total) | 80.04 GiB, 202.31 s | 80.04 GiB, 145.19 s |
| Available KV cache memory | 12.17 GiB | 12.31 GiB |
| GPU KV cache size | 1,808,321 tokens (logged only on rank0/EngineCore) | n/a (not logged on headless worker, expected) |
| Max concurrency @ 1,048,576 tok/req | 1.72x | n/a |
| CUDA graph capture (PIECEWISE) | 9/9 sizes, ~1.8 s | not separately logged (same capture list) |
| CUDA graph capture (FULL + dspark) | 6/6 + 5/5, 3 s total, 0.76 GiB | 3 s, 0.79 GiB |
| init engine (profile+kv+warmup) | 23.42 s | not logged separately |
| FlashInfer autotune cache | loaded, 24 configs, cache hit (no live autotune needed) | loaded, 24 configs, cache hit |
| WARNING lines (bootlog grep) | ~15 distinct warning types, recurring on each engine (re)init | same set, same order |
| ERROR/Traceback count (full log) | 0 | 0 |
| Hotfixes applied at start | ~15 (issue21, issue55 x5 sub-steps, issue117-shm-ring, mtp-buffer stage, vision-exp x3, empty-encoder-output, issue27, issue43, issue26-v2, issue133, suppress-stops) | identical set, identical order |

## Host facts

| | `<head>` | `<worker>` |
|---|---|---|
| Uptime / load avg | 9h31m up, load 0.46/0.46/0.31 | 9h30m up, load 0.17/0.38/0.30 |
| Memory (free -g) | 119G total, 113G used, 1G free, 6G available | 119G total, 110G used, 1G free, 8G available |
| GPU | NVIDIA GB10, util 0%, power 11.84 W, clocks 2392/3003 MHz (idle sample), temp 47°C | util 0%, power 11.36 W, clocks 2398/3003 MHz, temp 45°C |
| GPU memory.used/total via nvidia-smi | reports `[N/A]` (unified-memory GB10 doesn't expose this field via `--query-gpu`) | same |
| power.limit via nvidia-smi | `[N/A]` | same |
| CPU governor / cores | performance, 20 cores | performance, 20 cores |
| Disk (/ and /home) | 3.6T total, 76% used, 863G avail | 1.8T total, 75% used, 436G avail (smaller disk SKU) |
| HugePages | all zero | FileHugePages 61440 kB reserved, rest zero (minor) |
| Interconnect link | enp1s0f0np0, 200000 Mb/s, link up, MTU 9000 | same |
| RoCE HCA | rocep1s0f0 + rocep1s0f1, PORT_ACTIVE, link_layer=Ethernet (RoCE, not native IB), max/active MTU 4096 | same, distinct GUIDs |
| Ping `<head>`→`<worker>` | avg 0.827 ms (min 0.608 / max 1.069), 0% loss over 5 pings | — |
| ethtool -S (head) errors/drops/discards | all 0 except `rx_pause_ctrl_phy: 47` (pause frames, not an error counter) | not collected (per scope) |
| HF cache: tilelang / triton / hub | 6.0M / 91M / 678G | 6.0M / 91M / 323G |
| Local user (home dir owner) | `<user-a>` | `<user-b>` — differs from head |
| git @ ~/dspark-vision | `d828ddd` 2026-09-02 22:54:34 +0300 "Merge pull request #199 ... docs/readme-tp3-section", origin=MiaAI-Lab/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark, only untracked `artifacts/`, no diff vs HEAD | **not a git repository** — plain deployment directory (compose file, `.env.dspark`, `patches/`, `recipe/`, `artifacts/`, `vllm_patch_gb10/`) |

## Other workloads (must be preserved)

- `<head>`: `qwen36-8004-proxy` (healthy, 10h), `tradingagents-ashare` (healthy, 10h), plus many stopped/exited containers (gb10-unsloth-ab-*, vllm-qwen36-*, pdf2md-api, nemotron-*, comfyui, etc. — all `Exited`, not running).
- `<worker>`: `lexdata-ai` (healthy, 10h), plus stopped `gb10-deepseek-v4-vllm-dspark-1`, `gb10-podcast-asr`, `gb10-unsloth-ab-rpc-1`.
- Running systemd services on both are standard desktop/DGX-Spark base units (gdm, bluetooth, cups, dgx-dashboard*, nvidia-persistenced, rdma-ndd, rasdaemon, etc.) plus `<head>`-only extras: `1panel-agent`/`1panel-core` (web admin panel), `ollama.service`, `sing-box.service` (proxy/tunnel). None of these were touched.

## Runtime acceptance (SpecDecoding / throughput samples)

- Draft acceptance is workload-dependent and fluctuates widely: mean acceptance length ranged ~2.2–6.3 tokens and average draft-acceptance rate ranged ~19%–89% across the log window (rank0 log), with a visible dip to the 20–35% band around 17:00–17:16 (heavier/harder generations) before recovering to ~55–59% in the most recent samples (00:49–00:50 on 2026-09-04).
- Latest `Engine 000` loop line: `Avg prompt throughput: 7–8 tok/s, Avg generation throughput: ~47–50 tok/s, Running: 0–1 reqs, GPU KV cache usage: 0.0–0.4%, Prefix cache hit rate: 83.0%` — server is lightly loaded (near-idle, trickle traffic) at snapshot time, consistent with the near-zero GPU power draw and utilization observed.
- 0 ERROR/Traceback lines in either container's full log history.

## Versions (identical on both ranks)

vLLM `0.25.2.dev0+g752a3a504.d20260714`, torch `2.11.0+cu130`, CUDA `13.0`; flashinfer-python `0.6.15` (cubin/jit-cache `0.6.13`), nvidia-nccl-cu13 `2.30.7`, tilelang `0.1.9`, triton `3.6.0`, transformers `5.13.1`, xgrammar `0.2.3`.

## Anomalies

1. **`<worker>` has no git repository** at `~/dspark-vision` (plain files only), while `<head>` is a clean git checkout at `d828ddd`. There is no version-controlled provenance trail on the worker; a future rollback/diff must be done by hand or by trusting the head repo mirrors it. — **CLOSED 2026-09-04**: converted to a git checkout at `d828ddd` (branch `main`, origin upstream) without modifying any existing file; every file that was present proved byte-identical to the pin. Record: `2026-09-04-gb10-cluster-optimization-and-eval-design.md` §9.
2. **Patch-set drift between hosts**: `<head>`'s `patches/` directory has 4 entries not present on `<worker>`: `dsv4_tp_pad.py`, `fix-nvfp4-ds-mla-long-context.patch`, `keys-concurrency.patch`, `official-main-b12x-nvfp4-python.patch` (plus a stray `__pycache__`). All hotfix scripts that actually run at container boot (the ~15 in the "Hotfixes applied" list) are identical and applied identically on both ranks, so runtime behavior is unaffected today, but the extra head-only patch files should be reconciled or explained. — **CLOSED 2026-09-04**: the 4 files were simply missing from the worker's partial copy (all four are tracked at `d828ddd`, none is in the compose hotfix chain); restored from the pin, `patches/` now sha-identical on both hosts. Residual: `vllm_patch_gb10/` on the worker is an empty root-owned Docker mount point (unused: `ENABLE_VLLM_GB10_PATCH=0` on both ranks).
3. **`torch.compile` requested but unsupported**: both ranks log `torch.compile is turned on, but the model ... does not support it` at every worker init. The launch config still carries a full `compilation_config` (mode=VLLM_COMPILE) that appears to be a no-op for this model; cudagraph capture still runs (piecewise+full), so serving works, but the compile path itself is silently skipped — worth confirming this is expected for DeepSeek-V4-Flash-Vision-Exp rather than a misconfiguration.
4. **Speculative-decoding sizing warning** on every (re)init: `max_num_scheduled_tokens is set to 8162 based on the speculative decoding settings... Consider increasing max_num_batched_tokens or decreasing num_speculative_tokens or max_num_seqs.` This is a standing vLLM performance advisory, not yet acted on.
5. **Live JIT compilation during inference** shortly after each boot: `_prepare_dflash_inputs_kernel` and `_topk_topp_kernel` Triton kernels JIT-compile on first use in production traffic (both ranks), causing a one-time latency spike per restart; vLLM's own message suggests extending warmup to cover these shapes.
6. **4 unknown vLLM env vars** (`VLLM_BUILD_URL`, `VLLM_IMAGE_TAG`, `VLLM_BUILD_PIPELINE`, `VLLM_BUILD_COMMIT`) logged as "Unknown vLLM environment variable" on both ranks — cosmetic (custom build metadata not registered with vLLM's env schema) but adds log noise on every boot.
7. **Memory headroom is thin on both hosts**: only ~6–8 GiB "available" out of 119 GiB while the containers are healthy and idle-ish; this leaves little slack for a second heavy workload or a vLLM restart racing with page cache reclaim. `<worker>`'s disk is roughly half the size of `<head>`'s (1.8T vs 3.6T) — a real hardware SKU difference, not a config error, but worth remembering when placing large model/cache downloads.
8. **`nvidia-smi --query-gpu` reports `memory.used/total` and `power.limit` as `[N/A]`** on both hosts — expected quirk of GB10's unified-memory architecture / this driver version, not a fault, but means the requested per-GPU memory/power-cap fields aren't available through this query form (use `nvidia-smi -q` or `free`/DGX dashboard instead if that data is needed later).
9. GPU clocks were sampled mid-idle (0% util, ~11.8 W draw, 2.39 GHz vs 3.00 GHz max) — reflects the trickle traffic at snapshot time, not a clock-capping problem (Clocks Event Reasons all "Not Active" except a historical SW Power Capping counter accumulated since boot).

Raw command outputs saved under `tmp/cluster-audit-20260904/<head>/combined.txt` and `tmp/cluster-audit-20260904/<worker>/combined.txt` (secrets grepped out at collection time; not committed).
