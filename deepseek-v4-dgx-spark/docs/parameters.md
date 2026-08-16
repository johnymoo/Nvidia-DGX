# Parameter guide

## Distributed topology

| Parameter | Baseline | Meaning and constraints |
|---|---:|---|
| `--nnodes` | `2` | Number of hosts in the distributed process. Must match participating nodes. |
| `--node-rank` | `0` / `1` | Unique rank per host. Rank 0 is the head/API. |
| `--tensor-parallel-size` | `2` | Splits model tensor work across both GB10 GPUs. This is not replica count. |
| `--pipeline-parallel-size` | `1` | No pipeline stages; tensor parallelism owns distribution. |
| `--master-addr` | head fabric address | Rendezvous endpoint reachable over the selected fabric. |
| `--master-port` | `29510` default | Same unused port on both nodes; it is not the inference API port. |
| `--headless` | worker only | Suppresses an API frontend on rank 1. It does not mean disabling the desktop UI. |
| `--distributed-executor-backend` | `mp` | Patched DSpark multiprocess/distributed execution path used by this recipe. |

`VLLM_HOST_IP`, `NCCL_SOCKET_IFNAME`, `GLOO_SOCKET_IFNAME`, and
`TP_SOCKET_IFNAME` should all resolve to the intended fabric route. Accidental
management-interface selection can work functionally while destroying latency
or causing a socket fallback.

## Capacity and scheduling

| Parameter | Baseline | Meaning and trade-off |
|---|---:|---|
| `--max-model-len` | `1048576` | Per-request context ceiling. It reserves no single fixed request, but requires enough KV capacity. |
| `--max-num-seqs` | `6` | Maximum concurrent scheduled sequences. More concurrency raises KV and runtime pressure. |
| `--max-num-batched-tokens` | `8192` | Scheduler token budget per iteration. Larger values can improve prefill throughput but delay active decode and increase pressure. |
| `--gpu-memory-utilization` | `0.78` | Fraction used by vLLM profiling/KV planning. The remaining headroom covers runtime, speculative buffers and late allocations. |
| `--block-size` | `256` | KV allocation granularity used by this patched backend. Changing it alters fragmentation and compatibility. |
| `--enable-chunked-prefill` | on | Splits long prefills so they share scheduling with decode traffic. |
| `--async-scheduling` | on | Reduces CPU scheduling overhead; preserve with the validated runtime. |
| `--enable-prefix-caching` | on | Reuses matching prompt prefixes; useful for agent/system prompts but consumes cache metadata. |

These settings are coupled. Do not raise context, sequence count and memory
utilization independently. The accepted `0.78` leaves headroom for allocations
that appear only on the first real speculative request; a configuration that
boots is not necessarily stable under traffic.

## MLA KV and MTP

| Parameter | Baseline | Meaning and constraints |
|---|---:|---|
| `--kv-cache-dtype` | `nvfp4_ds_mla` | Quantized DeepSeek MLA KV cache. Primarily a context-capacity lever, not a guaranteed speed gain. |
| `VLLM_TRITON_MLA_SPARSE` | `1` | Enables the patched sparse MLA path. |
| `VLLM_SPARSE_INDEXER_MAX_LOGITS_MB` | `256` | Bounds temporary sparse-indexer logits memory. |
| speculative method | `dspark` | Uses the model's DSpark draft/MTP path. |
| `MTP_NUM_TOKENS` | `5` | Number of speculative tokens. The drafter emits five per pass; the accepted Patch4 profile is fixed at five. |
| `draft_sample_method` | `probabilistic` | Retained for recipe compatibility. In the pinned runtime it is effectively neutral unless draft probabilities are exported. |

Do not infer that a larger speculative depth is better. Values above the
drafter's five-token output can fail guards or generation shape checks. Patch4
also restores the draft model's always-on shared expert tensors; output quality
alone does not prove that the performance patch is present.

## Thinking, reasoning and tools

| Parameter | Role |
|---|---|
| `--reasoning-parser deepseek_v4` | Maps generated reasoning into protocol fields. It does not enable reasoning generation. |
| `--reasoning-config ...` | Defines parser boundaries such as `<think>` and `</think>`. |
| `--default-chat-template-kwargs '{"thinking":true}'` | Actually requests thinking from the DeepSeek V4 chat template. The base Compose sets `false`; the override sets `true`. |
| `--tool-call-parser deepseek_v4` | Parses model tool calls using the DeepSeek V4 format. |
| `--enable-auto-tool-choice` | Allows automatic tool selection for agent requests. |
| `--tokenizer-mode deepseek_v4` | Selects the model-specific tokenizer/chat behavior. |
| `--generation-config vllm` | Uses explicit vLLM defaults and avoids inheriting an incompatible model generation override. |

Verify thinking in two places: rendered Compose must contain only
`{"thinking":true}`, and actual `stream-json` output must contain thinking or
redacted-thinking blocks. Client UI settings and answer quality are not proof.

## NCCL and RoCE/RDMA

| Variable | Baseline | Meaning |
|---|---:|---|
| `NCCL_NET` | `IB` | Selects NCCL's InfiniBand/RDMA transport, including RoCE. |
| `NCCL_IB_DISABLE` | `0` | Keeps the RDMA transport enabled. |
| `NCCL_IB_HCA` | site-specific | Exact RDMA HCA exposed in the container. |
| `NCCL_SOCKET_IFNAME` | site-specific | Fabric Ethernet interface used for bootstrap/socket control. |
| `NCCL_IB_GID_INDEX` | `3` baseline | RoCE GID entry verified for the accepted fabric; discover it locally rather than assuming. |
| `NCCL_CROSS_NIC` | `1` | Allows cross-NIC routing behavior used by the recipe. |
| `NCCL_CUMEM_ENABLE` | `0` | Disables NCCL cuMem allocation path for this validated GB10 runtime. |
| `NCCL_NVLS_ENABLE` | `0` | NVLink SHARP is not part of this two-host RoCE topology. |
| `NCCL_DEBUG` | `WARN`, `INFO` for acceptance | INFO is useful to prove transport/rank initialization but is noisy for normal service. |

`NCCL_NET=IB` is an intention, not evidence. Acceptance logs must show the IB
transport and must not show `NET/Socket` as the selected data path. Monitor RDMA
receive/transmit and error counters across a bounded workload.

## Patch-specific environment

The `VLLM_USE_B12X_*`, `VLLM_DSPARK_*`, and `VLLM_DSV4_*` variables in Compose
select kernels, rejection/argmax behavior, capture timing and compatibility
paths supplied by the pinned DSpark runtime. They are not generic upstream vLLM
settings. Preserve them as an image/config tuple unless an isolated A/B run
includes deterministic correctness, concurrency, memory and soak evidence.

`TORCH_CUDA_ARCH_LIST=12.1a` and `FLASHINFER_CUDA_ARCH_LIST=12.1a` target GB10
Blackwell compilation. `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`
reduces allocator fragmentation; it does not increase physical memory.
