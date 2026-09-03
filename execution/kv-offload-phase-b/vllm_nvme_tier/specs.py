# SPDX-License-Identifier: Apache-2.0
"""LoadStoreSpecs for the NVMe tier.

Both directions use one spec class: `block_ids` are RING SLOT ids (the
transport rows owned by this worker), `keys` are the OffloadKeys (content
identity -> file path). Ordering contract (from the connector scheduler,
offloading/scheduler.py _build_store_jobs / load path): keys and slot ids
align 1:1 with the paired GPULoadStoreSpec's per-group block ordering
(group_sizes), because the manager allocates one slot per key in the same
order it returns them.
"""
from vllm.v1.kv_offload.base import BlockIDsLoadStoreSpec, OffloadKey


class NVMeLoadStoreSpec(BlockIDsLoadStoreSpec):
    """Ring slots + content keys for a store (GPU->NVMe) or load (NVMe->GPU)."""

    def __init__(self, block_ids: list[int], keys: list[OffloadKey]):
        assert len(block_ids) == len(keys)
        super().__init__(block_ids)
        self.keys: list[OffloadKey] = list(keys)

    @staticmethod
    def medium() -> str:
        return "NVME_TIER"
