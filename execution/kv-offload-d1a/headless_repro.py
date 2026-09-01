#!/usr/bin/env python3
"""D1a headless repro — run INSIDE the production image (f277b3d) with the
assembled overlay trio mounted at /tmp/d1a. Reproduces every boot-failure
call path in seconds, pre-build:

  boot 1: interface import + registry bootstrap (is_uniform_type ladder)
  boot 2: get_page_sizes on the group (fork pool sizing)
  boot 3: fork-style KVCacheTensor(**{size, shared_by}) construction
  boot 4: _max_memory_usage_bytes_from_groups (max_in_flight_tokens path)

Exit 0 = all paths pass on the WOULD-BE image content.
"""
import importlib.util
import sys
from types import SimpleNamespace

# 1. overlay trio over the real module names (proven equiv_test pattern:
#    sys.modules entry BEFORE exec, layout+registry before interface)
for name in ("vllm.v1.kv_cache_layout", "vllm.v1.kv_cache_spec_registry",
             "vllm.v1.kv_cache_interface"):
    spec = importlib.util.spec_from_file_location(name, f"/tmp/d1a/{name.split('.')[-1]}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)

import vllm.v1.kv_cache_interface as ifc  # noqa: E402  (overlay)

# 2. fork core kv_cache_utils binds the OVERLAY interface (imported after
#    the override) — faithful to the boot call chain
from vllm.v1.core.kv_cache_utils import (  # noqa: E402
    _get_kv_cache_groups_uniform_groups,
    _max_memory_usage_bytes_from_groups,
    group_and_unify_kv_cache_specs,
)

# 3. DSv4-shaped specs (nvfp4 MLA + SWA MLA, production page sizes)
mla = ifc.MLAAttentionSpec(
    block_size=256, num_kv_heads=1, head_size=512,
    dtype=__import__("torch").uint8,
    cache_dtype_str="nvfp4_ds_mla", model_version="deepseek_v4",
    compress_ratio=1,
)
swa = ifc.SlidingWindowMLASpec(
    block_size=8, num_kv_heads=1, head_size=146,
    dtype=__import__("torch").uint8, sliding_window=8192,
    cache_dtype_str="nvfp4_ds_mla", model_version="deepseek_v4",
    compress_ratio=1,
)
assert mla.page_size_bytes > 0 and swa.page_size_bytes > 0
print(f"spec pages: mla={mla.page_size_bytes} swa={swa.page_size_bytes}")

groups = _get_kv_cache_groups_uniform_groups(
    group_and_unify_kv_cache_specs({"mla": mla, "swa": swa})
)
assert len(groups) >= 1

# boot-2 path: get_page_sizes on each group's unified spec
for g in groups:
    g.kv_cache_spec.get_page_sizes()

# boot-3 path: fork-style KVCacheTensor construction
t = ifc.KVCacheTensor(size=1024, shared_by=["mla"])
assert t.size == 1024 and t.shared_by == ["mla"]

# boot-4 path: startup memory check with a fork-shaped config mock.
# Attrs = exactly what the overlay reads (audit_config_reads); a missing
# attr raises AttributeError = tripwire for unshimmed config reads.
cfg = SimpleNamespace(
    model_config=SimpleNamespace(max_model_len=1048576),
    scheduler_config=SimpleNamespace(max_num_batched_tokens=8192),
    parallel_config=SimpleNamespace(
        decode_context_parallel_size=1, pipeline_parallel_size=1
    ),
    cache_config=SimpleNamespace(block_size=256),
)
total = _max_memory_usage_bytes_from_groups(cfg, groups)
assert isinstance(total, int) and total > 0, total

# 2.0g cross-check on the spec directly (SWA-only input is invalid for
# group_and_unify — DSv4 branch requires an MLA spec): fork formula is
#   blocks = cdiv(min(sliding_window-1 + max_num_batched_tokens, max_model_len),
#                 block_size) + 1;  bytes = blocks * page_size_bytes
swa_bytes = swa.max_memory_usage_bytes(cfg)
expect_blocks = -(-min(8192 - 1 + 8192, 1048576) // 8) + 1  # cdiv + 1
assert swa_bytes == expect_blocks * swa.page_size_bytes, (
    swa_bytes, expect_blocks * swa.page_size_bytes)

print(f"HEADLESS REPRO PASS: groups={len(groups)} total_bytes={total} "
      f"swa_bytes={swa_bytes} (fork formula exact)")
