# Unsloth GGUF / llama.cpp Research - 2026-08-10

Research performed read-only by `gpt-5.6-terra` at high reasoning and revised
after the user correctly noted that Unsloth explicitly targets DGX Spark.

## Corrected Conclusion

Unsloth supports DGX Spark/GB10. Its IQ2/IQ3 sizing makes a 128 GB unified-
memory Spark an explicit target, and llama.cpp's existing RPC layer offload can
use two Sparks today. The separate benchmark fact remains: Unsloth's headline
120 tok/s was measured on one B200, not on one or two GB10s.

The route is a real A/B candidate. It is not the initial production baseline
because DSpark over two RPC endpoints has not been published and the current
two-Spark target-only GGUF results are below the vLLM evidence.

## Primary Sources

| Source | Status | Relevant evidence |
| --- | --- | --- |
| [Unsloth guide](https://unsloth.ai/docs/models/deepseek-v4) | Official | Recommends `UD-IQ3_XXS` for 128 GB systems and gives a GGUF+DSpark command. |
| [Unsloth DSpark README](https://huggingface.co/unsloth/DeepSeek-V4-Flash-0731-GGUF/blob/main/dspark/README.md) | Official | Pins llama.cpp requirements and B200 benchmark method. |
| [Unsloth discussion 36](https://huggingface.co/unsloth/DeepSeek-V4-Flash-0731-GGUF/discussions/36) | Official announcement | Advertises the 1.4-2x DSpark result; the guide identifies B200 hardware. |
| [llama.cpp RPC README](https://github.com/ggml-org/llama.cpp/blob/master/tools/rpc/README.md) | Upstream official | Existing layer offload distributes weights and KV. RDMA is automatic when built with `libibverbs`. |
| [Two-Spark reproduction](https://github.com/ggml-org/llama.cpp/issues/26820#issuecomment-5236104243) | Community measurement | Two GB10s over direct 200G RoCE: IQ2_M 20.19 tok/s; Q4_K_XL 16.49 tok/s, target only. |
| [RPC fix PR 26500](https://github.com/ggml-org/llama.cpp/pull/26500) | Open, used by reproduction | Fixes multi-RPC buffer ownership; head `f0c483c4df52f82cc5795433c9e9332fb3e8aa21`. |
| [Prompt-cache issue 26529](https://github.com/ggml-org/llama.cpp/issues/26529) | Open | Repeated RPC requests need `--cache-ram 0`. |
| [Tensor RPC PR 26610](https://github.com/ggml-org/llama.cpp/pull/26610) | Open, optional | Tensor split/custom all-reduce path; not required for existing layer offload. |

Direct Hugging Face origin timed out in the research environment. Public model
cards and discussion APIs were read through the Hugging Face mirror; canonical
URLs are cited above. No private Discord claims were used.

The downloader pins snapshot `fbbb5b93fb787c21338159b0af3318bb3f4d9768`.
Its six content checksums were re-read from that revision's LFS metadata and
the first shard was downloaded from the canonical origin and matched its LFS
SHA-256 (`d13ce8f9...`).

## Official Single-Spark Recipe

Unsloth's Spark-sized command is:

```bash
llama-server \
  -hf unsloth/DeepSeek-V4-Flash-0731-GGUF:UD-IQ3_XXS \
  --spec-type draft-dspark --spec-draft-n-max 3 \
  --fit off -ngl 99 -ngld 99 -fa on \
  -c 8192
```

The root Q8 sidecar is auto-discovered. Do not set `--spec-draft-device`; the
sidecar must follow the target across the same devices.

Required llama.cpp history:

- b10228+: DeepSeek V4 DSpark;
- b10247+ (`dbadb68e...`): multi-device scheduler fix;
- avoid b10259-b10268;
- b10269+ (`1c3c9674...`): recommended drafter-load fix.

The pinned RPC fix head `f0c483c4...` is 42 commits ahead of b10269 and zero
behind, verified through GitHub's compare API.

## Performance Evidence

Unsloth's 120 benchmark used Q4, greedy decoding, a seven-turn conversation,
replies up to 4096 tokens, decode-only rate, and median of three repetitions:

| Hardware | Baseline | DSpark n=3 |
| --- | ---: | ---: |
| 1x B200 | 62.6 | 119.7 tok/s |
| 4x B200, layer split | 61.0 | 112.4 tok/s |

One Spark evidence from llama.cpp PR 25784 is about 16.4 tok/s baseline and
19.8-39.3 tok/s with DSpark by workload. It lacks enough quant/context detail
for exact reproduction.

Two Spark target-only RPC evidence over direct 200G RoCE is 20.19 tok/s for
IQ2_M and 16.49 tok/s for Q4_K_XL (`tg128`). DSpark-over-RPC is not measured.

## Memory Fit

With the 10.148 GiB Q8 sidecar:

| Target | Combined | Free from 119 GiB |
| --- | ---: | ---: |
| `UD-IQ2_M` | 94.83 GiB | 24.17 GiB |
| `UD-Q2_K_XL` | 100.33 GiB | 18.67 GiB |
| `UD-IQ3_XXS` | 107.20 GiB | 11.80 GiB |
| `UD-IQ3_S` | 118.25 GiB | 0.75 GiB |

A measured cache log used about 0.78 GiB Q8 KV at 220K context plus about
4 GiB compute buffers. IQ3_XXS + sidecar therefore fits one Spark at 8K and
moderate context, but full 1M is too tight to promise. Two-node Q4 has ample
aggregate capacity and better published quality evidence.

## Prepared Two-Spark A/B

Topology:

```text
gb10   local ggml-rpc-server -> CUDA0
gb10-2 remote ggml-rpc-server -> CUDA0 over ConnectX-7/RDMA
gb10   llama-server coordinator -> both RPC endpoints
```

The prepared Compose has separate `target` and `dspark` profiles. Both use a
1:1 layer split, 256K context, single stream, and `--cache-ram 0`; the DSpark
profile adds the Q8 sidecar with draft maximum 3. The image builds PR 26500
head with CUDA, RPC, libibverbs, and RDMA support. RPC binds only to loopback
on the head and the dedicated fabric address on the worker because the
protocol is explicitly insecure.

Validation order after cabling:

1. Q4 target only, compare with the published 16.49 tok/s baseline;
2. add Q8 DSpark sidecar and prove both RPC devices receive target and draft;
3. deterministic quality and acceptance checks;
4. repeated requests, concurrency, soak, worker loss, and recovery;
5. A/B against vLLM using identical requests and completion-token accounting.

## Built Runtime Evidence

The pinned image was built on `gb10` as
`gb10-unsloth-llama:f0c483c4-rpc` with image ID
`sha256:42f458f96b761d9af4890496a60969adddc84afaf865d5a11214d5ddec7fb4f6`.
`llama-server --version` reported commit `f0c483c` for Linux aarch64. The RPC
binary resolved `libibverbs.so.1` inside a GPU container, and its help exposed
the CUDA device and cache options. Existing workloads remained healthy.
