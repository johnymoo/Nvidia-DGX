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
