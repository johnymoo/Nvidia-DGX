# SPDX-License-Identifier: Apache-2.0
"""Worker-side handler for the NVMe tier: GPU <-> staging ring <-> rank-local
NVMe files. Runs ONLY in each rank's worker process; file IO on a
DualQueueThreadPool (loads strictly prioritized over stores).

Transport layout (Rev 2): the ring is pinned transport, never a hit source.
  store:  GPU blocks -> ring rows (CUDA stream) -> file write per key
          (atomic temp+rename + fdatasync, exists-check dedupe) -> done.
  load:   file read per key -> crc verify -> ring rows -> GPU blocks
          (CUDA stream) -> done.

File format (per key): 24 B header + payload.
  header: magic b"KVNV" | version u16 | group_idx u16 | payload_len u64 |
          crc32(payload) u32 | reserved u32   (all little endian)
  payload: for each DISTINCT tensor_idx in the key's group (order of first
          appearance), the ring row's first `unpadded page bytes`.
Layers sharing a canonical tensor alias the same storage by construction
(the fork's uniform-group invariant), so one segment per tensor is exact.

O_DIRECT is deliberately NOT used (unpadded 1,168 B SWA pages break
alignment); buffered IO + posix_fadvise(POSIX_FADV_DONTNEED) after every
read/write keeps the page cache flat on these zero-headroom hosts.

All CUDA stream work is serialized on one stream; the chaining event is
updated under a lock because the load's CUDA leg is issued from the file
thread while stores are issued from the engine thread.
"""
import os
import struct
import threading
import time
import zlib
from collections import deque
from dataclasses import dataclass

import numpy as np
import torch

from vllm import _custom_ops as ops
from vllm.logger import init_logger
from vllm.utils.math_utils import cdiv
from vllm.v1.kv_offload.base import (
    BlockIDsLoadStoreSpec,
    CanonicalKVCaches,
    CanonicalKVCacheRef,
    GPULoadStoreSpec,
    OffloadKey,
    get_offload_group_idx,
)
from vllm.v1.kv_offload.cpu.gpu_worker import compute_sub_block_ptrs
from vllm.v1.kv_offload.file_mapper import FileMapper
from vllm.v1.kv_offload.tiering.fs.thread_pool import DualQueueThreadPool
from vllm.v1.kv_offload.worker.worker import (
    OffloadingHandler,
    TransferResult,
    TransferSpec,
)

from vllm_nvme_tier.specs import NVMeLoadStoreSpec

logger = init_logger(__name__)

_MAGIC = b"KVNV"
_VERSION = 1
_HEADER = struct.Struct("<4sHHQII")  # magic, ver, group, len, crc32, rsvd
assert _HEADER.size == 24

try:
    _FADV_DONTNEED = os.POSIX_FADV_DONTNEED

    def _fadvise_dontneed(fd: int) -> None:
        try:
            os.posix_fadvise(fd, 0, 0, _FADV_DONTNEED)
        except OSError:
            pass
except AttributeError:
    def _fadvise_dontneed(fd: int) -> None:
        pass


def _group_segment_refs(
    group_data_refs: list[CanonicalKVCacheRef],
) -> list[tuple[int, int]]:
    """Distinct (tensor_idx, unpadded_bytes) segments for one group, in order
    of first appearance; layers aliasing a tensor must agree on page bytes."""
    seen: dict[int, int] = {}
    out: list[tuple[int, int]] = []
    for ref in group_data_refs:
        if ref.tensor_idx in seen:
            assert seen[ref.tensor_idx] == ref.page_size_bytes, (
                "layers sharing a canonical tensor disagree on page size"
            )
            continue
        seen[ref.tensor_idx] = ref.page_size_bytes
        out.append((ref.tensor_idx, ref.page_size_bytes))
    return out



def write_key_file(path: str, group_idx: int, payload: bytes) -> None:
    """Atomic content-addressed write: tmp + fsync + rename; exists-check
    dedupe (a present file is byte-identical by construction)."""
    if os.path.exists(path):
        return
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    header = _HEADER.pack(_MAGIC, _VERSION, group_idx, len(payload), crc, 0)
    tmp = path + f".tmp{os.getpid()}_{threading.get_ident():x}"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, header + payload)
        os.fsync(fd)
        _fadvise_dontneed(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def read_key_file(path: str) -> tuple[int, bytes]:
    """Read + verify; returns (group_idx, payload). Raises OSError on any
    mismatch (caller treats as load failure)."""
    with open(path, "rb") as f:
        header = f.read(_HEADER.size)
        if len(header) != _HEADER.size:
            raise OSError("short header")
        magic, ver, group_idx, plen, crc, _r = _HEADER.unpack(header)
        if magic != _MAGIC or ver != _VERSION:
            raise OSError("bad header")
        payload = f.read(plen)
        if len(payload) != plen:
            raise OSError("short payload")
        if zlib.crc32(payload) & 0xFFFFFFFF != crc:
            raise OSError("crc mismatch")
        _fadvise_dontneed(f.fileno())
    return group_idx, payload


@dataclass
class _StoreJob:
    job_id: int
    keys: list[OffloadKey]
    slots: list[int]
    segments: list[list[tuple[int, int]]]
    start: torch.Event
    end: torch.Event
    num_bytes: int
    cuda_time: float | None = None
    filed: bool = False


@dataclass
class _LoadJob:
    job_id: int
    keys: list[OffloadKey]
    slots: list[int]
    segments: list[list[tuple[int, int]]]
    gpu_spec: GPULoadStoreSpec
    num_bytes: int
    start: torch.Event | None = None
    end: torch.Event | None = None
    cuda_ready: bool = False
    failed: bool = False


class NVMeOffloadingHandler(OffloadingHandler):
    """Both directions: (GPU, NVME_TIER) store and (NVME_TIER, GPU) load."""

    def __init__(
        self,
        kv_caches: CanonicalKVCaches,
        num_slots: int,
        file_mapper: FileMapper,
        io_threads: int = 4,
        physical_budget_bytes: int = 0,
        gc_interval_s: float = 60.0,
    ):
        assert num_slots > 0
        self._gpu_tensors: list[torch.Tensor] = []
        self._ring_tensors: list[torch.Tensor] = []
        for kt in kv_caches.tensors:
            page = kt.page_size_bytes
            self._gpu_tensors.append(kt.tensor.view(torch.int8).view((-1, page)))
            self._ring_tensors.append(
                torch.empty(
                    (num_slots, page), dtype=torch.int8, device="cpu",
                    pin_memory=True,
                )
            )
        self._group_segments = [
            _group_segment_refs(refs) for refs in kv_caches.group_data_refs
        ]
        self._mapper = file_mapper
        self._pool = DualQueueThreadPool(io_threads, io_threads, "nvme_tier")
        self._stream = torch.cuda.Stream()
        self._last_end_event: torch.Event | None = None
        self._chain_lock = threading.Lock()

        self._jobs: dict[int, _StoreJob | _LoadJob] = {}
        self._order: deque[int] = deque()  # job ids, FIFO completion barrier
        self._slot_busy: set[int] = set()
        self._slot_lock = threading.Lock()

        self._physical_budget = physical_budget_bytes
        self._gc_interval = gc_interval_s
        self._gc_stop = threading.Event()
        self._gc_thread = threading.Thread(
            target=self._gc_loop, name="nvme_tier_gc", daemon=True
        )
        self._gc_thread.start()
        # layout ground truth for the campaign log (warning: always printed)
        logger.warning(
            "NVME-TIER-LAYOUT gpu_tensors=%s ring_rows=%d segments=%s",
            [(t.shape[1], t.shape[0]) for t in self._gpu_tensors],
            num_slots,
            self._group_segments,
        )
        logger.info(
            "NVMe tier handler: %d tensors, ring %d slots (%.0f MiB), root %s_r%d",
            len(self._gpu_tensors), num_slots,
            sum(t.numel() for t in self._ring_tensors) / 2**20,
            file_mapper.base_path, file_mapper.rank,
        )

    # ---------------- pointer construction ----------------

    def _copy_ops(
        self,
        gpu_spec: GPULoadStoreSpec,
        other: BlockIDsLoadStoreSpec,
        gpu_is_src: bool,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
        """Per-(block, tensor-segment) copy ops between GPU blocks and ring
        slots. block_size_factor is 1 (the NVMe tier never sets extra
        block_size), so group i's GPU block ids and ring slots align 1:1.
        Tensor segments are deduped per group (aliased layers copy the same
        bytes; one op per distinct tensor is exact and cheaper)."""
        group_sizes = gpu_spec.group_sizes
        assert len(group_sizes) == len(self._group_segments)
        num_ops = sum(
            gs * len(segs) for gs, segs in zip(group_sizes, self._group_segments)
        )
        src = np.empty(num_ops, dtype=np.int64)
        dst = np.empty(num_ops, dtype=np.int64)
        sizes = np.empty(num_ops, dtype=np.int64)
        gpu_off = other_off = op = 0
        total = 0
        for gs, segments in zip(group_sizes, self._group_segments):
            if gs == 0:
                continue
            g_ids = gpu_spec.block_ids[gpu_off : gpu_off + gs]
            r_ids = other.block_ids[other_off : other_off + gs]
            assert len(r_ids) == len(g_ids)
            for tensor_idx, nbytes in segments:
                end = op + gs
                g = self._gpu_tensors[tensor_idx]
                r = self._ring_tensors[tensor_idx]
                if gpu_is_src:
                    compute_sub_block_ptrs(g_ids, 1, src[op:end], g)
                    compute_sub_block_ptrs(r_ids, 1, dst[op:end], r)
                else:
                    compute_sub_block_ptrs(r_ids, 1, src[op:end], r)
                    compute_sub_block_ptrs(g_ids, 1, dst[op:end], g)
                sizes[op:end] = nbytes
                total += gs * nbytes
                op = end
            gpu_off += gs
            other_off += gs
        assert op == num_ops and gpu_off == len(gpu_spec.block_ids)
        return src, dst, sizes, total

    # ---------------- transfer_async ----------------

    def _validate_ops(
        self,
        src: np.ndarray,
        dst: np.ndarray,
        sizes: np.ndarray,
        job_id: int,
        gpu_is_src: bool,
    ) -> None:
        """Bounds-check every op against its tensor's storage so a bad
        pointer surfaces as a readable exception instead of a CUDA
        segfault (20260902 boot-2: first store job died in
        cuMemcpyBatchAsync with no diagnostic)."""
        gpu_spans = [
            (t.data_ptr(), t.data_ptr() + t.untyped_storage().nbytes())
            for t in self._gpu_tensors
        ]
        ring_spans = [
            (t.data_ptr(), t.data_ptr() + t.numel())
            for t in self._ring_tensors
        ]

        def check(ptr: int, n: int, spans, kind: str, i: int) -> None:
            for b, e in spans:
                if b <= ptr < e:
                    if ptr + n > e:
                        raise RuntimeError(
                            f"NVMe tier job {job_id} op {i}: {kind} overrun "
                            f"ptr=0x{ptr:x} n={n} extent=[0x{b:x},0x{e:x})"
                        )
                    return
            raise RuntimeError(
                f"NVMe tier job {job_id} op {i}: {kind} pointer outside "
                f"any tensor: ptr=0x{ptr:x} spans="
                f"{[hex(b) for b, _ in spans]}"
            )

        for i in range(len(sizes)):
            sp, dp, n = int(src[i]), int(dst[i]), int(sizes[i])
            if gpu_is_src:
                check(sp, n, gpu_spans, "src(gpu)", i)
                check(dp, n, ring_spans, "dst(ring)", i)
            else:
                check(sp, n, ring_spans, "src(ring)", i)
                check(dp, n, gpu_spans, "dst(gpu)", i)

    def transfer_async(self, job_id: int, spec: TransferSpec) -> bool:
        src_spec, dst_spec = spec
        if isinstance(src_spec, GPULoadStoreSpec):
            assert isinstance(dst_spec, NVMeLoadStoreSpec)
            return self._start_store(job_id, src_spec, dst_spec)
        assert isinstance(src_spec, NVMeLoadStoreSpec)
        assert isinstance(dst_spec, GPULoadStoreSpec)
        return self._start_load(job_id, src_spec, dst_spec)

    def _claim_slots(self, slots: list[int]) -> None:
        with self._slot_lock:
            clash = self._slot_busy.intersection(slots)
            assert not clash, f"ring slots in flight: {sorted(clash)}"
            self._slot_busy.update(slots)

    def _start_store(
        self, job_id: int, gpu_spec: GPULoadStoreSpec, tier: NVMeLoadStoreSpec
    ) -> bool:
        slots = tier.block_ids.tolist()
        keys = tier.keys
        self._claim_slots(slots)
        src, dst, sizes, total = self._copy_ops(gpu_spec, tier, gpu_is_src=True)
        self._validate_ops(src, dst, sizes, job_id, gpu_is_src=True)
        start, end = torch.Event(enable_timing=True), torch.Event(enable_timing=True)
        with self._chain_lock:
            self._stream.wait_stream(torch.cuda.current_stream())
            if self._last_end_event is not None:
                self._stream.wait_event(self._last_end_event)
            with torch.cuda.stream(self._stream):
                start.record(self._stream)
                if len(sizes) > 0:
                    ops.swap_blocks_batch(
                        torch.from_numpy(src), torch.from_numpy(dst),
                        torch.from_numpy(sizes), is_src_access_order_any=False,
                    )
                end.record(self._stream)
            self._last_end_event = end
        self._jobs[job_id] = _StoreJob(
            job_id=job_id, keys=keys, slots=slots,
            segments=[self._group_segments[get_offload_group_idx(k)] for k in keys],
            start=start, end=end, num_bytes=total,
        )
        self._order.append(job_id)
        return True

    def _start_load(
        self, job_id: int, tier: NVMeLoadStoreSpec, gpu_spec: GPULoadStoreSpec
    ) -> bool:
        slots = tier.block_ids.tolist()
        keys = tier.keys
        self._claim_slots(slots)
        num_bytes = sum(n for k in keys
                        for _, n in self._group_segments[get_offload_group_idx(k)])
        job = _LoadJob(
            job_id=job_id, keys=keys, slots=slots,
            segments=[self._group_segments[get_offload_group_idx(k)] for k in keys],
            gpu_spec=gpu_spec, num_bytes=num_bytes,
        )
        self._jobs[job_id] = job  # register BEFORE enqueue (thread race)
        self._order.append(job_id)
        self._pool.enqueue_load(job_id, 1, [self._load_file_task(job)])
        return True

    # ---------------- file stages ----------------

    def _load_file_task(self, job: _LoadJob):
        def task() -> None:
            for key, slot, segments in zip(job.keys, job.slots, job.segments):
                if not self._read_key_into_ring(key, slot, segments):
                    job.failed = True
                    return
            # CUDA leg: ring -> GPU (thread-issued; chain under lock)
            src, dst, sizes, _ = self._copy_ops(
                job.gpu_spec, NVMeLoadStoreSpec(job.slots, job.keys),
                gpu_is_src=False,
            )
            self._validate_ops(src, dst, sizes, job.job_id, gpu_is_src=False)
            start, end = torch.Event(enable_timing=True), torch.Event(enable_timing=True)
            with self._chain_lock:
                if self._last_end_event is not None:
                    self._stream.wait_event(self._last_end_event)
                with torch.cuda.stream(self._stream):
                    start.record(self._stream)
                    if len(sizes) > 0:
                        ops.swap_blocks_batch(
                            torch.from_numpy(src), torch.from_numpy(dst),
                            torch.from_numpy(sizes), is_src_access_order_any=True,
                        )
                    end.record(self._stream)
                self._last_end_event = end
            job.start, job.end, job.cuda_ready = start, end, True

        return task

    def _read_key_into_ring(
        self, key: OffloadKey, slot: int, segments
    ) -> bool:
        path = self._mapper.get_file_name(key)
        try:
            _group_idx, payload = read_key_file(path)
        except OSError as e:
            logger.warning("NVMe load failed (%s): %r", path[-40:], e)
            # Best-effort unlink: the bytes are unverified/missing, the
            # scheduler drops the key from the table, and the physical GC
            # would otherwise keep the corpse until its LRU turn anyway.
            try:
                os.remove(path)
            except OSError:
                pass
            return False
        off = 0
        for tensor_idx, nbytes in segments:
            row = self._ring_tensors[tensor_idx][slot, :nbytes]
            row.copy_(torch.frombuffer(
                bytearray(payload[off : off + nbytes]), dtype=torch.uint8
            ).view(torch.int8))
            off += nbytes
        assert off == len(payload), (off, len(payload))
        return True

    def _write_key_from_ring(self, key: OffloadKey, slot: int, segments) -> None:
        payload = b"".join(
            self._ring_tensors[t][slot, :n].numpy().tobytes()
            for t, n in segments
        )
        write_key_file(
            self._mapper.get_file_name(key),
            get_offload_group_idx(key),
            payload,
        )

    def _store_file_task(self, job: _StoreJob, key, slot, segments):
        def task() -> None:
            self._write_key_from_ring(key, slot, segments)
        return task

    # ---------------- completion (FIFO barrier) ----------------

    def get_finished(self) -> list[TransferResult]:
        results: list[TransferResult] = []
        filed_now: dict[int, bool] = dict(self._pool.get_finished())
        while self._order:
            job_id = self._order[0]
            job = self._jobs.get(job_id)
            assert job is not None, job_id
            if isinstance(job, _StoreJob):
                if not job.filed:
                    if not job.end.query():
                        break
                    job.cuda_time = job.start.elapsed_time(job.end) * 1e-3
                    job.filed = True
                    self._pool.enqueue_store(
                        job_id, len(job.keys),
                        [self._store_file_task(job, k, s, seg)
                         for k, s, seg in zip(job.keys, job.slots, job.segments)],
                    )
                    break  # file stage runs async; re-check next call
                if job_id not in filed_now:
                    break
                success = filed_now.pop(job_id)
                self._pop_head(job_id, job.slots)
                results.append(TransferResult(
                    job_id=job_id, success=success,
                    transfer_size=job.num_bytes,
                    transfer_time=job.cuda_time,
                    transfer_type=("GPU", NVMeLoadStoreSpec.medium()),
                ))
            else:
                if job.failed:
                    self._pop_head(job_id, job.slots)
                    results.append(TransferResult(
                        job_id=job_id, success=False,
                        transfer_type=(NVMeLoadStoreSpec.medium(), "GPU"),
                    ))
                    continue
                if not job.cuda_ready or not job.end.query():
                    break
                self._pop_head(job_id, job.slots)
                results.append(TransferResult(
                    job_id=job_id, success=True,
                    transfer_size=job.num_bytes,
                    transfer_time=job.start.elapsed_time(job.end) * 1e-3,
                    transfer_type=(NVMeLoadStoreSpec.medium(), "GPU"),
                ))
        return results

    def _pop_head(self, job_id: int, slots: list[int]) -> None:
        assert self._order and self._order[0] == job_id
        self._order.popleft()
        del self._jobs[job_id]
        with self._slot_lock:
            self._slot_busy.difference_update(slots)

    def wait(self, job_ids: set[int]) -> None:
        while any(j in self._jobs for j in job_ids):
            for jid in job_ids:
                job = self._jobs.get(jid)
                if isinstance(job, _StoreJob) and job.filed:
                    continue
                if isinstance(job, _StoreJob) or isinstance(job, _LoadJob):
                    if job.end is not None:
                        job.end.synchronize()
            self.get_finished()
            if any(j in self._jobs for j in job_ids):
                time.sleep(0.002)

    def shutdown(self) -> None:
        self._gc_stop.set()
        self._pool.shutdown(wait=True)
        self._gpu_tensors.clear()
        self._ring_tensors.clear()

    # ---------------- physical GC ----------------

    def _gc_loop(self) -> None:
        while not self._gc_stop.wait(self._gc_interval):
            try:
                self._gc_once()
            except Exception as e:  # noqa: BLE001
                logger.warning("NVMe tier GC error: %r", e)

    def _gc_once(self) -> None:
        import glob
        base = f"{self._mapper.base_path}_r{self._mapper.rank}"
        now = time.time()
        for tmp in glob.glob(f"{base}/**/*.tmp*", recursive=True):
            try:
                if now - os.path.getmtime(tmp) > 600:
                    os.remove(tmp)
            except OSError:
                pass
        if self._physical_budget <= 0:
            return
        files: list[tuple[float, int, str]] = []
        total = 0
        for p in glob.glob(f"{base}/**/*.bin", recursive=True):
            try:
                st = os.stat(p)
            except OSError:
                continue
            files.append((st.st_mtime, st.st_size, p))
            total += st.st_size
        if total <= self._physical_budget:
            return
        files.sort()
        for _mtime, size, p in files:
            if total <= self._physical_budget:
                break
            try:
                os.remove(p)
                total -= size
            except OSError:
                pass
        logger.info("NVMe tier GC: pruned tier to %.1f GiB", total / 2**30)
