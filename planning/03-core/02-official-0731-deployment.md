# Official 0731 Deployment

Status: accepted. Run `20260811T002139Z` passed on 2026-08-11 using vLLM
revision `f277b3dfa718a5962bed64e69e7e640a5384ec2f` with Patch4.

## Contract

Run on `gb10` from `/home/chriswang/gb10-ds4` with base
`execution/docker-compose.yml` plus the active additive
`execution/docker-compose.f277b3d-timeout.yml`. The latter only supplies
`VLLM_ENGINE_READY_TIMEOUT_S=3600` and `PYTHONUNBUFFERED=1`.
`docker-compose.f277b3d-memory-profile.yml` is diagnostic-only and was not
active. Do not edit the base Compose or reduce: TP=2, 1,048,576 context,
six sequences, 0.78 memory utilization, NVFP4 MLA KV, or MTP=5.

The accepted command used `ACCEPTANCE_SKIP_PRESTART_CHECK=1`, retained Qwen
failure deferral, preserved stopped DeepSeek containers, and restored Qwen on
success. Worker starts before head. Evidence is at
`/home/chriswang/gb10-ds4/artifacts/acceptance/20260811T002139Z` and
`/home/admin/gb10-ds4/artifacts/acceptance/20260811T002139Z`.

## Topology and Immutable Inputs

| Alias | Role | Management / fabric | NIC / RDMA | Host stack |
| --- | --- | --- | --- | --- |
| `gb10` | head/API | `192.168.88.181` / `192.168.192.181/24` | `enp1s0f0np0` / `rocep1s0f0`, MTU 9000 | kernel `6.17.0-1014-nvidia`, Docker 29.2.1, Compose 5.0.2 |
| `gb10-2` | worker | `192.168.88.198` / `192.168.192.198/24` | `enp1s0f0np0` / `rocep1s0f0`, MTU 9000 | kernel `6.17.0-1014-nvidia`, Docker 29.2.1, Compose 5.0.2 |

The accepted image was `gb10-ds4-vllm:f277b3d-nvfp4`, normalized fingerprint
`36adbf92fe8cdd5c57609b2c5ccfa8e2fc32a340c9ee3d727be538143dda74db`.
The prior full 74-file manifest evidence is SHA
`50fe8ca783b4b394a357b0a3952fcedd71d4fca56ef49c5c159e10710b790faa`.

`--check` is read-only preflight; `--run` is the acceptance workflow. The
accepted invocation was:

```bash
cd /home/chriswang/gb10-ds4
ACCEPTANCE_SKIP_PRESTART_CHECK=1 \
ACCEPTANCE_KEEP_QWEN_STOPPED_ON_FAILURE=1 \
ACCEPTANCE_RESTORE_QWEN_ON_SUCCESS=1 \
ACCEPTANCE_PRESERVE_DEEPSEEK_CONTAINERS=1 \
timeout --foreground 10800 execution/run-vllm-acceptance.sh --run
```

## Verified Result

Receipt status was `passed`; model `deepseek-v4-flash-0731`; two ranks used
RoCE/NCCL `NET/IB`. KV capacity was 1,153,062 tokens. Correctness, tool use,
agent sanity, c1/2/4/6, and a 40-minute c4 soak passed. The soak completed
621 requests and 223,268 generated tokens with zero empty, garble, or HTTP
errors.

Known non-fatal evidence: `NVRM NV_ERR_NO_MEMORY` during warmup was tolerated
because warmup subsequently completed. Fatal monitor conditions are Xid,
Linux `oom-kill`/`Out of memory: Killed process`, and fatal mlx5 errors.

The log records model loading as 79.51 GiB per rank. It does not establish a
whole-process or simultaneous-service peak; treat those values as unknown.

The receipt records release, topology, frozen config, acceptance artifact
names, cleanup/restore state, service state, and full-manifest reference.
