#!/usr/bin/env python3
"""D1a headless repro — run INSIDE the production image (f277b3d) with the
assembled overlay tree BIND-MOUNTED over site-packages (same file set as the
Dockerfile COPYs + worker-dir removal; run via repro_run.sh). Exercises every
boot-failure call path in seconds, pre-build:

  boot 1: interface import + registry bootstrap (is_uniform_type ladder)
  boot 2: get_page_sizes on the group (fork pool sizing)
  boot 3: fork-style KVCacheTensor(**{size, shared_by}) construction
  boot 4: _max_memory_usage_bytes_from_groups (max_in_flight_tokens path)
  boot 5: build_offloading_config (cache_config.kv_cache_layout path)

Exit 0 = all paths pass on the WOULD-BE image content.
"""
import sys
from types import SimpleNamespace

import torch

import vllm.v1.kv_cache_interface as ifc
from vllm.v1.core.kv_cache_utils import (
    _get_kv_cache_groups_uniform_groups,
    _max_memory_usage_bytes_from_groups,
    group_and_unify_kv_cache_specs,
)
from vllm.distributed.kv_transfer.kv_connector.v1.offloading.config import (
    build_offloading_config,
)

# DSv4-shaped specs (nvfp4 MLA + SWA MLA)
mla = ifc.MLAAttentionSpec(
    block_size=256, num_kv_heads=1, head_size=512,
    dtype=torch.uint8,
    cache_dtype_str="nvfp4_ds_mla", model_version="deepseek_v4",
    compress_ratio=1,
)
swa = ifc.SlidingWindowMLASpec(
    block_size=8, num_kv_heads=1, head_size=146,
    dtype=torch.uint8, sliding_window=8192,
    compress_ratio=1, model_version="deepseek_v4",
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
    cache_config=SimpleNamespace(
        block_size=256, enable_prefix_caching=True, hash_block_size=None
    ),
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

# boot-5 path: connector config assembly on the worker side (CPU tier).
# cache_config deliberately LACKS kv_cache_layout (fork shape) — the 2.0h
# getattr shim must tolerate it; any other unshimmed read trips here.
kcc = SimpleNamespace(
    num_blocks=1000,
    kv_cache_tensors=[SimpleNamespace(size=mla.page_size_bytes * 1000)],
    kv_cache_groups=groups,
)
cfg2 = SimpleNamespace(
    model_config=SimpleNamespace(
        use_mla=True, dtype="uint8", model="deepseek-v4-flash",
        get_total_num_kv_heads=lambda: 1,
    ),
    parallel_config=SimpleNamespace(
        tensor_parallel_size=2, pipeline_parallel_size=1,
        prefill_context_parallel_size=1, decode_context_parallel_size=1,
        world_size=2, rank=0, distributed_executor_backend="mp",
        nnodes_within_dp=1, data_parallel_index=0, data_parallel_size=1,
        data_parallel_rank_local=True,
    ),
    cache_config=SimpleNamespace(
        cache_dtype="nvfp4_ds_mla", enable_prefix_caching=True, block_size=256,
        hash_block_size=None,
    ),
    kv_events_config=None,
    kv_transfer_config=SimpleNamespace(
        kv_connector_extra_config={"cpu_bytes_to_use": 8589934592},
        engine_id="repro",
    ),
    use_v2_model_runner=False,
)
oc = build_offloading_config(cfg2, kcc)
assert oc.kv_cache_layout is None, oc.kv_cache_layout
assert len(oc.groups) == len(groups)

# full connector import chain (the in-build smoke, re-checked here)
from vllm.distributed.kv_transfer.kv_connector.v1 import offloading_connector  # noqa: E402, F401

print(f"HEADLESS REPRO PASS: groups={len(groups)} total_bytes={total} "
      f"swa_bytes={swa_bytes} connector_groups={len(oc.groups)} "
      f"kv_cache_layout={oc.kv_cache_layout}")
sys.exit(0)
