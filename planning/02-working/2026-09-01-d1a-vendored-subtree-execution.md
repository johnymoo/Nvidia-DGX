# D1a: Vendored Offload Subtree Replacement — Execution Record (2026-09-01)

Status: **code complete and locally validated; NOT yet built or booted.**
Implements `planning/02-working/2026-09-01-kv-offload-upstream-rebase-scope.md`
§5.3 (route iii) at pin `f5e441de10bd` (upstream main, 2026-08-31). User
decision 2026-09-01 morning: skip D0, go direct to D1a; D0 assets stay ready
(`tmp/kv-offload-d0/`) if the D1b kill gate still fails.

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
   to D0 (`tmp/kv-offload-d0/` runbook is execution-ready).

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
