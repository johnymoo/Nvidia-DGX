#!/usr/bin/env python3
"""Assemble the D1a overlay tree under tmp/kv-offload-d1a/overlay/.

Sources:
  vendored/      59 pristine upstream files @ f5e441de10bd (already extracted)
  upstream repo  + vllm/v1/kv_cache_layout.py, vllm/distributed/kv_events.py
  apply-test     image kv_cache_utils.py + shm_broadcast.py (baseline blobs)
  container      fork kv_cache_interface.py delta (already computed inline)

Produces overlay/vllm/** = the exact files to COPY into
planning/01-raw/upstream-dspark/recipe/overlay/vllm/, plus
overlay/MANIFEST.tsv (path, kind, sha256, upstream-blob-sha or -).
Shim/backport hunks are marked '# D1a' in-file.
"""
import hashlib
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
VENDORED = HERE / "vendored"
OVERLAY = HERE / "overlay" / "vllm"
UP = Path("/tmp/vllm-upstream")
PIN = "f5e441de10bd"
BASELINE = "7e33081cee7b"
APPLY_INIT = "ea1e7797bbb023e14a9ad197c4208d794f31c6bc"

EXTRA_PRISTINE = [
    "vllm/v1/kv_cache_layout.py",
    "vllm/v1/kv_cache_spec_registry.py",
    "vllm/distributed/kv_events.py",
]


def git_show(path, rev=PIN):
    r = subprocess.run(["git", "-C", str(UP), "show", f"{rev}:{path}"],
                       capture_output=True, text=True, check=True)
    return r.stdout


def git_blob_sha(text):
    # git blob sha1: header "blob <len>\0"
    payload = f"blob {len(text.encode())}\0".encode() + text.encode()
    return hashlib.sha1(payload).hexdigest()


def sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()


def write(rel, text, kind, rows):
    p = OVERLAY / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    blob = git_blob_sha(text)
    upstream = blob if subprocess.run(
        ["git", "-C", str(UP), "cat-file", "-e", f"{PIN}:{rel}"],
        capture_output=True).returncode == 0 else "-"
    rows.append((f"vllm/{rel}", kind, sha256(text), upstream))


def main():
    rows = []
    # 1. pristine vendored 59 + 2 extra pristine
    for p in sorted(VENDORED.rglob("*.py")):
        rel = str(p.relative_to(VENDORED))
        write(rel, p.read_text(), "vendored-pristine", rows)
    for rel in EXTRA_PRISTINE:
        write(rel[len("vllm/"):], git_show(rel), "vendored-pristine", rows)

    # 2. kv_cache_interface.py = tip + fork-compat shims
    tip_if = git_show("vllm/v1/kv_cache_interface.py")

    # 2.0 re-add TQFullAttentionSpec (removed upstream; the fork's
    #     single_type_kv_cache_manager imports it). Baseline definition.
    tq_anchor = (
        "@dataclass(frozen=True, kw_only=True)\n"
        "class MLAAttentionSpec(FullAttentionSpec):\n"
    )
    tq_block = (
        "@dataclass(frozen=True, kw_only=True)\n"
        "class TQFullAttentionSpec(FullAttentionSpec):\n"
        "    \"\"\"D1a fork-compat: TQ-aware page size (removed upstream).\n"
        "    Kept because the fork's single_type_kv_cache_manager imports it.\n"
        "    \"\"\"\n"
        "\n"
        "    tq_slot_size: int = 0\n"
        "\n"
        "    @property\n"
        "    def real_page_size_bytes(self) -> int:\n"
        "        if self.tq_slot_size > 0:\n"
        "            return self.block_size * self.num_kv_heads * self.tq_slot_size\n"
        "        return super().real_page_size_bytes\n"
        "\n"
        "    @classmethod\n"
        "    def merge(cls, specs: list[Self]) -> Self:\n"
        "        merged = super().merge(specs)\n"
        "        assert all(s.tq_slot_size == specs[0].tq_slot_size for s in specs), (\n"
        "            \"All TQ layers in the same KV cache group must use the same tq_slot_size.\"\n"
        "        )\n"
        "        return replace(merged, tq_slot_size=specs[0].tq_slot_size)\n"
        "\n"
        "\n"
        "@dataclass(frozen=True, kw_only=True)\n"
        "class MLAAttentionSpec(FullAttentionSpec):\n"
    )
    assert tip_if.count(tq_anchor) == 1, "TQ insertion anchor"
    tip_if = tip_if.replace(tq_anchor, tq_block, 1)

    # 2.0b is_uniform_type: revert to the baseline isinstance ladder. The tip
    #     version consults KVCacheSpecRegistry, whose lazy bootstrap imports
    #     register_all_kvcache_specs from the TIP single_type manager (not
    #     shipped). Discovered in the first D1b boot attempt (ImportError in
    #     group_and_unify_kv_cache_specs).
    iut_anchor = (
        "        block_sizes = set(spec.block_size for spec in kv_cache_specs.values())\n"
        "        if len(block_sizes) > 1:\n"
        "            # Different block sizes, not uniform.\n"
        "            return False\n"
        "        first_spec = next(iter(kv_cache_specs.values()))\n"
        "        return first_spec.is_uniform_with_collection(kv_cache_specs)\n"
    )
    iut_new = (
        "        block_sizes = set(spec.block_size for spec in kv_cache_specs.values())\n"
        "        if len(block_sizes) > 1:\n"
        "            # Different block sizes, not uniform.\n"
        "            return False\n"
        "        one_spec = next(iter(kv_cache_specs.values()))\n"
        "        # D1a fork-compat: baseline isinstance ladder (the tip registry\n"
        "        # requires tip-core registration machinery we do not ship).\n"
        "        if isinstance(one_spec, SlidingWindowMLASpec):\n"
        "            return all(\n"
        "                isinstance(spec, SlidingWindowMLASpec)\n"
        "                and spec.sliding_window == one_spec.sliding_window\n"
        "                for spec in kv_cache_specs.values()\n"
        "            )\n"
        "        elif isinstance(one_spec, FullAttentionSpec):\n"
        "            return all(\n"
        "                isinstance(spec, FullAttentionSpec) for spec in kv_cache_specs.values()\n"
        "            )\n"
        "        elif isinstance(one_spec, CrossAttentionSpec):\n"
        "            return all(\n"
        "                isinstance(spec, CrossAttentionSpec) for spec in kv_cache_specs.values()\n"
        "            )\n"
        "        elif isinstance(one_spec, SlidingWindowSpec):\n"
        "            return all(\n"
        "                isinstance(spec, SlidingWindowSpec)\n"
        "                and spec.sliding_window == one_spec.sliding_window\n"
        "                for spec in kv_cache_specs.values()\n"
        "            )\n"
        "        elif isinstance(one_spec, ChunkedLocalAttentionSpec):\n"
        "            return all(\n"
        "                isinstance(spec, ChunkedLocalAttentionSpec)\n"
        "                and spec.attention_chunk_size == one_spec.attention_chunk_size\n"
        "                for spec in kv_cache_specs.values()\n"
        "            )\n"
        "        elif isinstance(one_spec, MambaSpec):\n"
        "            return all(\n"
        "                isinstance(spec, MambaSpec)\n"
        "                and spec.num_speculative_blocks == one_spec.num_speculative_blocks\n"
        "                for spec in kv_cache_specs.values()\n"
        "            )\n"
        "        else:\n"
        "            raise NotImplementedError(\n"
        "                f\"Unsupported KV cache spec type: {type(one_spec)}\"\n"
        "            )\n"
    )
    assert tip_if.count(iut_anchor) == 1, "is_uniform_type anchor"
    tip_if = tip_if.replace(iut_anchor, iut_new, 1)

    # 2.0c get_kv_cache_spec_kind wrapper branch: drop the registry
    #     consultation (baseline semantics — mixed inner kinds are UNKNOWN).
    kind_anchor = (
        "        # A group is only formed when all members share one registered\n"
        "        # uniform_type_base_spec, so UNKNOWN would discard what the merge\n"
        "        # already established.\n"
        "        base_specs = {\n"
        "            KVCacheSpecRegistry.get_uniform_type_base_spec(spec)\n"
        "            for spec in kv_cache_spec.kv_cache_specs.values()\n"
        "        }\n"
        "        if len(base_specs) == 1 and next(iter(base_specs)) is FullAttentionSpec:\n"
        "            return KVCacheSpecKind.FULL_ATTENTION\n"
        "        return KVCacheSpecKind.UNKNOWN\n"
    )
    kind_new = (
        "        # D1a fork-compat: baseline semantics — no registry consultation.\n"
        "        return KVCacheSpecKind.UNKNOWN\n"
    )
    assert tip_if.count(kind_anchor) == 1, "kind anchor"
    tip_if = tip_if.replace(kind_anchor, kind_new, 1)

    # 2.0d get_num_layer_tuples: fork core calls it (kv_cache_utils 926/1522/
    #     1776); tip renamed it to get_max_layers_per_page_size (same body).
    #     Insert an alias right after the tip definition.
    gnlt_anchor = (
        "    def get_max_layers_per_page_size(self) -> int:\n"
        "        \"\"\"Max number of layers sharing a page size. For a balanced bucket\n"
        "        this equals the number of repetitions of the layer pattern.\"\"\"\n"
        "        return Counter(\n"
        "            spec.page_size_bytes for spec in self.kv_cache_specs.values()\n"
        "        ).most_common(1)[0][1]\n"
    )
    gnlt_new = gnlt_anchor + (
        "\n"
        "    def get_num_layer_tuples(self) -> int:\n"
        "        \"\"\"D1a fork-compat alias (tip: get_max_layers_per_page_size).\"\"\"\n"
        "        return self.get_max_layers_per_page_size()\n"
    )
    assert tip_if.count(gnlt_anchor) == 1, "get_num_layer_tuples anchor"
    tip_if = tip_if.replace(gnlt_anchor, gnlt_new, 1)

    # 2.0f KVCacheTensor fork-compat: tip requires the layout triple
    #     (layers/layer_stride/block_stride); the fork core constructs only
    #     {size, shared_by} and its allocator ignores strides. Safe to
    #     default them: the vendored connector derives layout from live torch
    #     tensors (register_kv_caches / .stride(0)), never from these fields.
    #     Third boot-attempt discovery (TypeError: unexpected kwarg shared_by).
    dc_import_anchor = "from dataclasses import dataclass, fields, replace\n"
    dc_import_new = "from dataclasses import dataclass, field, fields, replace\n"
    assert tip_if.count(dc_import_anchor) == 1, "dataclasses import anchor"
    tip_if = tip_if.replace(dc_import_anchor, dc_import_new, 1)

    kvt_anchor = (
        "    size: int  # total size of the backing allocation in bytes\n"
        "    layers: list[str]  # layer names in L order\n"
        "    layer_stride: int\n"
        "    block_stride: int\n"
        "    offset: int = 0  # byte offset of layers[0]'s block 0\n"
    )
    kvt_new = (
        "    size: int  # total size of the backing allocation in bytes\n"
        "    # D1a fork-compat: all defaulted so the fork core's minimal\n"
        "    # {size, shared_by} construction works; unused by the fork\n"
        "    # allocator and by the vendored connector (live-tensor layout).\n"
        "    layers: list[str] = field(default_factory=list)  # layer names in L order\n"
        "    layer_stride: int = 0\n"
        "    block_stride: int = 0\n"
        "    offset: int = 0  # byte offset of layers[0]'s block 0\n"
        "    shared_by: list[str] = field(default_factory=list)  # fork field\n"
        "\n"
        "    def __post_init__(self):\n"
        "        if not self.layers and self.shared_by:\n"
        "            self.layers = list(self.shared_by)\n"
    )
    assert tip_if.count(kvt_anchor) == 1, "KVCacheTensor fields anchor"
    tip_if = tip_if.replace(kvt_anchor, kvt_new, 1)

    # 2.0e get_page_sizes: fork core's DSv4 pool-sizing math calls it (5
    #     sites in kv_cache_utils); removed at tip. Second boot-attempt
    #     discovery (AttributeError in _pool_bytes_per_block).
    gps_anchor = (
        "    def get_num_layer_tuples(self) -> int:\n"
        "        \"\"\"D1a fork-compat alias (tip: get_max_layers_per_page_size).\"\"\"\n"
        "        return self.get_max_layers_per_page_size()\n"
    )
    gps_new = gps_anchor + (
        "\n"
        "    def get_page_sizes(self) -> list[int]:\n"
        "        \"\"\"D1a fork-compat: distinct member page sizes.\"\"\"\n"
        "        return list(\n"
        "            set(spec.page_size_bytes for spec in self.kv_cache_specs.values())\n"
        "        )\n"
    )
    assert tip_if.count(gps_anchor) == 1, "get_page_sizes anchor"
    tip_if = tip_if.replace(gps_anchor, gps_new, 1)

    # 2a. MLAAttentionSpec: add compress_ratio field + storage_block_size +
    #     fork page-size branches; merge() carries compress_ratio.
    mla_anchor_fields = (
        "class MLAAttentionSpec(FullAttentionSpec):\n"
        "    # TODO(Lucas/Chen): less hacky way to do this\n"
        "    cache_dtype_str: str | None = None\n"
    )
    mla_fields_new = (
        "class MLAAttentionSpec(FullAttentionSpec):\n"
        "    # TODO(Lucas/Chen): less hacky way to do this\n"
        "    cache_dtype_str: str | None = None\n"
        "    # D1a fork-compat field (upstream equivalent: tokens_per_state).\n"
        "    # The fork's deepseek_v4 model still constructs specs with it.\n"
        "    compress_ratio: int = 1\n"
    )
    assert tip_if.count(mla_anchor_fields) == 1
    tip_if = tip_if.replace(mla_anchor_fields, mla_fields_new)

    mla_post_anchor = (
        "    def __post_init__(self):\n"
        "        super().__post_init__()\n"
        "        _apply_alignment_padding(self)\n"
        "\n"
        "    @classmethod\n"
        "    def merge(cls, specs: list[Self]) -> Self:\n"
        "        assert all(isinstance(spec, MLAAttentionSpec) for spec in specs), (\n"
    )
    mla_post_new = (
        "    def __post_init__(self):\n"
        "        super().__post_init__()\n"
        "        _apply_alignment_padding(self)\n"
        "\n"
        "    # ---- D1a fork-compat page-size arithmetic (re-applies the fork's\n"
        "    # +6-line delta of vllm/v1/kv_cache_interface.py onto the tip\n"
        "    # interface): packed-MLA dtypes size pages by BYTES PER TOKEN, not\n"
        "    # by head_size*dtype_size. The baseline core and the fork's\n"
        "    # deepseek_v4 model both read these sizes.\n"
        "    @property\n"
        "    def storage_block_size(self) -> int:\n"
        "        return self.block_size // self.compress_ratio\n"
        "\n"
        "    @property\n"
        "    def real_page_size_bytes(self) -> int:\n"
        "        if self.cache_dtype_str == \"fp8_ds_mla\":\n"
        "            if self.model_version == \"deepseek_v4\":\n"
        "                # 448B NoPE + 128B RoPE + 8B scale = 584B per token.\n"
        "                return self.storage_block_size * 584\n"
        "            # V3.2 main MLA: 656-byte custom layout.\n"
        "            return self.block_size * 656\n"
        "        if self.cache_dtype_str == \"nvfp4_ds_mla\":\n"
        "            if self.model_version == \"deepseek_v4\":\n"
        "                return self.storage_block_size * 584\n"
        "            return self.storage_block_size * 416\n"
        "        return (\n"
        "            self.storage_block_size\n"
        "            * self.num_kv_heads\n"
        "            * self.head_size\n"
        "            * get_dtype_size(self.dtype)\n"
        "        )\n"
        "\n"
        "    @property\n"
        "    def unpadded_page_size_bytes(self) -> int:\n"
        "        # Fork-constructed specs (packed ds_mla dtypes OR any explicit\n"
        "        # compression, e.g. the DSv4 indexer with compress_ratio>1 and\n"
        "        # no cache_dtype_str) size via the fork formula above; specs\n"
        "        # left at defaults keep the tip computation.\n"
        "        if self.cache_dtype_str in (\"fp8_ds_mla\", \"nvfp4_ds_mla\") or (\n"
        "            self.compress_ratio != 1\n"
        "        ):\n"
        "            return self.real_page_size_bytes\n"
        "        return super().unpadded_page_size_bytes\n"
        "\n"
        "    @classmethod\n"
        "    def merge(cls, specs: list[Self]) -> Self:\n"
        "        assert all(isinstance(spec, MLAAttentionSpec) for spec in specs), (\n"
    )
    assert tip_if.count(mla_post_anchor) == 1, "MLA post_init/merge anchor"
    tip_if = tip_if.replace(mla_post_anchor, mla_post_new)

    mla_merge_anchor = (
        "        merged_spec = cls(\n"
        "            block_size=specs[0].block_size,\n"
        "            num_kv_heads=specs[0].num_kv_heads,\n"
        "            head_size=specs[0].head_size,\n"
        "            dtype=specs[0].dtype,\n"
        "            kv_quant_mode=specs[0].kv_quant_mode,\n"
        "            page_size_padded=specs[0].page_size_padded,\n"
        "            num_head_slots=specs[0].num_head_slots,\n"
        "            state_content_bytes=specs[0].state_content_bytes,\n"
        "            cache_dtype_str=cache_dtype_str_set.pop(),\n"
        "            tokens_per_state=tokens_per_state_set.pop(),\n"
        "            model_version=model_version_set.pop(),\n"
        "            non_causal_multi_token_decode=non_causal_mtd_set.pop(),\n"
        "        )\n"
    )
    mla_merge_new = (
        "        merged_spec = cls(\n"
        "            block_size=specs[0].block_size,\n"
        "            num_kv_heads=specs[0].num_kv_heads,\n"
        "            head_size=specs[0].head_size,\n"
        "            dtype=specs[0].dtype,\n"
        "            kv_quant_mode=specs[0].kv_quant_mode,\n"
        "            page_size_padded=specs[0].page_size_padded,\n"
        "            num_head_slots=specs[0].num_head_slots,\n"
        "            state_content_bytes=specs[0].state_content_bytes,\n"
        "            cache_dtype_str=cache_dtype_str_set.pop(),\n"
        "            tokens_per_state=tokens_per_state_set.pop(),\n"
        "            model_version=model_version_set.pop(),\n"
        "            non_causal_multi_token_decode=non_causal_mtd_set.pop(),\n"
        "            compress_ratio=specs[0].compress_ratio,  # D1a fork-compat\n"
        "        )\n"
    )
    assert tip_if.count(mla_merge_anchor) == 1, "MLA merge kwargs anchor"
    tip_if = tip_if.replace(mla_merge_anchor, mla_merge_new)

    # 2b. SlidingWindowMLASpec: same treatment (fork dsv4 584 branch).
    swmla_anchor = (
        "class SlidingWindowMLASpec(SlidingWindowSpec):\n"
        "    \"\"\"Sliding window attention with MLA cache format.\"\"\"\n"
        "\n"
        "    cache_dtype_str: str | None = None\n"
        "    # DeepseekV4-only: see MLAAttentionSpec.model_version.\n"
        "    alignment: int | None = None  # Default to None for no padding.\n"
        "    model_version: str | None = None\n"
    )
    swmla_fields_new = (
        "class SlidingWindowMLASpec(SlidingWindowSpec):\n"
        "    \"\"\"Sliding window attention with MLA cache format.\"\"\"\n"
        "\n"
        "    cache_dtype_str: str | None = None\n"
        "    # DeepseekV4-only: see MLAAttentionSpec.model_version.\n"
        "    alignment: int | None = None  # Default to None for no padding.\n"
        "    compress_ratio: int = 1  # D1a fork-compat\n"
        "    model_version: str | None = None\n"
    )
    assert tip_if.count(swmla_anchor) == 1, "SWMLA fields anchor"
    tip_if = tip_if.replace(swmla_anchor, swmla_fields_new)

    swmla_post_anchor = (
        "    def __post_init__(self):\n"
        "        assert self.model_version in (None, \"deepseek_v4\"), (\n"
        "            f\"Unsupported model version: {self.model_version}\"\n"
        "        )\n"
        "        super().__post_init__()\n"
        "        _apply_alignment_padding(self)\n"
    )
    swmla_post_new = (
        "    def __post_init__(self):\n"
        "        assert self.model_version in (None, \"deepseek_v4\"), (\n"
        "            f\"Unsupported model version: {self.model_version}\"\n"
        "        )\n"
        "        super().__post_init__()\n"
        "        _apply_alignment_padding(self)\n"
        "\n"
        "    # D1a fork-compat (see MLAAttentionSpec shim above).\n"
        "    @property\n"
        "    def storage_block_size(self) -> int:\n"
        "        return self.block_size // self.compress_ratio\n"
        "\n"
        "    @property\n"
        "    def real_page_size_bytes(self) -> int:\n"
        "        if self.model_version == \"deepseek_v4\":\n"
        "            return self.storage_block_size * 584\n"
        "        return (\n"
        "            self.storage_block_size\n"
        "            * self.num_kv_heads\n"
        "            * self.head_size\n"
        "            * get_dtype_size(self.dtype)\n"
        "        )\n"
        "\n"
        "    @property\n"
        "    def unpadded_page_size_bytes(self) -> int:\n"
        "        if self.model_version == \"deepseek_v4\" or self.compress_ratio != 1:\n"
        "            return self.real_page_size_bytes\n"
        "        return super().unpadded_page_size_bytes\n"
    )
    assert tip_if.count(swmla_post_anchor) == 1, "SWMLA post_init anchor"
    tip_if = tip_if.replace(swmla_post_anchor, swmla_post_new)

    # SWMLA merge: add compress_ratio passthrough after model_version pop.
    swmla_merge_anchor = (
        "            model_version=model_version_set.pop(),\n"
        "        )\n"
        "\n"
        "        if TYPE_CHECKING:\n"
        "            base_spec = self\n"
    )
    if swmla_merge_anchor not in tip_if:
        # fall back: any merge kwargs ending model_version=model_version_set.pop()
        swmla_merge_anchor = (
            "            model_version=model_version_set.pop(),\n"
            "        )\n"
        )
        swmla_merge_new = (
            "            model_version=model_version_set.pop(),\n"
            "            compress_ratio=specs[0].compress_ratio,  # D1a fork-compat\n"
            "        )\n"
        )
        assert tip_if.count(swmla_merge_anchor) >= 1, "SWMLA merge anchor"
        # replace only inside SlidingWindowMLASpec (first occurrence after its class)
        pos = tip_if.index("class SlidingWindowMLASpec")
        head, tail = tip_if[:pos], tip_if[pos:]
        assert tail.count(swmla_merge_anchor) == 1, "SWMLA merge unique in class"
        tip_if = head + tail.replace(swmla_merge_anchor, swmla_merge_new, 1)
    else:
        swmla_merge_new = swmla_merge_anchor.replace(
            "            model_version=model_version_set.pop(),\n",
            "            model_version=model_version_set.pop(),\n"
            "            compress_ratio=specs[0].compress_ratio,  # D1a fork-compat\n",
        )
        tip_if = tip_if.replace(swmla_merge_anchor, swmla_merge_new, 1)

    write("v1/kv_cache_interface.py", tip_if, "tip+fork-shims", rows)

    # 3. base.py = tip + cross-layer back-compat stubs
    tip_base = git_show("vllm/distributed/kv_transfer/kv_connector/v1/base.py")
    stub = (
        "\n"
        "    # ---- D1a fork-compat stubs ---------------------------------\n"
        "    # Upstream removed the cross-layer KV registration API; the fork's\n"
        "    # gpu_model_runner (@7503) and kv_connector_model_runner_mixin still\n"
        "    # call it. (set_host_xfer_buffer_ops and CopyBlocksOp survive at\n"
        "    # tip — no shim needed.) No-op semantics match the upstream\n"
        "    # removal default (no cross-layer pooling).\n"
        "    @property\n"
        "    def prefer_cross_layer_blocks(self) -> bool:\n"
        "        \"\"\"Cross-layer block pooling is not used (fork-compat stub).\"\"\"\n"
        "        return False\n"
        "\n"
        "    def register_cross_layers_kv_cache(\n"
        "        self, kv_cache: torch.Tensor, attn_backend: type[\"AttentionBackend\"]\n"
        "    ) -> None:\n"
        "        \"\"\"No-op (fork-compat stub; cross-layer pooling not used).\"\"\"\n"
        "        return None\n"
    )
    lines = tip_base.splitlines(keepends=True)
    start = next(i for i, l in enumerate(lines) if l.startswith("class KVConnectorBase_V1"))
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("class ")),
        len(lines),
    )
    body = lines[start:end]
    while body and body[-1].strip() == "":
        body.pop()
    stub_lines = stub.splitlines(keepends=True)
    new_lines = lines[:start] + body + ["\n"] + stub_lines + lines[end:]
    tip_base = "".join(new_lines)
    write("distributed/kv_transfer/kv_connector/v1/base.py", tip_base, "tip+fork-shims", rows)

    # 4. kv_cache_utils.py = image content + appended backports
    r = subprocess.run(
        ["git", "-C", "/tmp/apply-test", "show", f"{APPLY_INIT}:v1/core/kv_cache_utils.py"],
        capture_output=True, text=True, check=True)
    img_kvcu = r.stdout
    backports = '''

# ---- D1a additive backports from upstream f5e441de10bd ---------------
# The vendored tip offloading stack imports these names at module scope
# (offloading/events.py: resolve_block_hashes; tiering/p2p/manager.py:
# get_none_hash_seed). The baseline core below is unchanged; these
# definitions are appended only so the vendored subtree imports cleanly.
# get_none_hash_seed always reports the deterministic default here: the
# baseline core initializes NONE_HASH without a per-process random seed.

DEFAULT_NONE_HASH_SEED = "vllm-none-hash"
_NONE_HASH_SEED: str | None = None


def get_none_hash_seed() -> str:
    """D1a backport: seed NONE_HASH was derived from (deterministic here)."""
    return DEFAULT_NONE_HASH_SEED


from typing import Iterator, overload  # noqa: E402


class BlockHashListWithBlockSize:
    """D1a backport: view block hashes at a coarser target block size."""

    def __init__(
        self,
        block_hashes: list,
        hash_block_size: int,
        target_block_size: int,
    ):
        self.block_hashes = block_hashes
        assert target_block_size % hash_block_size == 0
        self.scale_factor = target_block_size // hash_block_size

    def __len__(self) -> int:
        return len(self.block_hashes) // self.scale_factor

    @overload
    def __getitem__(self, idx: int): ...

    @overload
    def __getitem__(self, idx: slice): ...

    def __getitem__(self, idx):
        if isinstance(idx, int):
            return self._get_value_at(idx)
        if isinstance(idx, slice):
            start, stop, step = idx.indices(len(self))
            return [self._get_value_at(i) for i in range(start, stop, step)]
        raise TypeError(f"Invalid index type: {type(idx)!r}")

    def __iter__(self):
        for i in range(len(self)):
            yield self._get_value_at(i)

    def _get_value_at(self, idx: int):
        # The last hash_block_size hash within the target block chains over
        # the whole prefix, so it is the target block's hash.
        return self.block_hashes[(idx + 1) * self.scale_factor - 1]


BlockHashList = list | BlockHashListWithBlockSize


def resolve_block_hashes(
    block_hashes,
    hash_block_size: int,
    block_size: int,
    *,
    supports_fine_grained_hash_lookup: bool = False,
    alignment_tokens: int | None = None,
):
    """D1a backport: resolve the block-hash view at ``block_size``."""
    if block_size == hash_block_size:
        return block_hashes
    if isinstance(block_hashes, BlockHashListWithBlockSize):
        assert block_hashes.scale_factor == block_size // hash_block_size
        return block_hashes
    if (
        supports_fine_grained_hash_lookup
        and alignment_tokens is not None
        and alignment_tokens < block_size
        and block_size % alignment_tokens == 0
    ):
        return block_hashes
    assert block_size % hash_block_size == 0
    return BlockHashListWithBlockSize(block_hashes, hash_block_size, block_size)
'''
    write("v1/core/kv_cache_utils.py", img_kvcu + backports, "image+backports", rows)

    # 5. shm_broadcast.py = image content + appended check_shm_free_space
    r = subprocess.run(
        ["git", "-C", "/tmp/apply-test", "show", f"{APPLY_INIT}:distributed/device_communicators/shm_broadcast.py"],
        capture_output=True, text=True)
    if r.returncode != 0:
        r = subprocess.run(
            ["git", "-C", str(UP), "show", f"{BASELINE}:vllm/distributed/device_communicators/shm_broadcast.py"],
            capture_output=True, text=True, check=True)
    img_shm = r.stdout
    shm_bp = '''

# ---- D1a additive backport from upstream f5e441de10bd ----------------
def check_shm_free_space(required_bytes: int, shm_path: str = "/dev/shm") -> None:
    """D1a backport: raise if shm_path cannot fit a required segment."""
    import os as _os
    import shutil as _shutil

    if not _os.path.isdir(shm_path):
        return
    free_bytes = _shutil.disk_usage(shm_path).free
    if required_bytes <= free_bytes:
        return
    mib = 1 << 20
    raise RuntimeError(
        f"Insufficient space in {shm_path}: {required_bytes / mib:.0f} MiB "
        f"required, {free_bytes / mib:.0f} MiB free. Increase {shm_path} "
        "(e.g. --shm-size or --ipc=host)."
    )
'''
    write("distributed/device_communicators/shm_broadcast.py", img_shm + shm_bp, "image+backports", rows)

    # manifest (last write per path wins — shims overwrite pristine copies)
    dedup = {}
    for row in rows:
        dedup[row[0]] = row
    man = HERE / "overlay" / "MANIFEST.tsv"
    with man.open("w") as f:
        f.write("path\tkind\tsha256\tupstream-blob-sha-at-pin\n")
        for row in dedup.values():
            f.write("\t".join(row) + "\n")
    print(f"overlay assembled: {len(rows)} files; manifest at {man}")
    kinds = {}
    for _, k, _, _ in rows:
        kinds[k] = kinds.get(k, 0) + 1
    print(kinds)


if __name__ == "__main__":
    main()
