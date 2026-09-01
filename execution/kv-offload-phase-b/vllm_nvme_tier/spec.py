# SPDX-License-Identifier: Apache-2.0
"""NVMeTieredOffloadingSpec: mounts the per-rank NVMe tier through the
fork's OffloadingSpecFactory (`spec_module_path`). Rev 2 semantics —
staging ring (per-rank, few hundred MB) + NVMe-direct hits.

kv_connector_extra_config:
  nvme_root_dir      (required) container path of the tier root
  nvme_bytes_to_use  (required) CLUSTER byte budget, split per rank like
                     the CPU tier's cpu_bytes_to_use
  staging_ring_bytes (default 512 MiB) PER-RANK pinned transport ring
  io_threads         (default 4)
  gc_interval_s      (default 60)
  store_threshold / max_tracker_size / eviction_policy as in the CPU tier

REQUIRED companion env: PYTHONHASHSEED=0 on every host (D0-lite
2026-09-02: without it offload keys are unstable across processes and no
lookup can ever hit). Enforced at construction.
"""
import json
import os
import shutil
from collections.abc import Iterator

from vllm.config import VllmConfig
from vllm.platforms import current_platform
from vllm.v1.kv_cache_interface import (
    KVCacheConfig,
    UniformTypeKVCacheSpecs,
)
from vllm.v1.kv_offload.base import (
    CanonicalKVCaches,
    GPULoadStoreSpec,
    LoadStoreSpec,
    OffloadingManager,
    OffloadingSpec,
    OffloadKey,
    get_offload_group_idx,
)
from vllm.v1.kv_offload.file_mapper import FileMapper
from vllm.v1.kv_offload.worker.worker import OffloadingHandler

from vllm_nvme_tier.gpu_worker import NVMeOffloadingHandler
from vllm_nvme_tier.manager import NVMeTierManager
from vllm_nvme_tier.specs import NVMeLoadStoreSpec

_DEFAULT_RING_BYTES = 512 * 1024 * 1024


def _group_block_bytes(kv_cache_config: KVCacheConfig) -> list[int]:
    """Unpadded per-block payload bytes per KV group (scheduler-side view)."""
    out: list[int] = []
    for group in kv_cache_config.kv_cache_groups:
        spec = group.kv_cache_spec
        if isinstance(spec, UniformTypeKVCacheSpecs):
            out.append(
                sum(s.real_page_size_bytes for s in spec.kv_cache_specs.values())
            )
        else:
            out.append(spec.real_page_size_bytes)
    return out


class NVMeTieredOffloadingSpec(OffloadingSpec):
    def __init__(self, vllm_config: VllmConfig, kv_cache_config: KVCacheConfig):
        super().__init__(vllm_config, kv_cache_config)

        if os.environ.get("PYTHONHASHSEED") != "0":
            raise RuntimeError(
                "NVMeTieredOffloadingSpec requires PYTHONHASHSEED=0 on every "
                "host: without it offload keys are unstable across processes "
                "(see planning/02-working/2026-09-01-d1a-vendored-subtree-"
                "execution.md Rev 8)."
            )

        extra = self.extra_config
        try:
            self.nvme_root_dir = str(extra["nvme_root_dir"]).rstrip("/")
            cluster_bytes = int(extra["nvme_bytes_to_use"])
        except KeyError as e:
            raise Exception(
                f"missing kv_connector_extra_config key: {e}"
            ) from e
        world_size = vllm_config.parallel_config.world_size or 1
        self.per_rank_bytes = cluster_bytes // world_size

        self.staging_ring_bytes = int(extra.get("staging_ring_bytes",
                                                _DEFAULT_RING_BYTES))
        self.io_threads = int(extra.get("io_threads", 4))
        self.gc_interval_s = float(extra.get("gc_interval_s", 60.0))
        self.store_threshold = int(extra.get("store_threshold", 0))
        self.max_tracker_size = int(extra.get("max_tracker_size", 262_144))

        self._group_bytes = _group_block_bytes(kv_cache_config)
        max_block = max(self._group_bytes, default=0)
        if max_block <= 0:
            raise Exception("NVMe tier: no KV groups with positive page bytes")
        self.num_slots = self.staging_ring_bytes // max_block
        if self.num_slots < 8:
            raise Exception(
                f"staging_ring_bytes={self.staging_ring_bytes} too small: "
                f"max group block = {max_block} B, slots = {self.num_slots}"
            )

        self._manager: OffloadingManager | None = None
        self._handler: NVMeOffloadingHandler | None = None
        self._mapper: FileMapper | None = None

    def _per_key_bytes(self, key: OffloadKey) -> int:
        return self._group_bytes[get_offload_group_idx(key)]

    def get_manager(self) -> OffloadingManager:
        if not self._manager:
            kv_events_config = self.vllm_config.kv_events_config
            enable_events = (
                kv_events_config is not None
                and kv_events_config.enable_kv_cache_events
            )
            self._manager = NVMeTierManager(
                num_slots=self.num_slots,
                bytes_budget=self.per_rank_bytes,
                per_key_bytes=self._per_key_bytes,
                enable_events=enable_events,
                store_threshold=self.store_threshold,
                max_tracker_size=self.max_tracker_size,
            )
        return self._manager

    def get_handlers(
        self, kv_caches: CanonicalKVCaches
    ) -> Iterator[tuple[type[LoadStoreSpec], type[LoadStoreSpec], OffloadingHandler]]:
        if not current_platform.is_cuda_alike():
            raise Exception("NVMe tier requires CUDA-alike GPUs")
        if self._handler is None:
            self._mapper = FileMapper.from_offloading_spec(
                root_dir=self.nvme_root_dir,
                offloading_spec=self,
                gpu_blocks_per_file=1,
            )
            self._prepare_tier_dir()
            self._handler = NVMeOffloadingHandler(
                kv_caches=kv_caches,
                num_slots=self.num_slots,
                file_mapper=self._mapper,
                io_threads=self.io_threads,
                physical_budget_bytes=int(self.per_rank_bytes * 1.1),
                gc_interval_s=self.gc_interval_s,
            )
        yield GPULoadStoreSpec, NVMeLoadStoreSpec, self._handler
        yield NVMeLoadStoreSpec, GPULoadStoreSpec, self._handler

    def _prepare_tier_dir(self) -> None:
        """Worker-side cold start: publish the shared config fingerprint and
        wipe THIS rank's subtree (v1 is cold-start-clean by design; keys are
        content-addressed so a stale file is merely redundant, and the
        manager's key table lives only in scheduler memory)."""
        base = self._mapper.base_path
        rank_dir = f"{base}_r{self._mapper.rank}"
        os.makedirs(base, exist_ok=True)
        cfg_path = self._mapper.get_config_file_path()
        if not os.path.exists(cfg_path):
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(self._mapper.get_run_config(), f, indent=1)
        if os.path.isdir(rank_dir):
            shutil.rmtree(rank_dir, ignore_errors=True)
        os.makedirs(rank_dir, exist_ok=True)
