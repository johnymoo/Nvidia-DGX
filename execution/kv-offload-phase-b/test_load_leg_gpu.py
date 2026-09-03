#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""GPU test for the copy_-based load CUDA leg (boot-9 fault follow-up).

Runs ONLY in an idle window (production down), throwaway --gpus container:
  docker run --rm --gpus '"device=0"' --entrypoint python3 \
    -v /home/<user>/phase-b-nvme:/opt/pkg:ro \
    -e PYTHONPATH=/opt/pkg -e PYTHONHASHSEED=0 \
    gb10-ds4-vllm:f277b3d-nvfp4 /opt/pkg/test_load_leg_gpu.py

Real DS-V4-Flash tensor geometry: layers 0..19 have (1728, 8640, 37440)
pages; the last layer has (8640, 37440, 37440) — the tail the layout log
taught us (no 1728-class component on the final layer). Stores go through
the batch kernel (proven at scale); loads exercise the per-op copy_ leg.
"""
import os
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

# production segment lists (20260902 boot-9 NVME-TIER-LAYOUT)
G0_SEGMENTS = []
for layer in range(20):
    b = layer * 3
    G0_SEGMENTS += [(b + 1, 8448), (b + 2, 37376), (b + 0, 1168)]
G0_SEGMENTS += [(60, 8448), (61, 37376)]  # last layer: no 1728 component
G4_SEGMENTS = [(t, 32768) for t in (2, 5, 8, 11, 14, 17, 20, 23, 26, 29,
                                     32, 35, 38, 41, 44, 47, 50, 53, 56, 59)]

PAGES = [p for _ in range(20) for p in (1728, 8640, 37440)] + \
        [8640, 37440, 37440]


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"ok   {name}")
    else:
        FAIL += 1
        print(f"FAIL {name}")


def build_caches(rows):
    tensors = []
    for p in PAGES:
        t = torch.randint(-128, 128, (rows * p,), dtype=torch.int8,
                          device="cuda")
        tensors.append(CanonicalKVCacheTensor(
            tensor=t.view(rows, p), page_size_bytes=p))
    g0 = [CanonicalKVCacheRef(tensor_idx=t, page_size_bytes=n)
          for t, n in G0_SEGMENTS]
    g4 = [CanonicalKVCacheRef(tensor_idx=t, page_size_bytes=n)
          for t, n in G4_SEGMENTS]
    return CanonicalKVCaches(tensors=tensors, group_data_refs=[g0, g4])


class FakeMapper:
    def __init__(self, base):
        self.base_path = base
        self.rank = 0

    def get_file_name(self, key):
        h = bytes(key).hex()[:32]
        return os.path.join(f"{self.base_path}_r{self.rank}",
                            f"{h}_g{key[-1]}.bin")


def drain(handler, job_id, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for r in handler.get_finished():
            if r.job_id == job_id:
                return r
        time.sleep(0.01)
    return None


def main():
    assert torch.cuda.is_available()
    torch.cuda.init()
    rows, slots = 600, 320
    caches = build_caches(rows)
    root = tempfile.mkdtemp(prefix="nvme_loadleg_")
    handler = NVMeOffloadingHandler(
        kv_caches=caches, num_slots=slots, file_mapper=FakeMapper(root),
        io_threads=4, physical_budget_bytes=1 << 30, gc_interval_s=3600,
    )
    try:
        check("segment count 62", len(handler._group_segments[0]) == 62)
        check("ring pages match", all(
            handler._ring_tensors[i].shape[1] == PAGES[i]
            for i in range(len(PAGES))))

        # ---- store 256 g0 keys + 8 g4 keys (batch kernel, proven) ----
        n0, n4 = 256, 8
        keys0 = [make_offload_key(f"ll-{i}".encode(), 0) for i in range(n0)]
        # G4-style layout mounted as LOCAL group 1 (segment content is what matters)
        keys4 = [make_offload_key(f"ll4-{i}".encode(), 1) for i in range(n4)]
        src_rows0 = list(range(10, 10 + n0))
        src_rows4 = list(range(10, 10 + n4))
        spec0 = NVMeLoadStoreSpec(list(range(n0)), keys0)
        spec4 = NVMeLoadStoreSpec(list(range(n0, n0 + n4)), keys4)
        gpu_store0 = GPULoadStoreSpec(src_rows0, group_sizes=[n0, 0],
                                      block_indices=[10, 0])
        gpu_store4 = GPULoadStoreSpec(src_rows4, group_sizes=[0, n4],
                                      block_indices=[0, 10])
        assert handler.transfer_async(1, (gpu_store0, spec0))
        assert handler.transfer_async(2, (gpu_store4, spec4))
        r1, r2 = drain(handler, 1), drain(handler, 2)
        check("store g0 finished", r1 is not None and r1.success)
        check("store g4 finished", r2 is not None and r2.success)
        n_t2 = dict(G0_SEGMENTS)[2]  # 37376: segments cover row heads only
        expect0 = {i: caches.tensors[2].tensor[i, :n_t2].clone()
                   for i in (10, 137, 265)}
        expect4 = caches.tensors[2].tensor[10, :n_t2].clone()

        # ---- wipe GPU rows, load back via the copy_ leg ----
        for t in handler._gpu_tensors:
            t.zero_()
        torch.cuda.synchronize()
        dst_base = n0 + 40
        dst_rows0 = list(range(dst_base, dst_base + n0))
        dst_rows4 = list(range(dst_base, dst_base + n4))
        gpu_load0 = GPULoadStoreSpec(dst_rows0, group_sizes=[n0, 0],
                                     block_indices=[dst_base, 0])
        gpu_load4 = GPULoadStoreSpec(dst_rows4, group_sizes=[0, n4],
                                     block_indices=[0, dst_base])
        t_ = time.perf_counter()
        assert handler.transfer_async(3, (spec0, gpu_load0))
        r3 = drain(handler, 3, timeout=300)
        dt = time.perf_counter() - t_
        check("load g0 (copy_ leg) finished",
              r3 is not None and r3.success)
        if r3 is not None:
            print(f"     256-key g0 load wall {dt:.2f} s "
                  f"({r3.transfer_size / 2**20:.0f} MiB)")
        assert handler.transfer_async(4, (spec4, gpu_load4))
        r4 = drain(handler, 4)
        check("load g4-style (copy_ leg) finished",
              r4 is not None and r4.success)

        torch.cuda.synchronize()
        check("g0 byte-exact via copy_ leg", all(
            torch.equal(
                caches.tensors[2].tensor[dst_rows0[i - 10], :n_t2],
                expect0[i]) for i in (10, 137, 265)))
        check("g4-style byte-exact via copy_ leg",
              torch.equal(
                  caches.tensors[2].tensor[dst_base, :n_t2], expect4))
        check("context healthy after 16k-op copy_ load",
              torch.cuda.synchronize() is None)
    finally:
        handler.shutdown()
        import shutil
        shutil.rmtree(root, ignore_errors=True)

    print(f"LOAD-LEG TESTS: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
