# Patch4 vs Gitee Recipe Pin-to-Pin Benchmark

Date: 2026-08-12 (Asia/Shanghai)

Status: checked working conclusion; exact Gitee benchmark matrix rerun on Patch4

## Conclusion

The Gitee runtime is modestly faster on this one exact-matrix run, but the result is not
one-sided. Both runtimes completed all 20 cells and all 116 requests. Gitee won aggregate
output throughput in 13 of 20 cells; Patch4 won 7. The median Patch4 throughput delta across
the 20 cells was `-5.45%` relative to Gitee. Mean aggregate throughput grouped by concurrency
was 1.1% to 7.7% lower on Patch4.

Patch4 remains the accepted runtime. This matrix is a short performance A/B, not a replacement
for Patch4's correctness, tool-use, agent, recovery, and 40-minute soak acceptance evidence.
It also does not validate practical 1M latency: the matrix stops at approximate 2,048-token
input/output pairs.

## Pin-to-Pin Contract

The comparison used the exact same adapted Gitee scripts for both runs:

| Input | Identity |
| --- | --- |
| Gitee source | commit `17ef49b0035d3f017e239e528d6f13801a3fc374` |
| `benchmark-matrix.py` | SHA-256 `68da23cf46e68395eda302c366ff41bf93442c4f661909d7b3ecf80ee4304b8b` |
| `benchmark-ttft-tps.py` | SHA-256 `be1f374d7058594f014cdb897408ee9d8bd3780ef1e7bd4a4a8f180a7b795831` |
| Concurrency | `1, 3, 5, 8, 10` |
| Approximate input/output lengths | `50, 500, 1024, 2048` |
| Request mode | OpenAI chat completions, streaming, temperature `0.6`, top-p `0.95` |
| Requests per cell | `max(concurrency, 3)` |

Only the API endpoint and served-model name differed. Gitee used the Anemll image at
`gpu-memory-utilization=0.80`; Patch4 used the accepted `f277b3d` image at `0.78`. Both used
the official 0731 checkpoint, TP=2 over the same two GB10 hosts, 1,048,576 configured context,
NVFP4 MLA KV, DSpark speculation with five draft tokens, and `thinking=false`.

## Aggregate Output Throughput

Higher is better. Delta is `(Patch4 / Gitee - 1) * 100`.

| C | Approx. input/output | Patch4 tok/s | Gitee tok/s | Patch4 delta | Winner |
| ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 50 | 45.73 | 63.09 | -27.52% | Gitee |
| 1 | 500 | 50.25 | 43.85 | +14.58% | Patch4 |
| 1 | 1024 | 44.44 | 46.51 | -4.45% | Gitee |
| 1 | 2048 | 50.08 | 41.90 | +19.54% | Patch4 |
| 3 | 50 | 52.97 | 58.46 | -9.39% | Gitee |
| 3 | 500 | 87.41 | 93.44 | -6.45% | Gitee |
| 3 | 1024 | 95.01 | 102.92 | -7.68% | Gitee |
| 3 | 2048 | 91.38 | 75.56 | +20.93% | Patch4 |
| 5 | 50 | 124.09 | 127.28 | -2.51% | Gitee |
| 5 | 500 | 108.84 | 94.36 | +15.34% | Patch4 |
| 5 | 1024 | 100.82 | 100.52 | +0.30% | Patch4 |
| 5 | 2048 | 88.89 | 115.52 | -23.05% | Gitee |
| 8 | 50 | 119.47 | 129.84 | -7.99% | Gitee |
| 8 | 500 | 116.36 | 107.80 | +7.94% | Patch4 |
| 8 | 1024 | 124.84 | 123.85 | +0.80% | Patch4 |
| 8 | 2048 | 115.41 | 129.52 | -10.89% | Gitee |
| 10 | 50 | 129.67 | 139.79 | -7.24% | Gitee |
| 10 | 500 | 119.35 | 135.38 | -11.84% | Gitee |
| 10 | 1024 | 112.74 | 127.10 | -11.30% | Gitee |
| 10 | 2048 | 130.17 | 130.47 | -0.22% | Gitee |

### Throughput Summary by Concurrency

Each row is the arithmetic mean of the four length cells at that concurrency.

| Concurrency | Patch4 tok/s | Gitee tok/s | Patch4 delta |
| ---: | ---: | ---: | ---: |
| 1 | 47.63 | 48.84 | -2.48% |
| 3 | 81.69 | 82.60 | -1.09% |
| 5 | 105.66 | 109.42 | -3.44% |
| 8 | 119.02 | 122.75 | -3.04% |
| 10 | 122.99 | 133.18 | -7.66% |

## TTFT p90

Lower is better. Delta is `(Patch4 / Gitee - 1) * 100`; negative favors Patch4.

| C | Approx. input/output | Patch4 ms | Gitee ms | Patch4 delta | Winner |
| ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 50 | 291.6 | 207.8 | +40.34% | Gitee |
| 1 | 500 | 519.7 | 5735.0 | -90.94% | Patch4 |
| 1 | 1024 | 2598.8 | 6903.1 | -62.35% | Patch4 |
| 1 | 2048 | 653.4 | 5668.8 | -88.47% | Patch4 |
| 3 | 50 | 1942.7 | 244.9 | +693.28% | Gitee |
| 3 | 500 | 784.0 | 734.9 | +6.68% | Gitee |
| 3 | 1024 | 830.6 | 721.2 | +15.17% | Gitee |
| 3 | 2048 | 866.5 | 1573.0 | -44.92% | Patch4 |
| 5 | 50 | 539.3 | 380.8 | +41.62% | Gitee |
| 5 | 500 | 1236.6 | 6133.8 | -79.84% | Patch4 |
| 5 | 1024 | 1242.3 | 6701.1 | -81.46% | Patch4 |
| 5 | 2048 | 1062.5 | 1002.9 | +5.94% | Gitee |
| 8 | 50 | 3252.6 | 3362.6 | -3.27% | Patch4 |
| 8 | 500 | 23182.0 | 31444.9 | -26.28% | Patch4 |
| 8 | 1024 | 20362.4 | 35534.0 | -42.70% | Patch4 |
| 8 | 2048 | 31942.0 | 20351.4 | +56.95% | Gitee |
| 10 | 50 | 3842.2 | 3317.5 | +15.82% | Gitee |
| 10 | 500 | 27630.0 | 26865.8 | +2.84% | Gitee |
| 10 | 1024 | 37646.8 | 39557.1 | -4.83% | Patch4 |
| 10 | 2048 | 29349.7 | 27912.5 | +5.15% | Gitee |

TTFT split exactly 10 cells each. Its median Patch4 delta was `-0.21%`, but individual cells
ranged from `-90.94%` to `+693.28%`. With only 3 to 10 requests per cell and runtime JIT
warnings during inference, this run supports a variance finding, not a stable latency ranking.

## Decode TPS and Run-Level Results

Patch4 mean per-request decode TPS was higher in 4 of 20 cells and lower in 16; the median
Patch4 delta was `-7.35%`. Both matrices completed 116 successful requests with zero request
failures. Patch4 took 721.6 seconds versus 690.9 seconds for Gitee, 4.44% longer overall.

| Run-level item | Patch4 | Gitee |
| --- | ---: | ---: |
| Completed cells | 20 / 20 | 20 / 20 |
| Successful requests | 116 | 116 |
| Failed requests | 0 | 0 |
| Matrix duration | 721.6 s | 690.9 s |
| Aggregate-throughput cell wins | 7 | 13 |
| TTFT p90 cell wins | 10 | 10 |
| Decode-TPS cell wins | 4 | 16 |

## Interpretation and Limits

1. This is pin-to-pin at the benchmark-script and request-matrix level, not a configuration-
   identical runtime test. The runtime implementations and memory utilization settings are the
   intended independent variables.
2. The prompt builder targets approximate lengths, and generation is stochastic. A successful
   request may stop before `max_tokens`; throughput therefore measures the actual generated
   workload in that cell, not a fixed-token synthetic kernel.
3. The matrix has small sample counts and executes cells in a fixed order. JIT compilation and
   cache history can materially move TTFT. Repeat runs with randomized cell order are required
   before assigning a latency SLO.
4. The matrix covers only up to approximate 2,048-token input/output pairs. It provides no 1M
   context performance evidence.
5. Patch4's broader accepted evidence remains materially stronger: correctness, tool use, agent
   sanity, concurrent requests, bounded recovery, and a 40-minute c4 soak. This short A/B does
   not supersede that operational acceptance.

## Evidence

Gitee baseline run: `20260812T064519Z`. Its 20-cell JSON manifest SHA-256 is
`3c7d32d5a27389c013c10242dd5b02b91c6e0dc701a86ad6ff2506819699daf9`; generated report
SHA-256 is `8950f0f671963a7d0f9d6e63a4fb45deeef7ae953e6c19e1eba6f65b4f621f87`.

Patch4 run: service receipt `20260812T081254Z`, release
`f277b3dfa718a5962bed64e69e7e640a5384ec2f`, normalized fingerprint
`36adbf92fe8cdd5c57609b2c5ccfa8e2fc32a340c9ee3d727be538143dda74db`,
`thinking=false`. Its 20-cell JSON manifest SHA-256 is
`9bd7930d80acd3778647062d7c6df9d1b22fc3e94b34520c943665e74246ffd9`; generated report
SHA-256 is `94e10e47fa053c55dc39939eab39a357f502fca38c9935f32e9bc23c52871748`.

Both Patch4 ranks had `OOMKilled=false`, restart count 0, and no fatal NCCL, Linux OOM-kill,
Xid, or worker-loss pattern in the captured benchmark logs. The service controller stopped
Patch4 and restored Qwen. Post-restore checks recorded Qwen, TradingAgents, and worker Lexdata
healthy with restart count 0 and no active Patch4 service receipt.
