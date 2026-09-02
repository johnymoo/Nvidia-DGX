#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fault-injection tests for the connector failure overlay (no GPU needed).

Runs inside a throwaway container of the production image WITH THE OVERLAY
BIND-MOUNTED over the real connector paths (that also smoke-tests the exact
deployment mechanism):

  docker run --rm --entrypoint python3 \
    -v /home/<user>/phase-b-nvme:/opt/pkg:ro \
    -e PYTHONPATH=/opt/pkg -e PYTHONHASHSEED=0 \
    $(for f in common.py scheduler.py worker.py; do echo -n \
      "-v /home/<user>/phase-b-nvme/overlay/vllm/distributed/kv_transfer/kv_connector/v1/offloading/$f:/opt/env/lib/python3.12/site-packages/vllm/distributed/kv_transfer/kv_connector/v1/offloading/$f:ro "; done) \
    gb10-ds4-vllm:f277b3d-nvfp4 /opt/pkg/connector-failure-overlay/test_failure_recompute.py

Covers: worker-side failure reporting, metadata aggregation, scheduler-side
degrade-to-recompute (num_computed_tokens truncation + manager key drop),
store-failure key drop, TP partial-failure semantics, success-path regression,
manager complete_load(success=False), handler corrupt-file unlink.
"""
import os
import sys
import tempfile
from types import SimpleNamespace

import vllm.distributed.kv_transfer.kv_connector.v1.offloading.common as oc
import vllm.distributed.kv_transfer.kv_connector.v1.offloading.scheduler as osched
import vllm.distributed.kv_transfer.kv_connector.v1.offloading.worker as oworker
from vllm.distributed.kv_transfer.kv_connector.v1.offloading.common import (
    OffloadingWorkerMetadata,
    TransferJob,
)
from vllm.distributed.kv_transfer.kv_connector.v1.offloading.scheduler import (
    OffloadingConnectorScheduler,
    TransferJobStatus,
)
from vllm.distributed.kv_transfer.kv_connector.v1.offloading.worker import (
    OffloadingConnectorWorker,
)
from vllm.v1.kv_offload.base import (
    ReqContext,
    make_offload_key,
)
from vllm.v1.kv_offload.worker.worker import TransferResult

from vllm_nvme_tier.manager import NVMeTierManager

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


# ---------------- overlay is actually mounted ----------------

def test_overlay_active():
    import dataclasses
    field_names = {f.name for f in dataclasses.fields(OffloadingWorkerMetadata)}
    check("failed_jobs field exists", "failed_jobs" in field_names)
    check("failed_jobs default", OffloadingWorkerMetadata().failed_jobs == {})
    check("mark_failed exists", hasattr(OffloadingWorkerMetadata, "mark_failed"))
    src = inspect_source(oworker.OffloadingConnectorWorker.get_finished)
    check("worker assert removed", "assert transfer_result.success" not in src)
    check("worker failure branch present", "mark_failed" in src)
    ssrc = inspect_source(OffloadingConnectorScheduler.update_connector_output)
    check("scheduler failure branch present", "num_locally_computed_tokens" in ssrc)


def inspect_source(fn):
    import inspect
    return inspect.getsource(fn)


# ---------------- worker side ----------------

def make_conn_worker(load_jobs, results):
    w = OffloadingConnectorWorker.__new__(OffloadingConnectorWorker)
    w.spec = None
    w.worker = SimpleNamespace(get_finished=lambda: results)
    from vllm.distributed.kv_transfer.kv_connector.v1.offloading.metrics import (
        OffloadingConnectorStats,
    )
    w.kv_connector_stats = OffloadingConnectorStats()
    w._load_jobs = dict(load_jobs)
    w._unsubmitted_store_jobs = []
    w._connector_worker_meta = OffloadingWorkerMetadata()
    w._failed_start_recving = set()
    return w


def test_worker_failures():
    results = [
        TransferResult(job_id=7, success=False, transfer_type=("NVME_TIER", "GPU")),
        TransferResult(job_id=8, success=False, transfer_type=("GPU", "NVME_TIER")),
        TransferResult(job_id=9, success=True, transfer_size=100,
                       transfer_time=0.1, transfer_type=("GPU", "NVME_TIER")),
        TransferResult(job_id=10, success=True, transfer_size=200,
                       transfer_time=0.2, transfer_type=("NVME_TIER", "GPU")),
    ]
    w = make_conn_worker({7: "req-A", 10: "req-B"}, results)
    sending, recving = w.get_finished(set())
    check("failed load emits finished_recving", recving == {"req-A", "req-B"})
    check("no finished_sending", sending == set())
    m = w.build_connector_worker_meta()
    check("failed jobs reported", m is not None
          and m.failed_jobs == {7: 1, 8: 1}
          and m.completed_jobs == {9: 1, 10: 1})
    check("failed load popped", 7 not in w._load_jobs)

    # meta with ONLY failures must still be delivered
    w2 = make_conn_worker({1: "r"}, [
        TransferResult(job_id=1, success=False),
    ])
    w2.get_finished(set())
    check("failure-only meta delivered",
          w2.build_connector_worker_meta() is not None)


def test_aggregate():
    a = OffloadingWorkerMetadata()
    a.mark_completed(5)
    a.mark_failed(6)
    b = OffloadingWorkerMetadata()
    b.mark_failed(6)
    b.mark_completed(7)
    m = a.aggregate(b)
    check("aggregate completed", m.completed_jobs == {5: 1, 7: 1})
    check("aggregate failed", m.failed_jobs == {6: 2})


# ---------------- scheduler side ----------------

class FakeReq:
    def __init__(self, rid, computed):
        self.request_id = rid
        self.num_computed_tokens = computed
        self._finished = False

    def is_finished(self):
        return self._finished


def make_sched():
    s = OffloadingConnectorScheduler.__new__(OffloadingConnectorScheduler)
    s.manager = NVMeTierManager(
        num_slots=8, bytes_budget=10000,
        per_key_bytes=lambda key: 100, enable_events=False,
    )
    s._stale_job_threshold = 0
    s._jobs = {}
    s._req_status = {}
    s._blocks_being_loaded = set()
    s._block_id_to_pending_jobs = {}
    return s


def add_load_job(s, jid, keys, computed=5000, local=3000):
    req = FakeReq(f"req-{jid}", computed)
    rs = SimpleNamespace(
        req=req,
        req_context=ReqContext(req_id=req.request_id, kv_transfer_params=None),
        transfer_jobs={jid},
        num_locally_computed_tokens=local,
    )
    s._req_status[req.request_id] = rs
    s._jobs[jid] = TransferJobStatus(
        req_id=req.request_id, pending_count=2, keys=set(keys), is_store=False,
    )
    # manager side: key on disk + a load in flight
    out = s.manager.prepare_store(list(keys), CTX)
    s.manager.complete_store(out.keys_to_store, CTX)
    s.manager.prepare_load(list(keys), CTX)
    s._blocks_being_loaded.update(keys)
    return req


def feed(s, completed=None, failed=None):
    meta = OffloadingWorkerMetadata(
        completed_jobs=completed or {}, failed_jobs=failed or {}
    )
    s.update_connector_output(
        SimpleNamespace(kv_connector_worker_meta=meta)
    )


def test_load_failure_recompute():
    key = k(b"load-fail" * 3)
    s = make_sched()
    req = add_load_job(s, 7, [key])
    feed(s, failed={7: 2})
    check("num_computed truncated to local",
          req.num_computed_tokens == 3000)
    check("manager dropped failed key", s.manager.lookup(key, CTX) is False)
    check("blocks_being_loaded cleaned", not s._blocks_being_loaded)
    check("job cleaned", 7 not in s._jobs and not rs_jobs(s, req))


def rs_jobs(s, req):
    return s._req_status[req.request_id].transfer_jobs


def test_partial_rank_failure():
    key = k(b"partial" * 3)
    s = make_sched()
    req = add_load_job(s, 8, [key])
    feed(s, completed={8: 1}, failed={8: 1})
    check("any-failure wins", req.num_computed_tokens == 3000)
    check("key dropped on partial failure",
          s.manager.lookup(key, CTX) is False)


def test_success_regression():
    key = k(b"success" * 3)
    s = make_sched()
    req = add_load_job(s, 9, [key])
    feed(s, completed={9: 2})
    check("success keeps computed tokens", req.num_computed_tokens == 5000)
    check("success keeps key", s.manager.lookup(key, CTX) is True)


def test_store_failure_drops_keys():
    key = k(b"store-fail" * 2)
    s = make_sched()
    req = FakeReq("req-s", 100)
    s._req_status["req-s"] = SimpleNamespace(
        req=req,
        req_context=ReqContext(req_id="req-s", kv_transfer_params=None),
        transfer_jobs={11},
        num_locally_computed_tokens=0,
    )
    # key mid-store (storing=True)
    out = s.manager.prepare_store([key], CTX)
    assert out is not None and out.keys_to_store
    s._jobs[11] = TransferJobStatus(
        req_id="req-s", pending_count=2, keys={key}, is_store=True,
    )
    feed(s, failed={11: 2})
    check("failed store drops key", s.manager.lookup(key, CTX) is False)
    out2 = s.manager.prepare_store([key], CTX)
    check("failed store re-offerable",
          out2 is not None and len(out2.keys_to_store) == 1)


def test_stale_failed_job_ignored():
    key = k(b"stale" * 4)
    s = make_sched()
    s._stale_job_threshold = 100
    add_load_job(s, 50, [key])
    feed(s, failed={50: 2})  # must not raise KeyError / touch manager
    check("stale failed job ignored", s.manager.lookup(key, CTX) is True)


def test_load_failed_to_start():
    """transfer_async returning False for a load must degrade: mark_failed
    (scheduler truncates + drops manager keys) and emit finished_recving
    on the NEXT get_finished so the parked request is promoted+rescheduled."""
    key = k(b"nostart" * 2)
    w = make_conn_worker({}, [])
    w.worker = SimpleNamespace(
        transfer_async=lambda job_id, spec: False,
        get_finished=lambda: [],
    )
    meta = oc.OffloadingConnectorMetadata(
        load_jobs={3: TransferJob(
            req_id="req-nostart",
            transfer_spec=(SimpleNamespace(), SimpleNamespace()),
        )},
        store_jobs={},
    )
    w.start_kv_transfers(meta)
    check("failed start marked", w._connector_worker_meta.failed_jobs == {3: 1})
    check("load job popped", 3 not in w._load_jobs)
    check("pending recving recorded", w._failed_start_recving == {"req-nostart"})
    _sending, recving = w.get_finished(set())
    check("finished_recving emitted next step", recving == {"req-nostart"})
    check("pending cleared", not w._failed_start_recving)

    # store failing to start: mark_failed only, no recving
    w2 = make_conn_worker({}, [])
    w2.worker = SimpleNamespace(
        transfer_async=lambda job_id, spec: False,
        get_finished=lambda: [],
    )
    meta2 = oc.OffloadingConnectorMetadata(
        load_jobs={},
        store_jobs={4: TransferJob(
            req_id="req-store",
            transfer_spec=(SimpleNamespace(), SimpleNamespace()),
        )},
    )
    w2.prepare_store_kv(meta2)
    w2.start_kv_transfers(oc.OffloadingConnectorMetadata(
        load_jobs={}, store_jobs={}))
    # prepare_store_kv defers; flush via handle_preemptions
    w2.handle_preemptions(oc.OffloadingConnectorMetadata(
        load_jobs={}, store_jobs={}))
    check("store failed start marked",
          w2._connector_worker_meta.failed_jobs == {4: 1})


# ---------------- manager + handler failure semantics ----------------

def test_manager_complete_load_failure():
    m = NVMeTierManager(num_slots=8, bytes_budget=10000,
                        per_key_bytes=lambda key: 100)
    key = k(b"mgr-fail" * 2)
    out = m.prepare_store([key], CTX)
    m.complete_store(out.keys_to_store, CTX)
    m.prepare_load([key], CTX)  # ref_cnt 1, slot held
    before = m._get_num_free_slots()
    m.complete_load([key], CTX, success=False)
    check("failure load frees slot", m._get_num_free_slots() == before + 1)
    check("failure load removes entry", m.lookup(key, CTX) is False)
    check("disk bytes restored", m._disk_bytes == 0)


def test_handler_unlinks_corrupt_file():
    from vllm_nvme_tier.gpu_worker import NVMeOffloadingHandler, write_key_file

    class FakeMapper:
        def get_file_name(self, key):
            return path_holder[0]

    path_holder = [None]
    fake = SimpleNamespace(_mapper=FakeMapper(), _ring_tensors=[])
    key = k(b"corrupt" * 3)

    with tempfile.TemporaryDirectory() as d:
        path_holder[0] = os.path.join(d, "bad_g0.bin")
        with open(path_holder[0], "wb") as f:
            f.write(b"KVNV" + b"\x00" * 40)  # bad header
        ok = NVMeOffloadingHandler._read_key_into_ring(fake, key, 0, [])
        check("corrupt read returns False", ok is False)
        check("corrupt file unlinked", not os.path.exists(path_holder[0]))

        # valid path sanity: empty segments with an empty payload round-trips
        import vllm_nvme_tier.gpu_worker as gw
        good = os.path.join(d, "good_g0.bin")
        gw.write_key_file(good, 0, b"")
        path_holder[0] = good
        ok = NVMeOffloadingHandler._read_key_into_ring(fake, key, 0, [])
        check("good read returns True", ok is True)
        check("good file kept", os.path.exists(good))


def main():
    test_overlay_active()
    test_worker_failures()
    test_aggregate()
    test_load_failure_recompute()
    test_partial_rank_failure()
    test_success_regression()
    test_store_failure_drops_keys()
    test_stale_failed_job_ignored()
    test_load_failed_to_start()
    test_manager_complete_load_failure()
    test_handler_unlinks_corrupt_file()
    print(f"FAILURE-OVERLAY TESTS: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
