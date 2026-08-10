# Model and Runtime Candidates - 2026-08-10

## Requirements

- Run DeepSeek-V4-Flash-0731 across two 119 GiB GB10 systems.
- Preserve 1M-token model capability where practical.
- Support the native DSpark draft module.
- Expose a stable API suitable for agent workloads.
- Prefer measured 2x GB10 evidence over single-datacenter-GPU marketing.

## Candidate A: Official 0731 + Patched vLLM

Checkpoint already present on `gb10`:

- source snapshot revision recorded by ModelScope metadata:
  `d597f160eddfbbdbae9652e347990814c8a8cfea` for configuration/source files and
  `9df777ea6da5d513b5e5f6efff2bae0030357450` for weight shards;
- indexed weight size: 166,878,536,440 bytes;
- 48 indexed shards, 48 present, zero missing;
- `quant_method=fp8`, format `e4m3`, 128x128 blocks, dynamic activations;
- `expert_dtype=fp4`;
- native `dspark_block_size=5` and 1,048,576 maximum positions.

Runtime candidate:

- upstream source `tonyd2wild/DeepSeek-v4-Flash-0731-DSpark-1M-NVFP4-KV-2x-DGX-Spark`;
- pinned revision `f277b3dfa718a5962bed64e69e7e640a5384ec2f`;
- pinned aarch64 base manifest
  `sha256:d8492e7677cf1b9aaa3344e0e6865efc468454013eee5ebabac85be90af027be`;
- Patch 4 is present in the pinned source and loads the 0731 DSpark shared
  expert `w1`/`w3` tensors;
- proposed lane: TP=2, `nvfp4_ds_mla` KV, DSpark k=5, 1M context,
  `max_num_seqs=6`, GPU memory utilization 0.78.

The upstream reports roughly 55 tok/s typical, 78 tok/s peak on two DGX Spark
nodes for the official 0731 checkpoint. These numbers are external evidence,
not yet reproduced on this pair.

## Candidate B: Unsloth GGUF + llama.cpp

Status: accepted as a real A/B candidate after corrected Spark-specific review.
The image, model download manifest, and two-RPC Compose are prepared separately
from the vLLM baseline.

The Unsloth 120 tok/s claim is for one B200, not one or two GB10 systems, and
does not disclose enough benchmark detail to project performance here. The
released llama.cpp DSpark work has single-Spark results, while its two-Spark
RDMA tensor path remains an open pull request and has no DSpark benchmark.

If the route later becomes viable, the first A/B candidate is
`UD-Q4_K_XL` (155.095 GB) plus the required Q8 DSpark sidecar (10.896 GB).
This quant is near-lossless, not identical: reported PPL 4.5335 vs 4.5319,
KLD 0.0102, and 96.28% same top token. Lower Q2/Q3 variants have no comparable
primary quality result for this checkpoint.

## Decision Gate

Use a route as the primary deployment only if all are known:

1. exact immutable model files and runtime revision;
2. both-node memory fit including KV cache at the claimed context;
3. multi-node GB10/CUDA/aarch64 support, not only multi-GPU in one host;
4. native DSpark enabled and verified rather than a non-speculative baseline;
5. model quality implications of the selected weight quant;
6. OpenAI-compatible serving and operational health/status behavior;
7. reproducible throughput methodology suitable for an A/B run.

## Preparation Decision

Candidate A is the prepared, reproducible baseline: official 0731 mixed
FP8/FP4 with patched vLLM TP=2 and `nvfp4_ds_mla` KV.

Candidate B is an executable A/B: Unsloth `UD-Q4_K_XL` plus the Q8 DSpark
sidecar, two llama.cpp CUDA RPC devices, layer split, 256K context, and PR 26500
head `f0c483c4`. Existing two-Spark evidence proves target-only RPC but not
DSpark-over-RPC, so it does not replace Candidate A before live comparison.

Use Candidate A for the first distributed acceptance run because its external
two-Spark evidence is materially faster and more mature. Then run Candidate B
against the same prompt corpus and completion-token accounting. Select the
long-term primary from measured quality, single-stream TPS, aggregate TPS,
context capacity, repeated-request stability, and recovery behavior.
