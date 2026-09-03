# Phase B B-Campaign Runbook (2026-09-02)

Status: PLANNED (D1/D2/D3 complete; awaiting idle window)

Stack: fork-native OffloadingConnector + `vllm_nvme_tier` (custom
NVMeTieredOffloadingSpec, out-of-tree via PYTHONPATH) + connector
failure overlay (3 file bind-mounts) + `PYTHONHASHSEED=0`. NO image
change (B0 is image-parity-free by construction; the existing
fingerprint assertion still pins the image the mounts ride on).

Companion docs: `2026-09-02-phase-b-nvme-dev.md` (D1-D3 detail),
`2026-08-31-kv-offload-phase-b-nvme-design.md` Section 8 (gates, Rev 2
amendments). Evidence dir: `tmp/followup-tests/<UTC>/phase-b/`.

## Pre-flight (both hosts, before stopping production)

1. Staging present (already synced 2026-09-02):
   - `~/phase-b-nvme/vllm_nvme_tier/` (5 files)
   - `~/phase-b-nvme/overlay/vllm/.../offloading/{common,scheduler,worker}.py`
   - `<service-root>/kv-offload-tier/` (empty)
   - `<service-root>/execution/apply-phase-b-edits.sh` (rehearsed on
     gb10 scratch: apply idempotent, verify 8/8 conjuncts, rollback
     byte-exact)
2. Production idle: `num_requests_running==0` AND
   `generation_tokens_total` static across 2 polls ≥60 s apart.
   NEVER stop while generation advances.

## Sequence

```
B-pre   stop production (run-private-ds-production.sh --stop),
        ≥3 min settle
B-gpu   GPU round-trip test in throwaway --gpus container
        (test_gpu_roundtrip.py; includes on-GPU failure branch).
        GATE: all checks pass, probe ≥ 100 MiB/s end-to-end.
        FAIL → abort campaign, restart original production.
B-edits apply-phase-b-edits.sh <UTC> apply head   (gb10)
        apply-phase-b-edits.sh <UTC> apply worker (gb10-2)
        then verify on both; diff .bak pairs by eye once.
B1      --start; boot gates (13-16 min fork boot, ≥3 min settle):
        - both ranks up, model_ok, protected services ok
        - journal (TZ=UTC): "Creating offloading spec with name:
          NVMeTieredOffloadingSpec"; ring slots log line
          ("NVMe tier handler: ... ring N slots"); PYTHONHASHSEED guard
          passed; no new NVRM/NCCL/CUDA/OOM
        - KV floor: "Available KV cache memory" ≥ 7.3 GiB/rank
          (ring is 512 MiB/rank pinned — after KV sizing, expect ≈0
          reduction vs baseline)
        - `free -g`: head available ≥ 4 GiB after boot
        - canary: 17,000-word needle → answer identical to baseline,
          TTFT sane; first-traffic probes (64K/130K cold prefill) within
          ±10% of baseline 1744-1772 / 1630-1732 tok/s
        FAIL → `apply-phase-b-edits.sh <UTC> rollback` both hosts →
        --start → verify original healthy.
B2      Offload-hit correctness (one-vote veto):
        1. seed 90001 17,000-word needle, temp 0, record answer
        2. flood ≥1.5M fresh tokens (new-seed probes) to force GPU-pool
           eviction through the tier
        3. re-issue identical needle prompt:
           - answer byte-identical
           - cached_tokens > 0 (target: the offloaded prefix)
           - TTFT ≤ 30 s (cold ≈ 155 s; micro-bench predicts ~2-5 s/rank)
           - `du -sh kv-offload-tier` grew (stores happening);
             vllm:kv_offload_* metrics monotone
        4. amplification honesty: store-side offers vs logical stores —
           the manager dedupe absorbs repeats; metric-level
           amplification ≤ 1.3× (design Section 8 + Rev 2).
        FAIL → rollback per B1.
B3      Fault injection (the D2a overlay under fire):
        - pick a live hash file under kv-offload-tier/offload_r0/...,
          truncate it mid-flight, then re-issue the needle:
          expect "degrading to cold recompute" warning, request
          completes with CORRECT answer (recomputed), service stays
          healthy ≥ 10 min, no worker crash. Also delete a whole rank
          dir once → same expectation.
        FAIL (crash/hang/wrong answer) → rollback per B1.
B4      Soak ≥ 40 min mixed load (probe suite): zero failed requests;
        every 60 s sample: `free -g` (head ≥ 4 GiB), `df` on the tier
        root, `iostat -x 5 3` on nvme0n1 (util% < 80 sustained),
        page-cache watch (`grep -E "Cached|MemAvailable" /proc/meminfo`
        — POSIX_FADV_DONTNEED should keep Cached roughly flat),
        vllm:kv_offload_* + TTFT within gates.
        FAIL → rollback per B1.
B-adopt LEAVE RUNNING. Post: update this doc + dev doc status, commit
        evidence pointers, PR note. 48 h watch: portal slow-request
        (30 s+ TTFT) count vs pre-Phase-B baseline.
```

## Rollback invariant

Every host file touched has `.bak-<UTC>`; rollback = restore all four
(+ acceptance on head) → `--start` → B1 boot gates on ORIGINAL config.
The tier dir keeps its files (harmless; wiped on next Phase B cold
start by `_prepare_tier_dir`).

## Metrics to watch (Prometheus :8890)

- `vllm:kv_offload_total_bytes` / `total_time` / `size` (monotone
  growth during flood, stable after)
- TTFT histogram + `num_requests_running`
- decode tok/s under concurrent load (≥ ~30 tok/s free-text baseline)
