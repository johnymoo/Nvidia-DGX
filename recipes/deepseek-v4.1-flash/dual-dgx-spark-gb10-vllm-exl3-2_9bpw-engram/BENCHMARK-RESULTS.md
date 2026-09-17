# DeepSeek-V4.1-Flash EXL3 2.9bpw — validation evidence (2026-09-17)

Two-node DGX Spark (GB10) pair, CX7 RoCE direct, TP=2 nnodes=2, API on the
head. Checkpoint: community EXL3 uniform 2.9bpw mul1 (~197 GiB) + native
Engram tables (shards 47/48, slim-hardlinked bind mount) + in-checkpoint
DSpark MTP k=3. Native vision tower retained. MIT license.

Profile: `MAX_MODEL_LEN=300000`, `GPU_MEM_UTIL=0.84`, KV pin 2 GiB
(pool 597,614 tokens = 1.99x of 300k, fp8_ds_mla), MNBT 1536,
`MAX_NUM_SEQS=4`. Boot to healthy: **368 s**. All quantiles from 5-run
streams; production DeepSeek service on the same cluster provides the
reference column.

## Decode (temp 0, thinking off, 400 tokens)

| Probe | This profile | GLM-5.3-Flash EXL3 4bpw (2026-09-11, same cluster) | DeepSeek-V4-Flash reference (production) |
|---|---:|---:|---:|
| structured c1 tok/s (median) | **41.9** | 64.1 | ~43-55 |
| structured accept/step | 2.08 | 6.59 | 3.11 (MTP k=6) |
| structured TTFT s | **0.258** | 0.340 | 64% <= 0.5 s |
| prose c1 tok/s (median) | **31.3** | 24.4 | **38-50** |
| prose TTFT s | 0.270 | 0.345 | - |

Structured run spread (tok/s): min 41.8 / p50 41.94 / p95 42.55 / max 42.55.
Prose run spread: min 30.1 / p50 31.3 / max 32.7.

## Concurrency (aggregate / per-stream tok/s, median of 3)

| Prompt | c2 | c4 |
|---|---:|---:|
| structured | 67.6 / 34.6 | 60.3 / 15.4 |
| prose | 42.9 / 22.2 | 44.3 / 11.2 |

## Prefill ladder (unique-salt cold prompts)

| Rung | tok/s |
|---|---:|
| 8k | 914.9 |
| 16k | 631.3 |
| 32k+ | aborted by memory guard |

The run aborts at the 32k rung with host MemAvailable at 795 MB (guard floor
1200 MB). This profile pins `MAX_NUM_BATCHED_TOKENS=1536` and
`LONG_PREFILL_TOKEN_THRESHOLD=1280` under the 119.63 GiB UMA envelope;
long-prompt cold ingest is intentionally conservative here and cold ingest
throughput beyond ~16k prompts should not be assumed.

## Vision

- Synthetic suite: **6/6 passed**.
- 47-field menu task: **off 38/47 in 22.1 s**, thinking 37/47 in 84.9 s.
  (Reference: GLM-5.3 off 32 / thinking 38; production DeepSeek vision
  exp off 9. The menu truth itself is production data and is not
  published; only scores and method are.)
- Streaming aggregate tok/s: off c1/c2 = 32.9/38.7, thinking c1/c2 =
  38.3/53.5.
- An earlier same-day profile at `GPU_MEM_UTIL=0.86` scored menu off
  38/47 before an unrelated host-memory abort — cross-confirming the
  score is not memory-tuning-sensitive.

## Agent real tasks (hermes loop, thinking=low, 3 frozen cron tasks)

3/3 success, total wall **861.3 s** (GLM 423.9 s, production DS 489.6 s on
the same cluster/runner). Server-side: decode 34.5 tok/s, uncached prefill
474 tok/s, prefix-cache hit **93.2%** (highest of the three). The wall-time
gap is driven by the longest outputs (17,247 tokens vs 12,288 DS / 3,744
GLM) and the most agent calls (54), not by tool-calling or schema
incompatibilities. Task prompts are production data; only walls and server
deltas are published.

## Stability notes

- Six pre-success boot attempts across two root causes (stale worker-rank
  container pinning ~112 GiB after a crash; the slim Engram staging step
  being skipped) — both fixes are folded into `scripts/window-step.sh`.
- `GPU_MEM_UTIL=0.86` aborts under host memory pressure during large-image
  vision workloads; 0.84 completed clean (decode/concurrency/prefill/
  vision/agent).
- 47-field menu vision truth and agent prompts are production data and are
  not published; only scores, timings, and method appear here.
