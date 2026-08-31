# KV Offload Block-Hash Mismatch: Root-Cause Analysis (2026-09-01)

Status: root cause REDUCED and fault class proven; exact faulting line requires
one 30-minute zero-code-change diagnostic arm (designed below, "D0"). Phase B
is blocked on D0 + fix. All code citations verified read-only in the live
container 2026-09-01 (02:30-04:30 local, baseline+A0 config — code identical to
what A1 ran). `$VLLM` = `/opt/env/lib/python3.12/site-packages/vllm`.
Evidence artifacts: `tmp/followup-tests/20260831T170721Z/` (A1 arm).

## Conclusion first

1. **The fault class is proven: while OffloadingConnector is registered, the
   block-hash-keyed identity of KV content is unstable — the same content
   yields keys that match in NEITHER hash table (GPU
   `cached_block_hash_to_block` nor CPU offload `_policy`), and (proven by
   arithmetic below) the offload keys for the same (request, block) even
   differ ACROSS SCHEDULER PASSES within a single request.** This one fault
   produces both A1 kill signals: 0 prefix-cache hits and ~9-13x store
   amplification.
2. **Static analysis exonerates every individually-read component** (hasher,
   key derivation, dedupe, caching, lookup — full list in Section 4 with
   citations). The bug therefore lives in a runtime interaction — the prime
   candidates (Section 5) all involve this fork's ~July-2026 snapshot of the
   upstream offloading stack interacting with async-scheduling + MTP +
   chunked prefill on the 5-group hybrid DSv4 KV layout.
3. **The deployed offloading stack is a mid-refactor upstream snapshot.**
   Upstream `offloading/scheduler.py` has since grown 996 → 1775 lines with
   at least 8 bugfix commits directly in this area (Section 6). The
   recommended fix path is NOT a bespoke patch hunt: pin the faulting line
   with D0, then adopt the upstream-current offloading stack in the Phase B
   image rebuild (which Phase B requires anyway), with the minimal-overlay
   fallback only if the D0 result shows a fork-local one-liner.
4. Until fixed, ANY offload tier (DRAM or NVMe) writes ~13x traffic and can
   never hit. For NVMe this is also an endurance hazard (~1.5 TB/day of junk
   writes at incident-level traffic). Hence D0 is a hard Phase B prerequisite.

## 1. Symptoms (from the A1 campaign report, all reproduced references)

- `vllm:prefix_cache_hits_total` = 0.0 after 1,084,361 queried tokens;
  byte-identical 60,163-token requery (sha256-verified prompt) returned
  `cached_tokens: null`, 39.14 s full cold recompute. Same test after
  rollback: 17,664/17,803 cached, 0.54 s. Connector-causal (A/B controlled).
- `vllm:kv_offload_total_bytes{GPU_to_CPU}` = 113.2 GB for ~700K computed
  tokens (expected ~9.7 GB); 292 store jobs, 288 of them > 200 MB
  (`a1-offload8g/metrics-post-requery.prom`).
- `vllm:external_prefix_cache_hits_total` = 0; CPU_to_GPU (load) metric series
  never appeared — zero load attempts all session.
- No corruption: needle answer byte-identical cold vs post-flood; failure mode
  is pure miss.

## 2. Proof 1 — store amplification implies per-pass key instability

The store path has TWO independent guards that each suffice to prevent
re-storing the same content, and both were verified intact in the deployed
code:

- Per-request high-water mark: `_build_store_jobs` only offers
  `offload_keys[next_stored_block_idx : num_offloadable // 256]` and advances
  the index when a job is built (`$VLLM/distributed/kv_transfer/kv_connector/
  v1/offloading/scheduler.py` ~794 `group_state.next_stored_block_idx =
  num_blocks`) and in both empty paths (~735, ~745 `advance_stored_idx`).
- Manager dedupe at PREPARE time (not completion time): `prepare_store`
  filters `[k for k in keys if self._policy.get(k) is None]` and INSERTS
  accepted keys into `_policy` immediately (`$VLLM/v1/kv_offload/cpu/
  manager.py:146-147, 186-188`) — so even in-flight stores dedupe.

Now the arithmetic. During A1 first-traffic alone (64K probe + 130K probe +
small ≈ 195K unique tokens ≈ 758 unique 256-token blocks ≈ 2.8 GB), the
metrics show 66 store jobs totaling 25 GB ≈ 6,900 block-stores ≈ 9x. The CPU
pool holds 2,366 blocks (8 GiB / 3.63 MB), so at ≤758 unique keys the pool had
NOT wrapped — LRU eviction cannot explain dedupe misses. Furthermore the
per-pass job sizes reproduce the triangular sum of re-storing the ENTIRE
accumulated prefix every scheduler pass: with
`LONG_PREFILL_TOKEN_THRESHOLD=6144`, sum over passes for 130K = ~21 passes ≈
1.4M token-stores ≈ 20 GB, plus 64K's ≈ 3.4 GB ≈ 23.4 GB ≈ observed 25 GB.

With both guards intact, the ONLY way this happens is that the keys offered on
pass N+1 are DIFFERENT byte-values from the keys inserted on pass N for the
same blocks. Offload keys are a pure function of `request.block_hashes`
(`offloading/scheduler.py:192-207`: `make_offload_key(req.block_hashes[i],
group_idx)`). **Therefore `request.block_hashes` content for the same
(request, block index) changed between scheduler passes.** This is the proven
core anomaly — and it is "impossible" per the static code (the list is
append-only: `$VLLM/v1/request.py:229-232`), which is precisely why the
faulting line must be caught at runtime (D0).

## 3. Proof 2 — the GPU-side miss shares the same root

The GPU prefix cache and the connector consume the SAME `request.block_hashes`
(lookup: `find_longest_cache_hit(request.block_hashes, ...)`,
`$VLLM/v1/core/kv_cache_manager.py:220-224`; caching:
`coordinator.cache_blocks` inside `allocate_slots`, `kv_cache_manager.py`
~433). The requery-miss alone could have load-dependent explanations
(upstream #42948's entry-destruction family), but combined with Proof 1 the
parsimonious conclusion is one shared fault in the block-hash timeline. Note
the A1 traffic pattern nuance: first-traffic was all unique content, so
"hits=0" is only DIAGNOSTIC for the needle→flood→requery sequence — the
requery is the single controlled repeat-content datum, and it missed while its
blocks arithmetically could not have been evicted (509K total tokens allocated
against a 1.27M-token pool, ~5,100 of 8,585 HMA blocks never touched).

## 4. Exonerated by direct code reading (all in-container, A1-identical code)

- Hasher construction: single site, engine-core process only, unconditional
  on prefix-caching OR connector (`$VLLM/v1/engine/core.py:205-214`);
  `prefix_caching_hash_algo="sha256"` → pickle+sha256, content-deterministic
  for (bytes, tuple[int], None) inputs (`$VLLM/utils/hashing.py:26-40,
  91-92`); `NONE_HASH` initialized once per engine-core process
  (`kv_cache_utils.py:97-112`, sole caller core.py:210).
- Hash input: `(parent_hash, tuple(prompt_token_ids_slice), extra_keys)`
  (`kv_cache_utils.py:565-570`); extra_keys is None for our traffic (no
  mm/LoRA/cache_salt/prompt_embeds, `kv_cache_utils.py:503-538`).
- `hash_block_size` contract: one `resolve_kv_cache_block_sizes` result feeds
  both the hasher and the KVCacheManager (`core.py:144-156`, overlay
  `sched/scheduler.py:225-237`); connector presence does NOT alter it when
  prefix caching is on (`kv_cache_utils.py:607-611`). A0 vs A1
  `cache_config_info` metrics are identical except num_gpu_blocks profiling
  variance (8108 vs 8585).
- Offload key derivation: deterministic, incremental, alignment-correct
  islice (`offloading/scheduler.py:192-207`); populated fully (the
  `_lookup` assert at ~395 would crash otherwise).
- GPU-side caching not skipped: `delay_cache_blocks` only for async-load
  requests (overlay `sched/scheduler.py:728`), never taken (zero loads);
  `enable_caching` True (queries recorded AFTER the skip-branch,
  `kv_cache_manager.py:210-231`).
- Deployed `sched/scheduler.py` is byte-identical to the local overlay copy
  (`planning/01-raw/upstream-dspark/recipe/overlay/vllm/v1/core/sched/
  scheduler.py`) — one source of truth.
- OffloadingConnector does NOT override `bind_gpu_block_pool` /
  `on_new_request` (base no-ops); `get_block_ids_with_load_errors` not
  implemented → `invalid_block_ids` empty → the prefix-entry-destroying
  `evict_blocks` path (`block_pool.py:435-452`) never ran.
- `request_finished` registers pending-store fences only, returns
  (False, None) — no block-freeing changes (`offloading/scheduler.py:916-944`).

## 5. Candidate mechanisms (ranked; D0 discriminates)

- **C1 (primary): async-scheduling placeholder/optimistic-token interaction
  with request block-hash extension under MTP + chunked prefill.** Upstream
  PR #27648 ("Offloading connector async scheduling support") documents that
  under async scheduling "scheduled-but-not-yet-generated tokens may
  temporarily reduce available block hashes vs. the optimistic boundary";
  the deployed fork has a related but different accommodation
  (`num_offloadable_tokens = min(num_tokens_after_batch, req.num_tokens)`,
  `offloading/scheduler.py` ~683). If the fork's async path lets
  optimistic/placeholder token state reach `update_block_hashes()` (or
  re-extends hashes across the optimistic boundary differently per pass),
  hash values become timing-dependent — exactly the proven anomaly. This is
  a fork-lineage-specific code path (async_scheduling + dspark MTP) that
  upstream's connector was never tested against in this combination.
- **C2: fork snapshot vs upstream drift in the offloading scheduler
  itself.** Deployed `offloading/scheduler.py` (996 lines) is a mid-refactor
  snapshot; upstream is at 1775 lines with `hashes_per_chunk`,
  `LookupResult`, partial-tail, and multiple bugfixes in the exact store/hash
  bookkeeping area (Section 6). A now-fixed bookkeeping bug may simply be
  present in the snapshot.
- **C3 (explains GPU side only, cannot explain Proof 1): DSv4-Flash hybrid
  coordinator single-storage first-block entry destruction — upstream
  #42948.** Kept on the list because it is DSv4-specific, currently OPEN
  upstream, and would independently degrade GPU hits under block-reassignment
  churn; but it is connector-independent and A0 hits fine, so it is not the
  A1 root cause.

## 6. Upstream references (fork lineage confirmed: base commit
`1967a5627bc3` exists in vllm-project/vllm)

- Directly-relevant open bugs: [#42948 DSv4-Flash hybrid groups lose
  first-block cache keys on reassignment](https://github.com/vllm-project/vllm/issues/42948),
  [#43093 DSv4-Flash + OffloadingConnector crashes (stale hash_block_size)](https://github.com/vllm-project/vllm/issues/43093),
  [#33864 offloading misses decode-formed blocks (block_hashes not yet
  available in _get_reqs_to_store)](https://github.com/vllm-project/vllm/issues/33864).
- Async-scheduling support for this connector: [PR #27648](https://github.com/vllm-project/vllm/pull/27648).
- Post-snapshot upstream fixes in this exact area (commits to
  `offloading/scheduler.py` after 2026-05-27): #46972 (store interior
  chunk-boundary blocks under MTP/Eagle), #49285 (num_tokens_after_batch
  termination types), #48596 (offload last block at finish + reuse race),
  #49052 (bound unaligned SWA loads), #48911 (preserve reachable SWA tails),
  #48102 (stale transfer_jobs after reset_cache), #46231/#45823 (defer
  reads/finish while transfers pending), #25856 (GPU block tracking on
  failed prepare_store).
- Operational note from NVIDIA Dynamo's OffloadingConnector guide: they run
  `PYTHONHASHSEED=0` ("deterministic block hashes across workers") — required
  hygiene for any cross-instance hash sharing; also makes `NONE_HASH`
  deterministic across restarts (upstream later made this default: #51875
  "Make prefix-cache NONE_HASH deterministic by default").

## 7. D0 — the decisive 30-minute diagnostic arm (zero code changes)

Goal: observe the actual block-hash bytes at cache/store time vs lookup time
and pin where divergence enters. Mechanism: KV cache events carry raw hashes.

1. Campaign window, A1 config + TWO additions (env/compose only, .bak'd):
   `--kv-events-config '{"enable_kv_cache_events":true,"publisher":"zmq",
   "endpoint":"tcp://127.0.0.1:19555","topic":"kv"}'` and
   `PYTHONHASHSEED=0` (hygiene; also removes one variable). Note:
   `enable_kv_cache_events` also activates the offload manager's events
   (`cpu/spec.py:64-67` wires it into CPUOffloadingManager).
2. Local subscriber (~100 lines, tmp/) records: GPU-side BlockStored/
   BlockRemoved (block_pool events, per group) and connector-side
   BlockStored/BlockRemoved (`offloading/scheduler.py:946-965` take_events →
   hashes + medium).
3. Probe battery, all at temperature 0: (a) 3K-token probe A; (b) identical
   probe A again; (c) 20K-token probe B prefilled in ≥3 chunks (exceeds
   6144/pass) with max_tokens 200 (exercises MTP decode boundary).
4. Read out, per anomaly:
   - Probe B's connector BlockStored streams: same hash stored twice across
     passes ⇒ per-pass instability CONFIRMED + the pass boundary identifies
     the writer; hashes all-unique-per-pass ⇒ hash-input instability (C1);
     hashes stable but re-stored ⇒ manager/bookkeeping (C2).
   - Probe A vs A': GPU BlockStored hash sets equal ⇒ cross-request hashing
     fine, table entries being destroyed (C3-family); unequal ⇒ C1 at
     request-creation level.
5. Rollback per campaign template. Total: 1 boot + 15 min probes.

## 8. Fix draft

- **Preferred (fold into Phase B D0/D1): upgrade the offloading stack (and
  its sched/scheduler.py touchpoints) to upstream-current in the Phase B
  image rebuild**, picking up the Section 6 fix set wholesale. Scope: the
  offloading connector tree + `v1/kv_offload/` + the scheduler hook deltas;
  estimated 2-4 days of overlay/rebase work + the existing image pipeline,
  amortized because Phase B rebuilds the image anyway. Re-run the A1 gate
  battery (offload-hit correctness kill-arm) before any NVMe work.
- **Fallback (if D0 pins a fork-local one-liner):** minimal overlay patch at
  the pinned line + A1 gate re-run; keep the upstream upgrade as Phase B+1
  hygiene.
- Either path: add `PYTHONHASHSEED=0` to both hosts' env (Dynamo-documented
  practice, prerequisite for any future cross-instance/persistent tier), and
  add a standing acceptance probe: identical-prompt-twice must show
  `cached_tokens > 0` while a connector is enabled (this exact check was the
  A1 kill trigger and takes <1 min in run-vllm-acceptance.sh).

## 9. What this means for Phase B (design doc updated separately, Rev 2)

- D0 + fix is a hard prerequisite (new schedule item D0 before D1).
- Write-budget note: at the proven ~13x amplification, an NVMe tier would
  absorb ~160-200 MB/s of sustained junk writes (~1.5 TB/day at incident
  traffic) and never hit — endurance + futility. Post-fix budget returns to
  the designed 12-15 MB/s steady / 63 MB-per-step bursts.
- The A1 soak calibration curves were never produced (arm killed early);
  all `[A1-cal]` parameters re-tagged `[B0-cal]` or given conservative fixed
  values in the design doc Rev 2.

---

# Rev 2 (2026-09-01) — corrections and additions from the rebase scoping study

Source: `planning/02-working/2026-09-01-kv-offload-upstream-rebase-scope.md`
(read-only blob-provenance audit of the image's offloading stack against
vllm-project/vllm history, plus function-level diff of the fork's boundary
files). The body above is preserved unmodified as the original reasoning
record; where this Rev contradicts it, this Rev wins.

## R2.1 Baseline lineage correction (supersedes the Section 6 heading claim)

- Section 6's claim "base commit `1967a5627bc3` exists in vllm-project/vllm"
  is a **GitHub fork-network artifact**: the API resolves commits from ANY
  fork in the network. `1967a5627bc3` ("fix(sm120): pass scratch for small
  prefill chunks", 2026-05-27) is a private vllm-spark commit and is NOT in
  upstream history (`git rev-parse` on a fresh upstream clone: unknown
  revision).
- The true upstream baseline is **`7e33081cee7b` (2026-05-26)**, proven by
  byte-level blob provenance: 42 of 46 audited offloading-stack and
  hash-touchpoint files in the live image are byte-identical to upstream at
  exactly this commit (zero mismatches as a set). The 4 non-matching files
  are fork-modified boundary files, none inside the offloading stack.
- Consequence: the deployed offloading stack (`v1/kv_offload/**`,
  `offloading/*`, `offloading_connector.py`) is **100% pristine upstream
  code** frozen the day before the v0.22 release train. Everything we had
  assumed was "fork V4 offload customization" (GroupOffloadConfig SWA
  alignment, the DSv4 store-skip, `_get_kv_cache_config_deepseek_v4`) is
  upstream code. The stack is missing ~120 upstream commits since baseline,
  of which **~23 are fixes directly relevant to our configuration** (the
  Section 6 set plus R2.3 below).

## R2.2 Candidate C2 rewording

C2 should read: **"pristine but STALE upstream snapshot missing ~20 later
fixes"**, not "fork mid-refactor snapshot" — there are NO fork edits inside
the offloading stack. Likewise, the `num_offloadable_tokens =
min(num_tokens_after_batch, req.num_tokens)` accommodation cited under C1 as
"a related but different accommodation" of the fork is in fact upstream
baseline code, not a fork change. C1's substance (async-scheduling + MTP +
chunked prefill interaction) stands, but the fork-specific part of that
surface is now precisely R2.4, not the connector scheduler.

## R2.3 Additional config-relevant upstream fixes (extends the Section 6 list)

Found during rebase scoping; each directly touches mechanisms our deployment
uses (hybrid HMA groups, nvfp4_ds_mla, MTP, chunked prefill, load-failure
semantics). Merge SHAs on upstream main:

| SHA | Date | PR | Subject (relevance) |
| --- | --- | --- | --- |
| 7ad894c86 | 06-16 | #44784 | Prevent cuMemcpyBatchAsync segfault with MTP + KV offloading |
| 32aef4438 | 07-14 | #48411 | Include inline per-token-head scales in offloaded page transfer width (nvfp4/fp8 scale-carrying KV — OUR dtype) |
| 12f2c515a | 07-16 | #48530 | Fix `set_` overflow for packed non-uniform KV caches (our 37,376 B vs 1,168 B heterogeneous pages) |
| bed3280f5 | 08-31 | #50696 | Order CPU→GPU loads against the compute stream (load correctness) |
| 480fadab1 | 06-02 | #42959 | Prevent offloading stale sliding-window blocks (SWA groups) |
| 798185d43 | 06-27 | #46888 | Fix tensors_per_block stride (multi-tensor pages) |
| 1b0ce31f3 | 08-09 | #49328 | Failed-load livelock → mark lookup verdict a miss (the load-failure semantics Phase B relies on) |
| e6bfe03ad | 08-27 | #52227 | Count store offers, not lookups, for store_threshold |
| cf9fd6457 | 06-24 | #46284 | Fix request-finished lifecycle contract |
| d30b1ecd1 | 07-25 | #49671 | Defer request finalization until final store |

Core-side (scheduler/cache-manager) fixes in the connector × hybrid × async
intersection, also absent from the image: e9e08c49b (#44082, EAGLE/MTP
lookahead block in SWA prefix-cache mask — upstream twin of the fork's
`eagle_extra_cache_blocks`), a6183563b (#43447, DSv4 selective prefix-cache
retention — upstream twin of the fork's protected-prompt-blocks), 373eb314a
(#46066) + a0c092ee7 (#48245) (num_output_placeholders underflow with async
scheduling + spec decode — directly adjacent to Patch 3's territory),
530852f95 (#48481, PD async-scheduling race for hybrid models), 229e01e9e
(#48425) + d6941300f (#50344) (per-group prefix-hit divergence for hybrid
models with a KV connector), 8950394e0 (#48860, prefix-cache metrics
double-count when a connector defers requests).

Note also: the fix-set map in the scoping doc Section 2.1 gives merge SHAs
for all Section 6 items, and found that the coordinator comment citing
"PR #41834 (e6c46a50fb)" refers to a PR/SHA that does not exist upstream —
that tail-block alignment scheme is fork-local code with an unverifiable
citation.

## R2.4 The fork's only code in the hash/caching pipeline — D0's precise
discrimination targets

With the offloading stack proven pristine, the fork-local suspect surface
reduces to exactly two features in the boundary files:

1. **DSpark Patch 3** — `Scheduler.update_from_output`
   (`$VLLM/v1/core/sched/scheduler.py`, overlay): under async scheduling,
   resizes `request.spec_token_ids = [-1] * draft_len` from
   `model_runner_output.draft_token_lengths` (field added in
   `v1/outputs.py`), decode-only guarded. Placeholder token state adjacent
   to the hash-extension timeline; upstream's #46066/#48245 fix underflows
   in the same mechanism and are absent from the image.
2. **Protected-prompt-blocks + eagle-mask machinery** —
   `kv_cache_manager.allocate_slots` → `_has_enough_free_blocks` release
   cascade; `kv_cache_coordinator.verify_and_split_kv_cache_groups`
   (per-manager `cache_alignment_tokens`, `eagle_extra_cache_blocks`),
   `HybridKVCacheCoordinator.cache_blocks` (lcm truncation removed),
   `release_protected_prompt_blocks`; `single_type_kv_cache_manager`
   (+189 lines: `_protect_prompt_blocks` et al., new `MLAAttentionManager` /
   `SlidingWindowMLAManager`, `SlidingWindowManager._cache_block_mask`
   eagle disable). Extra block_pool references and altered cache_blocks
   truncation sit directly in the GPU-side caching path of Proof 2.

**D0 readout addition (extends Section 7 step 4):**

- If the divergence signature localizes to Patch 3's placeholder resize —
  connector BlockStored hash instability appearing only on passes where
  `draft_token_lengths` triggers the `spec_token_ids` resize (MTP decode
  boundaries), or probe B unstable while pure-prefill probe A/A' is stable —
  **the fix belongs to a fork-side shim (Patch 3 / placeholder handling,
  possibly adopting upstream #46066/#48245 semantics), NOT to the upstream
  vendor swap** — vendoring the offloading subtree alone would not fix A1.
- Conversely, instability independent of decode/MTP passes (present in
  chunked-prefill-only passes) points at the stale-snapshot bugs (C2) or
  the protected-prompt-blocks interaction; the vendored subtree at
  `f5e441de10bd` (scoping doc Section 5.3) is then the fix vehicle, with
  the protected-blocks hypothesis checked by the GPU-side (probe A/A')
  readout.

## R2.5 Effect on Section 8 (fix draft)

The "upgrade the offloading stack to upstream-current" path is now concretely
scoped: **vendored subtree replacement at pinned upstream main SHA
`f5e441de10bd`** (per-fix cherry-picking is mechanically dead — 3 of 23 fixes
apply cleanly; whole-image tag upgrade rejected on the documented GB10/SM120
boot-failure precedent). Route, shims, and the revised effort estimate
(expected 2 d, worst ~5 d, replacing "2-4 days") are in the scoping doc
Sections 5-6. The Section 8 fallback ("minimal overlay patch if D0 pins a
fork-local one-liner") now has a concrete candidate location: R2.4 item 1.
