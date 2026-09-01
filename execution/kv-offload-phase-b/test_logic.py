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
    check("store beyond slots returns None", m.prepare_store(
        [k(b"z" * 20)] * 6 and [k(bytes([9, i]) * 20) for i in range(6)], CTX
    ) is None)
    check("no partial allocation", m._get_num_free_slots() == 3)
    m.complete_store(out.keys_to_store, CTX)  # 8 free again
    in_flight = [k(bytes([20 + i]) * 20) for i in range(6)]
    m.prepare_store(in_flight, CTX)  # 2 free <= floor 2
    check("lookup None under slot pressure", m.lookup(first[0], CTX) is None)


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
    test_budget_eviction()
    test_store_threshold()
    test_file_io()
    print(f"LOGIC TESTS: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
