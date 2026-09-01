# D1a: Vendored Offload Subtree Replacement — Execution Record (2026-09-01)

Status: **code complete and locally validated; NOT yet built or booted.**
Implements `planning/02-working/2026-09-01-kv-offload-upstream-rebase-scope.md`
§5.3 (route iii) at pin `f5e441de10bd` (upstream main, 2026-08-31). User
decision 2026-09-01 morning: skip D0, go direct to D1a; D0 assets stay ready
(`execution/kv-offload-d0/`) if the D1b kill gate still fails.

## What shipped (66 files into `recipe/overlay/vllm/`)

| Kind | Count | Content |
| --- | --- | --- |
| vendored-pristine | 62 | byte-exact upstream @ `f5e441de10bd`: the 59-file offloading stack (§5.3 list), plus 3 discovered transitive deps: `v1/kv_cache_layout.py` (58-line leaf enum module), `v1/kv_cache_spec_registry.py` (209-line leaf registry), `distributed/kv_events.py` (whole file; diff vs image baseline is additive: MEDIUM_CPU/MEDIUM_STORAGE constants + optional event fields; only removal is the msgspec `array_like` wire-format flag) |
| tip+fork-shims | 2 | `v1/kv_cache_interface.py`, `distributed/kv_transfer/kv_connector/v1/base.py` |
| image+backports | 2 | `v1/core/kv_cache_utils.py` (image content + appended `get_none_hash_seed`, `BlockHashListWithBlockSize`, `resolve_block_hashes`), `distributed/device_communicators/shm_broadcast.py` (image content + appended `check_shm_free_space`) |

Provenance manifest: `recipe/overlay/vllm-d1a-kv-offload.MANIFEST.tsv`
(path, kind, sha256, upstream-blob-sha-at-pin where pristine).

Deletion handled in-image: `v1/kv_offload/worker/` (upstream #45053 removed
it) + stale `__pycache__` under all replaced paths — see the `RUN rm/find`
block in `recipe/Dockerfile.dspark-runtime-overlay`.

## The two shimmed files (markered `# D1a` in-file)

### `v1/kv_cache_interface.py` — tip + fork arithmetic re-applied
Upstream REFACTORED the spec API between baseline and tip: `compress_ratio` /
`storage_block_size` were removed in favor of `tokens_per_state` /
`state_content_bytes`, and page-size arithmetic moved from dtype-switch
properties into model-layer construction values. The fork's
`deepseek_v4` model code (grade C, untouched) still constructs specs with
`compress_ratio=` and relies on interface-level dtype arithmetic. The shim:
- re-adds `compress_ratio: int = 1` + `storage_block_size` on
  `MLAAttentionSpec` and `SlidingWindowMLASpec`; both `merge()`s carry it;
- re-applies the fork's real-page-size arithmetic (fp8_ds_mla 584/656,
  nvfp4_ds_mla 584/416, generic) as `real_page_size_bytes`, overriding tip's
  `unpadded_page_size_bytes` whenever the spec is fork-constructed
  (packed ds_mla dtype OR compress_ratio != 1 — the latter matters for the
  DSv4 indexer spec, which has no cache_dtype_str);
- hunk 1 of the fork delta (nvfp4_ds_mla → KVQuantMode.NVFP4) is superseded
  upstream (`startswith("nvfp4")`), not re-applied.

**Validation (decisive):** in-container equivalence test
(`tmp/kv-offload-d1a/equiv_test.py`, run under the image's /opt/env python
3.12 + torch against the LIVE fork interface): 109/109 checks pass — full
matrix (dtype × cache_dtype × model_version × compress_ratio × alignment) on
both MLA classes, `merge()`, quant-mode mapping by member name. Production
shape exact: MLA page 149,504 B real / 149,760 B padded (584 × 256, aligned
to 576) — identical to the live fork interface. Note: tip renumbered the
KVQuantMode enum (NVFP4=5); identity is member-based, value differences are
expected and harmless.

### `kv_connector/v1/base.py` — tip + cross-layer stubs
Upstream removed `register_cross_layers_kv_cache` / `prefer_cross_layer_blocks`;
the fork's `gpu_model_runner.py:7503` calls the former and the image's
`kv_connector_model_runner_mixin.py:157` reads the latter. Two no-op stubs
(restoring baseline signatures) appended to `KVConnectorBase_V1`.

## Build-pipeline changes

- `recipe/Dockerfile.dspark-runtime-overlay`: D1a header + pin label, rm/find
  cleanup RUN, 12 new COPY entries (2 dir-trees + 10 files), extended
  compile gate (`compileall` over every replaced path). Existing 18 dspark
  COPYs untouched.
- `recipe/nvfp4/Dockerfile.stage-a` and `.stage-c`: the three
  `v1/kv_cache_interface.py` patcher `replace()` calls REMOVED (their output
  is superseded by the overlay file; their anchors no longer exist at tip, so
  the build would have failed). The nvfp4_ds_mla patches for
  `config/cache.py`, `utils/torch_utils.py`, and the attention/kernel files
  remain. This resolves the provenance question of the fork's "+6 lines":
  they were applied by stage-a/stage-c at build time, not baked into the
  base image.
- `scripts/verify-overlay-sources.sh` passes against the new Dockerfile.

## Import-compatibility audit (tooling: `tmp/kv-offload-d1a/audit_imports.py`)

Symbol-level static audit of every `vllm.*` import in the 66 overlay files
against (overlay tree → image). Root-caused and fixed:
`kv_cache_spec_registry` (genuinely absent in image → vendored);
`MEDIUM_CPU/MEDIUM_STORAGE` (→ kv_events vendored whole);
`resolve_block_hashes`/`get_none_hash_seed` (→ additive backport);
`check_shm_free_space` (→ additive backport); `KVCacheLayout`/
`group_kernel_blocks` (→ tip interface vendored with shims). Remaining audit
rows are proven tool artifacts (tuple-unpacked constants, lazy
`__getattr__` attrs, TYPE_CHECKING blocks, enum renumbering); every flagged
module/symbol was individually verified present in the live container
(`docker exec python -c` import check, 2026-09-01). One audit-model
correction worth keeping: the image tree is NOT uniformly
upstream-baseline — the base image is the private vllm-spark tree; only the
46 scoping-audited files are blob-proven upstream-identical.

## What D1b must still do (NOT done here)

1. Build on the hosts via `build-dspark-vllm-runtime.sh` under a NEW image
   tag (do not overwrite `gb10-ds4-vllm:f277b3d-nvfp4`); both gb10 + gb10-2.
   Consider extending the post-overlay smoke test to
   `import vllm.distributed.kv_transfer.kv_connector.v1.offloading_connector`.
2. Throwaway boot + the A1-derived gate battery (identical-prompt-twice
   `cached_tokens > 0`, ≤1.3× store amplification, needle correctness,
   perf band, C1–C5). Window required (production must stop; GPUs are
   fully occupied).
3. Update `run-vllm-service.sh` fingerprint assertion + runbook when the
   new image is accepted.
4. If gates fail with connector×core interaction signatures → Stage 2
   (extend vendored set to `kv_cache_utils`/`block_pool`/`request.py`/
   `sched/output.py` wholesale + re-merge the 4 grade-B files), or fall back
   to D0 (`execution/kv-offload-d0/` runbook is execution-ready).

## Residual risks (accepted, D1b will test)

- Tip offload stack on May-era core is an upstream-untested pairing
  (scoping §5.3). Static import audit cannot see semantic drift in
  `update_connector_output`/preemption interplay.
- `vllm.fs_io_C` (C batch IO for the fs tier) absent in image → guarded
  Python fallback (slower fs tier; only relevant if D1b evaluates the
  upstream fs tier).
- P2P/obj tiers vendored for completeness; unimported in our config.
- p2p `get_none_hash_seed` backport always returns the deterministic
  default (baseline core never seeds a random NONE_HASH).

---

## Rev 2 (2026-09-01, same day) — build executed and validated

**Discovery that changed the build route:** neither host has the original
build chain (fusion base / mia-raf-pr1 / stage tags are gone; only the final
production image remains). The build therefore stacks D1a DIRECTLY on
`gb10-ds4-vllm:f277b3d-nvfp4` via a new
`recipe/Dockerfile.d1a-kvoffload` (durable copy in `execution/kv-offload-d1a/`):
cleanup RUN + the D1a COPY block + compileall + an in-build import smoke.
This is strictly safer than rebuilding the chain: exact running bits as base,
one layer, no network, no tag mutation. Both prior Dockerfiles remain valid
for full-chain rebuilds if the chain images ever return.

**Reverse-dependency audit (new, closing a blind spot of the forward audit):**
the fork's OWN files import symbols from the replaced modules. Enumerated
every `from <replaced-module> import ...` across the image tree. Two real
gaps, one false alarm:

- `TQFullAttentionSpec` — removed upstream, imported by the fork's
  `single_type_kv_cache_manager.py:15`. Re-added to the overlay interface as
  a fork-compat class (baseline definition verbatim).
- `CopyBlocksOp` — my first symbol check missed assignments; it SURVIVES at
  tip (base.py:71) together with `set_host_xfer_buffer_ops` (tip:274). No
  shim needed.
- Build bug caught by the in-build smoke: the first
  `Dockerfile.d1a-kvoffload` omitted the `kv_cache_utils.py` COPY line (the
  compileall referenced the base-image original). Fixed.

**Build results (2026-09-01, service untouched, running container unaffected):**

| Host | Tag | Result |
| --- | --- | --- |
| gb10 | `gb10-ds4-vllm:d1a-kvoffload` | built (sha256:f4308f0a…); import smoke OK |
| gb10-2 | `gb10-ds4-vllm:d1a-kvoffload` | built; import smoke OK |

- Full-chain import smoke inside the image (fork core + tip offload stack
  together: single_type/kv_cache_manager/coordinator/mixin/offloading_*
  /cpu spec+manager/tiering fs): PASS, TQ shim visible.
- Cross-host parity: all 66 overlay files byte-identical between the two
  images (sha256 manifest comparison); `v1/kv_offload/worker/` absent.
- Equivalence test re-run on the FINAL interface (post-TQ-shim): 109/109,
  production MLA 149,504/149,760 B exact.
- Rollback: production image + tag untouched; `docker rmi
  gb10-ds4-vllm:d1a-kvoffload` on both hosts removes the D1a artifacts.

**D1b (pending, needs window): stop production → boot `d1a-kvoffload` with
the A1 connector config → gate battery (identical-prompt-twice cached_tokens
> 0, ≤1.3× amplification, needle, perf band, C1–C5) → adopt or rollback.
Compose edit tooling from Phase A (`edit_files.py`) and the D0 subscriber
kit (`execution/kv-offload-d0/`) are ready if the gate fails.**

---

## Rev 3 (2026-09-01 ~10:30 local) — D1b boot attempts 1-3: three more interface shims; rolled back to production by user decision

User decision (~10:15 local): restore original config during the day; retry
the new image tonight. Rollback executed cleanly (details below).

Three boot attempts, each failing fast (~4-6 min, memory-profiling stage),
each a distinct tip×fork-core interface incompatibility in
`v1/kv_cache_interface.py` — all fixed by new shims in the overlay interface
(marked `# D1a`, assemble.py sections 2.0b-2.0f):

| Boot | Failure | Shim added |
| --- | --- | --- |
| 1 | `ImportError: register_all_kvcache_specs` (tip registry's lazy bootstrap needs tip core) | `is_uniform_type` reverted to the baseline isinstance ladder; `get_kv_cache_spec_kind` wrapper branch de-registry'd |
| 2 | `AttributeError: get_page_sizes` (fork DSv4 pool sizing, 5 call sites) | `get_page_sizes` re-added (baseline body); also `get_num_layer_tuples` alias (tip renamed it) |
| 3 | `TypeError: KVCacheTensor __init__ unexpected kwarg 'shared_by'` (tip redesigned the tensor; fork constructs `{size, shared_by}` only) | tip layout fields defaulted (`layers/layer_stride/block_stride`) + `shared_by` field + `__post_init__` sync; SAFE because the vendored connector derives layout from live torch tensors (`.stride(0)`), never these fields |

Audit hardening between attempts (tools under tmp/kv-offload-d1a/):
- constructor-kwargs audit (all interface dataclasses × fork-core call sites)
  — after 2.0f, zero real gaps (only inherited-field false positives)
- attribute-read audit on spec/tensor/group receivers — no further gaps
- **headless repro** (docker run + file mount): runs `group_and_unify` +
  `_pool_bytes_per_block` + fork-style `KVCacheTensor` construction against
  the patched interface — all pass; catches this failure class pre-build now

Round-4 image (all shims incl. KVCacheTensor) built on gb10
(`b845f104b33e1927473b9d3d7a7eb4e4f05a41c327efc26ee85a367e33a53326`);
gb10-2 sync was in flight at rollback time (round-3 `ca6f3d89` present;
round-4 completes in background). Equiv test re-run after each round: 109/109.

## Rollback record (executed ~10:20 local)

- `rollback-host` both hosts + `rollback-head` on gb10 (tag 20260901T0043);
  spot-verified: KV lines 0/0 in both composes + acceptance, image env =
  f277b3d-nvfp4, KV_OFFLOAD_CPU_BYTES gone, service fp = 36adbf92 restored.
- Restart with original config: run **20260901T022534Z**, acceptance PASS,
  KV pool 8.94 GiB / 1,291,388 tokens.
- Post-restore canary: identical 18,427-token prompt → 2nd request 0.46 s,
  cached_tokens 18,176 — prefix caching healthy (and re-confirms A1's
  zero-hit was connector-caused).
- D1a images left in place on both hosts (d1a-kvoffload tags) for tonight.
- Known script nit: `rollback-host`/`verify` subcommands try to read head
  files and error on the worker (files restore BEFORE the error; verified
  clean by grep) — cosmetic, fix before next campaign.

## Tonight's retry plan (round-4 image)

1. Confirm gb10-2 has `b845f104` fingerprint; refresh head edits
   (`rollback-head` → `head` with NEW_FP=b845f104…; host edits re-apply).
2. `--stop --restore-qwen` (original scripts must be in place BEFORE stop —
   learned: stop loads active.json against the CURRENT fingerprint contract).
3. Re-apply D1b edits (host both + head gb10) → `--start`.
4. Gate battery (fast→slow): canary_twice → amplification + 64K cold perf →
   needle/flood/requery kill-arm → decode + C1-C5 (MAX_TOKENS_OVERRIDE=1024)
   → 20-30 min soak with monitor.sh.
5. Any gate failure → rollback per this record; escalate to Stage 2 (core
   file adoption) or D0 diagnostic (assets ready in execution/kv-offload-d0/).

## Durable copies (2026-09-01, pre-PR)

Session tooling promoted from untracked `tmp/` into the repo (evidence stays
in `tmp/` per Phase A convention):

- `execution/kv-offload-d1a/assemble.py` synced to the final 660-line version
  (shim sections 2.0b-2.0f; the previously committed 466-line copy predated
  boot attempts 1-3).
- `execution/kv-offload-d1b/`: `edit_files.py` (NEW_FP=b845f104…) + gate
  scripts (canary_twice / amplification / needle_offload / correctness /
  probe / monitor).
- `execution/kv-offload-d0/`: full D0 fallback kit (subscriber + probes +
  analyzer + selftest).

---

## Rev 4 (2026-09-02 ~01:00 local) — night retry: boot 4 found `max_in_flight_tokens`; shim 2.0g; round-5 image

User directive (~23:59 local): start after 30 min, wait for in-flight
inference to drain first (last generation finished 00:56), then execute.
Pre-stop evidence: `tmp/followup-tests/20260901T162905Z/d1b/`. Stop clean at
~00:59; D1b edits re-applied tag `20260901T1659` (worker host + head host +
head scripts; verify all-true, worker by grep).

**Boot 4** (~01:04): got PAST group_and_unify and pool sizing — shims
2.0b-2.0f all effective — then died in `_check_enough_kv_cache_memory`:
`AttributeError: 'VllmConfig' object has no attribute 'max_in_flight_tokens'`
(`kv_cache_interface.py:804`, tip `SlidingWindowSpec.max_memory_usage_bytes`).
Root cause: tip added a VllmConfig property
(`max_concurrent_batches * max_num_batched_tokens`, async-sched aware); fork
VllmConfig lacks it and fork's original specs passed
`scheduler_config.max_num_batched_tokens` directly. Both tip read sites
(ChunkedLocalAttentionSpec + SlidingWindowSpec) share one line.

**Fix — shim 2.0g** (assemble.py): both sites now pass
`vllm_config.scheduler_config.max_num_batched_tokens` (fork baseline formula,
kwarg name unchanged) — startup pool check keeps production semantics
instead of importing tip's 2× async-sched inflation.

Audit closure for the class (new tool
`tmp/kv-offload-d1a/audit_config_reads.py`): every `<x>_config.<attr>` read
across the overlay diffed against the fork config classes extracted from the
production image (vllm/scheduler/parallel/cache/model/speculative) —
**exactly one missing attr existed (`max_in_flight_tokens`, 2 sites); all 24
distinct reads now present**. No other config seams anywhere in the 66 files.

`headless_repro.py` promoted to a durable script (was ad-hoc): mounts the
overlay trio over the production image, walks the boot call path
group_and_unify → `_get_kv_cache_groups_uniform_groups` →
`_max_memory_usage_bytes_from_groups` + get_page_sizes + fork-style
KVCacheTensor — PASS in seconds, incl. SWA fork-formula cross-check
(306,333,696 B exact). equiv_test re-run on the 2.0g interface: 109/109,
production MLA pages 149,504/149,760 B unchanged.

Round-5 image building from `/tmp/d1a-build` (only the interface file
changed); then fingerprint → ship to gb10-2 → boot 5.

## Rev 5 (2026-09-02 ~02:00 local) — boot 5: `kv_cache_layout`; shim 2.0h; repro upgraded to full-tree bind-mount

Boot 4 fix (2.0g) held — boot 5 got through scheduler-side checks, KV pool
**8.34 GiB / 1,262,892 tokens**, and INTO connector creation, then died at
worker-side `build_offloading_config`:
`AttributeError: 'CacheConfig' object has no attribute 'kv_cache_layout'`
(offloading/config.py:219). Tip CacheConfig declares it as
`str|None = field(default=None, init=False)` — a post-init resolved field;
the only consumer is the file-tier mapper (asserts not-None). **Shim 2.0h**:
tolerant `getattr(..., "kv_cache_layout", None)` = tip's None default for
the CPU tier, byte-identical semantics. (Phase B file tier will need a real
layout resolution — noted for that design.)

Audit upgraded to depth-2 chains (`vllm_config.<sub>.<attr>` + local
aliases) + dynamic `self.X =` assignments in config __post_init__ surfaces:
after 2.0h the sweep is clean — zero missing reads across all 66 files
(`original_max_model_len` was a false positive: both fork and tip set it
dynamically in __post_init__).

headless repro rebuilt to a **full-tree bind-mount harness** (repro_run.sh
generates per-file `-v` binds of the build-context overlay over
site-packages in the f277b3d image — real import machinery, no sys.modules
gymnastics; caught the fork-stale `offloading/metrics.py →
vllm.v1.kv_offload.worker` trap that only affects registration-based
loading, not the built image). Now covers boots 1-5 paths +
`resolve_kv_cache_block_sizes` + full `offloading_connector` import:
PASS in ~30 s, pre-build. Mock VllmConfig attrs = audit-derived set
(exact tripwire: any unshimmed config read crashes the repro).

Round-6 image `bf11564d…` built (only offloading/config.py changed) and
validated in-image (same repro, no mounts needed for the trio — run against
built tag directly). Head edits rolled back and re-applied with the round-6
fingerprint; shipping to gb10-2; boot 6 next.

## Rev 6 (2026-09-02 ~02:50 local) — boot 6: KVCacheTensor.size semantics; shim 2.0i (Σ tensor sizes)

Boot 5 fix (2.0h) held — boot 6 reached `register_kv_caches` →
`create_next_worker_view` inside the CPU tier's shared mmap region, then:
`AssertionError: Worker offset 8640 exceeds worker area end 1728
(overflowed by 6912 = 4×1728)`. Root cause: **tip vs fork
KVCacheTensor.size semantics**. Tip: every tensor's `.size` = the whole
backing allocation ("its size is the total, not a per-tensor share" — tip's
own comment). Fork: `.size` = per-tensor share (DSv4: 5 uniform-slot
tensors of equal size). `build_offloading_config` derived
`worker_kv_bytes_per_block = tensors[0].size // num_blocks` → 5× too small;
the per-tensor view loop then needs Σ = 5×page per worker. The numbers
reconcile exactly: 8640 required vs 1728 reserved, overflow 6912.

**Shim 2.0i**: `total_gpu_kv_bytes = sum(t.size for t in
kv_cache_tensors)` — fork-compatible total. Cross-checks: A1's cluster
accounting (8 GiB / ~605K tokens ≈ 13.9 KiB/token, fork stack) matches Σ
semantics; the `replicated_layout` gate short-circuits (multi-group), so
the only consumer of the old value is the pool sizing.

Repro extended (boots 1-6 now): SharedOffloadRegion layout math headless
(/dev/shm mmap + 5 worker views with shape/stride asserts, ~30 s; cleanup
BufferError warning is benign and self-logged). Round-7 image `8a741c7a…`
built, repro PASS in-image, head edits re-applied; boot 7 after ship.

## Rev 7 (2026-09-02 ~03:30 local) — boots 7-8: connector fully initializes; capacity wall then fork-core invariant; ROUTE VERDICT

**Boot 7** (round-7, all shims): every interface/config/layout seam clean —
connector fully constructed, mmap region created. Died at the CAPACITY
wall: with the CPU tier pinned (8 GiB cluster = 4 GiB/rank on world_size 2),
"Available KV cache memory" fell 8.34 → 5.63 GiB (pinned + alignment ≈
0.68× exchange rate on unified LPDDR), below the 7.3 GiB floor for
max_model_len 1,048,576. Not a bug — the plan's R2/R3 tradeoff
materializing one level deeper than expected.

**Boot 8** (gmu 0.78 → 0.796 via env+acceptance edits, no image change;
estimated KV ≈ 7.5 GiB + 550K-token CPU tier): died at
`v1/worker/utils.py:155 KVBlockZeroer.init_meta` —
`Non-uniform page sizes: 2160 vs 9360`. Fork's dspark zero-on-free
machinery (anti cross-request-KV-leak) asserts all groups share ONE
uniform page layout; the tip connector's per-group canonical tensor model
violates it. **Not shim-able**: a wrong fix here is silent KV leakage
between requests — precisely the class the kill-gate discipline forbids
improvising.

**Route verdict — vendored subtree (Stage 1) BLOCKED at fork-core
invariants.** Six seams in five boots (2.0b-2.0f interface; 2.0g VllmConfig;
2.0h CacheConfig; 2.0i KVCacheTensor.size semantics; then fork-internal
KVBlockZeroer), each deeper: the two stacks' KV-layout MODELS differ
structurally (fork: uniform-slot shared tensor; tip: per-group canonical).
Bridging at every internal invariant is unbounded and risks correctness.
Evidence: `tmp/followup-tests/20260901T162905Z/d1b/` (pre-stop → boot 8);
tools durable in execution/kv-offload-d1a/ (audits + repro cover boots 1-6
classes pre-build).

**What the campaign still proved**: A0-era seam map, the full connector
config/layout pipeline works through register_kv_caches on the vendored
stack, capacity exchange rate measured (pinned:KV ≈ 0.68×), and the A1
zero-hit question remains untested empirically (never served a request).

**Next (user-directed Phase B)**: custom per-rank NVMe OffloadingSpec on
the FORK-NATIVE stack (factory `spec_module_path`, no image rebuild —
A1 proved the fork stack boots and serves; its defect was the CPU spec's
store-on-fill policy, which a custom spec replaces with store-on-eviction,
directly dissolving the A1 structural law without any vendoring).

Rolled back cleanly ~03:30 (both .bak-1659 sets + env/acceptance gmu
edits covered by the same restores; worker env byte-identical to
pristine). Production restart = see restore record below.
