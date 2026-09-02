# SPDX-License-Identifier: Apache-2.0
"""Scheduler-side metadata manager for the NVMe tier (Rev 2 semantics).

Single-tier key table (disk residency only — the staging ring is pure
transport on the worker side and is never a hit source, per the campaign-
verified structural law that an inclusive LRU tier smaller than the GPU
pool can never serve a hit). Owns:

  - ring-slot allocation/freeing (slots are held from prepare_* to
    complete_*; stores and loads share one pool),
  - disk-residency tracking with a logical byte budget + LRU eviction,
  - the store_threshold lookup counter (patterned on cpu/manager.py),
  - offloading events for the kv-events stream.

All state lives in the scheduler process; no file IO ever happens here.
"""
from collections import OrderedDict
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass, field

from vllm.logger import init_logger
from vllm.v1.kv_offload.base import (
    LoadStoreSpec,
    OffloadingEvent,
    OffloadingManager,
    OffloadKey,
    PrepareStoreOutput,
    ReqContext,
    get_offload_group_idx,
)
from vllm_nvme_tier.specs import NVMeLoadStoreSpec

logger = init_logger(__name__)

# lookup() returns None (retry-later) when free slots drop to this floor,
# which is the Rev 2 ring-exhaustion backpressure. Scaled to the ring size
# (production rings are thousands of slots; tiny rings in tests).
_MAX_LOOKUP_SLOT_FLOOR = 16


@dataclass
class _KeyEntry:
    storing: bool = True  # prepared but not yet persisted
    on_disk: bool = False
    ref_cnt: int = 0  # concurrent loads holding this key
    slot: int = -1  # store in-flight ring slot (valid while storing)
    load_slots: list[int] = field(default_factory=list)  # one per held load
    size_bytes: int = 0


class NVMeTierManager(OffloadingManager):
    def __init__(
        self,
        num_slots: int,
        bytes_budget: int,
        per_key_bytes: Callable[[OffloadKey], int],
        enable_events: bool = False,
        store_threshold: int = 0,
        max_tracker_size: int = 262_144,
    ):
        self.medium = NVMeLoadStoreSpec.medium()
        self._num_slots = num_slots
        self._bytes_budget = bytes_budget
        self._per_key_bytes = per_key_bytes
        self._entries: OrderedDict[OffloadKey, _KeyEntry] = OrderedDict()
        self._disk_bytes = 0
        self.events: list[OffloadingEvent] | None = [] if enable_events else None
        self.store_threshold = int(store_threshold)
        self.max_tracker_size = int(max_tracker_size)
        # lookup counter (store_threshold >= 2 enables admission filtering)
        self.counts: OrderedDict[OffloadKey, int] | None = (
            OrderedDict() if self.store_threshold >= 2 else None
        )
        # slot pool
        self._free_slots: list[int] = list(range(num_slots))
        self._lookup_floor = min(_MAX_LOOKUP_SLOT_FLOOR, max(1, num_slots // 4))

    # --- slot pool ---

    def _get_num_free_slots(self) -> int:
        return len(self._free_slots)

    def _alloc_slots(self, keys: list[OffloadKey]) -> list[int] | None:
        if len(keys) > self._get_num_free_slots():
            return None
        return [self._free_slots.pop() for _ in keys]

    # --- OffloadingManager interface ---

    def lookup(self, key: OffloadKey, req_context: ReqContext) -> bool | None:
        if self.counts is not None:
            if key in self.counts:
                self.counts.move_to_end(key)
                self.counts[key] += 1
            else:
                if len(self.counts) >= self.max_tracker_size:
                    self.counts.popitem(last=False)
                self.counts[key] = 1
        entry = self._entries.get(key)
        if entry is None:
            return False
        if entry.storing:
            return None  # persist in flight; retry
        if self._get_num_free_slots() <= self._lookup_floor:
            return None  # ring exhaustion backpressure (Rev 2)
        return True

    def prepare_load(
        self,
        keys: Collection[OffloadKey],
        req_context: ReqContext,
    ) -> LoadStoreSpec:
        keys = list(keys)
        slots = self._alloc_slots(keys)
        assert slots is not None, "lookup() gate must reserve ring capacity"
        for key, slot in zip(keys, slots):
            entry = self._entries[key]
            assert entry is not None and entry.on_disk, key
            assert not entry.storing, key
            entry.ref_cnt += 1
            entry.load_slots.append(slot)
            self._entries.move_to_end(key)
        return NVMeLoadStoreSpec(slots, keys)

    def touch(self, keys: Collection[OffloadKey], req_context: ReqContext) -> None:
        for key in keys:
            if key in self._entries:
                self._entries.move_to_end(key)

    def complete_load(
        self,
        keys: Collection[OffloadKey],
        req_context: ReqContext,
        success: bool = True,
    ) -> None:
        for key in keys:
            entry = self._entries.get(key)
            if entry is None or entry.ref_cnt <= 0:
                continue
            entry.ref_cnt -= 1
            if entry.load_slots:
                self._free_slots.append(entry.load_slots.pop())
            if entry.ref_cnt == 0 and entry.storing is False and not entry.load_slots:
                entry.load_slots = []
            if not success:
                # The file failed to load (corrupt/missing): forget the key
                # so future lookups miss instead of re-offering a bad file.
                # The worker unlinks the file; any concurrent load of the
                # same key fails on its own and lands here too.
                removed = self._entries.pop(key, None)
                if removed is not None:
                    self._disk_bytes -= removed.size_bytes

    def prepare_store(
        self,
        keys: Collection[OffloadKey],
        req_context: ReqContext,
    ) -> PrepareStoreOutput | None:
        if self.counts is not None:
            keys = [k for k in keys if self.counts.get(k, 0) >= self.store_threshold]
        # dedupe: skip anything already tracked (persisting or persisted);
        # this absorbs the fork connector's repeat store offers (D0-lite
        # measured ~9x offers on the CPU manager path).
        keys_to_store = [k for k in keys if k not in self._entries]
        if not keys_to_store:
            return PrepareStoreOutput(
                keys_to_store=[],
                store_spec=NVMeLoadStoreSpec([], []),
                evicted_keys=[],
            )

        # Partial acceptance: an offer larger than the ring would deadlock
        # if we returned None (the connector re-offers the same, only
        # growing set without advancing next_stored_block_idx — observed
        # 20260902 boot-4: "cannot store blocks" every step, zero stores).
        # Accept a prefix that fits (loads keep the lookup-floor reserve);
        # the unaccepted tail is skipped by the connector's index advance
        # — a coverage loss, never a correctness one.
        capacity = self._get_num_free_slots() - self._lookup_floor
        if capacity <= 0:
            return None  # ring busy with in-flight jobs; retry next pass
        if len(keys_to_store) > capacity:
            keys_to_store = keys_to_store[:capacity]
        slots = self._alloc_slots(keys_to_store)
        assert slots is not None

        # logical disk-budget eviction (LRU, protected = current + pinned)
        protected = set(keys) | {k for k, e in self._entries.items()
                                 if e.storing or e.ref_cnt > 0}
        to_evict: list[OffloadKey] = []
        incoming_bytes = sum(self._per_key_bytes(k) for k in keys_to_store)
        while self._disk_bytes + incoming_bytes > self._bytes_budget:
            victim = next(
                (k for k in self._entries
                 if not self._entries[k].storing and self._entries[k].ref_cnt == 0
                 and k not in protected),
                None,
            )
            if victim is None:
                logger.warning(
                    "NVMe tier over budget by %d B; no evictable keys",
                    self._disk_bytes + incoming_bytes - self._bytes_budget,
                )
                break
            entry = self._entries.pop(victim)
            self._disk_bytes -= entry.size_bytes
            to_evict.append(victim)

        if to_evict and self.events is not None:
            self.events.append(
                OffloadingEvent(keys=to_evict, medium=self.medium, removed=True)
            )

        for key, slot in zip(keys_to_store, slots):
            self._entries[key] = _KeyEntry(
                slot=slot, size_bytes=self._per_key_bytes(key)
            )

        return PrepareStoreOutput(
            keys_to_store=keys_to_store,
            store_spec=NVMeLoadStoreSpec(slots, keys_to_store),
            evicted_keys=to_evict,
        )

    def complete_store(
        self,
        keys: Collection[OffloadKey],
        req_context: ReqContext,
        success: bool = True,
    ) -> None:
        stored_keys: list[OffloadKey] = []
        for key in keys:
            entry = self._entries.get(key)
            if entry is None or not entry.storing:
                continue
            if success:
                entry.storing = False
                entry.on_disk = True
                self._disk_bytes += entry.size_bytes
                stored_keys.append(key)
            else:
                del self._entries[key]
            if entry.slot != -1:
                self._free_slots.append(entry.slot)
                entry.slot = -1
        if stored_keys and self.events is not None:
            self.events.append(
                OffloadingEvent(keys=stored_keys, medium=self.medium, removed=False)
            )

    def reset_cache(self) -> None:
        # scheduler guarantees no complete_* callbacks for pre-reset jobs
        self._entries.clear()
        self._disk_bytes = 0
        self._free_slots = list(range(self._num_slots))

    def take_events(self) -> Iterable[OffloadingEvent]:
        if self.events is not None:
            yield from self.events
            self.events.clear()

    def shutdown(self) -> None:
        return
