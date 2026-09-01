# Phase B NVMe Tier Development (2026-09-02)

Status: **D1 complete** (package + logic tests 30/30 + IO micro-bench);
D2/D3/D4 pending windows. Design:
`2026-08-31-kv-offload-phase-b-nvme-design.md` (Rev 1 + Rev 2 staging-ring
amendment + Rev 3 R3.1/R3.2 note — the R3.2 vendored-tree evaluation is
superseded by the Rev 7 verdict in
`2026-09-01-d1a-vendored-subtree-execution.md`: the vendored route is
blocked at fork-core invariants, so the custom spec targets the FORK-native
API as Rev 1 designed).

## Route recap (why fork-native)

- D1b (vendored tip subtree, boots 1-8): six seams deep, final blocker is
  the fork `KVBlockZeroer` uniform-page invariant vs tip per-group layout —
  not shim-able safely (cross-request KV leakage risk). Route closed.
- D0-lite (fork stack + `PYTHONHASHSEED=0`): A1's zero-hit kill DISSOLVES
  (canary 18,176 cached / 0.67 s). Store-side ~9× offers persist but are a
  manager-side repeat-offer behavior — absorbed by our manager's dedupe.
- Therefore: fork stack + custom spec (this package) + PYTHONHASHSEED=0.

## Deliverable (D1): `execution/kv-offload-phase-b/vllm_nvme_tier/`

| File | Role |
| --- | --- |
| `spec.py` | `NVMeTieredOffloadingSpec(OffloadingSpec)` — mounts via factory `spec_module_path`; cluster byte budget split per rank like `cpu_bytes_to_use`; ring sizing from per-group unpadded block bytes (max group → slot count, min 8); PYTHONHASHSEED=0 hard-guard; cold-start rank-dir wipe + config fingerprint (FileMapper) |
| `manager.py` | `NVMeTierManager(OffloadingManager)` — single-tier disk key table (Rev 2: ring is transport, never a hit source); ring-slot pool shared by stores/loads with `prepare_store -> None` re-offer backpressure and adaptive lookup floor; LRU byte-budget eviction with load/store pinning; store_threshold counter; offloading events |
| `gpu_worker.py` | `NVMeOffloadingHandler(OffloadingHandler)` — both directions on one handler; reuses fork `compute_sub_block_ptrs` (factor=1) for GPU↔ring; ring = per-tensor pinned `(num_slots, page)`; file IO = module-level `write_key_file`/`read_key_file` (24 B header KVNV|ver|group|len|crc32|rsvd, atomic tmp+rename+fsync, exists-check dedupe, crc verified on EVERY read, buffered + POSIX_FADV_DONTNEED — O_DIRECT rejected for unaligned 1,168 B SWA pages); loads thread-issued pipelined (file→ring then ring→GPU on one serialized stream, chain-lock guarded); DualQueueThreadPool (load priority); mtime-based physical GC at 1.1× budget + tmp litter cleanup |
| `specs.py` | `NVMeLoadStoreSpec(BlockIDsLoadStoreSpec)` — medium `NVME_TIER`; block_ids = ring slots, keys = content keys, 1:1 per group with the paired GPULoadStoreSpec (connector contract: `_build_store_jobs` filters src blocks to keys_to_store; factor-1 alignment) |
| `test_logic.py` | 30 checks, all passing in a throwaway container of the production image (no GPU): manager state machine, failure/reset, slot backpressure, budget eviction + pinning, store_threshold, file round-trip/corruption/truncation/dedupe, tensor-segment dedupe |

Key contract notes (verified against the fork source in
`tmp/phase-b-fork-ref/`):

- `kv_cache_tensors` sizing: the fork's own CPU spec sums per-tensor sizes
  (independently confirming the D1b 2.0i shim semantics).
- The connector's store path re-offers blocks when `prepare_store` returns
  None WITHOUT advancing `next_stored_block_idx` — that IS the Rev 2
  ring-full backpressure, no new mechanism needed.
- `offloading/worker.py get_finished` asserts `success` ("we currently do
  not support job failures") — the ~50-line load-failure→recompute plumbing
  diff (design doc Section 3) is still REQUIRED before the campaign; without
  it a corrupt/missing tier file crashes the worker instead of degrading to
  cold recompute.

## Micro-bench (gb10 NVMe, in-container, buffered + per-file fsync)

- store: 1000 × 149,504 B files → **137 MiB/s (961 files/s)**; steady-state
  store demand is 12-15 MB/s/rank → ~9× headroom single-threaded.
- load: **437 MiB/s (3,062 files/s)** single-threaded; 400K-token reload
  (≈2.2 GiB rank-local) ≈ 5 s single-thread, ~2 s across 4 prioritized
  threads — inside the ≤30 s campaign gate with margin.
- (Rev 1 raw disk: 4.2/5.6 GB/s sequential — the fsync-per-file cost is the
  real constraint and it still clears every budget. B-R4 batching knob
  `gpu_blocks_per_file` remains available if soak shows SWA tiny-file
  pressure.)

## Deployment shape (campaign prep, D3)

- Package ships out-of-tree first: `-v <dir>:/opt/kv-tier -e PYTHONPATH=`
  (factory imports `vllm_nvme_tier.spec`); bake into the image only at
  adoption time.
- Compose KV line (both files, both hosts):
  `--kv-transfer-config '{"kv_connector":"OffloadingConnector","kv_role":"kv_both","kv_load_failure_policy":"recompute","kv_connector_extra_config":{"spec_name":"NVMeTieredOffloadingSpec","spec_module_path":"vllm_nvme_tier.spec","nvme_bytes_to_use":${KV_OFFLOAD_NVME_BYTES:-137438953472},"nvme_root_dir":"/kv-offload","staging_ring_bytes":536870912}}'`
- env (both hosts): `PYTHONHASHSEED=0` (required — spec enforces),
  `KV_OFFLOAD_NVME_BYTES=137438953472`, per-host `KV_OFFLOAD_DIR` volume
  binding to the rank-local NVMe path.
- acceptance jq conjuncts: `contains("NVMeTieredOffloadingSpec")`,
  `contains("recompute")`.

## Remaining before the B-campaign (D2/D3)

1. GPU-path round-trip test (store→file→load with real CUDA tensors in a
   `--gpus` throwaway container — idle-window only, never beside
   production).
2. The connector failure-plumbing overlay diff (load-fail → recompute;
   design Section 3) + its fault-injection test.
3. Campaign runbook (B0 image-parity-free boot since NO image change
   needed; B1 gates per design Section 8 + Rev 2 amendments: flood ≥1.5M
   fresh tokens, amplification ≤1.3× at the metric level, TTFT ≤30 s,
   fault-injection, soak with iostat + page-cache watch).
4. Store-side 9× root-cause (D0-events window) — optional for Phase B
   correctness (manager dedupe absorbs it) but needed to interpret the
   amplification gate honestly.
