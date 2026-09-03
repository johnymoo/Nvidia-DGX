#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Standalone logic tests for the NVMe tier package (no GPU needed).
Run inside a throwaway container of the production image:
  docker run --rm --entrypoint python3 \
    -v <pkg-dir>:/opt/pkg -e PYTHONPATH=/opt/pkg \
    gb10-ds4-vllm:f277b3d-nvfp4 /opt/pkg/test_logic.py
"""
import os
import sys
import tempfile
import time

from vllm.v1.kv_offload.base import (
    OffloadingEvent,
    make_offload_key,
    get_offload_group_idx,
)

from vllm_nvme_tier.manager import NVMeTierManager
from vllm_nvme_tier.specs import NVMeLoadStoreSpec

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"FAIL: {name}")


def k(blob: bytes, group: int = 0):
    return make_offload_key(blob, group)


CTX = None


def new_manager(num_slots=8, budget=10000, events=False, threshold=0):
    return NVMeTierManager(
        num_slots=num_slots,
        bytes_budget=budget,
        per_key_bytes=lambda key: 100 + get_offload_group_idx(key),
        enable_events=events,
        store_threshold=threshold,
    )


def test_state_machine():
    m = new_manager()
    key_a, key_b = k(b"a" * 20), k(b"b" * 20)
    check("lookup absent False", m.lookup(key_a, CTX) is False)

    out = m.prepare_store([key_a, key_b], CTX)
    check("store 2 keys", len(out.keys_to_store) == 2)
    check("store slots distinct", len(set(out.store_spec.block_ids.tolist())) == 2)
    check("storing lookup None", m.lookup(key_a, CTX) is None)

    m.complete_store(out.keys_to_store, CTX)
    check("stored lookup True", m.lookup(key_a, CTX) is True)

    out2 = m.prepare_store([key_a, key_b], CTX)
    check("dedupe repeat store", out2.keys_to_store == [])

    load_spec = m.prepare_load([key_a], CTX)
    check("load spec slots", isinstance(load_spec, NVMeLoadStoreSpec)
          and len(load_spec.block_ids) == 1)
    load_spec2 = m.prepare_load([key_a], CTX)
    check("concurrent load distinct slot",
          load_spec.block_ids[0] != load_spec2.block_ids[0])
    m.complete_load([key_a], CTX)
    m.complete_load([key_a], CTX)

    out3 = m.prepare_store([key_a], CTX)
    check("slot freed after loads", out3.keys_to_store == [])


def test_store_failure_and_reset():
    m = new_manager()
    key = k(b"x" * 20)
    out = m.prepare_store([key], CTX)
    m.complete_store(out.keys_to_store, CTX, success=False)
    check("failed store removes key", m.lookup(key, CTX) is False)
    out2 = m.prepare_store([key], CTX)
    check("re-store after failure", len(out2.keys_to_store) == 1)
    m.reset_cache()
    check("reset clears", m.lookup(key, CTX) is False)


def test_slot_backpressure():
    m = new_manager(num_slots=8)  # lookup floor = min(16, 8//4) = 2
    first = [k(bytes([i]) * 20) for i in range(5)]
    out = m.prepare_store(first, CTX)
    # 3 free, floor 2 -> capacity 1: a 6-key offer is PARTIALLY accepted
    out6 = m.prepare_store(
        [k(bytes([9, i]) * 20) for i in range(6)], CTX
    )
    check("oversized offer partially accepted",
          out6 is not None and len(out6.keys_to_store) == 1)
    check("partial alloc bounded", m._get_num_free_slots() == 2)
    m.complete_store(out.keys_to_store, CTX)
    m.complete_store(out6.keys_to_store, CTX)  # 8 free again
    full = m.prepare_store(
        [k(bytes([20 + i]) * 20) for i in range(6)], CTX
    )
    check("fits when ring drains", full is not None
          and len(full.keys_to_store) == 6)
    m.complete_store(full.keys_to_store, CTX)
    # 2 free <= floor 2 -> capacity 0 -> None (busy, not deadlock)
    m.prepare_store([k(bytes([40 + i]) * 20) for i in range(6)], CTX)
    check("busy ring returns None", m.prepare_store(
        [k(b"y" * 20)], CTX) is None)
    check("lookup None under slot pressure", m.lookup(first[0], CTX) is None)


def test_idle_wedge_regression():
    # Boots 6/7 wedge: flood stores hold the whole ring in storing
    # entries whose completions cannot reach the scheduler while the
    # engine is idle (worker get_finished only runs inside execute_model).
    # The load reserve must keep load claims admissible so the recheck
    # proceeds, executes, and flushes the backlog.
    m = new_manager(num_slots=80)  # floor 16, load reserve 20
    needle = [k(b"ndl" + bytes([i]) * 17) for i in range(4)]
    out0 = m.prepare_store(needle, CTX)
    m.complete_store(out0.keys_to_store, CTX)  # 4 on disk
    flood = [k(b"fld" + bytes([i]) * 17) for i in range(80)]
    out1 = m.prepare_store(flood, CTX)
    check("flood accepts ring minus reserve",
          len(out1.keys_to_store) == 60)
    check("reserve survives flood", m._get_num_free_slots() == 20)
    # completions unreported (idle engine): storing entries hold 60 slots
    hits = [m.lookup(x, CTX) for x in needle]
    check("idle recheck lookups hit", all(h is True for h in hits))
    spec = m.prepare_load(needle, CTX)
    check("idle recheck load admitted", len(spec.block_ids) == 4)


def test_claim_cap():
    # lookup() claims at most (free - floor) keys per pass so
    # prepare_load can never over-allocate the ring (the connector
    # claims the maximal hit prefix before allocating anything).
    m = new_manager(num_slots=80)  # floor 16, reserve 20
    needle = [k(b"ndl" + bytes([i]) * 17) for i in range(10)]
    out = m.prepare_store(needle, CTX)   # capacity 60, accepts 10
    m.complete_store(out.keys_to_store, CTX)  # 10 on disk, free 80
    flood = [k(b"fld" + bytes([i]) * 17) for i in range(80)]
    out2 = m.prepare_store(flood, CTX)   # accepts 60, free 20
    check("flood holds ring minus reserve", len(out2.keys_to_store) == 60)
    check("free equals reserve", m._get_num_free_slots() == 20)
    res = [m.lookup(x, CTX) for x in needle]
    check("claims capped at free minus floor",
          sum(r is True for r in res) == 4)
    check("excess claims truncate to False", res[4] is False)
    spec = m.prepare_load(needle[:4], CTX)
    check("capped load allocates", len(spec.block_ids) == 4)


def test_starve_degrade():
    # free <= floor with no completions for a long time: lookups degrade
    # to misses (recompute) instead of deferring forever. Stores alone
    # cannot reach the floor (the reserve stops them), so pin the rest
    # with an in-flight load first.
    m = new_manager(num_slots=80)  # floor 16, reserve 20
    keys = [k(b"str" + bytes([i]) * 17) for i in range(10)]
    out = m.prepare_store(keys, CTX)
    m.complete_store(out.keys_to_store, CTX)  # 10 on disk, free 80
    flood = [k(b"fld" + bytes([i]) * 17) for i in range(80)]
    m.prepare_store(flood, CTX)               # 60 storing, free 20
    m.prepare_load(keys[:4], CTX)             # free 16 == floor
    check("ring at floor", m._get_num_free_slots() == 16)
    on_disk = keys[9]
    m._last_completion = time.monotonic()
    check("fresh starve defers", m.lookup(on_disk, CTX) is None)
    m._last_completion = time.monotonic() - 20.0
    check("stale starve degrades to miss", m.lookup(on_disk, CTX) is False)


def test_stuck_store_degrade():
    # a storing entry older than the grace window is dropped and its
    # slot freed; requests recompute instead of deferring forever.
    m = new_manager(num_slots=8)
    key = k(b"stk" + b"x" * 17)
    out = m.prepare_store([key], CTX)
    check("one slot held", m._get_num_free_slots() == 7)
    entry = m._entries[key]
    entry.t_stored = time.monotonic() - 60.0
    check("stuck store degrades to miss", m.lookup(key, CTX) is False)
    check("entry dropped", key not in m._entries)
    check("slot recovered", m._get_num_free_slots() == 8)


def test_budget_eviction():
    m = new_manager(num_slots=8, budget=250, events=True)
    batches = []
    for i in range(4):
        keys = [k(f"{i:02d}".encode() * 10)]
        out = m.prepare_store(keys, CTX)
        check(f"store batch {i}", out is not None and len(out.keys_to_store) == 1)
        m.complete_store(out.keys_to_store, CTX)
        batches.append(keys[0])
    # budget 250 vs 4 keys * 101 B = 404 -> LRU eviction must have fired
    evicted = [e for e in m.take_events() if e.removed]
    check("eviction events emitted", len(evicted) >= 1)
    check("oldest evicted", m.lookup(batches[0], CTX) is False)
    check("newest survives", m.lookup(batches[-1], CTX) is True)
    # pinned keys are protected: load-hold blocks eviction
    m.prepare_load([batches[-1]], CTX)
    keys = [k("zz".encode() * 10) for _ in range(3)]
    out = m.prepare_store(keys, CTX)
    check("pinned not evicted", m.lookup(batches[-1], CTX) is not False)


def test_store_threshold():
    m = new_manager(threshold=2)
    key = k(b"t" * 20)
    m.lookup(key, CTX)  # count 1
    out = m.prepare_store([key], CTX)
    check("threshold filters", out.keys_to_store == [])
    m.lookup(key, CTX)  # count 2
    out = m.prepare_store([key], CTX)
    check("threshold admits at 2", len(out.keys_to_store) == 1)


def test_file_io():
    # import from gpu_worker without instantiating the CUDA handler
    from vllm_nvme_tier.gpu_worker import (
        _group_segment_refs,
        read_key_file,
        write_key_file,
    )
    from vllm.v1.kv_offload.base import CanonicalKVCacheRef

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "aa", "bb_g0", "cafe.bin")
        payload = os.urandom(149504)
        write_key_file(path, 0, payload)
        group, back = read_key_file(path)
        check("file round trip", group == 0 and back == payload)
        st1 = os.stat(path)
        write_key_file(path, 0, b"different-but-skipped")
        check("exists dedupe keeps original", os.stat(path).st_mtime_ns == st1.st_mtime_ns)

        # corruption: flip a payload byte
        with open(path, "r+b") as f:
            f.seek(24 + 100)
            f.write(bytes([f.read(1)[0] ^ 0xFF]))
        try:
            read_key_file(path)
            check("crc detects corruption", False)
        except OSError:
            check("crc detects corruption", True)

        # truncation
        short = os.path.join(d, "cc.bin")
        with open(short, "wb") as f:
            f.write(b"KVNV")
        try:
            read_key_file(short)
            check("short header rejected", False)
        except OSError:
            check("short header rejected", True)

    # segment dedupe: layers aliasing one tensor collapse to one segment
    refs = [
        CanonicalKVCacheRef(tensor_idx=0, page_size_bytes=149504),
        CanonicalKVCacheRef(tensor_idx=0, page_size_bytes=149504),
        CanonicalKVCacheRef(tensor_idx=1, page_size_bytes=1168),
    ]
    segs = _group_segment_refs(refs)
    check("segment dedupe", segs == [(0, 149504), (1, 1168)])


def main():
    test_state_machine()
    test_store_failure_and_reset()
    test_slot_backpressure()
    test_idle_wedge_regression()
    test_claim_cap()
    test_starve_degrade()
    test_stuck_store_degrade()
    test_budget_eviction()
    test_store_threshold()
    test_file_io()
    print(f"LOGIC TESTS: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
