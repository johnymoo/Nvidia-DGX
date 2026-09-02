#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""GPU-path round-trip test: store -> file -> load with REAL CUDA tensors.

Runs in a throwaway --gpus container of the production image (never beside
the production stack):
  docker run --rm --gpus '"device=0"' --entrypoint python3 \
    -v /home/<user>/phase-b-nvme:/opt/pkg:ro \
    -e PYTHONPATH=/opt/pkg -e PYTHONHASHSEED=0 \
    gb10-ds4-vllm:f277b3d-nvfp4 /opt/pkg/test_gpu_roundtrip.py

Exercises the only CUDA-touching code the logic tests cannot: the real
swap_blocks_batch kernel on a non-default stream, pinned-ring staging,
thread-issued load CUDA leg, event chaining, FIFO completion barrier, and
the on-GPU failure branch (missing file -> success=False, not a crash).
"""
import hashlib
import os
import shutil
import sys
import tempfile
import time

import torch

from vllm.v1.kv_offload.base import (
    CanonicalKVCaches,
    CanonicalKVCacheRef,
    CanonicalKVCacheTensor,
    GPULoadStoreSpec,
    make_offload_key,
)

from vllm_nvme_tier.gpu_worker import NVMeOffloadingHandler
from vllm_nvme_tier.specs import NVMeLoadStoreSpec

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


def k(blob: bytes, group: int = 0):
    return make_offload_key(blob, group)


class FakeMapper:
    """FileMapper stand-in: flat rank dir, content-addressed names."""

    def __init__(self, base):
        self.base_path = base
        self.rank = 0

    def get_file_name(self, key):
        h = hashlib.sha256(bytes(key)).hexdigest()[:32]
        return os.path.join(
            f"{self.base_path}_r{self.rank}", f"{h}_g{key[-1]}.bin"
        )


def build_caches(num_blocks, page0, page1):
    def rows(page):
        t = torch.randint(-128, 128, (num_blocks * page,),
                          dtype=torch.int8, device="cuda")
        return t.view(num_blocks, page)

    t0, t1 = rows(page0), rows(page1)
    tensors = [
        CanonicalKVCacheTensor(tensor=t0, page_size_bytes=page0),
        CanonicalKVCacheTensor(tensor=t1, page_size_bytes=page1),
    ]
    # group 0 uses both tensors (hybrid MLA+SWA), group 1 only tensor 1
    refs = [
        [
            CanonicalKVCacheRef(tensor_idx=0, page_size_bytes=page0),
            CanonicalKVCacheRef(tensor_idx=1, page_size_bytes=page1),
        ],
        [CanonicalKVCacheRef(tensor_idx=1, page_size_bytes=page1)],
    ]
    return CanonicalKVCaches(tensors=tensors, group_data_refs=refs), t0, t1


def drain(handler, job_id, timeout=60):
    """Poll get_finished until job_id's result appears."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for r in handler.get_finished():
            if r.job_id == job_id:
                return r
        time.sleep(0.01)
    return None


def main():
    assert torch.cuda.is_available(), "needs a real GPU"
    torch.cuda.init()

    num_blocks, page0, page1 = 64, 149504, 1168
    caches, t0, t1 = build_caches(num_blocks, page0, page1)
    root = tempfile.mkdtemp(prefix="nvme_rt_")
    try:
        handler = NVMeOffloadingHandler(
            kv_caches=caches, num_slots=8, file_mapper=FakeMapper(root),
            io_threads=4, physical_budget_bytes=1 << 30, gc_interval_s=3600,
        )

        expect0a = t0[3].clone()
        expect0b = t0[4].clone()
        expect1 = t1[7].clone()
        keys = [k(b"gpu-rt-a", 0), k(b"gpu-rt-b", 0), k(b"gpu-rt-c", 1)]
        tier_spec = NVMeLoadStoreSpec([0, 1, 2], keys)

        # ---- store: group0 blocks 3,4 + group1 block 7 ----
        gpu_store = GPULoadStoreSpec(
            [3, 4, 7], group_sizes=[2, 1], block_indices=[3, 7],
        )
        t_ = time.perf_counter()
        assert handler.transfer_async(1, (gpu_store, tier_spec))
        r = drain(handler, 1)
        dt = time.perf_counter() - t_
        check("store finished", r is not None and r.success)
        check("store reported size",
              r is not None and r.transfer_size == 2 * (page0 + page1) + page1)
        print(f"     store wall {dt * 1e3:.1f} ms")
        check("files written",
              all(os.path.exists(handler._mapper.get_file_name(x)) for x in keys))

        # ---- load: clobber GPU rows, reload into fresh blocks, byte-compare ----
        t0[3] = 0
        t0[4] = 0
        t1[7] = 0
        torch.cuda.synchronize()
        gpu_load = GPULoadStoreSpec(
            [10, 11, 12], group_sizes=[2, 1], block_indices=[10, 12],
        )
        t_ = time.perf_counter()
        assert handler.transfer_async(2, (tier_spec, gpu_load))
        r = drain(handler, 2)
        dt = time.perf_counter() - t_
        check("load finished", r is not None and r.success)
        print(f"     load wall {dt * 1e3:.1f} ms")
        check("load bytes group0 block0", torch.equal(t0[10], expect0a))
        check("load bytes group0 block1", torch.equal(t0[11], expect0b))
        check("load bytes group1", torch.equal(t1[12], expect1))

        # ---- failure branch: delete a file, load must degrade not crash ----
        os.remove(handler._mapper.get_file_name(keys[1]))
        assert handler.transfer_async(3, (tier_spec, gpu_load))
        r = drain(handler, 3)
        check("missing file degrades to success=False",
              r is not None and not r.success)

        # ---- throughput probe: 4 sequential 8-slot stores (256 blocks) ----
        # Sequential submit->drain: slots 0-7 are only reclaimed when a
        # result is popped, exactly like scheduler-driven ring backpressure.
        t_ = time.perf_counter()
        done = 0
        for j in range(4):
            first = 32 + j * 8
            g = GPULoadStoreSpec(
                list(range(first, first + 8)),
                group_sizes=[8], block_indices=[first],
            )
            kk = [k(f"probe-{j}-{i}".encode(), 0) for i in range(8)]
            assert handler.transfer_async(
                100 + j, (g, NVMeLoadStoreSpec(list(range(8)), kk))
            )
            r = drain(handler, 100 + j)
            if r is not None and r.success:
                done += 1
        probe_dt = time.perf_counter() - t_
        mib = 32 * page0 / 2**20
        print(f"     probe: 4 jobs / {mib:.0f} MiB in {probe_dt:.2f}s "
              f"({mib / probe_dt:.0f} MiB/s end-to-end)")
        check("probe completed", done == 4)

        handler.shutdown()
    finally:
        shutil.rmtree(f"{root}_r0", ignore_errors=True)
        try:
            os.rmdir(root)
        except OSError:
            pass

    print(f"GPU ROUND-TRIP TESTS: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
