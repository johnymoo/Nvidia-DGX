#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""In-vitro reproduction of the boot-9 load CUDA fault (real geometry).

Rebuilds the production layout (63 GPU tensors, 8,933 rows; 3 GiB pinned
ring) and submits a 256-key group-0 load leg (16,128 ops, ~234 MiB) via
swap_blocks_batch, A/B on is_src_access_order_any.

  docker run --rm --gpus all --entrypoint python3 \
    -v $HOME/phase-b-nvme:/opt/pkg:ro -e PYTHONPATH=/opt/pkg \
    <image> /opt/pkg/test_load_flag_repro.py true|false [--window N]

Run ONLY while production is down (needs ~9 GiB GPU + 3 GiB pinned).
"""
import sys

import numpy as np
import torch

from vllm import _custom_ops as ops
from vllm.v1.kv_offload.cpu.gpu_worker import compute_sub_block_ptrs

# NVME-TIER-LAYOUT from boot-9 logs: 21 layers x (1728, 8640, 37440) pages
GPU_PAGES = [p for _ in range(21) for p in (1728, 8640, 37440)]
G0_SEGMENTS = []
for layer in range(21):
    base = layer * 3
    # per layer: (small, big, mla) tensor order rotates, bytes fixed
    G0_SEGMENTS += [(base + 1, 8448), (base + 2, 37376), (base + 0, 1168)]
ROWS = 8933
SLOTS = 3062
NKEYS = 256
DST_BASE = 1000


def main():
    flag_any = sys.argv[1].lower() == "true"
    n_window = 0
    if "--window" in sys.argv:
        # extra sliding-window-group keys (group 1 layout: 22-segment rows)
        n_window = int(sys.argv[sys.argv.index("--window") + 1])

    torch.cuda.init()
    gpu = [torch.zeros((ROWS, p), dtype=torch.int8, device="cuda")
           for p in GPU_PAGES]
    ring = [torch.zeros((SLOTS, p), dtype=torch.int8, pin_memory=True)
            for p in GPU_PAGES]

    # window-group segments (all five groups, from boot-9 layout log)
    g1_segments = [(t, 37376) for t in (2, 5, 8, 11, 14, 17, 20, 23, 26,
                                        29, 32, 35, 38, 41, 44, 47, 50,
                                        53, 56, 59, 61, 62)]
    g2_segments = list(g1_segments)
    g3_segments = []
    for layer in range(20):
        base = layer * 3
        g3_segments += [(base + 1, 8192), (base + 2, 32768)]
    g3_segments += [(60, 8192), (61, 32768)]
    g4_segments = [(t, 32768) for t in (2, 5, 8, 11, 14, 17, 20, 23, 26,
                                        29, 32, 35, 38, 41, 44, 47, 50,
                                        53, 56, 59)]

    ops_src, ops_dst, ops_size = [], [], []
    expect = []  # (tensor, gpu_row, nbytes, slot) for verification

    def add_key(slot, gpu_block, segments):
        for t, n in segments:
            off = (slot * 131 + t * 7 + 1) & 0x7F
            pattern = (np.arange(n) + off) & 0x7F
            # flat view: some groups' segment bytes exceed the tensor's
            # page (e.g. (61, 37376) on an 8640-page tensor) — the raw
            # pointers the kernel receives cross rows, so fill/verify the
            # same flat spans the kernel will touch
            ring[t].view(-1)[slot * GPU_PAGES[t]:
                             slot * GPU_PAGES[t] + n] = torch.from_numpy(
                                 pattern.astype(np.int8))
            ops_src.append(ring[t].data_ptr() + slot * GPU_PAGES[t])
            ops_dst.append(gpu[t].data_ptr() + gpu_block * GPU_PAGES[t])
            ops_size.append(n)
            expect.append((t, gpu_block, n, slot))

    for k in range(NKEYS):
        add_key(k, DST_BASE + k, G0_SEGMENTS)
    if n_window:
        # mirror job 149's tail: window keys across ALL groups
        slot, block = 256, DST_BASE + 256
        for segs in (g1_segments, g2_segments, g3_segments, g4_segments):
            for _ in range(n_window):
                add_key(slot, block, segs)
                slot += 1
                block += 1

    src = torch.tensor(ops_src, dtype=torch.int64)
    dst = torch.tensor(ops_dst, dtype=torch.int64)
    sizes = torch.tensor(ops_size, dtype=torch.int64)
    total_mb = sum(ops_size) / 2**20
    print(f"ops={len(ops_size)} bytes={total_mb:.1f} MiB flag_any={flag_any}")

    stream = torch.cuda.Stream()
    start, end = torch.Event(enable_timing=True), torch.Event(enable_timing=True)
    fault = None
    try:
        with torch.cuda.stream(stream):
            start.record(stream)
            ops.swap_blocks_batch(src, dst, sizes,
                                  is_src_access_order_any=flag_any)
            end.record(stream)
        end.synchronize()
        torch.cuda.synchronize()
        _ = gpu[0].sum().item()  # force a real kernel after the copy
    except Exception as e:  # noqa: BLE001
        fault = repr(e)

    if fault:
        print(f"FAULT: {fault}")
        sys.exit(2)

    bad = 0
    for t, row, n, slot in expect:
        got = gpu[t].view(-1)[row * GPU_PAGES[t]:
                              row * GPU_PAGES[t] + n].cpu()
        want = ring[t].view(-1)[slot * GPU_PAGES[t]:
                                slot * GPU_PAGES[t] + n]
        if not torch.equal(got, want):
            bad += 1
            if bad <= 3:
                print(f"MISMATCH t={t} row={row} slot={slot} n={n}")
    print("VERIFY:", "PASS byte-exact" if bad == 0 else f"FAIL {bad} rows")
    sys.exit(0 if bad == 0 else 1)


if __name__ == "__main__":
    main()
