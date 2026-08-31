# KV Offload Upstream Rebase Scope (2026-09-01)

Status: draft — scoping study for the Phase B D1 rebase. Decision ammunition
for the user; presets no conclusion about the D0 diagnostic window or the
final fix route. All evidence gathered read-only on 2026-09-01: partial clone
of vllm-project/vllm at `/tmp/vllm-upstream` (main tip `f5e441de10bd`,
2026-08-31), in-container file hashing/pulls via `docker exec` (no writes, no
service operations), mechanical patch-apply tests on throwaway copies under
`/tmp`. No overlay, planning/03-core, or execution files touched.

## Conclusions first

1. **Recommended route: vendored subtree replacement** of the offloading
   stack at a pinned upstream main SHA (proposed pin: `f5e441de10bd`,
   2026-08-31), keeping the fork core, plus a small enumerated shim set
   (Section 5.3). Not per-fix cherry-picking, not a whole-image tag upgrade.
2. **Per-fix cherry-picking is mechanically dead.** A cumulative
   `git apply` test of the 23 config-relevant upstream fixes against the
   actual image tree: **3 apply cleanly, 20 conflict** (Section 5.1). The
   fixes ride on a chain of ~10 upstream refactors of the same files;
   porting them by hand ≈ re-deriving upstream's evolution manually.
3. **Whole-image tag upgrade (candidate: v0.28.0) is out of Phase B scope.**
   The fork team already tested stock upstream main on GB10/SM120 on
   2026-07-01 and it failed to boot (documented in
   `planning/01-raw/upstream-dspark/UPSTREAM_V024_STATUS.md`; DeepGEMM
   "Unknown SF transformation", Marlin PTX failure, flashinfer device
   rejections). That route is the pre-existing multi-week "official main
   port" project (`OFFICIAL_MAIN_PORT_PLAN.md`), not a Phase B prerequisite.
4. **Feasibility of the subtree route is unusually good because the image's
   offloading stack is 100% pristine upstream code.** Byte-level provenance
   (Section 2): 42 of 46 audited files are byte-identical to upstream blobs,
   all consistent with one sync point — upstream main commit
   **`7e33081cee7b` (2026-05-26)**. Every "fork V4 offload customization" we
   had assumed (GroupOffloadConfig SWA alignment, DeepSeek V4 store-skip,
   `_get_kv_cache_config_deepseek_v4`) is upstream code. The fork's real
   modifications live in exactly 7 boundary files with small, well-understood
   deltas (Section 4).
5. **Baseline correction:** the image version string's commit
   `1967a5627bc3` ("fix(sm120): pass scratch for small prefill chunks",
   2026-05-27) is NOT in upstream history — it resolves via the GitHub API
   only because the API searches the whole fork network. It is a private
   vllm-spark commit. The true upstream baseline for all rebase math is
   `7e33081cee7b`. (Corrects the root-cause doc Section 6 lineage note.)
6. **Effort re-estimate:** Stage-1 subtree swap + shims + throwaway-container
   boot: 1–1.5 days; gate battery re-run: 0.5 day (campaign window). If the
   gate battery fails on tip-stack/May-core interaction, Stage-2 core-file
   adoption adds 2–3 days. So the previous 2–4 day estimate holds as the
   expected case, 4–5 days worst case (Section 6).
7. **Two side findings** (Section 7): (a) upstream independently built
   equivalents of the fork's protected-prompt-blocks and MTP/SWA-mask
   features (#43447, #44082) — a future full upgrade replaces rather than
   ports them; (b) at tip, the blockers that made us reject the in-tree
   tiering/fs NVMe tier are largely lifted upstream (HMA enablement,
   canonical parallelism-agnostic layout, batched async lookup, O_DIRECT
   fallback) — Phase B's custom NVMe spec may shrink to configuration +
   validation. Both feed the D1 entry review.

## 1. Baseline determination (method and result)

Method: pulled the 46 offloading-stack and hash-touchpoint files out of the
live container (read-only tar), computed their git blob SHAs, and searched
upstream history for commits whose trees carry exactly those blobs.

- Result: every one of the 42 matching files is byte-identical to its
  upstream version as of `7e33081cee7b` (2026-05-26, one day before the
  private fork-base commit). Verified as a set: zero mismatches at that
  commit.
- The 4 non-matching files are fork-modified (Section 4). None of them is in
  `v1/kv_offload/` or `kv_connector/v1/offloading*`.
- Upstream tags near the sync point: v0.22.0rc1 was cut 2026-05-27; the fork
  therefore froze immediately before the v0.22 release train. Current
  upstream: v0.28.0 (stable, 2026-08-24), v0.28.1rc0 (2026-08-27), main tip
  `f5e441de10bd` (2026-08-31).

## 2. Upstream commit enumeration since `7e33081cee7b`

Counts per path group (2026-05-26 → 2026-08-31):

| Group | Paths | Commits |
| --- | --- | --- |
| G1 | `vllm/v1/kv_offload/**` | 88 |
| G2 | `offloading/` connector + `offloading_connector.py` | 59 |
| G1∪G2 | offloading stack union | ~120 unique |
| G3 | `kv_connector/v1/{base,metrics}.py`, `kv_connector/factory.py`, `config/kv_transfer.py` | 9 |
| G4 | `v1/worker/kv_connector_model_runner_mixin.py` | 5 |
| G5 | `v1/request.py`, `utils/hashing.py` | 10 |
| G6 | `v1/core/sched/scheduler.py` + kv_cache_utils/block_pool/kv_cache_manager/coordinator/single_type | 123 |

### 2.1 The root-cause fix set, mapped to merge SHAs

All 7 post-baseline fixes from the root-cause doc Section 6 exist in range;
the 2 older ones are pre-baseline (already in the image):

| PR | SHA | Date | Class | Subject |
| --- | --- | --- | --- | --- |
| #45823 | f428718ff | 06-18 | bugfix | Defer on_request_finished until in-flight transfers drain |
| #46231 | d3ad8e8bc | 06-21 | bugfix | Defer offload reads while transfers are pending |
| #46972 | 3354dba38 | 07-07 | bugfix | Store interior chunk-boundary blocks under MTP/Eagle |
| #48102 | 4c81772e8 | 07-12 | bugfix | Fix stale transfer_jobs after reset_cache |
| #48596 | f38f3d11f | 07-17 | bugfix | Offload last block at request finish + reuse race |
| #48911 | fbfe58133 | 07-20 | bugfix | Preserve reachable tails for hybrid SWA groups |
| #49052 | 555967922 | 07-26 | bugfix | Bound unaligned SWA loads by physical GPU blocks |
| #49285 | 3f1d40960 | 07-26 | bugfix | Fix num_tokens_after_batch termination types |
| #51875 | ef47a897e | 08-18 | core | Make prefix-cache NONE_HASH deterministic by default |
| #25856 | cfd302db9 | 2025-09-30 | bugfix | (pre-baseline — already in image) |
| #27648 | 685c99ee7 | 2025-11-01 | feature | async-scheduling support (pre-baseline — already in image) |

Note: the fork coordinator comment cites "PR #41834 (e6c46a50fb)" for the
hybrid tail-block alignment change; neither that PR-number pattern nor that
SHA exists on upstream main. The fork's tail-block/`cache_alignment_tokens`
scheme is a fork-local reimplementation with an unverifiable citation —
treat it as fork code, not a backport (matters for Section 4 grading).

### 2.2 Additional config-relevant fixes NOT in the original fix set

These directly touch mechanisms our deployment uses (hybrid HMA groups,
nvfp4_ds_mla, MTP, chunked prefill, load-failure semantics):

| SHA | Date | PR | Subject (why it matters to us) |
| --- | --- | --- | --- |
| 480fadab1 | 06-02 | #42959 | Prevent offloading stale sliding-window blocks (SWA groups) |
| 4bc83323f | 06-12 | #44592 | Respect skip_reading_prefix_cache flag |
| 7ad894c86 | 06-16 | #44784 | Prevent cuMemcpyBatchAsync segfault with MTP + KV offloading |
| ed938ad7d | 06-18 | #45757 | Guard CPU eviction check |
| cf9fd6457 | 06-24 | #46284 | Fix request-finished lifecycle contract |
| 798185d43 | 06-27 | #46888 | Fix tensors_per_block stride (multi-tensor pages) |
| 32aef4438 | 07-14 | #48411 | Include inline per-token-head scales in offloaded page transfer width (nvfp4/fp8 scale-carrying KV — OUR dtype) |
| 12f2c515a | 07-16 | #48530 | Fix set_ overflow for packed non-uniform KV caches (heterogeneous page sizes — our 37,376 B vs 1,168 B layout) |
| 94ed0bf4e | 07-21 | #49146 | Handle queued aborts without allocated KV blocks |
| d30b1ecd1 | 07-25 | #49671 | Defer request finalization until final store |
| 1b0ce31f3 | 08-09 | #49328 | Fix failed-load livelock: mark lookup verdict a miss (load-failure semantics Phase B relies on) |
| eb24bc38c | 08-09 | #51161 | Handle chunked local attention in offloading scheduler |
| bed3280f5 | 08-31 | #50696 | Order CPU→GPU loads against the compute stream (load correctness) |
| bc39ded3c | 08-25 | #53329 | Defer request-level cascade of in-flight primary keys |
| e6bfe03ad | 08-27 | #52227 | Count store offers, not lookups, for store_threshold |

Core-side (G6) fixes in the connector × hybrid × async intersection —
relevant to the A1 root cause AND to what a full core upgrade would bring:

| SHA | Date | PR | Subject |
| --- | --- | --- | --- |
| e9e08c49b | 06-02 | #44082 | Cache the EAGLE/MTP lookahead block in the SWA prefix-cache mask (upstream twin of the fork's `eagle_extra_cache_blocks` fix) |
| a6183563b | 06-04 | #43447 | DSv4: selective prefix-cache retention for sliding-window KV (upstream twin of the fork's protected-prompt-blocks) |
| 373eb314a | 07-06 | #46066 | Fix num_output_placeholders underflow with async scheduling + spec decode |
| 530852f95 | 07-16 | #48481 | Fix PD async-scheduling race for hybrid attention models |
| 8950394e0 | 07-21 | #48860 | Prefix-cache metrics double-counted when a KV connector defers requests |
| 229e01e9e | 07-22 | #48425 | Handle per-group prefix-hit divergence for hybrid models with KV connector |
| a0c092ee7 | 07-29 | #48245 | Fix num_output_placeholders preemption underflow |
| d6941300f | 08-09 | #50344 | Scope divergent hybrid cache hits to capable connectors |
| ef47a897e | 08-18 | #51875 | NONE_HASH deterministic by default |

### 2.3 The refactor chain (why cherry-picks can't land)

Between the baseline and the fixes sit at least these structural rewrites of
the same files (chronological):

1. 864990e8d (05-28, #39983) token-offset selective offload — rewrote the
   connector-scheduler store path 2 days after our baseline.
2. a3ed5ab10 (05-28, #43205) per-request offloading policy via
   `on_new_request`.
3. 2a2b5ca79 (06-02, #44206) `on_schedule_end()` lifecycle hook.
4. af65e08fc (06-10, #44193) async batched lookup (lookup API change;
   `bool | None` → `LookupResult` enum family).
5. f237e16b4 (06-24, #45053) **Replace OffloadingHandler with
   OffloadingWorker — `v1/kv_offload/worker/` no longer exists at tip.**
6. c46ced1ee (07-07, #46544) tier-owned KV event handling (+ new
   `offloading/events.py`).
7. a9531edfa (07-16, #48150) clean backend configuration boundary (+ new
   `kv_offload/config.py`, `offloading/config.py`).
8. 472d330c2 (07-17, #48878) `blocks_per_chunk` for heterogeneous KV groups.
9. 542a8fad6 (07-29, #50094) CPUOffloadingSpec moved onto
   SharedOffloadRegion.
10. 2c4d34884 / 81840a172 (07-31 / 08-10, #48408/#48414) canonical per-layer
    page mappings + canonical CPU layout (parallelism-agnostic offload; new
    `offloading/canonical_mapping.py`).
11. 62c5e2162 (08-05, #50507) partial-tail prefix reuse, fine-grained
    matching (`hashes_per_chunk`; connector scheduler grew 996 → 1775 lines).
12. dc1be7903 (07-29, #49114) CachePolicyFactory (+ `cpu/policies/factory.py`,
    `cpu/swap_blocks_triton.py`).

## 3. Route (i): targeted cherry-pick — empirical apply test

Cumulative `git apply -p2` of the 23 fixes above (vllm/ paths only, ordered
by date) onto a git-initialized copy of the actual image tree:

| Verdict | Count | SHAs |
| --- | --- | --- |
| APPLIED cleanly | 3 | 7ad894c86 (#44784), 3354dba38 (#46972), 4c81772e8 (#48102) |
| CONFLICT | 20 | everything else, incl. ALL SWA/hybrid/termination fixes |

Failure signature: 15 of 20 conflicts are in
`offloading/scheduler.py` / `offloading/worker.py` — the two files most
rewritten by the Section 2.3 chain. Three more fail on files that don't
exist at the baseline (`tiering/async_lookup.py`, `tiering/p2p/*`) and one
(#48411) on the fork-modified `kv_cache_interface.py`.

Verdict: **not viable.** A hand-port of 20 conflicting patches into a
996-line snapshot whose upstream successor is 1775 lines is strictly more
work and more risk than adopting the successor. The 3 clean picks alone do
not cover the SWA-tail, unaligned-load, termination-type, or
scale-width fixes that our hybrid/nvfp4 config specifically needs.

## 4. File-level conflict surface (grades: A = whole-file replace,
B = three-way merge, C = fork-only, keep)

### Grade A — byte-identical to upstream@baseline; replaceable as a set

| File(s) | Image provenance (last upstream change before baseline) | Upstream commits since |
| --- | --- | --- |
| `v1/kv_offload/**` — all 22 files incl. base/factory/cpu/*/tiering/*/file_mapper | 2025-09-24 … 2026-05-24 blobs, all ⊂ `7e33081cee7b` | 88 |
| `kv_connector/v1/offloading/{__init__,common,metrics,scheduler,worker}.py` | scheduler @357fddf61477 (05-24), worker @7e33081cee7b (05-26) | 59 |
| `kv_connector/v1/offloading_connector.py` | @5bd8c71e792a (05-14) | 9 |
| `kv_connector/v1/base.py` | @13bf2421009a (05-13) | 7 |
| `kv_connector/v1/metrics.py` | @880be2b1b80f (03-20) | 0 |
| `kv_connector/factory.py` | @755043cf3cd6 (05-26) | 2 |
| `config/kv_transfer.py` | @5a3f1eb62fb8 (03-13) | 2 |
| `utils/hashing.py` | @9bcf92295a91 (2025-12-03) | 0 |
| `v1/core/kv_cache_utils.py` | @27b85d2084c4 (05-15) | 36 |
| `v1/core/block_pool.py` | @4b364f810e12 (05-15) | 9 |
| `v1/request.py` | @f34623bf3cac (05-19) | 10 |
| `v1/core/sched/output.py` | @14043dfecd35 (05-01) | 11 |
| `v1/worker/kv_connector_model_runner_mixin.py` | @856589ed9aa7 (03-31) | 5 (tip slimmed 283 → 107 lines) |

Caveat on grade A: "replaceable" is mechanical, not free. Replacing
`kv_cache_utils.py` / `block_pool.py` / `request.py` wholesale means adopting
the partial-prefix-hit primitives (#45939/#46384), two-phase KV allocation
(#44409), and BlockHash-type changes — which the four grade-B files build
against. Stage 1 therefore replaces ONLY the offloading stack + connector
API layer and keeps core files at the fork version (Section 5.3).

### Grade B — fork-modified; three-way merge required (functions listed)

| File | Fork delta vs baseline | Functions touched |
| --- | --- | --- |
| `v1/core/sched/scheduler.py` | 3 hunks | `update_from_output` (DSpark Patch 3: `draft_token_lengths` → resize `spec_token_ids` placeholders under async scheduling, decode-only guards), `reset_connector_cache` (no-op success without connector) |
| `v1/core/kv_cache_manager.py` | 5 hunks | `allocate_slots` (free-block check → `_has_enough_free_blocks` with protected-block release cascade), `reset_prefix_cache`, `evict_blocks`, new `_block_ids_to_skip_releasing` |
| `v1/core/kv_cache_coordinator.py` | 4 hunks | `verify_and_split_kv_cache_groups` (per-manager `cache_alignment_tokens`; `eagle_extra_cache_blocks` wiring), `HybridKVCacheCoordinator.cache_blocks` (lcm truncation removed), new `release_protected_prompt_blocks`, `get_blocks` |
| `v1/core/single_type_kv_cache_manager.py` | 12 hunks, +189 lines | protected-prompt-blocks machinery (`_protect_prompt_blocks` et al.), NEW classes `MLAAttentionManager` + `SlidingWindowMLAManager`, `SlidingWindowManager._cache_block_mask` eagle disable, `spec_manager_map` rebinding, `max_model_len` plumb |
| `v1/kv_cache_interface.py` | +6 lines | `nvfp4_ds_mla` → `KVQuantMode.NVFP4`; DSv4 page-size accounting (`storage_block_size * 584` / `* 416`) |
| `v1/outputs.py` | +5 lines | `draft_token_lengths` field on ModelRunnerOutput (Patch 3 support) |
| `v1/worker/gpu_model_runner.py` | +303/−7 lines | DSpark spec-decode wiring, deferred connector finalize, warmup — overlay file |

### Grade C — fork-only, untouched by this upgrade

DSpark model/kernel tree (`models/deepseek_v4/**`, `v1/spec_decode/dspark*`,
`b12x_*`, `envs.py`, `config/speculative.py`, attention backend registry
entries) and the three fork features embedded in the grade-B files
(protected prompt blocks, Patch 3, eagle mask disable) — these must survive
any route.

## 5. Route evaluation and recommendation

### 5.1 Route (i) — targeted cherry-pick: REJECTED

Empirically dead (Section 3): 3/23 clean. The ordered SHA list and per-patch
verdicts are in Section 3; the conflict cause is the Section 2.3 refactor
chain. If the user nevertheless wants a minimal-risk interim patch while D0
runs, the only meaningful clean subset is:
`7ad894c86 → 3354dba38 → 4c81772e8` (MTP segfault, MTP chunk-boundary
stores, reset_cache job hygiene) — none of which addresses the A1 hash
mismatch.

### 5.2 Route (ii) — whole-image upgrade to an upstream tag: REJECTED for Phase B

- Candidate tags would be v0.28.0 (stable, 08-24) or v0.28.1 when released;
  v0.28.1rc0 (08-27) misses 6 of the 7 offload fixes landed 08-27..08-31
  (incl. bed3280f5 load-ordering).
- Passively introduced subsystems since v0.22: KV-cache layout refactor
  series (#44456 … #51718 "6/N"), partial prefix-cache hits for hybrids,
  two-phase KV allocation, upstream DSpark lane evolution (post-#46995),
  ModelRunnerV2 changes, attention-backend restructuring, quantization
  backend churn — each a re-validation surface for a 1M-context NVFP4
  deployment.
- Decisive precedent: `UPSTREAM_V024_STATUS.md` — stock official main
  (2026-07-01, containing merged DSpark PR #46995) imported but FAILED to
  boot this checkpoint on 2x DGX Spark/SM120 across all 5 attention/quant
  backend attempts. The gap list (nvfp4_ds_mla resolution, B12X MXFP4
  bridge) is exactly the fork's grade-B/C surface. A prototype bridge patch
  exists (`patches/official-main-b12x-nvfp4-python.patch`) but never passed
  full model boot. This is the "official main port" project — weeks, its own
  validation program — and must not be a Phase B dependency.

### 5.3 Route (iii) — vendored subtree replacement: RECOMMENDED

Replace, as one unit, at pinned upstream SHA `f5e441de10bd` (or the newest
main SHA at execution time; record the pin in the overlay):

- `vllm/v1/kv_offload/**` (delete `worker/`, add `config.py`,
  `cpu/policies/factory.py`, `cpu/swap_blocks_triton.py`, tiering additions)
- `vllm/distributed/kv_transfer/kv_connector/v1/offloading/` (add
  `canonical_mapping.py`, `config.py`, `events.py`)
- `vllm/distributed/kv_transfer/kv_connector/v1/offloading_connector.py`
- `vllm/distributed/kv_transfer/kv_connector/v1/{base.py,metrics.py}` and
  `kv_connector/factory.py`, `config/kv_transfer.py` (API layer, grade A)

Boundary shims (all verified against the pulled tip sources):

1. `base.py` back-compat stubs: keep no-op `register_cross_layers_kv_cache`
   + `prefer_cross_layer_blocks` (removed at tip; still called at 3 sites in
   the fork's gpu_model_runner/mixin). ~10 lines.
2. `kv_cache_interface.py`: re-apply the fork's +6 nvfp4/DSv4 page-size
   lines onto whatever page-size accessors the tip stack reads (tip adds
   inline-scale-aware transfer width, #48411 — verify the fork's *584/*416
   constants against it; this is a REVIEW item, possibly zero code).
3. Optional core call sites: tip core calls `has_pending_push_work` /
   `ensure_cache_available`; absence in the fork scheduler degrades to
   pre-#49582 drain behavior for the offloading connector (which implements
   `has_pending_push_work` for idle-flush #45595). Wire the one
   `has_pending_push_work` call into the fork scheduler's drain path if the
   idle-flush behavior is wanted; not boot-blocking.
4. Import surface: verified present in-image — `utils/math_utils` (cdiv,
   round_down/up), `utils/torch_utils` (PIN_MEMORY), `v1/attention/backend`
   (AttentionMetadata), `distributed/kv_events`, `v1/core/sched/output`
   (SchedulerOutput), `v1/outputs` (KVConnectorOutput), `_custom_ops`.
   Request attributes used by the tip connector scheduler
   (block_hashes, num_prompt_tokens, num_tokens, skip_reading_prefix_cache,
   kv_transfer_params, status) all exist in the image's request.py.
5. Config: the `--kv-transfer-config` JSON keys survive
   (`spec_name`/`spec_module_path` seam intact at tip factory.py:31-49;
   `cpu_bytes_to_use`, `eviction_policy`, `store_threshold` still read by
   tip cpu/spec.py; new optional keys available: `cache_policy_module_path`,
   `max_tracker_size`).

Residual risk, stated plainly: tip offloading stack on a May-era core is a
pairing upstream never tested. Specifically, the divergent-hybrid-hit
handling (#48425/#50344) partially lives in core files we are NOT replacing
in Stage 1; and semantics the tip stack expects from `update_connector_output`
/ preemption paths may have drifted in ways import-level analysis cannot see.
Mitigation: this route ships inside the Phase B image rebuild and must pass
the A1-derived kill-arm gate battery (identical-prompt-twice cached_tokens>0,
≤1.3x write-amplification detector, needle correctness) in a throwaway boot
before any campaign window; fallback is byte-exact image rollback as
rehearsed in Phase A. If Stage-1 gates fail with connector-core interaction
signatures, Stage 2 extends the vendored set to
`kv_cache_utils.py`/`block_pool.py`/`request.py`/`sched/output.py` (grade A,
36/9/10/11 commits behind) and re-merges the four grade-B files against tip
(their fork deltas are small and enumerated in Section 4) — +2–3 days.

### 5.4 Why not pin at v0.28.0/v0.28.1rc0 for the subtree

The 08-25..08-31 window contains offload correctness fixes we want
(bed3280f5 load/compute-stream ordering; e6bfe03ad store_threshold; 
bc39ded3c in-flight key cascade; 15227b934/f9d666f91/9acbc5360 event
correctness) — v0.28.1rc0 contains only bc39ded3c of these. Since we vendor
a subtree (not consume a package), a pinned main SHA gives strictly more
fixes at identical integration cost; the pin is recorded and reproducible.

## 6. Revised effort estimate (was: 2–4 days)

| Stage | Work | Estimate |
| --- | --- | --- |
| D1a | Vendor subtree at pin + shims 1-2-4-5, build image via existing `build-dspark-vllm-runtime.sh` overlay pipeline | 1–1.5 d |
| D1b | Throwaway-container boot + A1 gate battery (no campaign window needed for the throwaway; campaign window only for the production swap) | 0.5 d |
| D1c (contingent) | Stage-2 core-file extension + grade-B re-merge if D1b fails | +2–3 d |
| — | Whole-image tag route (rejected) | weeks (own project) |

Expected case 2 days, worst case ~5. The previous "2–4 days" stands, now
with a defined internal structure and an explicit early-fail point (D1b).

## 7. Addenda for the root-cause doc and Phase B design

1. **Root-cause doc corrections** (to fold into its next revision):
   Section 6's "base commit exists in vllm-project/vllm" is a GitHub
   fork-network artifact; true baseline `7e33081cee7b`. Candidate C2 should
   read "pristine but stale upstream snapshot missing ~20 later fixes", not
   "fork mid-refactor snapshot" — there are NO fork edits inside the
   offloading stack. The `num_offloadable_tokens = min(...)` accommodation
   is upstream baseline code, not a fork change.
2. **New root-cause-relevant discovery:** the fork's only code in the
   hash/caching pipeline is now precisely enumerated — Patch 3
   (`update_from_output` writing `spec_token_ids = [-1] * draft_len` under
   async scheduling) and the protected-prompt-blocks/eagle-mask machinery in
   coordinator/single_type managers. These are exactly the fork-local
   suspects the D0 kv-events diagnostic can discriminate from
   stale-upstream-snapshot bugs (C1 vs C2 in the root-cause doc). Upstream's
   #46066/#48245 (num_output_placeholders underflow fixes with async + spec
   decode) are adjacent to Patch 3's territory and are absent from the image.
3. **Phase B design impact (for the design doc's next rev):**
   - The Rev 1/Rev 2 worker-side seam (`v1/kv_offload/worker/worker.py`
     `register_handler` by medium pair) NO LONGER EXISTS at tip (#45053).
     A custom NVMe spec on the new stack targets `OffloadingWorker` +
     `Medium` enum + the `kv_offload/config.py` boundary instead.
   - The `spec_module_path` factory seam survives at tip, and #51007 adds a
     second seam (out-of-tree secondary tier managers via `module_path`).
   - The reasons we rejected the in-tree tiering/fs NVMe tier (single-group
     assert; scheduler-process IO wrong on 2-node TP) are addressed upstream
     during the drift window: HMA models enabled for tiering (#44287),
     canonical parallelism-agnostic layouts (#48408/#48414), DP-replica
     awareness (#47987), async batched lookup (#44193), C-accelerated batch
     IO (#46713/#49152), O_DIRECT with fallback (#49734), HIT_PENDING
     promotion (#51840), per-request tier filters (#48123). At D1 entry,
     re-evaluate "configure upstream fs tier per-rank" vs "write custom
     NVMe spec" — the former may reduce Phase B code to near zero, with the
     2-node-TP audit as the deciding check.
   - `kv_load_failure_policy` plumbing: tip offloading connector still does
     not implement `get_block_ids_with_load_errors`; upstream's answer is
     manager-level miss-marking (#49328). The design doc's ~50-line
     failure-plumbing estimate stands, or adopt #49328 semantics.

## Appendix A — full offloading-stack commit list (G1∪G2, chronological)

(120 commits, 2026-05-28 → 2026-08-31; classification tags:
B=bugfix, R=refactor, F=feature, P=platform/other-tier)

```
05-28 a3ed5ab10 R per-request offloading policy via on_new_request (#43205)
05-28 4bfa0f2b1 R rename SecondaryTierManager.get_finished -> get_finished_jobs (#43870)
05-28 864990e8d R/F token-offset based selective offload (#39983)
05-28 1b16f2ddc R rename fs_python secondary tier to fs (#43600)
05-29 d63108fb1 B skip decode-phase blocks in CPU offload (#43797)
06-02 480fadab1 B prevent offloading stale sliding-window blocks (#42959)
06-02 2a2b5ca79 R on_schedule_end hook (#44206)
06-02 93da882e7 R @override decorators (#44177)
06-02 3f0a91bb9 R tiering nits (#44293)
06-03 726845799 F enable HMA models for tiering offloading (#44287)
06-03 1fa9ea09f F triton fast path small CPU->GPU swap_blocks_batch (#42212)
06-03 3d76f395e B align SharedOffloadRegion blocks to page size (#43689)
06-05 6a894574b F objectstore secondary tier (#41968)
06-07 810966453 P XPU support (#36423)
06-10 9dfc313bd F offloading manager stats (#35669)
06-10 af65e08fc R async batched lookup (#44193)
06-11 b927004c4 B Mamba CPU offloading (#44599)
06-11 c3662b36e F parallel-agnostic fs-tier cache, single full-attn group (#44733)
06-12 4bc83323f B respect skip_reading_prefix_cache (#44592)
06-15 7e612a0f0 F reset_cache for TieringOffloadingManager (#44541)
06-16 7ad894c86 B prevent cuMemcpyBatchAsync segfault with MTP (#44784)
06-17 6d8fff569 B avoid blocking engine to flush offloads on idle (#45595)
06-18 ed938ad7d B guard CPU eviction check (#45757)
06-18 f428718ff B defer on_request_finished until transfers drain (#45823)
06-18 ea6078fe6 B disable parallel-agnostic fs-tier on V2 runner (#46044)
06-18 421c1ec44 R remove dummy worker-side stats (#45905)
06-19 01192139b F [DSv4] pack KV caches into contiguous per-block allocations (#44577)
06-20 7df3d7dad B ensure memory pinned before async h2d (#45424)
06-20 cc22621b5 F packed HMA KV cache layout (#46205)
06-20 3b4a76b63 F CPU cache usage metric (#45737)
06-21 d3ad8e8bc B defer offload reads while transfers pending (#46231)
06-21 c441ad1c0 F labeled metrics (#45957)
06-22 68567ef2d R evictable list in LRUCachePolicy (#46216)
06-22 a9f7b2d41 F self-describing KV events for OffloadingConnector (#43468)
06-23 091bc1026 F tiering metric plumbing (#45959)
06-24 e7df23228 B gate packed HMA on cross-layer config (#46252)
06-24 f237e16b4 R replace OffloadingHandler with OffloadingWorker (#45053)
06-24 f889325c5 F background thread for mmap/pinning (#45850) [reverted 06-29]
06-24 bb61177e4 R lookup verdict type change (bool -> enum family)
06-24 cf9fd6457 B fix request-finished lifecycle contract (#46284)
06-27 798185d43 B fix tensors_per_block stride (#46888)
06-29 36bbecd64 B revert #45850 background pinning (#46958)
06-29 c8fb2963b F FS batch lookup in C (#46713)
06-30 0fc251209 R pass ScheduleEndContext to on_schedule_end (#46450)
06-30 bec232a91 F secondary tier for PD disaggregation (#42285)
07-07 3354dba38 B store interior chunk-boundary blocks under MTP/Eagle (#46972)
07-07 48fcfc926 R ParentManager ABC for secondary tier callbacks (#47274)
07-07 e040899a0 F basic offloading metrics (#45958)
07-07 c46ced1ee R tier-owned KV event handling (#46544)
07-07 65a7b4628 P objectstore workload identity (#47063)
07-08 0ca6eee74 R pass request context to cache-policy touch (#47744)
07-10 2d814a008 F tier-owned BlockStored events FS/OBJ (#47923)
07-12 4c81772e8 B fix stale transfer_jobs after reset_cache (#48102)
07-12 5c0c987c0 F DP-replica-aware tiering offload region (#47987)
07-14 32aef4438 B inline per-token-head scales in transfer width (#48411)
07-14 cdaa40d2a F split cpu_cache_usage into write/read gauges (#47666)
07-15 615834ee5 P P2P env vars (#47636)
07-16 12f2c515a B fix set_ overflow packed non-uniform KV (#48530)
07-16 a9531edfa R clean backend configuration boundary (#48150)
07-16 ce6538561 F split tiering_lookup_delay histograms (#47679)
07-17 f38f3d11f B offload last block at finish + reuse race (#48596)
07-17 426d48bfa F optional tier locality in FS/OBJ events (#48281)
07-17 472d330c2 F blocks_per_chunk for heterogeneous KV groups (#48878)
07-19 b6ff8a2f5 F MRV2 virtual-batch PCP for MLA (#46570)
07-20 fbfe58133 B preserve reachable tails hybrid SWA (#48911)
07-20 f007cceb4 F self-describing events with TieringOffloadingSpec (#48679)
07-21 6700813f8 R [3/N] layout refactor: standardize Mamba cache (#44456)
07-21 94ed0bf4e B queued aborts without allocated blocks (#49146)
07-24 89f6aa3a9 B O_DIRECT fallback to buffered IO (#49734)
07-25 d30b1ecd1 B defer request finalization until final store (#49671)
07-26 555967922 B bound unaligned SWA loads by physical GPU blocks (#49052)
07-26 b68d7ef26 B namespace auto cache dtype (#49438)
07-26 7a29a3c54 B namespace persistent cache by model runner (#49440)
07-26 7eca0e1a6 F dedupe replicated MLA KV in shared CPU region (#48906)
07-26 3f1d40960 B fix num_tokens_after_batch termination types (#49285)
07-26 da3a252fd P generic P2P secondary tier (#48021)
07-27 53397fbfa B P2P reaped-peer crash (#49823)
07-27 394beb633 P ROCm batch DMA loads (#49843)
07-27 77cba0259 F per-request tier filtering TierFilter/TierMatcher (#48123)
07-28 1e81853af B Mamba span under DCP (#49964)
07-28 52c3c4a42 B OBJ job completion during cleanup (#49947)
07-28 30217b0e8 B P2P serve-state scoping (#49877)
07-28 a8f296083 R TP-independent compact secondary identity (#49858)
07-28 d18ed2304 F FS batch store/load in C (#49152)
07-29 542a8fad6 R CPUOffloadingSpec onto SharedOffloadRegion (#50094)
07-29 dc1be7903 R CachePolicyFactory pluggable eviction (#49114)
07-30 437e0b7f8 B P/D preemption race (#50297)
07-31 2c4d34884 R canonical per-layer KV page mappings (#48408)
07-31 541128bde F single-copy MLA layout for CPUOffloadingSpec (#50301)
08-04 41a7e7da0 F partial secondary-tier load results (#50321)
08-05 9833aa53d B fail fast when CPU region exceeds space (#50358)
08-05 8543522ca F out-of-tree secondary tier managers via module_path (#51007)
08-05 62c5e2162 R/F partial-tail prefix reuse, fine-grained matching (#50507)
08-05 b92352ca2 B avoid quadratic ARC batch eviction (#50992)
08-06 46e6a83ce B clean up after init failure (#51227)
08-06 ef2615c2e B MADV_POPULATE_WRITE fallback (#51116)
08-07 c810e5ee9 B Mamba all-mode boundary alignment (#51100)
08-09 eb24bc38c B chunked local attention in offloading scheduler (#51161)
08-09 c42399864 F self-describing events for partial recurrent blocks (#51243)
08-09 1b0ce31f3 B failed-load livelock -> lookup miss (#49328)
08-10 81840a172 R canonical CPU layout (#48414)
08-10 a123159f7 F tiering offloading metrics (#48798)
08-11 0fec3d652 B centralize shared mmap cleanup (#51622)
08-11 0f2ea973b B keep per-layer KV registration with canonical_layout (#51688)
08-11 1ab2801dd P ROCm cleanup (#50907)
08-12 15227b934 B CPU events at KV-group block granularity (#51614)
08-12 f067737b2 B HIT_PENDING when KV promotion triggered (#51840)
08-12 f9a0f629b F expose DP topology to offloading backends (#51879)
08-18 ef47a897e B/R NONE_HASH deterministic by default (#51875)
08-20 0a111cca2 R metrics rename block->chunk (#52812)
08-21 8bdc70ec7 R [6/N] standardize KV cache layout (#51718)
08-25 bc39ded3c B defer request-level cascade of in-flight primary keys (#53329)
08-27 e6bfe03ad B store offers not lookups for store_threshold (#52227)
08-29 6b110badb B Mooncake exact Mamba boundary states (#51358)
08-31 4c58a0c39 B unlink /dev/shm region after all workers map (#52596)
08-31 e0d27040d B P2P preserve aborted loads (#52571)
08-31 d8de4ae32 B P2P REQUEST_LEVEL producer leg (#52912)
08-31 c5d840ff6 B certify attention-only hybrids in canonical portability gate (#51689)
08-31 f9d666f91 B forward ownership in KV cache events (#52067)
08-31 bed3280f5 B order CPU->GPU loads against compute stream (#50696)
08-31 9acbc5360 B preserve KV event metadata until residency removal (#52068)
```

## Appendix B — evidence trail (all read-only)

- Blob-provenance pinning: `git hash-object` of 46 in-container files vs
  `git rev-list`/`rev-parse` walks of `/tmp/vllm-upstream` (partial clone,
  `--filter=blob:none`); whole-set verification at `7e33081cee7b` = 0
  mismatches.
- Apply test: `/tmp/apply-test` (git-initialized copy of the pulled image
  tree), cumulative `git apply -p2 --check`/apply of 23 fix diffs
  (`git show SHA -- 'vllm/*'`), verdicts as in Section 3.
- Tip sources pulled for boundary analysis: offloading stack + base.py +
  factory + cpu/spec + core scheduler + kv_cache_utils + request +
  mixin (19 files) at `origin/main` = `f5e441de10bd`.
- Fork deltas: `diff -u` of upstream@`7e33081cee7b` blobs vs in-container
  files for the 7 grade-B files; hunk-to-function mapping script.
- Container access: `docker exec gb10-deepseek-v4-vllm-dspark-1` `sha256sum`
  / `tar -cf -` / `sh -c '[ -e … ]'` only. No writes, no lifecycle
  operations, service untouched (verified healthy low-traffic throughout).
