# Live Inventory - 2026-08-10

## Objective

Serve `DeepSeek-V4-Flash-0731` with tensor parallelism across `gb10` and
`gb10-2`, then verify the OpenAI-compatible API, output correctness,
concurrency, stability, and distributed participation.

## Host Summary

| Item | `gb10` (head candidate) | `gb10-2` (worker candidate) |
| --- | --- | --- |
| Hostname | `fusionxparkgb10-3e23` | `spark-3345` |
| SSH user | `chriswang` | `admin` |
| Management IP | `192.168.88.181` | `192.168.88.198` |
| OS | Ubuntu 24.04.4, aarch64 | Ubuntu 24.04.4, aarch64 |
| GPU | NVIDIA GB10 | NVIDIA GB10 |
| Driver / CUDA | 580.126.09 / 13.0 | 580.142 / 13.0 |
| Unified memory | 119 GiB | 119 GiB |
| Root storage | 3.6 TiB, 865 GiB free | 1.8 TiB, 1.5 TiB free |
| Docker | 29.1.3, user access works | 29.2.1, `admin` lacks socket access |
| Passwordless sudo | yes | no |

## Existing Assets

On `gb10`:

- Official model directory:
  `/home/chriswang/model/DeepSeek-V4-Flash-0731` (about 156 GiB, 48 shards).
- Preview model directory:
  `/home/chriswang/model/DeepSeek-V4-Flash-DSpark` (about 5.2 GiB).
- Upstream deployment checkout:
  `/home/chriswang/project/DeepSeek-v4-Flash-0731-DSpark-1M-NVFP4-KV-2x-DGX-Spark`.
- Upstream revision at inventory time: `cd366d5` on `main`.
- Existing user workloads include a healthy Qwen vLLM container on port 8004,
  plus `pdf2md-api` and `tradingagents-ashare`. They must be preserved.

On `gb10-2`:

- No model or deployment checkout was found under `/home/admin`.
- The GPU was idle at inventory time.

## Network Findings

- Management connectivity succeeds between `192.168.88.181` and
  `192.168.88.198`, with roughly 1-2.5 ms ping latency.
- `gb10` reports a 2.5 Gbit/s management link; `gb10-2` reports 1 Gbit/s.
- Each host exposes four ConnectX-7 ports, but every port reports
  `NO-CARRIER`. No high-speed fabric IP is configured.
- The imported recipe was validated on a dedicated RoCE/InfiniBand fabric and
  expects `NCCL_NET=IB`. The current management network is not an equivalent
  production fabric.

## Current Blockers

1. Establish physical carrier on at least one matching ConnectX-7 port per
   host, then configure a dedicated fabric subnet.
2. On `gb10-2`, grant `admin` Docker access (or provide another authorized
   operator account). This requires one privileged action outside the current
   SSH session.
3. Replicate the runtime image, repository, and model to `gb10-2` after the
   high-speed path is available.

## Safety Decision

Do not stop the existing Qwen vLLM workload on `gb10`. The new distributed
service should use a distinct compose project and port unless memory pressure
proves that coexistence is impossible; any replacement then requires explicit
authorization.
