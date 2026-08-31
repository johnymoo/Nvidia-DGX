# KV Offload Phase B Design: Per-Rank NVMe Tier via Custom OffloadingSpec (2026-08-31)

Status: draft design, pending Phase A calibration. All code citations verified
read-only in the live container on 2026-08-31 (22:15-23:30 local, before the
Phase A window). `$VLLM` = `/opt/env/lib/python3.12/site-packages/vllm` inside
`gb10-deepseek-v4-vllm-dspark-1`. Facts in
`2026-08-31-kv-offload-phase-a-plan.md` Section 1 take precedence on conflict.

## Conclusions first

- Build `NVMeTieredOffloadingSpec`: a two-tier (DRAM hot + NVMe backing)
  OffloadingSpec mounted through the fork's own extension seam
  (`$VLLM/v1/kv_offload/factory.py:40-49`: `spec_name` looked up in the
  registry, else `spec_module_path` is imported and `getattr(module,
  spec_name)` is instantiated as `spec_cls(config, kv_cache_config)`).
  No connector change of identity: still `OffloadingConnector`, so every
  V4/HMA/MTP/async property proven in Phase A carries over.
- Core idea that removes the hard problems: **write-through to NVMe with the
  DRAM tier as an inclusive cache**. Every offloaded block is persisted to the
  rank-local disk as part of its (already asynchronous, already deferred)
  store job; DRAM eviction then becomes a metadata-only operation and needs NO
  demotion transfer, which is exactly the coordination the framework cannot
  express (scheduler cannot initiate worker transfers outside request jobs).
- File IO runs ONLY in each rank's worker process against its own NVMe,
  dispatched by the framework's `(src_medium, dst_medium)` handler table
  (`$VLLM/v1/kv_offload/worker/worker.py:100-117`). The scheduler-side manager
  is pure metadata. This is precisely how we avoid the two disqualifying flaws
  of the in-image `TieringOffloadingSpec` (secondary-tier IO in the scheduler
  process, `tiering/base.py` ~57-59; single-group assert, `tiering/spec.py`
  ~113).
- Big reuse discovery: the image already ships `$VLLM/v1/kv_offload/
  file_mapper.py` — a per-rank, config-fingerprinted `OffloadKey -> file path`
  mapper (`<root>/<model>_<sha12>_r<rank>/<hhh>/<hh>_g<group>/<hash>.bin`) —
  plus reusable atomic file IO (`tiering/fs/io.py`: temp+rename, exists-check
  dedupe) and a load-prioritized `DualQueueThreadPool`
  (`tiering/fs/thread_pool.py:50`). Phase B reuses all three, cutting new code
  to ~770 lines.
- Failure semantics: `kv_load_failure_policy: "recompute"` exists in the fork
  (`$VLLM/config/kv_transfer.py:70`, `Literal["recompute","fail"]`) with full
  scheduler support (`$VLLM/v1/core/sched/scheduler.py:132-135, 1313-1318,
  2200-2345`) and runner plumbing
  (`kv_connector_model_runner_mixin.py:112` reads
  `kv_connector.get_block_ids_with_load_errors()`). The OffloadingConnector
  does NOT yet implement that hook and its worker asserts transfer success
  ("we currently do not support job failures",
  `$VLLM/distributed/kv_transfer/kv_connector/v1/offloading/worker.py`
  get_finished, assert at ~273). A small overlay diff (~50 lines) closes this
  gap so a corrupt/missing disk block degrades to cold recompute instead of
  crashing.
- Measured tonight (read-only `dd iflag=direct bs=16M`, 1.5 GiB):
  gb10 NVMe (ESL04TBTLCZ 4T) 4.2 GB/s, gb10-2 (ESL02TBTLCZ 2T) 5.6 GB/s
  sequential read; kernel 6.17.0-1014-nvidia both. A 400K-token reload
  (~2.9 GiB/rank) reads in <1 s per rank; end-to-end NVMe-hit TTFT budget is
  single-digit seconds vs ~155-300 s cold recompute.
- Estimate: ~770 new/changed overlay lines + ~300 lines of standalone logic
  tests; 3 dev days + 1 campaign day (arms B0 image-parity, B1 NVMe tier).

## 1. Architecture: scheduler/worker split

### Components

| Piece | Process | Role |
| --- | --- | --- |
| `NVMeTieredOffloadingSpec(OffloadingSpec)` | both (role-dependent) | config parsing, sizing, wiring (`base.py:337+` gives `gpu_block_size` per group, `hash_block_size`, `extra_config`) |
| `NVMeTieredManager(OffloadingManager)` | scheduler only | metadata: one key table `OffloadKey -> {on_disk: bool, dram_row: int|None, protect_cnt, lru}`; LRU for DRAM rows and for disk capacity; NO file IO |
| `NVMeGpuHandlers` | worker only (per rank) | the only place that opens files; GPU<->pinned-DRAM copies reuse the CPU tier's stream/`swap_blocks_batch` machinery (`cpu/gpu_worker.py` ~415-436 style pinned per-canonical-tensor buffers); disk IO on a `DualQueueThreadPool` |
| worker GC thread | worker only | enforces the physical per-rank disk budget by mtime, decoupled from scheduler LRU (see 5/6) |

The connector calls `spec.get_manager()` only on the scheduler side and
`spec.get_handlers(kv_caches)` only on the worker side (abstract contract in
`$VLLM/v1/kv_offload/base.py:370-411`; `CPUOffloadingSpec` demonstrates the
split, `cpu/spec.py:62-103`). Files are opened lazily inside
`get_handlers`, so the scheduler process never touches the tier directory.
This is the structural answer to the TieringOffloadingSpec rejection: on our
2-node TP=2, rank0's files live on gb10's NVMe and rank1's on gb10-2's, each
accessed exclusively by the local worker.

### Mediums and handler registration

`get_handlers` yields exactly two entries (same shape as
`cpu/spec.py:96-103`):

- `(GPULoadStoreSpec, NVMeTierSpec, store_handler)`
- `(NVMeTierSpec, GPULoadStoreSpec, load_handler)`

`NVMeTierSpec.medium() == "NVME_TIER"` — a fresh medium string, so the
`OffloadingWorker.register_handler` uniqueness assert
(`worker/worker.py:113`) cannot collide with the stock "CPU" medium, and the
stock CPU handlers are simply not registered.

### Two-tier flow (write-through, inclusive DRAM)

- Store job (one per new-block batch, built by the connector as today):
  stage 1 GPU -> pinned DRAM rows (per-transfer CUDA stream + event +
  `ops.swap_blocks_batch`, identical to the CPU tier); stage 2 on event
  completion, enqueue per-key file writes (atomic temp+rename via
  `tiering/fs/io.py::store_block` pattern, buffered mode) + crc header +
  `fdatasync`. The job's `TransferResult` is emitted only when BOTH stages
  finish, so `complete_store` (=> block loadable, `base.py:196+`) implies
  persisted-on-disk. Deferral to next step start is inherited unchanged
  (NOTE(orozery), `offloading/worker.py` ~251-257).
- DRAM eviction: metadata-only (row freed; disk copy remains). No transfer.
- Load job (one per request, as today): for keys with a valid `dram_row`,
  serve straight from the row; for disk-only keys, `preadv` the file into a
  freshly allocated pinned row (promotion — re-warms the hot tier), verify
  crc, then one batched `swap_blocks_batch` of all rows -> GPU; complete on
  the CUDA event. The request waits in `WAITING_FOR_REMOTE_KVS` as in Phase A.
- Backpressure: if the manager cannot allocate promotion rows (all rows
  load-protected), `lookup()` returns `None`, which the framework defines as
  "retry later" and delays scheduling (`base.py:113-129`). No new mechanism
  needed.
- Disk capacity: scheduler LRU drops key metadata when
  `nvme_bytes_to_use` blocks are exceeded (emitting `OffloadingEvent
  removed=True`); physical unlink happens in the worker GC. Because keys are
  content-addressed (block hash), a stale not-yet-unlinked file that gets
  re-stored is byte-identical, and `store_block`'s exists-check dedupe
  (`fs/io.py:42-44`) makes the re-store free. The reverse race (GC deleted a
  tracked file) is absorbed by the recompute failure policy.

## 2. Multi-group / heterogeneous-layer compatibility

- We never set `kv_connector_extra_config.block_size`, so
  `block_size_factor` stays 1 and the single-group assert path in
  `$VLLM/v1/kv_offload/base.py:352-365` is never entered (verified: the
  assert only executes when `block_size` is supplied). Offloaded block =
  GPU block = 256 tokens per group.
- Group identity is carried in the key itself: `OffloadKey = block_hash +
  group_idx` (`base.py:26-44`), and `GPULoadStoreSpec` natively describes
  multi-group batches via `group_sizes` + `block_indices`
  (`base.py:246-283`). Our specs are `BlockIDsLoadStoreSpec` subclasses that
  additionally carry the ordered `OffloadKey` list, so each worker derives
  file paths locally through its own rank-scoped `FileMapper`
  (`file_mapper.py::get_file_name`).
- Heterogeneous per-layer page sizes (37,376 B MLA pages vs 1,168 B SWA
  pages across 43 layers) are already resolved before bytes reach us: the
  worker receives `CanonicalKVCaches` — unique `(num_blocks, ...)` tensors
  with per-tensor `page_size_bytes` plus per-group `CanonicalKVCacheRef`s
  recording each layer's UNPADDED `real` page size (`base.py:286-330`); the
  pinned rows are allocated per canonical tensor exactly as the CPU tier does
  (`cpu/gpu_worker.py` ~415-436). The file payload for one key is simply the
  concatenation of that block's unpadded per-layer pages for the key's group,
  sliced out of the pinned row — layout is fully determined by
  `group_data_refs`, no new geometry code.
- Medium graph (every edge's handler + layout):

| Edge | Handler | Data layout |
| --- | --- | --- |
| GPU -> DRAM | store stage 1 (reused CPU-tier stream/`swap_blocks_batch` path) | pinned per-canonical-tensor rows, padded page stride |
| DRAM -> NVMe | store stage 2 (thread pool `pwritev`) | per-key file: 24 B header + concatenated unpadded pages of the key's group |
| NVMe -> DRAM | load stage 1 (thread pool `preadv` + crc verify) | file -> promotion row (unpadded -> padded re-strided during row fill) |
| DRAM -> GPU | load stage 2 (batched `swap_blocks_batch`) | rows -> GPU blocks |

GPU<->NVMe never exists as a direct edge; on Grace unified LPDDR5x the extra
DRAM hop costs microseconds and buys promotion-into-hot-tier for free.

## 3. Interaction with existing features (why nothing breaks)

- **async-scheduling**: all accommodation lives in the connector scheduler
  layer we do not touch ("with async scheduling, some tokens may be missing",
  `offloading/scheduler.py` ~683; loads via `get_num_new_matched_tokens`
  ~498-541 returning `(hits, True)`). The spec/manager/handler API sits below
  that layer; we only change WHERE bytes rest, not when jobs are created.
- **MTP deferred finalize** (`gpu_model_runner.py:4403,4420` sets
  `defer_kv_connector_finalize=True`): store submission is already deferred
  to the next step start (`offloading/worker.py` ~251-257) and our disk stage
  runs on a thread pool completely off the GPU stream, so token-sampling
  latency is untouched. The only observable change is that store jobs
  complete later (after persist), which lengthens the existing
  `jobs_to_flush` block-reuse fence — bounded by write throughput (Section 4:
  worst-case burst ~63 MB/rank/step vs GB/s-class writes) and gated in the
  campaign perf arm.
- **2-node TP completion aggregation**: unchanged —
  `OffloadingWorkerMetadata.aggregate()` still sums per-worker completions
  with `pending_count = num_workers` (`offloading/common.py`); both ranks
  execute every job symmetrically on their own local files, so an asymmetric
  disk merely delays the aggregate completion instant, never correctness.
  Rank-scoped paths (`_r{rank}`, `file_mapper.py`) make cross-rank collision
  impossible even if a shared filesystem were ever mounted.
- **Load-failure recompute** (the one place we DO touch the connector):
  overlay diff replaces the load-side `assert transfer_result.success`
  (`offloading/worker.py` get_finished ~273) with: mark the failed job's
  request + collect its GPU block ids; implement
  `get_block_ids_with_load_errors()` (base default at
  `kv_connector/v1/base.py:375`) on the worker connector; extend
  `OffloadingWorkerMetadata` with a `failed_jobs` field (union on aggregate)
  so the scheduler side calls `complete_store(success=False)` for failed
  stores. Downstream is all pre-existing fork code:
  `kv_connector_model_runner_mixin.py:112` -> `KVConnectorOutput.
  invalid_block_ids` -> `scheduler.py:1313-1318` -> `_handle_invalid_blocks`
  recompute path (`scheduler.py:2200-2345`), enabled by
  `"kv_load_failure_policy": "recompute"` (`config/kv_transfer.py:70`).

## 4. IO path and throughput budget

- **Primitives**: `os.preadv`/`os.pwritev` into `memoryview`s of the pinned
  rows (verified available in the container Python; no gcc in the image, so
  no compiled helpers). Thread pool = reuse `DualQueueThreadPool`
  (`tiering/fs/thread_pool.py:50`, loads strictly prioritized over stores),
  4 threads initial. `io_uring` rejected for v1 (kernel 6.17 supports it but
  the image has no binding and no compiler); `O_DIRECT` rejected for v1
  (unpadded 1,168 B SWA pages break 512 B/4 KiB alignment; would force bounce
  buffers). Instead: buffered IO + `os.posix_fadvise(POSIX_FADV_DONTNEED)`
  after every read/write (verified available) to stop page-cache growth on
  these zero-headroom unified-memory hosts.
- **Write budget**: sustained prefill 1600-1900 tok/s x 7.7 KB/token/rank ≈
  12-15 MB/s/rank steady; worst single-step burst ≈ 32 blocks x ~2 MB/rank ≈
  63 MB/rank. Both are noise against a GB/s-class NVMe; `fdatasync` per file
  at ~34K files per 8.7M tokens is the dominant cost and is measured in the
  D3 micro-bench.
- **Read budget (the point of Phase B)**: 254K-token session ≈ 1.9 GiB/rank,
  400K ≈ 2.9 GiB/rank. Measured sequential O_DIRECT read: 4.2 GB/s (gb10) /
  5.6 GB/s (gb10-2); assume 50% effectiveness for sharded-file buffered reads
  => ~1-1.5 s read. crc32 verify (zlib, no xxhash in image — verified) at
  ~1.5-2 GB/s/thread across 4 threads => <1 s. `swap_blocks_batch` H2D on
  unified memory: negligible. **End-to-end NVMe-hit TTFT estimate: ~3-8 s for
  a 400K reload vs ~155 s cold at 254K / 4-5 min at 400K.** Campaign gate set
  at <= 30 s (aligned with A1's DRAM gate) with single-digit expectation.
- **No separate staging ring in v1**: promotion writes land directly in
  pinned DRAM rows (they ARE the staging), with `lookup() -> None`
  backpressure when rows are exhausted. A dedicated few-hundred-MB pinned
  ring is documented as the fallback if row contention appears in soak.

## 5. Capacity / eviction / threshold parameters

`[A1-cal]` = to be filled from tonight's A1 soak curves
(`vllm:kv_offload_total_bytes`, `..._total_time`, `..._size`,
`offloading/metrics.py:106,112,118`) and the eviction-event pattern.

| Parameter | Initial value | Basis / calibration |
| --- | --- | --- |
| `cpu_bytes_to_use` (`KV_OFFLOAD_CPU_BYTES`) | 8589934592 (A1 value; 4 GiB pinned/host) | `[A1-cal]` whether to SHRINK to 6 GiB once NVMe absorbs capacity misses — decide from A1 `kv_offload_size` plateau + hit latency mix |
| `nvme_bytes_to_use` (`KV_OFFLOAD_NVME_BYTES`) | 137438953472 (128 GiB cluster = 64 GiB/rank ≈ 8.7M tokens ≈ 7x GPU pool; disk free 1.3T / 649G) | `[A1-cal]` size from 24-48 h `total_bytes` growth; hard cap: keep < 200 GiB/rank for gb10-2 headroom |
| `nvme_root_dir` | `/kv-offload` (container path) | fixed |
| `eviction_policy` (DRAM rows) | `lru` | `[A1-cal]` A1 runs lru; switch to `arc` only with evidence |
| disk-tier eviction | LRU over key metadata | fixed v1 |
| `store_threshold` | 0 (store everything) | `[A1-cal]` raise to >=2 only if A1 shows store churn (steep `total_bytes` slope with low re-hit) |
| `max_tracker_size` | 262144 (default 64_000 is below the 128 GiB tier's ~34K keys/group x groups x safety) | `[A1-cal]` confirm against observed key counts |
| `gpu_blocks_per_file` (`FileMapper`) | 1 | `[dev-bench]` batch SWA-group blocks if the file-size histogram shows dominant tiny files |
| io threads | 4 | `[dev-bench]` D3 micro-bench |
| GC physical watermark / interval | 1.10 x logical budget / 60 s | fixed v1 |
| `fdatasync` per file | on | `[dev-bench]` relax to batched sync only if store-fence latency shows |
| `kv_load_failure_policy` | `"recompute"` | fixed (top-level KVTransferConfig field, not extra_config) |

## 6. Data integrity

- **Per-file header (24 B)**: magic `KVNV`, version u16, group_idx u16,
  payload_len u64, crc32 u32 (zlib), 4 B reserved. crc computed over the
  payload at store time; verified on EVERY read before the row is swapped to
  GPU. xxhash is not in the image (verified `ModuleNotFoundError`); crc32 is
  adequate for media/torn-write detection at these sizes.
- **Atomic writes**: temp-file + `os.replace` rename, exists-check dedupe —
  the exact `tiering/fs/io.py::store_block` pattern (buffered mode). A crash
  mid-write leaves only `.tmp` litter, never a half-valid `.bin`.
- **Startup residue**: v1 is cold-start-clean — at `get_handlers` time each
  worker wipes its own `<base>_r{rank}` subtree (and stray `.tmp` files).
  Reuse across restarts would be unsound anyway because the manager's key
  table lives only in scheduler memory. Config drift is additionally
  fire-walled by `FileMapper`'s base-path fingerprint (sha256 over
  model/dtype/tp/pp/hash_block_size/kv_cache_groups,
  `file_mapper.py::_compute_base_path`) — a changed config simply lands in a
  different directory. Warm-restart metadata persistence is a Phase B+1
  option, out of scope.
- **Load-failure semantics**: ENOENT / short read / crc mismatch =>
  the job reports failure => `invalid_block_ids` => scheduler recompute
  (Section 3). Fail-fast to cold compute; unverified bytes are never served.
  Store-failure (e.g. ENOSPC) => `complete_store(success=False)` => the block
  is simply not offloaded; the service continues.

## 7. Delivery pipeline

New overlay files under `planning/01-raw/upstream-dspark/recipe/overlay/vllm/`
(mirroring `$VLLM` paths), estimated lines:

| File | Est. lines | Content |
| --- | --- | --- |
| `vllm/v1/kv_offload/nvme/__init__.py` | ~5 | package |
| `vllm/v1/kv_offload/nvme/specs.py` | ~40 | `NVMeTierSpec` (medium "NVME_TIER", block rows + OffloadKeys) |
| `vllm/v1/kv_offload/nvme/manager.py` | ~260 | two-tier metadata manager (patterned on `cpu/manager.py`, 240 lines) |
| `vllm/v1/kv_offload/nvme/gpu_worker.py` | ~280 | handlers (reuse CPU-tier stream machinery, `fs/io.py`, `DualQueueThreadPool`), GC thread, header/crc |
| `vllm/v1/kv_offload/nvme/spec.py` | ~120 | `NVMeTieredOffloadingSpec` (sizing incl. cluster-wide byte semantics copied from `cpu/spec.py:33-38`, `FileMapper.from_offloading_spec`) |
| MODIFY `.../kv_connector/v1/offloading/worker.py` | ~+30 | load-failure path replacing the success assert; `get_block_ids_with_load_errors` |
| MODIFY `.../kv_connector/v1/offloading/common.py` | ~+10 | `failed_jobs` in worker metadata + aggregate |
| MODIFY `.../kv_connector/v1/offloading_connector.py` | ~+10 | plumb the new hook |
| Total | ~755 | + ~300 lines standalone manager logic tests |

Build & contract sync (all pre-existing mechanisms):

1. Rebuild via `build-dspark-vllm-runtime.sh` (head local build + rsync
   worker build); new image tag `gb10-ds4-vllm:<newrev>-nvfp4`.
2. Update the hardcoded fingerprint asserts at `run-vllm-service.sh:194-195`
   and the `active.json` contract to the new revision.
3. Compose (BOTH `docker-compose.yml` and `docker-compose.thinking-on.yml` —
   the override replaces the whole `command:`, double-write mandatory):
   - `volumes:` add `- ${KV_OFFLOAD_DIR:?set KV_OFFLOAD_DIR}:/kv-offload`
     (precedent: `${CACHE_ROOT:?...}:/cache/huggingface`, compose L20-22).
   - Replace the Phase A `--kv-transfer-config` line with:

     ```
     --kv-transfer-config '{"kv_connector":"OffloadingConnector","kv_role":"kv_both","kv_load_failure_policy":"recompute","kv_connector_extra_config":{"spec_name":"NVMeTieredOffloadingSpec","spec_module_path":"vllm.v1.kv_offload.nvme.spec","cpu_bytes_to_use":${KV_OFFLOAD_CPU_BYTES:-8589934592},"nvme_bytes_to_use":${KV_OFFLOAD_NVME_BYTES:-137438953472},"nvme_root_dir":"/kv-offload"}}'
     ```

     (single-quoted JSON, compose-interpolated vars — the `--reasoning-config`
     precedent; JSON contains no single quotes.)
4. `env/common.env` per host: head `KV_OFFLOAD_DIR=/home/chriswang/
   kv-offload-tier`, worker `KV_OFFLOAD_DIR=/home/admin/kv-offload-tier`;
   both: `KV_OFFLOAD_NVME_BYTES=137438953472`.
5. `run-vllm-acceptance.sh` `assert_rendered_config`: add conjuncts
   `contains("NVMeTieredOffloadingSpec")` and `contains("recompute")`.

## 8. Test campaign skeleton (08-24 / Phase A template)

Same hard constraints, evidence layout (`tmp/followup-tests/<UTC>/`), backup
(`.bak-<UTC>`), drain/stop/settle >= 3 min/boot 13-16 min discipline, 7 h
budget, Section-7-style unconditional final verification.

- **Arm B0 — image parity** (new image, config UNCHANGED from adopted A1,
  i.e. still CPUOffloadingSpec): boot gate (KV pool >= 7.3 GiB floor, journal
  clean, connector init), first-traffic (small + 18300 + 37000 fresh-seed
  probes), perf spot +-10% vs A1, C1-C5 smoke. Isolates rebuild drift from
  the new tier. FAIL => revert image tag, stop.
- **Arm B1 — NVMe tier on** (spec switch + volume + env): gates in order:
  1. Boot: tier directory populated with the fingerprinted base path on both
     hosts; pinned watermark unchanged vs A1 (`free -g` floors gb10 >= 4Gi);
     KV floor; journal.
  2. First traffic as B0.
  3. DRAM-hit correctness: re-run A1's kill-arm gate unchanged (17000-word
     seed-90001 needle, flood >= 1.3M, re-query: identical AURORA-73-KESTREL
     answer, `cached_tokens > 0`, <= 15 s).
  4. **NVMe-hit correctness (kill-arm)**: needle -> flood >= 2.6M fresh
     tokens (> GPU 1.2M + DRAM ~0.5M + margin, forcing the needle out of BOTH
     upper tiers) -> re-query: identical answer, `cached_tokens > 0`,
     TTFT <= 30 s (expect <= 10 s), plus evidence the hit was served from
     disk (kv_offload transfer-type stats / handler log line). 254K variant
     likewise. Any wrong answer = corruption = kill arm + rollback.
  5. **Recompute-fallback fault injection**: truncate ONE tier `.bin` of the
     needle on gb10 (tier files are campaign artifacts, not production
     files), re-query: correct answer via recompute (slow is fine), log
     evidence of `invalid_block_ids`/load-failure, NO crash, service healthy
     after. This is the only gate exercising the new failure plumbing.
  6. Soak >= 40 min (A1 driver) adding `iostat -x` sampling and page-cache
     watch; `free -g` floors at every sample; journal + docker-log scans;
     `vllm:kv_offload_*` curve capture.
  7. Perf +-10% vs A1's own numbers (isolates tier overhead); HOL <= ~15 s;
     C1-C5.
- **Rollback**: revert compose image tag + config to the adopted A1 state
  from `.bak`s (old image retained on both hosts — record `docker image ls`
  before starting), baseline start, A1 boot-gate re-verify. Tier directories
  are inert data; removal is post-campaign cleanup, not rollback-critical.

## 9. Risk register

| # | Risk | Detection | Mitigation |
| --- | --- | --- | --- |
| B-R1 | Image rebuild drift (unrelated fork delta / fingerprint mismatch) | B0 arm boot/perf gates | keep old image; revert tag; fix contract offline |
| B-R2 | Page-cache growth from buffered IO on zero-headroom hosts | soak `free -g` floor breach | `posix_fadvise(DONTNEED)` after IO (in v1); fallback O_DIRECT+bounce alignment |
| B-R3 | Store-persist latency lengthens `jobs_to_flush` GPU-block-reuse fence under heavy prefill | B1 perf gate prefill tok/s regression | measured burst is ~63 MB/rank/step; fallback: two-phase `complete_store` (loadable-from-DRAM before persisted) — documented design variant |
| B-R4 | SWA-group tiny files (metadata/fsync overhead) | D3 micro-bench file-size histogram; store `total_time` metric | `gpu_blocks_per_file > 1` batching in `FileMapper` (built-in param) |
| B-R5 | GC vs scheduler-LRU divergence unlinks a tracked file | load-failure log + recompute events | 1.10x watermark margin; recompute policy absorbs; content-addressed re-store is free |
| B-R6 | Bug in NEW failure plumbing (the only connector-code change) | B1 gate 5 fault injection | small diff (~50 lines), exercised before adoption; fail-closed default is crash-visible not silent |
| B-R7 | crc32 CPU cost inflates reload TTFT | gate 4 TTFT; D3 bench | 4 threads bound the cost (<1 s per 2.9 GiB); header-only verify as degraded mode is REJECTED (integrity first) |
| B-R8 | ENOSPC / disk pressure | preflight `df` gate; store-failure counters | budget 64 GiB/rank << 649G-1.3T free; ENOSPC => block not offloaded, service continues |
| B-R9 | Stale tier dirs from crashed runs accumulate | boot wipe log line; `du` in soak | cold-start wipe of `_r{rank}` subtree at `get_handlers`; GC also removes `.tmp` litter |

## 10. Development schedule (2-3 dev days + 1 campaign day)

- **D1** (~1 d): `nvme/manager.py` + `specs.py` + `spec.py`; standalone logic
  tests (no GPU needed): key table, two-tier LRU, promotion-row backpressure
  (`lookup -> None`), disk-capacity eviction events, store/load state
  machine. Run in a THROWAWAY container (`docker run --rm` on the existing
  image with the overlay bind-mounted) — never the production container.
- **D2** (~1 d): `nvme/gpu_worker.py` (handlers, GC, header/crc) + the ~50
  line connector failure-plumbing diff; import smoke + CPU-path unit runs in
  the throwaway container; file-IO micro-bench on a tier dir on gb10's NVMe
  (read/write/fsync profile, io-thread count, file-size histogram from a
  recorded A1 block-size distribution).
- **D3** (~0.5-1 d): image build both hosts via `build-dspark-vllm-runtime.sh`;
  fingerprint + `active.json` contract sync; pre-stage all compose/env/
  acceptance edits + `.bak` commands; write the B-campaign runbook doc
  (02-working) with the Section 8 gates fully scripted.
- **D4** (1 d): campaign window B0 -> B1 (~5-6 h + report), lead reviews for
  adoption; lead session updates `planning/03-core/03-operations-runbook.md`
  and the repo mirrors.

No skip gate. User decision (2026-08-31, reaffirmed): Phase B proceeds
unconditionally, starting immediately after the Phase A campaign concludes.
A1's `vllm:kv_offload_*` metrics are used ONLY to calibrate the
`[A1-calibration-pending]` parameters in Section 5, never to defer or cancel
this work.

---

# Rev 2 (2026-09-01) — post-A1-campaign revision

Phase A outcome (report: `tmp/followup-tests/20260831T170721Z/report.md`):
A0 adopted (+3.6% KV pool); A1 KILLED and rolled back — 0 prefix-cache hits
across 1,084,361 queried tokens and ~13x GPU→CPU store write amplification
while the connector was enabled. A1 never reached soak, so no calibration
curves exist. This Rev overrides the sections named below; everything else in
Rev 1 stands.

## R2.1 New hard prerequisite: D0 — block-hash mismatch root-cause + fix

Root-cause analysis:
`planning/02-working/2026-09-01-kv-offload-hash-mismatch-rootcause.md`.
Proven fault class: while OffloadingConnector is registered, block-hash-keyed
identity is unstable — offload keys for the same (request, block) differ
across scheduler passes (proven by store arithmetic: 25 GB stored for 758
unique blocks ≈ 2.8 GB during A1 first-traffic, with the dedupe and
high-water guards verified intact in code), and byte-identical requeries miss
both hash tables. Phase B inherits this exact store path: unfixed, the NVMe
tier would take ~160-200 MB/s of sustained junk writes (~1.5 TB/day at
incident traffic) and NEVER hit. Therefore the schedule gains **D0 (before
D1): run the zero-code kv-events diagnostic arm (rootcause doc Section 7),
pin the faulting line, apply the fix — preferred: adopt the upstream-current
offloading stack in the Phase B image rebuild (rootcause doc Section 8 lists
8+ post-snapshot upstream fixes in this exact area); fallback: minimal
overlay patch if D0 pins a fork-local one-liner — and re-run the A1
offload-hit kill-arm gate on a DRAM config until it PASSES.** Phase B proper
does not start until that gate is green. D0 also adds `PYTHONHASHSEED=0` to
both hosts' env (deterministic NONE_HASH; NVIDIA Dynamo-documented practice
for this connector; upstream made it default in #51875).

## R2.2 Structural law — the DRAM tier is demoted to a staging ring
(overrides Rev 1 Sections 1 and 4 tier semantics)

Campaign-verified law: a same-timeline inclusive cache tier with LRU must
EXCEED the GPU pool (1.27M tokens ≈ 18.1 GiB cluster) to produce ANY hit —
the GPU prefix cache and the tier see the same insert/touch timeline, so the
smaller inclusive LRU always evicts a key before the bigger LRU does. The
Rev 1 "DRAM inclusive hot cache @ 8 GiB (~605K tokens)" therefore yields
~zero hits and is REMOVED. New design:

- **Pinned staging ring, per rank, few hundred MB** (`staging_ring_bytes`,
  default 536,870,912 = 512 MB/rank; a per-rank knob on our own spec — no
  cluster/world_size division). Fixed slots sized to the largest
  per-canonical-tensor block stride; a slot is held only for one transfer
  leg.
- **All offload hits are served from NVMe directly**: load = pipelined
  `preadv` file → ring slot (+ crc verify) → `swap_blocks_batch` ring → GPU,
  chunk k reading while chunk k-1 swaps. The ring is transport, never a hit
  source; the scheduler-side manager tracks ONLY disk residency
  (single-tier metadata — simpler than Rev 1's two-tier table; the
  `lookup() -> None` backpressure now applies to ring-slot exhaustion).
- **Stores unchanged in principle (write-through)**: GPU → ring slot →
  `pwritev` + fdatasync → slot freed; `complete_store` still fires only
  after persist. Ring full ⇒ skip this pass's store WITHOUT advancing
  `next_stored_block_idx`, so the framework re-offers it next pass
  (backpressure by deferral, no new mechanism).
- Medium graph collapses to GPU ↔ RING(transport) ↔ NVMe with the same two
  registered handlers as Rev 1 ((GPU, NVME_TIER) store, (NVME_TIER, GPU)
  load).

Revised TTFT budget (replaces Rev 1 Section 4 read budget): 400K-token
reload = 2.9 GiB/rank; pipelined pread at measured 4.2/5.6 GB/s (gb10 /
gb10-2; 50% derate for sharded buffered reads) overlapped with crc32 and H2D
on unified LPDDR5x → **still ~3-8 s end-to-end**. The removed DRAM-resident
hit path costs nothing material: on Grace the extra hop was microseconds,
and what the DRAM tier was supposed to buy (fast re-hits inside the same
timeline window) is exactly what the structural law proves it could never
deliver. Campaign gate stays <= 30 s with single-digit expectation.

## R2.3 Write budget re-check (post-D0 fix, 13x → 1x)

Steady state 1600-1900 tok/s prefill x 7.7 KB/token/rank ≈ 12-15 MB/s/rank;
worst single-pass burst ≈ 63 MB/rank absorbed by one ring-slot cycle;
fdatasync per file remains the dominant cost (D2 micro-bench). Endurance:
~1.3 TB/day at continuous incident-level traffic vs a realistic duty cycle
well under 10% → <150 GB/day, trivial for these 2-4 TB drives. New B1-arm
gate: soak `vllm:kv_offload_total_bytes` must be <= 1.3x the soak's
computed-token bytes (amplification detector — the A1 signature was ~13x, so
a regression cannot be missed).

## R2.4 Parameter table re-tag ([A1-cal] is dead — A1 never reached soak)

| Parameter | Rev 2 value | Tag |
| --- | --- | --- |
| `staging_ring_bytes` (replaces the KV_OFFLOAD_CPU_BYTES role) | 536870912 /rank | fixed; [B0-cal] may shrink to 256 MB |
| `nvme_bytes_to_use` (`KV_OFFLOAD_NVME_BYTES`) | 137438953472 (128 GiB cluster = 64 GiB/rank ≈ 8.7M tokens ≈ 6.8x GPU pool — satisfies the R2.2 law with headroom) | fixed conservative; [B0-cal] from B-campaign soak `kv_offload_*` curves |
| `store_threshold` | 0 | fixed; [B0-cal] raise to >=2 only on churn evidence |
| `max_tracker_size` | 262144 | fixed |
| `eviction_policy` (disk metadata LRU) | lru | fixed |
| `gpu_blocks_per_file` | 1 | [dev-bench D2] |
| io threads | 4 | [dev-bench D2] |
| fdatasync per file | on | [dev-bench D2] |
| GC watermark / interval | 1.10x / 60 s | fixed |
| `kv_load_failure_policy` | "recompute" | fixed |
| `PYTHONHASHSEED` | 0 (both hosts) | fixed (D0) |

A1 calibration that DID survive (valid despite the bug): GPU→CPU DMA
sustained >25 GB/s aggregate; per-job transfer sizes 200-400 MB completed
with zero failures; pinned allocation and 2-rank completion aggregation
worked. The transport layer is sound; only the key bookkeeping is broken.

## R2.5 Revised schedule (amends Section 10)

- **D0 (new, ~1 d dev + one campaign window): kv-events diagnostic arm →
  pin faulting line → fix decision (upstream-stack adoption vs one-line
  overlay) → re-run the A1 offload-hit kill-arm gate until green.** If the
  fix is the upstream-stack adoption, D0's rebase work merges into D1/D3
  image work (+1-2 d total).
- D1-D4 as Rev 1, with these amendments: the manager is now simpler
  (single-tier disk table + ring allocator, est. ~180 lines instead of
  ~260); the B1 NVMe-hit kill-arm flood is >= 1.5M fresh tokens (GPU pool
  1.27M + margin; the Rev 1 "GPU + DRAM tier" flood sizing no longer
  applies); B1 soak adds the R2.3 amplification gate.

---

# Rev 3 (2026-09-01) — post-rebase-scoping amendments

Source: `planning/02-working/2026-09-01-kv-offload-upstream-rebase-scope.md`.
The D1 rebase route is now concretely scoped (recommended and lead-approved:
vendored subtree replacement of the offloading stack at pinned upstream main
SHA `f5e441de10bd`, fork core kept, ~4 shims). Three design consequences:

## R3.1 The worker-side handler seam this design targets no longer exists
at tip

Upstream #45053 (f237e16b4, 06-24) deleted `v1/kv_offload/worker/` — the
`OffloadingHandler` / `register_handler((src_medium, dst_medium))` API that
Rev 1 Section 1 builds on (including the `worker/worker.py:113` uniqueness
assert) is gone from the stack D1 will vendor. **All custom-spec work must
target the vendored subtree at the pin, not the current in-image API.** New
mount points at `f5e441de10bd`:

- Worker side: `OffloadingWorker` (successor of OffloadingHandler; medium
  pairs remain the dispatch key) — `NVMeGpuHandlers` becomes an
  OffloadingWorker specialization.
- Scheduler side: the OffloadingManager contract gained `LookupResult`
  (replacing the bool lookup verdict, #44193), `on_schedule_end` with
  `ScheduleEndContext` (#44206/#46450), tier-owned KV events
  (`offloading/events.py`, #46544), `Medium`/`Locality` enums,
  `TierFilter`/`TierMatcher` (#48123), `has_pending_work`.
- Config boundary: `v1/kv_offload/config.py` + `offloading/config.py`
  (#48150) — sizing/extra-config parsing moves here.
- Loading seams that SURVIVE: `spec_module_path` (tip `factory.py:31-49`)
  plus a new `register_spec`; and #51007 adds out-of-tree **secondary tier
  managers** via `module_path` — a second, smaller seam: an NVMe tier can
  plug in as a secondary tier under the stock CPU/tiering spec instead of
  replacing the whole spec.
- Rev 1's line-level citations (`cpu/gpu_worker.py` ~415-436 pinned buffers,
  `base.py:337+`/`370-411`, `fs/io.py` patterns) are baseline-snapshot
  citations; re-derive them against the vendored tree at D1.

## R3.2 New D1-entry decision item: evaluate configuring the upstream
in-tree tiering/fs NVMe tier FIRST; the custom spec is demoted to fallback

Rev 1 rejected `TieringOffloadingSpec` for two reasons; both are lifted in
the upstream drift window:

- *Single-GPU-block-size-group assert (crashes multi-group V4)* → HMA models
  enabled for tiering (#44287), `blocks_per_chunk` for heterogeneous KV
  groups (#48878), attention-only hybrids certified in the canonical
  portability gate (#51689).
- *Scheduler-process IO against a per-host /dev/shm mmap (wrong on 2-node
  TP)* → canonical parallelism-agnostic per-layer page mappings + canonical
  CPU layout (#48408/#48414), TP-independent compact secondary identity
  (#49858), DP-replica-aware regions (#47987).

The fs tier also now ships capabilities the custom spec would otherwise have
to build: async batched lookup (#44193), C-accelerated batch lookup/store/
load (#46713/#49152), O_DIRECT with buffered fallback (#49734), HIT_PENDING
promotion (#51840), failed-load → lookup-miss semantics (#49328),
store_threshold counted on store offers (#52227), tier-owned self-describing
events + metrics (#47923/#48679/#48798).

**Evaluation checklist (run against the vendored tree + D1b throwaway
boot):**

1. Per-rank IO semantics under our 2-node TP=2: where does fs-tier file IO
   execute at tip (per-rank worker vs scheduler process); can each rank be
   pointed at its local NVMe path; does the canonical layout make shards
   rank-local or does it assume shared storage.
2. nvfp4_ds_mla pages: inline per-token-head scale transfer width (#48411)
   vs the fork's `*584`/`*416` page-size lines in `kv_cache_interface.py`
   (shim 2 of the scoping doc); `set_` overflow fix for packed non-uniform
   pages (#48530) present at the pin.
3. Capacity/eviction coverage: can the fs tier express the R2.4 parameters —
   64 GiB/rank cap, LRU (or CachePolicyFactory policy, #49114), the R2.2
   "tier must exceed the 1.27M-token GPU pool" law, GC observability.
4. Failure semantics: equivalent of `kv_load_failure_policy="recompute"` —
   #49328 marks failed loads as misses at the manager; confirm no
   livelock/crash on injected IO error; O_DIRECT fallback behavior on ext4.
5. Staging path: the fs tier stages through the CPU region
   (SharedOffloadRegion, #50094); can that region be sized down to the R2.2
   staging-ring budget (~512 MB/rank) instead of a full DRAM tier, and does
   dedupe of replicated MLA KV (#48906) apply to our layout.

If items 1-4 pass, **Phase B custom code collapses to configuration +
validation** (near-zero new code) and Rev 1 Sections 1-7 become the fallback
design, re-targeted per R3.1. If the fs tier fails the checklist, the custom
spec proceeds on the new API, considering the #51007 secondary-tier seam
before a whole-spec replacement.

## R3.3 Code volume and schedule correction

- **Code estimate**: Rev 1's ~600-900 lines (Rev 2: manager ~180) was priced
  against the now-deleted OffloadingHandler API. Best case (R3.2 passes):
  near zero — config + acceptance probes only. Fallback custom spec:
  re-estimate at D1 after the R3.2 checklist; expect the same order of
  magnitude on the new API, minus whatever the #51007 secondary-tier seam
  absorbs.
- **Schedule**: D0 unchanged (R2.5). D1 gains the internal structure from
  the scoping doc Section 6 — D1a vendor subtree at the pin + shims + image
  build (1-1.5 d); D1b throwaway boot + A1-derived gate battery, with the
  R3.2 checklist folded into this boot (0.5 d); D1c contingent Stage-2
  core-file extension only if D1b fails with connector-core interaction
  signatures (+2-3 d). Expected D1 total 2 d, worst ~5 d — replaces the
  flat "rebase 2-4 d" placeholder. If R3.2 passes, Rev 1's D1-D2 custom-spec
  dev days collapse; D3 (image/runbook) and D4 (B-campaign, Section 8 gates
  + Rev 2 amendments) are unchanged.
