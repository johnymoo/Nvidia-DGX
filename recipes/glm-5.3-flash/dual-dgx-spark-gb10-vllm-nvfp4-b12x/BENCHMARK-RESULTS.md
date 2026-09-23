# Benchmark results — GLM-5.3-Flash NVFP4 B12X (2026-09-21 window)

2× DGX Spark GB10 · KV 8G pinned (1,061,538 tok) · 500k ctx · MNBT 4096 · MTP k=5.
Same runners and frozen tasks as the EXL3 4bpw recipe (09-19 window) unless noted.

## Headline (vs EXL3 #219+MOE_FAST, 09-19)

| Metric | EXL3 09-19 | NVFP4 09-21 | Δ |
|---|---|---|---|
| Cold prefill 16k→256k | 1,243–1,366 tok/s | **1,924–2,018 tok/s** | +18% |
| Cold prefill near-limit | — | **492,514 tok @ 1,827 tok/s, zero NVRM** | new headroom |
| Decode c1 prose | 34.2 tok/s | 31.7 tok/s | par |
| Decode c1 structured | 77.5 tok/s (acc 0.91) | **33.1 tok/s (acc 0.46) ⚠** | −57%, see gap |
| Concurrency struct c2 / c4 | 126.2 / — | 85.4 / 133.4 | mixed |
| menu47 off / on | 37 / 38 | **47 / 39** | +10 / +1 |
| hermes 3 real agent tasks | 3/3, 423.8 s | 3/3, **230 s (−46%)** | |
| Context / KV pool | 300k / 309,523 | **500k / 1,061,538** | |
| Vision (on-mode) | 5/6 | 6/6 | |

## Dual-agent growth ladder (new test, `scripts/bench_agent_context.py --agents 2`)

Two agents grow context +2k/step concurrently to 400k each: 412 requests,
10.6 min wall, TTFT p50 **3.06 s** / max **8.5 s**, **zero cliffs**,
prefix-cache retention **99.0%** (81.97T/82.77T tokens).

## pi dual-agent real-client compaction (new test, `scripts/run_pi_dual_compaction.py`)

Two real pi agent sessions grow to the 300k client window: steady turns
2.0–2.4 s; auto-compaction fires at ~284k (95% window); compaction turn
165 s (client-side summarization); post-compaction context 37.7k, first turn
19.8 s cold, then normal.

## Open gap: structured decode acceptance

Same fixed prompt (count 1–200, temp 0, thinking off): acceptance dropped
0.91 → 0.46 between NVFP4 configs (yesterday's 6G/350k/MNBT 2048 config hit
55.0 tok/s on this same stack+weights). Prime suspect: MNBT 4096 spec-decode
scheduling (fork warning) vs boot-time draft autotune variance. Next window:
single-variable MNBT A/B.

## Memory

Steady MemAvailable: head ~1.5 GiB, worker ~3.5 GiB (bench-time trough
250–320 MB is prefill-ladder churn). KV 8→7 GiB relaxation (+1 GiB) available
as a one-line change if headroom is needed.

## Chinese prose (new methodology, `scripts/bench_decode_zh.py`)

The model answers Chinese technical prompts with long English reasoning
(thinking on/off); measured with a light-reasoning Chinese writing task and
phase-split timing: ZH body **41.6 tok/s (est) / 82 chars/s**, after ~22 s of
English reasoning. Decode throughput is language-independent; latency in ZH
workloads is dominated by reasoning length (`--reasoning low` helps).
