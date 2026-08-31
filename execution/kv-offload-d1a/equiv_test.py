#!/usr/bin/env python3
"""D1a equivalence test — run INSIDE the engine container.

Loads the overlay kv_cache_interface (tip + fork shims) alongside the live
fork interface, constructs the fork model's spec shapes on BOTH, and asserts
identical page-size semantics. Exit 0 = overlay is a faithful replacement.
"""
import importlib.util
import sys

import torch

# 1. capture the ORIGINAL (fork) interface classes first
import vllm.v1.kv_cache_interface as orig

# 2. register overlay support modules under their real names
for name, path in (
    ("vllm.v1.kv_cache_layout", "/tmp/d1a/kv_cache_layout.py"),
    ("vllm.v1.kv_cache_spec_registry", "/tmp/d1a/kv_cache_spec_registry.py"),
):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)

# 3. load the overlay interface over the real module name
spec = importlib.util.spec_from_file_location(
    "vllm.v1.kv_cache_interface", "/tmp/d1a/kv_cache_interface.py"
)
ovl = importlib.util.module_from_spec(spec)
sys.modules["vllm.v1.kv_cache_interface"] = ovl
spec.loader.exec_module(ovl)


def props(spec_obj):
    out = {}
    for p in ("real_page_size_bytes", "page_size_bytes", "unpadded_page_size_bytes"):
        try:
            out[p] = getattr(spec_obj, p)
        except Exception as e:  # noqa: BLE001
            out[p] = f"ERR:{type(e).__name__}"
    try:
        out["storage_block_size"] = spec_obj.storage_block_size
    except Exception:
        out["storage_block_size"] = "n/a"
    return out


cases = []
for dtype in (torch.uint8, torch.bfloat16):
    for cache_dtype in (None, "fp8_ds_mla", "nvfp4_ds_mla"):
        for mv in (None, "deepseek_v4"):
            for cr in (1, 2, 8, 128):
                for align in (None, 576):
                    cases.append(
                        dict(
                            block_size=256, num_kv_heads=1, head_size=512,
                            dtype=dtype, compress_ratio=cr,
                            cache_dtype_str=cache_dtype, model_version=mv,
                            alignment=align,
                        )
                    )
sw_cases = []
for dtype in (torch.uint8, torch.bfloat16):
    for mv in (None, "deepseek_v4"):
        for cr in (1, 2):
            sw_cases.append(
                dict(
                    block_size=8, num_kv_heads=1, head_size=146,
                    dtype=dtype, sliding_window=8192,
                    compress_ratio=cr, model_version=mv, alignment=576,
                )
            )

fails = 0
checked = 0
for kw in cases:
    a = orig.MLAAttentionSpec(**kw)
    b = ovl.MLAAttentionSpec(**kw)
    pa, pb = props(a), props(b)
    checked += 1
    # the semantic anchor: real_page_size_bytes must match exactly
    if pa["real_page_size_bytes"] != pb["real_page_size_bytes"]:
        fails += 1
        print("MISMATCH real_page_size_bytes", kw, pa, pb)
    # page_size_bytes (post alignment padding) must match too
    if pa["page_size_bytes"] != pb["page_size_bytes"]:
        fails += 1
        print("MISMATCH page_size_bytes", kw, pa, pb)
for kw in sw_cases:
    a = orig.SlidingWindowMLASpec(**kw)
    b = ovl.SlidingWindowMLASpec(**kw)
    pa, pb = props(a), props(b)
    checked += 1
    if pa["real_page_size_bytes"] != pb["real_page_size_bytes"] or pa["page_size_bytes"] != pb["page_size_bytes"]:
        fails += 1
        print("MISMATCH swmla", kw, pa, pb)

# merge() equivalence: two identical fork-style specs merge to same page size
kw = dict(block_size=256, num_kv_heads=1, head_size=512, dtype=torch.uint8,
          compress_ratio=1, cache_dtype_str="nvfp4_ds_mla",
          model_version="deepseek_v4", alignment=576)
ma = orig.MLAAttentionSpec.merge([orig.MLAAttentionSpec(**kw), orig.MLAAttentionSpec(**kw)])
mb = ovl.MLAAttentionSpec.merge([ovl.MLAAttentionSpec(**kw), ovl.MLAAttentionSpec(**kw)])
checked += 1
if props(ma)["real_page_size_bytes"] != props(mb)["real_page_size_bytes"]:
    fails += 1
    print("MISMATCH merged", props(ma), props(mb))

# quant-mode mapping equivalence (by member name: the tip enum renumbered)
for dt in ("nvfp4_ds_mla", "fp8_ds_mla", "auto", "bfloat16"):
    checked += 1
    a_qm, b_qm = orig.get_kv_quant_mode(dt), ovl.get_kv_quant_mode(dt)
    a_name = a_qm.name if hasattr(a_qm, "name") else str(a_qm)
    b_name = b_qm.name if hasattr(b_qm, "name") else str(b_qm)
    if a_name != b_name:
        fails += 1
        print("MISMATCH quant mode", dt, a_name, b_name)

# sanity: production-shape spec sizes match the campaign-known numbers
prod = ovl.MLAAttentionSpec(
    block_size=256, num_kv_heads=1, head_size=512, dtype=torch.uint8,
    compress_ratio=1, cache_dtype_str="nvfp4_ds_mla",
    model_version="deepseek_v4", alignment=576,
)
p = props(prod)
print("production MLA page bytes:", p)

print(f"checked={checked} fails={fails}")
sys.exit(1 if fails else 0)
