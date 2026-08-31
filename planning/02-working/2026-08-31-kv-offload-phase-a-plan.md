# KV Offload Phase A Test Plan: OffloadingConnector DRAM Tier (2026-08-31)

Status: approved plan, window authorized for the night of 2026-08-31 (local
Asia/Shanghai, after 00:00 on 09-01). Executor measures every arm; the lead
session reviews the report and decides adoption. Unlike the 08-24 campaigns,
arm A1 is an ADOPTION CANDIDATE: if all gates pass it stays live; otherwise
restore to baseline byte-identically.

Trigger: 2026-08-31 21:07-21:18 local eviction-thrash incident. Concurrent
~400K-token sessions evicted each other's prefixes in the 8.81 GiB / 1.22M
token GPU KV pool; each turn cold re-prefilled 150-400K tokens (4-5 min TTFT)
while all other requests decoded at ~1-2 tok/s. Runbook option 2 (KV offload)
approved by the user; Phase B (custom per-rank NVMe OffloadingSpec via
`spec_module_path`, image rebuild) is separately committed and starts after
Phase A adoption. Phase A adds a DRAM second tier via the fork-native
OffloadingConnector: cluster 8 GiB = 4 GiB pinned per host ≈ +530K tokens
(+44%), combined ≈ 1.73M ≥ the 1.6M-token incident working set.

## 0. Hard constraints (violating any of these = stop and report)

Identical to `2026-08-24-long-context-followup-test-plan.md` Section 0, plus:

- Operate the service ONLY through
  `ssh gb10 'cd /home/chriswang/gb10-ds4 && execution/run-private-ds-production.sh --check|--start|--status|--stop'`.
  Never per-rank compose while `artifacts/service/active.json` exists.
- Do not touch `:8004` proxy, pdf2md, trading, lexdata, SSH relay unit.
- Never store/request passwords; never push git; do not modify local repo
  files during the campaign (remote host files + local `tmp/` evidence only).
- Frozen: `--max-model-len 1048576`, `MAX_NUM_SEQS=6`,
  `MAX_NUM_BATCHED_TOKENS=8192`, `LONG_PREFILL_TOKEN_THRESHOLD=6144`,
  `MTP_NUM_TOKENS=5`, `KV_CACHE_DTYPE=nvfp4_ds_mla`,
  `GPU_MEMORY_UTILIZATION=0.78`, `VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=0`.
- Backup every edited remote file first:
  `cp FILE FILE.bak-$(date -u +%Y%m%dT%H%M)`; record every path.
- Wall budget: 7 hours from first restart; on overrun jump to Section 7
  (final restore/adopt verification), which runs UNCONDITIONALLY.
- Two failed starts at any point: restore all backups, one final baseline
  start, STOP, report exact state.
- Journal scans always `TZ=UTC journalctl ...` (hosts are Asia/Shanghai).
- Shell hygiene: `ssh HOST 'bash -s' < local_script.sh` for anything nested;
  no bare `===` echoes in zsh.

## 1. Fixed facts (verified read-only 2026-08-31, do not re-derive)

- Fork vLLM `0.21.1rc1.dev339+g1967a5627bc3`; image `gb10-ds4-vllm:f277b3d-nvfp4`;
  container `gb10-deepseek-v4-vllm-dspark-1` on both hosts; python at
  `/opt/env/bin/python` (no `python3` on PATH). `$VLLM` below =
  `/opt/env/lib/python3.12/site-packages/vllm`.
- `--kv-transfer-config` accepted (`$VLLM/engine/arg_utils.py:1469`);
  `_check_feature_supported` (:2254) does NOT reject kv_transfer.
- Chosen connector: `OffloadingConnector` + default `CPUOffloadingSpec`.
  Rationale (all verified in-container): DeepSeek-V4-specific engineering in
  `$VLLM/distributed/kv_transfer/kv_connector/v1/offloading/scheduler.py`
  (~66-72 SWA alignment, ~720 "reduces SWA stores by ~78%"); heterogeneous
  per-layer page sizes handled per canonical tensor
  (`offloading/worker.py`, `$VLLM/v1/kv_offload/cpu/gpu_worker.py` ~415-436);
  declares `SupportsHMA` (`offloading_connector.py` ~46) which the factory
  REQUIRES on this hybrid multi-group model (`kv_connector/factory.py`
  ~56-60); async-scheduling accommodated (`offloading/scheduler.py` ~683);
  MTP deferred finalize supported (`gpu_model_runner.py:4403,4420`;
  `offloading_connector.py` ~105-121); 2-node TP completion aggregation
  (`OffloadingWorkerMetadata.aggregate()` in `offloading/common.py`).
- REJECTED: SimpleCPUOffloadConnector (`reset_cache` NotImplementedError,
  no V4 logic); LMCacheConnectorV1 (no SupportsHMA -> factory refuses at
  boot; lmcache not installed; no gcc in image); in-image
  TieringOffloadingSpec (single-group assert `$VLLM/v1/kv_offload/tiering/spec.py`
  ~113 crashes multi-group V4; secondary-tier IO runs in the scheduler
  process against per-host /dev/shm -> wrong on 2-node TP).
- HARD PREREQUISITE (drives arm A0): live env has
  `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`
  (base compose line 64 ONLY; not in thinking-on override, not in env files,
  not asserted by `assert_rendered_config`). `$VLLM/config/vllm.py:782-823`
  `_verify_kv_transfer_compat` raises ValueError for ANY kv connector while
  that setting is present (unless cumem allocator). Verified live 2026-08-31.
- Sizing semantics (verified `$VLLM/v1/kv_offload/cpu/spec.py:33-38`):
  `cpu_bytes_to_use` is CLUSTER-total; per-worker share = value / world_size
  (world_size=2 -> 4 GiB pinned per host at 8 GiB). Pinned allocation happens
  in `register_kv_caches` BEFORE CUDA-graph capture
  (`$VLLM/v1/worker/gpu_worker.py:558` vs `:610`).
- Do NOT set `kv_connector_extra_config.block_size` (single-KV-group assert
  in `$VLLM/v1/kv_offload/base.py` ~352-365 would crash multi-group V4).
  Leave `spec_name` / `eviction_policy` (LRU) at defaults.
- Offload Prometheus counters: `vllm:kv_offload_total_bytes`, `..._total_time`,
  `..._size` (`offloading/metrics.py:106,112,118`) on `:8890/metrics`.
- Host memory while live: gb10 ~12Gi available, gb10-2 ~15Gi, no swap.
- Baseline numbers (2026-08-23/24, unchanged config since): boot KV pool
  8.81 GiB / 1,221,928 tokens (clean boot; same-session restarts have come up
  as low as 8.22 GiB); cold prefill ~1939 tok/s @14K -> ~1573 @254K; solo 64K
  cold ~36 s; 130K cold ~1630-1732 tok/s; HOL small request during 130K cold
  prefill ~11-13 s; free-prose decode ~32-34 tok/s (never compare against the
  ~62 tok/s structured figure).
- KV floor: "Available KV cache memory" must be >= 7.3 GiB per rank or the
  frozen 1,048,576 context cannot boot.
- Probe tool: `tmp/prefill-probe/probe.py <n_words> <seed>` (local; ~3.5
  tokens/word; thinking off; max_tokens=1; prints latency/prompt_tokens/
  cached_tokens/tok_per_s). Never reuse a seed for a cold measurement.
  Correctness battery: `execution/benchmarks/correctness.py`
  (`URL=http://192.168.88.181:8890/v1`); C1-C5 definitions in the 08-24 plan
  Section 3 step 5 (C5 needle: 17000 words seed 90001, passphrase
  "AURORA-73-KESTREL" after word 7000, temperature 0).
- The three campaign restarts land in the low-traffic window; drain first
  (poll `vllm:num_requests_running` to 0, up to 10 min), stop, wait >= 3 min
  and `free -g` recovery, start (boot 13-16 min).

## 2. Evidence layout

`tmp/followup-tests/<UTC>/` with subdirs `a0-alloc/`, `a1-offload8g/`,
`a2-offload12g/` (optional), `restore-or-adopt/`, `scripts/`;
`backup-paths.txt` and final `report.md` at top level. For every boot record:
run ID from active.json, both ranks' KV pool lines
(`docker logs ... | grep -iE "kv cache (size|memory)"`), `free -g` both hosts,
`TZ=UTC` journal scan, connector init lines
(`docker logs ... | grep -iE "offload|kv.?connector|kv.?transfer"`).

## 3. Arm A0 - drop expandable_segments (NO connector yet)

Purpose: clear the `_verify_kv_transfer_compat` prerequisite and prove the
memory profile (KV pool >= 7.3 GiB floor) survives without the VMM allocator.
This is the gating unknown for everything else, including Phase B.

Apply (both hosts, path prefix head `/home/chriswang/gb10-ds4/`, worker
`/home/admin/gb10-ds4/`):
1. Backup `execution/docker-compose.yml`; edit line 64:
   `PYTORCH_CUDA_ALLOC_CONF: expandable_segments:True`
   -> `PYTORCH_CUDA_ALLOC_CONF: "${PYTORCH_CUDA_ALLOC_CONF:-}"`
   (passthrough, default empty; matches the B12X passthrough precedent).
2. Backup `execution/env/common.env`; append documentation line
   `PYTORCH_CUDA_ALLOC_CONF=` (empty; explicit off).
   No thinking-on edit (environment maps merge). No acceptance edit (the env
   is not asserted).
3. Pre-drain baseline light-touch capture (no restart): --status, active.json,
   `/v1/models`, metrics snapshot, `free -g` both hosts.
4. Drain -> `--stop` -> settle >= 3 min -> `--start`.

Gates:
- Boot: both ranks running; KV pool >= 7.3 GiB per rank (RECORD GiB+tokens;
  expect ~8.2-8.8 GiB; materially lower without expandable_segments is the
  R3 signal); `TZ=UTC` journal scan for the boot window - NVRM bursts during
  CUDA-graph capture are known-noise on every boot, gate on NO POST-BOOT
  events and no new error kinds (Xid, OOM-killer, NCCL fatal).
- First traffic: small request; probe 18300 (fresh seed); probe 37000 (fresh
  seed); after each - both containers up, API 200.
- Perf spot: 18300/37000 tok_per_s within ~10% of baseline; one decode
  request (max_tokens 500, thinking off) ~32-34 tok/s; HOL check (37000-word
  probe backgrounded + small request 5 s later, expect <= ~15 s).
- FAIL -> restore both .bak files, baseline `--start`, STOP campaign (A1
  cannot proceed); report escalates to lead for the
  `enable_cumem_allocator` alternative (a separate future arm - the fork
  exempts cumem from the rejection, see vllm.py:801-809) or abandonment.
- PASS -> proceed directly to A1 (A0 edits stay in place; the A1 restart
  subsumes further A0 soak - both arms share the allocator change).

## 4. Arm A1 - OffloadingConnector @ cluster 8 GiB (ADOPTION CANDIDATE)

Apply (on top of A0, both hosts):
1. Backup `execution/docker-compose.yml` (again, post-A0 copy) and
   `execution/docker-compose.thinking-on.yml`. In BOTH files' `command:`
   folded block, insert directly after the `--enable-chunked-prefill` line:
   `--kv-transfer-config '{"kv_connector":"OffloadingConnector","kv_role":"kv_both","kv_connector_extra_config":{"cpu_bytes_to_use":${KV_OFFLOAD_CPU_BYTES:-8589934592}}}'`
   (single-quoted JSON follows the `--reasoning-config` precedent; compose
   interpolates `${KV_OFFLOAD_CPU_BYTES:-...}` textually before the shell
   sees it; JSON contains no single quotes).
2. Both hosts: append to `execution/env/common.env`:
   `KV_OFFLOAD_CPU_BYTES=8589934592`.
3. Head only: backup `execution/run-vllm-acceptance.sh`; in
   `assert_rendered_config` add two conjuncts after the
   `--kv-cache-dtype` line:
   `and ($c | contains("--kv-transfer-config"))`
   `and ($c | contains("OffloadingConnector"))`.
4. Drain -> `--stop` -> settle -> `--start`.

Gates (in order; any failure = kill arm, Section 6 rollback):
- Boot: connector init present in both ranks' logs; KV pool floor holds;
  post-boot `free -g` available: gb10 >= 4Gi, gb10-2 >= 6Gi (4 GiB pinned
  each was allocated); `TZ=UTC` journal per A0 rule.
- First traffic: as A0 (small + 18300 + 37000 fresh-seed probes).
- OFFLOAD-HIT CORRECTNESS (kill-arm gate, the point of the whole arm):
  a. Build the C5 needle prompt (17000 words seed 90001, AURORA-73-KESTREL);
     send at temperature 0, record answer + `cached_tokens` (expect ~0 cold).
  b. Flood: >= 1,300,000 fresh tokens of new-seed probes (e.g. 5x 72500-word
     probes, sequential) to force full GPU-pool eviction of (a).
  c. Re-send (a) byte-identical: REQUIRE answer contains AURORA-73-KESTREL
     and equals the (a) answer, `cached_tokens > 0`, wall latency <= 15 s
     (cold would be ~35-40 s at this depth; a connector hit must be far
     faster; also grep logs for kv_load_failure / WAITING_FOR_REMOTE_KVS
     stalls).
  d. 254K-scale variant: 72500-word needle (fresh seed, same passphrase
     insertion mechanics mid-text), flood >= 1.3M fresh tokens, re-send:
     answer correct, `cached_tokens > 0`, wall <= 30 s (cold ~155 s).
  Any wrong/other answer = KV corruption via the offload path: kill arm,
  rollback IMMEDIATELY, preserve full logs first.
- Soak >= 40 min (08-24 Phase-B driver: alternating 18300/37000 cold prefills
  every ~6 min backgrounded, small request every 30 s, decode request every
  ~6 min, <= 3 in flight). Monitor every 60 s: docker ps both hosts, curl -m 5
  /v1/models, `free -g` (gb10 available >= 4Gi at ALL samples - single dip
  below = R8 fail), `TZ=UTC journalctl -k --since '-2 min'` grep
  Xid/oom/NV_ERR, docker logs 2m-window grep CUDA|OOM|Error|Traceback, and
  metrics snapshot of `vllm:kv_offload_*` + `vllm:prefix_cache_*` (offload
  bytes should grow then plateau; record for Phase B calibration).
- Perf: 18300/37000 fresh-seed tok_per_s and decode within ~10% of A0's own
  numbers (isolates connector overhead from allocator change); HOL <= ~15 s.
- Correctness battery C1-C5 (temperature 0): C2 exact "391", C5 contains
  passphrase, C1/C3/C4 semantically equal to baseline records.

PASS ALL -> A1 is adopted-pending-lead-review: leave running, go to A2
decision, then Section 7 verification. FAIL ANY -> Section 6.

## 5. Arm A2 (OPTIONAL) - escalate to 12 GiB

Only if A1 passed AND its soak-minimum `free -g` available on gb10 >= 7Gi.
Apply: change `KV_OFFLOAD_CPU_BYTES=12884901888` in both common.env (no
compose/acceptance edits - env-only), drain/stop/settle/start, rerun A1's
boot gate, first-traffic, ONE offload-hit correctness pass (60K variant), and
a 20-min soak with the same memory-watermark rule (gb10 >= 3Gi). PASS ->
adopt 12 GiB; FAIL -> revert env to 8589934592, restart, re-verify A1 boot
gate + smoke (A1 remains the adopted config).

## 6. Rollback (any arm failure)

1. Restore EVERY edited file from its .bak (list in backup-paths.txt);
   `diff` each against its backup - all diffs must be empty.
2. Drain if API is up -> `--stop` -> settle -> `--start` (baseline).
3. Verify: `--status`, `/v1/models`, KV pool ~8.2-8.8 GiB / ~1.15-1.22M
   tokens, one smoke chat, one small probe, `:8004` proxy healthy,
   pdf2md/trading/lexdata untouched.
4. Capture full failure logs BEFORE recovery wherever possible.

## 7. Final verification (UNCONDITIONAL; adopt or restore)

If adopted: verify final state = baseline + exactly the intended diff set
(diff every touched file vs its ORIGINAL pre-A0 backup; the only hunks
allowed: compose L64 passthrough, the one `--kv-transfer-config` command line
in both compose files, `PYTORCH_CUDA_ALLOC_CONF=`/`KV_OFFLOAD_CPU_BYTES=`
lines in common.env, two jq conjuncts in run-vllm-acceptance.sh). Record
run ID, KV pool lines, `free -g`, metrics snapshot, one smoke chat + small
probe, `:8004` proxy + protected services healthy. If restored: Section 6
step 3 checks, diffs vs backups all empty.

## 8. Report format

report.md with: executive verdict per arm (PASS/FAIL + the one number);
A0 vs baseline KV pool and perf deltas; A1 offload-hit table (cold latency,
flooded re-query latency, cached_tokens, answers verbatim, 60K + 254K);
soak event counts + memory watermark min/max per host + kv_offload metric
curve; C1-C5 matrix; timeline of every stop/start with run IDs; all backup
paths; deviations from plan; final-state diff evidence. Also return a chat
summary. The lead session (not the executor) updates
`planning/03-core/03-operations-runbook.md`, syncs the local repo compose
mirrors, and records the Outcome.

## 9. Phase B pointer (committed, separate campaign)

Custom per-rank NVMe `OffloadingSpec` via `spec_module_path`
(`$VLLM/v1/kv_offload/factory.py:44-49`), worker-side medium handler
dispatched by `(src_medium,dst_medium)`, file IO per rank on its own NVMe
(gb10 1.3T free, gb10-2 649G free), shipped through
`planning/01-raw/upstream-dspark/` overlay + `build-dspark-vllm-runtime.sh`
rebuild (new fingerprint -> update run-vllm-service.sh asserts + active.json
contract). A1's `vllm:kv_offload_*` soak curve calibrates tier sizing and
store thresholds. DRAM tier then shrinks to a hot tier above disk.
