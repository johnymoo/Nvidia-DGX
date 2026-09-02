#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Boot-path instantiation tests for NVMeTieredOffloadingSpec (no GPU).

Everything here runs at PRODUCTION BOOT and nowhere else — the logic tests
never construct the spec. Runs in a plain container of the image:
  docker run --rm --entrypoint python3 \
    -v /home/<user>/phase-b-nvme:/opt/pkg:ro \
    -e PYTHONPATH=/opt/pkg -e PYTHONHASHSEED=0 \
    gb10-ds4-vllm:f277b3d-nvfp4 /opt/pkg/test_boot_paths.py
"""
import os
import sys
import tempfile
from types import SimpleNamespace

import vllm_nvme_tier.spec as spec_mod
from vllm_nvme_tier.spec import NVMeTieredOffloadingSpec

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"ok   {name}")
    else:
        FAIL += 1
        print(f"FAIL {name}")


def fake_layer(page_bytes, real_bytes, block_size=256):
    return SimpleNamespace(
        block_size=block_size,
        page_size_bytes=page_bytes,
        real_page_size_bytes=real_bytes,
    )


def fake_group(layers, name_suffix):
    # duck-typed UniformTypeKVCacheSpecs: .kv_cache_specs dict + .block_size
    inner = {f"{name_suffix}-l{i}": ly for i, ly in enumerate(layers)}
    agg = SimpleNamespace(
        kv_cache_specs=inner,
        block_size=256,
        page_size_bytes=sum(l.page_size_bytes for l in inner.values()),
        real_page_size_bytes=sum(l.real_page_size_bytes for l in inner.values()),
    )
    return SimpleNamespace(kv_cache_spec=agg, layer_names=list(inner))


def fake_configs():
    ml = fake_layer(37376, 37376)
    sw = fake_layer(1168, 1168)
    groups = [fake_group([ml], "mla"), fake_group([sw] * 4, "swa")]
    vllm_config = SimpleNamespace(
        parallel_config=SimpleNamespace(
            world_size=2, tensor_parallel_size=2, pipeline_parallel_size=1,
            prefill_context_parallel_size=1, decode_context_parallel_size=1,
            rank=0,
        ),
        cache_config=SimpleNamespace(
            cache_dtype="nvfp4_ds_mla", block_size=256,
            hash_block_size=None, enable_prefix_caching=True,
        ),
        kv_events_config=None,
        model_config=SimpleNamespace(model="DeepSeek-V4-Flash-0731"),
    )
    # tensors mirror the real fork geometry: per-slot span = sum of
    # per-block bytes over ALL tensors (t.size // num_blocks); group
    # bytes come from shared_by ∩ group layer_names (side-invariant)
    kv_cache_tensors = [
        SimpleNamespace(size=1000 * 37376, shared_by=["mla-l0"]),
        SimpleNamespace(size=1000 * 1168,
                        shared_by=["mla-l0"] + [f"swa-l{i}" for i in range(4)]),
    ]
    kv_cache_config = SimpleNamespace(
        num_blocks=1000, kv_cache_groups=groups,
        kv_cache_tensors=kv_cache_tensors,
    )
    return vllm_config, kv_cache_config


EXTRA = {
    "nvme_root_dir": "WILL-OVERRIDE",
    "nvme_bytes_to_use": 137438953472,
    "staging_ring_bytes": 536870912,
}


def new_spec(root):
    vllm_config, kv_cache_config = fake_configs()
    extra = dict(EXTRA, nvme_root_dir=root)
    vllm_config.kv_transfer_config = SimpleNamespace(
        kv_connector_extra_config=extra
    )
    return NVMeTieredOffloadingSpec(vllm_config, kv_cache_config)


def main():
    # hash-seed guard
    seed = os.environ.pop("PYTHONHASHSEED", None)
    try:
        new_spec("/tmp/x")
        check("guard fires without PYTHONHASHSEED", False)
    except RuntimeError:
        check("guard fires without PYTHONHASHSEED", True)
    os.environ["PYTHONHASHSEED"] = "0"

    with tempfile.TemporaryDirectory() as root:
        s = new_spec(root)
        per_rank = 137438953472 // 2
        check("cluster budget split per rank", s.per_rank_bytes == per_rank)
        # group bytes via tensor geometry: g0 = 37,376+1,168; g1 = 1,168
        check("group block bytes", s._group_bytes == [38544, 1168])
        # ring slots from TENSOR GEOMETRY (side-invariant): per-slot span
        # = 37,376 + 1,168 across all tensors
        expect_slots = 536870912 // (37376 + 1168)
        check("ring slots from tensor geometry", s.num_slots == expect_slots)

        mgr = s.get_manager()
        check("manager budget", mgr._bytes_budget == per_rank)
        check("manager events off (kv_events_config None)",
              mgr.events is None)
        check("manager slot pool", mgr._get_num_free_slots() == expect_slots)
        check("get_manager cached", s.get_manager() is mgr)

        # FileMapper + tier dir prep (the boot-only worker-side paths)
        from vllm.v1.kv_offload.file_mapper import FileMapper
        s._mapper = FileMapper.from_offloading_spec(
            root_dir=root, offloading_spec=s, gpu_blocks_per_file=1,
        )
        check("mapper rank", s._mapper.rank == 0)
        check("mapper base under root", s._mapper.base_path.startswith(root))
        s._prepare_tier_dir()
        rank_dir = f"{s._mapper.base_path}_r0"
        check("rank dir created", os.path.isdir(rank_dir))
        check("config json published",
              os.path.isfile(s._mapper.get_config_file_path()))
        # cold-start wipe: stale litter removed on second prep
        litter = os.path.join(rank_dir, "stale.bin")
        with open(litter, "wb") as f:
            f.write(b"x" * 10)
        s._prepare_tier_dir()
        check("cold-start wipe", not os.path.exists(litter))

        # missing required keys
        vllm_config, kv_cache_config = fake_configs()
        vllm_config.kv_transfer_config = SimpleNamespace(
            kv_connector_extra_config={"nvme_bytes_to_use": 1}
        )
        try:
            NVMeTieredOffloadingSpec(vllm_config, kv_cache_config)
            check("missing root dir rejected", False)
        except Exception:
            check("missing root dir rejected", True)

        # tiny ring rejected
        vllm_config, kv_cache_config = fake_configs()
        vllm_config.kv_transfer_config = SimpleNamespace(
            kv_connector_extra_config=dict(
                EXTRA, nvme_root_dir="/tmp/x", staging_ring_bytes=1024
            )
        )
        try:
            NVMeTieredOffloadingSpec(vllm_config, kv_cache_config)
            check("tiny ring rejected", False)
        except Exception:
            check("tiny ring rejected", True)

    print(f"BOOT-PATH TESTS: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
