#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Concurrent-canary reproduction of the boot-9 load CUDA fault.

Neither existing in-vitro test exercised the two conditions actually
present in production when boot-9 died: a CUDA graph replay in the same
context shortly after the load's CUDA leg (vLLM decode == graph replay),
and/or that leg running concurrently with other engine CUDA activity.
test_load_flag_repro.py ran the batch kernel in a fresh idle context and
only chased it with a plain `.sum()`; test_load_leg_gpu.py drove the
copy_-leg fix end-to-end but also only in an idle context. This script
adds both back in as two testable hypotheses:

  H1: batch copy (or the copy_-leg fix) followed by a CUDA GRAPH REPLAY
      in the same context faults -- mirrors boot-9's next execute_model
      dying with cudaErrorLaunchFailure ~95 s after the load completed.
  H2: the copy leg running CONCURRENT with engine-like CUDA activity
      (kernels and/or graph replays on the default stream, issued from
      another host thread) faults.

  docker run --rm --gpus all --entrypoint python3 \
    -v $HOME/phase-b-nvme:/opt/pkg:ro -e PYTHONPATH=/opt/pkg \
    <image> /opt/pkg/test_load_concurrent_canary.py --leg batch --sim both
  docker run --rm --gpus all --entrypoint python3 \
    -v $HOME/phase-b-nvme:/opt/pkg:ro -e PYTHONPATH=/opt/pkg \
    <image> /opt/pkg/test_load_concurrent_canary.py --leg copy --sim graph

Run ONLY while production is down. --leg batch at defaults needs ~9 GiB
GPU + 3 GiB pinned; --leg copy defaults to a much smaller footprint since
it goes through the full production handler (file IO per iteration).

Real DS-V4-Flash geometry (20260902 boot-9 NVME-TIER-LAYOUT, CORRECTED):
layers 0..19 have (1728, 8640, 37440) pages, the last layer has
(8640, 37440, 37440) -- no 1728-class component on the final layer. This
supersedes test_load_flag_repro.py's original 21x(1728,8640,37440) guess;
it is the same layout test_load_leg_gpu.py uses.
"""
import argparse
import random
import sys
import threading
import time
import traceback

import numpy as np
import torch

from vllm import _custom_ops as ops

PAGES = [p for _ in range(20) for p in (1728, 8640, 37440)] + \
        [8640, 37440, 37440]
assert len(PAGES) == 63

G0_SEGMENTS = []
for _layer in range(20):
    _b = _layer * 3
    G0_SEGMENTS += [(_b + 1, 8448), (_b + 2, 37376), (_b + 0, 1168)]
G0_SEGMENTS += [(60, 8448), (61, 37376)]  # last layer: no 1728 component
assert len(G0_SEGMENTS) == 62

PAGE_BYTES_TOTAL = sum(PAGES)

# Populated by the simulator thread on any exception; read by the main
# thread only for diagnostics/the final pass/fail decision (advisory --
# the main thread's own try/except around its CUDA calls is what actually
# catches a poisoned context on its side).
sim_fault: dict = {}


# --------------------------- CUDA graph helpers -------------------------

def _build_graph(tag: str, seed: int):
    """Standard capture idiom: warm up 3x on a side stream, sync, then
    capture. Returns (graph, static_bufs); static_bufs must stay alive
    for as long as the graph is replayed."""
    torch.manual_seed(seed)
    a = torch.randn(1024, 1024, dtype=torch.float16, device="cuda")
    b = torch.randn(1024, 1024, dtype=torch.float16, device="cuda")
    c = torch.randn(1024, 1024, dtype=torch.float16, device="cuda")
    out = torch.zeros(1024, 1024, dtype=torch.float16, device="cuda")

    def chain():
        t = torch.matmul(a, b)
        t = torch.softmax(t, dim=-1)
        t = t + c
        t = torch.matmul(t, b)
        t = torch.softmax(t, dim=-1)
        t = t + c
        t = torch.matmul(t, b)
        out.copy_(t)

    side = torch.cuda.Stream()
    side.wait_stream(torch.cuda.current_stream())
    with torch.cuda.stream(side):
        for _ in range(3):
            chain()
    torch.cuda.current_stream().wait_stream(side)
    torch.cuda.synchronize()

    graph = torch.cuda.CUDAGraph()
    with torch.cuda.graph(graph):
        chain()
    print(f"captured {tag} graph (8-op chain, 1024x1024 fp16)")
    return graph, (a, b, c, out)


def probe(tag: str, checker) -> None:
    """H1 detector: replay the checker graph, then launch a trivial
    kernel. Any CUDA fault here means the context was poisoned by
    whatever ran just before this call."""
    graph, _bufs = checker
    try:
        graph.replay()
        torch.cuda.synchronize()
        x = torch.ones(65536, device="cuda")
        x.add_(1)
        _ = x.sum().item()
        torch.cuda.synchronize()
    except Exception as e:  # noqa: BLE001
        print(f"FAULT at {tag}: {repr(e)}")
        if sim_fault:
            print(f"sim_fault: {sim_fault}")
        print(f"CANARY FAULT: probe failed at {tag}: {repr(e)}")
        sys.exit(2)


# --------------------------- engine simulator ---------------------------

def _sim_kernel_iter(a: torch.Tensor, b: torch.Tensor) -> None:
    t = torch.matmul(a, b)
    t = torch.softmax(t, dim=-1)
    t = torch.matmul(t, b)
    t = torch.softmax(t, dim=-1)
    _ = torch.matmul(t, b)


def engine_simulator(mode: str, sim_graph, sim_bufs, stop_event) -> None:
    """Daemon thread: engine-like CUDA activity on the DEFAULT stream,
    concurrent with the leg under test running on its own dedicated
    stream (H2). Every exception is captured into `sim_fault` and the
    thread exits; it never re-raises into the interpreter."""
    del sim_bufs  # kept alive by caller's reference, not needed here
    try:
        a = torch.randn(4096, 4096, dtype=torch.float16, device="cuda")
        b = torch.randn(4096, 4096, dtype=torch.float16, device="cuda")
        pinned_h = torch.ones(512, 512, dtype=torch.float16).pin_memory()
        dev_buf = torch.empty(512, 512, dtype=torch.float16,
                               device="cuda")
    except Exception as e:  # noqa: BLE001
        sim_fault["error"] = repr(e)
        sim_fault["traceback"] = traceback.format_exc()
        sim_fault["stage"] = "alloc"
        stop_event.set()
        return

    i = 0
    while not stop_event.is_set():
        try:
            use_graph = mode == "graph" or (mode == "both" and i % 2 == 1)
            if use_graph:
                sim_graph.replay()
            else:
                _sim_kernel_iter(a, b)
                dev_buf.copy_(pinned_h, non_blocking=True)
                _ = dev_buf.cpu()
            if i % 50 == 49:
                torch.cuda.synchronize()
            i += 1
            time.sleep(0.002)
        except Exception as e:  # noqa: BLE001
            sim_fault["error"] = repr(e)
            sim_fault["traceback"] = traceback.format_exc()
            sim_fault["stage"] = f"iter {i}"
            stop_event.set()
            return


def _check_sim_alive(stop_event, it: int) -> None:
    """Fast-fail if the sim thread already died -- don't wait for the
    leg's own CUDA calls to also trip over a poisoned context."""
    if stop_event.is_set() and sim_fault:
        print(f"CANARY FAULT: sim thread died before iter {it}: "
              f"{sim_fault}")
        sys.exit(2)


# ------------------------------ batch leg -------------------------------

def run_batch_leg(args, rows: int, slots: int, checker, stop_event) -> None:
    """Raw-op repro leg: swap_blocks_batch(is_src_access_order_any=True)
    submitted repeatedly on a dedicated stream, each iteration chased by
    probe() (H1) while the sim thread runs concurrently (H2)."""
    keys = args.keys
    assert keys <= slots, f"keys={keys} must be <= slots={slots}"
    dst_base = rows - keys - 8
    assert dst_base > 0, f"rows={rows} too small for keys={keys}"

    print(f"batch leg: {len(PAGES)} GPU tensors x {rows} rows, "
          f"{len(PAGES)} ring tensors x {slots} slots, dst_base={dst_base}")
    gpu = [torch.zeros((rows, p), dtype=torch.int8, device="cuda")
           for p in PAGES]
    ring = [torch.zeros((slots, p), dtype=torch.int8, pin_memory=True)
            for p in PAGES]

    # Pointers built ONCE: src/dst addresses don't change across
    # iterations, only the ring's contents do (refilled below).
    ops_src, ops_dst, ops_size = [], [], []
    expect = []  # (tensor_idx, gpu_row, nbytes, slot) for sampled verify
    for k in range(keys):
        slot, gpu_row = k, dst_base + k
        for tensor_idx, n in G0_SEGMENTS:
            ops_src.append(ring[tensor_idx].data_ptr() +
                           slot * PAGES[tensor_idx])
            ops_dst.append(gpu[tensor_idx].data_ptr() +
                           gpu_row * PAGES[tensor_idx])
            ops_size.append(n)
            expect.append((tensor_idx, gpu_row, n, slot))
    src = torch.tensor(ops_src, dtype=torch.int64)
    dst = torch.tensor(ops_dst, dtype=torch.int64)
    sizes = torch.tensor(ops_size, dtype=torch.int64)
    total_mib = sum(ops_size) / 2**20
    print(f"batch leg: ops={len(ops_size)} load={total_mib:.1f} MiB/iter")

    def refill(it: int) -> None:
        # Every G0 segment fits inside its own tensor's page in the
        # corrected layout (no row-crossing spans like the old window-
        # group layout had), so the flat span
        # ring[t].view(-1)[slot*P : slot*P+n] for slot in [0, keys) is
        # exactly ring[t][:keys, :n] -- one vectorized write per tensor
        # instead of keys*len(G0_SEGMENTS) individual ones.
        for tensor_idx, n in G0_SEGMENTS:
            offs = ((np.arange(keys) * 131 + tensor_idx * 7 +
                     it * 13 + 1) & 0x7F)[:, None]
            pattern = ((offs + np.arange(n)[None, :]) & 0x7F)
            ring[tensor_idx][:keys, :n] = torch.from_numpy(
                pattern.astype(np.int8))

    def verify_sample(n_sample: int) -> list:
        bad = []
        for tensor_idx, row, n, slot in random.sample(
                expect, min(n_sample, len(expect))):
            p = PAGES[tensor_idx]
            got = gpu[tensor_idx].view(-1)[
                row * p: row * p + n].cpu().numpy()
            want = ring[tensor_idx].view(-1)[
                slot * p: slot * p + n].cpu().numpy()
            if not np.array_equal(got, want):
                bad.append((tensor_idx, row, slot, n))
        return bad

    def verify_all() -> list:
        bad = []
        for tensor_idx, n in G0_SEGMENTS:
            got = gpu[tensor_idx][dst_base:dst_base + keys, :n].cpu()
            want = ring[tensor_idx][:keys, :n]
            if not torch.equal(got, want):
                bad.append((tensor_idx, n))
        return bad

    stream = torch.cuda.Stream()
    for it in range(args.iters):
        _check_sim_alive(stop_event, it)
        refill(it)

        start = torch.Event(enable_timing=True)
        end = torch.Event(enable_timing=True)
        try:
            with torch.cuda.stream(stream):
                start.record(stream)
                ops.swap_blocks_batch(src, dst, sizes,
                                      is_src_access_order_any=True)
                end.record(stream)
            end.synchronize()
            torch.cuda.synchronize()
        except Exception as e:  # noqa: BLE001
            print(f"FAULT at batch iter {it} submit: {repr(e)}")
            if sim_fault:
                print(f"sim_fault: {sim_fault}")
            print(f"CANARY FAULT: submit failed at iter {it}: {repr(e)}")
            sys.exit(2)

        probe(f"batch iter {it} post-copy", checker)

        do_full = it % 5 == 4
        bad = verify_all() if do_full else verify_sample(400)
        if bad:
            kind = "ALL" if do_full else "sample400"
            print(f"CANARY MISMATCH: iter {it} ({kind}) "
                  f"count={len(bad)} first={bad[:5]}")
            sys.exit(1)

        copy_ms = start.elapsed_time(end)
        vkind = "ALL" if do_full else "sample400"
        print(f"iter {it:3d}: copy={copy_ms:8.2f} ms verify={vkind} ok")


# ------------------------------- copy leg -------------------------------

def run_copy_leg(args, rows: int, slots: int, checker, stop_event) -> None:
    """End-to-end leg through the production handler (copy_ fix), like
    test_load_leg_gpu.py, but looped with probe() (H1) and an optional
    concurrent engine simulator (H2). vllm_nvme_tier is imported lazily
    here so --leg batch works even if the package isn't on PYTHONPATH."""
    import os
    import shutil
    import tempfile

    from vllm.v1.kv_offload.base import (
        CanonicalKVCacheRef,
        CanonicalKVCacheTensor,
        CanonicalKVCaches,
        GPULoadStoreSpec,
        make_offload_key,
    )

    from vllm_nvme_tier.gpu_worker import NVMeOffloadingHandler
    from vllm_nvme_tier.specs import NVMeLoadStoreSpec

    keys = args.keys
    assert keys <= slots, f"keys={keys} must be <= slots={slots}"
    # src rows start at 10, dst rows at keys + 40: both ranges must fit
    assert 2 * keys + 40 <= rows, f"rows={rows} too small for keys={keys}"

    class FakeMapper:
        def __init__(self, base):
            self.base_path = base
            self.rank = 0

        def get_file_name(self, key):
            h = bytes(key).hex()[:32]
            return os.path.join(f"{self.base_path}_r{self.rank}",
                                f"{h}_g{key[-1]}.bin")

    def drain(handler, job_id, timeout=300):
        deadline = time.time() + timeout
        while time.time() < deadline:
            for r in handler.get_finished():
                if r.job_id == job_id:
                    return r
            time.sleep(0.01)
        return None

    print(f"copy leg: {len(PAGES)} tensors x {rows} rows, "
          f"handler ring {slots} slots")
    tensors = []
    for p in PAGES:
        t = torch.zeros((rows, p), dtype=torch.int8, device="cuda")
        tensors.append(CanonicalKVCacheTensor(tensor=t, page_size_bytes=p))
    g0 = [CanonicalKVCacheRef(tensor_idx=t, page_size_bytes=n)
          for t, n in G0_SEGMENTS]
    caches = CanonicalKVCaches(tensors=tensors, group_data_refs=[g0])

    root = tempfile.mkdtemp(prefix="nvme_canary_")
    handler = NVMeOffloadingHandler(
        kv_caches=caches, num_slots=slots, file_mapper=FakeMapper(root),
        io_threads=4, physical_budget_bytes=4 << 30, gc_interval_s=3600,
    )
    try:
        src_rows = list(range(10, 10 + keys))
        okeys = [make_offload_key(f"canary-{i}".encode(), 0)
                for i in range(keys)]
        spec_tier = NVMeLoadStoreSpec(list(range(keys)), okeys)
        gpu_store = GPULoadStoreSpec(src_rows, group_sizes=[keys],
                                     block_indices=[10])

        # Seed real (non-zero) source content so the load-back has
        # something byte-exact to check against -- zeros trivially
        # "match" a zeroed destination and would hide a corrupted copy.
        for tensor_idx, n in G0_SEGMENTS:
            t = caches.tensors[tensor_idx].tensor
            t[src_rows[0]:src_rows[-1] + 1, :n] = torch.randint(
                -128, 128, (keys, n), dtype=torch.int8, device="cuda")
        torch.cuda.synchronize()

        assert handler.transfer_async(1, (gpu_store, spec_tier))
        r1 = drain(handler, 1)
        if r1 is None or not r1.success:
            print(f"CANARY FAULT: initial g0 store did not finish: {r1}")
            sys.exit(2)

        n_by_tensor = dict(G0_SEGMENTS)
        probe_tensors = [t for t in (2, 32, 61) if t in n_by_tensor]
        probe_positions = sorted({0, keys // 2, keys - 1})
        snapshot = {}
        for pt in probe_tensors:
            n = n_by_tensor[pt]
            for k in probe_positions:
                snapshot[(pt, k)] = caches.tensors[pt].tensor[
                    src_rows[k], :n].clone()

        dst_base = keys + 40
        dst_rows = list(range(dst_base, dst_base + keys))
        gpu_load = GPULoadStoreSpec(dst_rows, group_sizes=[keys],
                                    block_indices=[dst_base])

        n_ops = keys * len(G0_SEGMENTS)
        load_mib = sum(n for _, n in G0_SEGMENTS) * keys / 2**20
        print(f"copy leg: ops={n_ops} load={load_mib:.1f} MiB/iter "
              f"dst_base={dst_base}")

        for it in range(args.iters):
            _check_sim_alive(stop_event, it)

            for tensor_idx, _n in G0_SEGMENTS:
                caches.tensors[tensor_idx].tensor[
                    dst_base:dst_base + keys, :].zero_()
            torch.cuda.synchronize()

            job_id = 1000 + it
            t0 = time.perf_counter()
            ok = handler.transfer_async(job_id, (spec_tier, gpu_load))
            if not ok:
                print(f"CANARY FAULT: transfer_async rejected "
                      f"iter {it}")
                sys.exit(2)
            r = drain(handler, job_id, timeout=300)
            wall = time.perf_counter() - t0
            if r is None or not r.success:
                print(f"FAULT at copy iter {it} load: job did not "
                      f"finish: {r}")
                if sim_fault:
                    print(f"sim_fault: {sim_fault}")
                print(f"CANARY FAULT: load job {job_id} failed "
                      f"iter {it}")
                sys.exit(2)

            probe(f"copy iter {it} post-load", checker)

            bad = []
            for (pt, k), want in snapshot.items():
                got = caches.tensors[pt].tensor[
                    dst_rows[k], :want.numel()]
                if not torch.equal(got, want):
                    bad.append((pt, k))
            if bad:
                print(f"CANARY MISMATCH: iter {it} bad probes: {bad}")
                sys.exit(1)

            mib = r.transfer_size / 2**20
            print(f"iter {it:3d}: wall={wall:6.2f} s mib={mib:7.1f}")
    finally:
        handler.shutdown()
        shutil.rmtree(root, ignore_errors=True)


# --------------------------------- main ----------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--leg", choices=["batch", "copy"], required=True,
                    help="batch: raw swap_blocks_batch repro leg. "
                         "copy: end-to-end copy_ leg through the "
                         "production handler.")
    ap.add_argument("--sim", choices=["none", "kernels", "graph", "both"],
                    default="both",
                    help="concurrent engine-simulator activity on the "
                         "default stream (H2). default: both.")
    ap.add_argument("--iters", type=int, default=20,
                    help="canary iterations (default: 20).")
    ap.add_argument("--rows", type=int, default=4000,
                    help="GPU tensor rows (default: 4000). NOTE: if left "
                         "at the default and --leg copy is selected, "
                         "this is silently lowered to 1500 (the copy leg "
                         "goes through the full handler, not a raw op "
                         "battery, so it doesn't need the batch leg's "
                         "~9 GiB geometry). Pass --rows explicitly to "
                         "override.")
    ap.add_argument("--slots", type=int, default=3062,
                    help="pinned ring slots (default: 3062). Same "
                         "--leg copy default-lowering caveat as --rows "
                         "(silently lowered to 800 at the default).")
    ap.add_argument("--keys", type=int, default=256,
                    help="group-0 keys per load (default: 256).")
    ap.add_argument("--fill-gib", type=int, default=0,
                    help="allocate N GiB of GPU filler before the run to "
                         "mimic production memory pressure (boot-9 head "
                         "had ~8-10 GiB free of 119). default: 0.")
    args = ap.parse_args()

    rows, slots = args.rows, args.slots
    if args.leg == "copy":
        # Smaller footprint by default: the copy leg goes through the
        # full production handler (per-key file IO), not a raw op
        # battery, so it doesn't need the batch leg's ~9 GiB geometry.
        if rows == 4000:
            rows = 1500
        if slots == 3062:
            slots = 800

    assert torch.cuda.is_available(), "CUDA required"
    torch.cuda.init()

    gpu_bytes = rows * PAGE_BYTES_TOTAL
    ring_bytes = slots * PAGE_BYTES_TOTAL
    total_bytes = gpu_bytes + ring_bytes
    assert total_bytes < 16 * 2**30, (
        f"peak memory too large: gpu={gpu_bytes / 2**30:.2f} GiB "
        f"ring={ring_bytes / 2**30:.2f} GiB "
        f"total={total_bytes / 2**30:.2f} GiB (limit 16 GiB)"
    )

    n_ops = args.keys * len(G0_SEGMENTS)
    load_mib = args.keys * sum(n for _, n in G0_SEGMENTS) / 2**20
    print(f"config leg={args.leg} sim={args.sim} iters={args.iters} "
          f"rows={rows} slots={slots} keys={args.keys} ops={n_ops} "
          f"load={load_mib:.1f} MiB gpu={gpu_bytes / 2**30:.2f} GiB "
          f"ring={ring_bytes / 2**30:.2f} GiB")

    filler = None
    if args.fill_gib:
        # One tensor per GiB: a single huge alloc can fail where many
        # 1 GiB allocs succeed, and per-GiB granularity degrades softly.
        filler = []
        for _ in range(args.fill_gib):
            filler.append(torch.empty(1 << 30, dtype=torch.int8,
                                      device="cuda"))
        # Touch the filler so the pages are actually resident, then
        # leave it alone: pure occupancy pressure, like model weights.
        for f in filler:
            f[:: 1 << 20].fill_(1)
        torch.cuda.synchronize()
        print(f"filler resident: {len(filler)} GiB")

    # Capture BOTH graphs before any thread starts (capture is not
    # thread-safe against concurrent CUDA activity on other streams).
    print("capturing checker/sim CUDA graphs (main thread, pre-thread)")
    checker = _build_graph("checker", seed=1)
    sim_graph, sim_bufs = _build_graph("sim", seed=2)

    stop_event = threading.Event()
    sim_thread = None
    if args.sim != "none":
        sim_thread = threading.Thread(
            target=engine_simulator,
            args=(args.sim, sim_graph, sim_bufs, stop_event),
            name="engine_sim", daemon=True,
        )
        sim_thread.start()

    try:
        if args.leg == "batch":
            run_batch_leg(args, rows, slots, checker, stop_event)
        else:
            run_copy_leg(args, rows, slots, checker, stop_event)
    finally:
        stop_event.set()
        if sim_thread is not None:
            sim_thread.join(timeout=10)

    if sim_fault:
        print(f"CANARY FAULT: sim thread died during the run: "
              f"{sim_fault}")
        sys.exit(2)

    print(f"CANARY PASS: leg={args.leg} sim={args.sim} "
          f"iters={args.iters} (no fault, byte-exact)")
    sys.exit(0)


if __name__ == "__main__":
    main()
