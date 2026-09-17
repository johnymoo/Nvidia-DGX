# DeepSeek-V4.1-Flash EXL3 2.9bpw + Engram — dual DGX Spark (GB10)

Serves the community EXL3 re-quantization of DeepSeek-V4.1-Flash (uniform
2.9bpw mul1, ~197 GiB across 39 shards) on a two-node GB10 pair with TP=2
over CX7 RoCE. The un-quantized Engram n-gram tables (native checkpoint
shards 47/48) are bind-mounted from a slim hardlinked tree, and the
in-checkpoint DSpark MTP drafter (k=3) accelerates decode. Native vision
tower is retained; the checkpoint is MIT-licensed.

Status: **Reference** — full validation executed 2026-09-17 on a
119.63 GiB UMA pair; see `BENCHMARK-RESULTS.md` and
`benchmark-results-20260917.json`.

## Headline numbers (this cluster, 2026-09-17)

| Probe | Result |
|---|---:|
| Decode structured c1 | 41.9 tok/s (MTP accept/step 2.08), TTFT 0.26 s |
| Decode prose c1 | 31.3 tok/s, TTFT 0.27 s |
| Concurrent structured c2 / c4 aggregate | 67.6 / 60.3 tok/s |
| Menu vision task (47 fields) | off 38/47 in 22 s, thinking 37/47 |
| Synthetic vision suite | 6/6 |
| Hermes agent real tasks | 3/3 success, server prefix-cache hit 93.2% |
| Boot to healthy | 368 s |

## Deployment notes (differences vs the upstream kit)

1. **Memory envelope.** This kit exposes 119.63 GiB UMA per node vs the
   upstream kit's ~121.7 GiB. `GPU_MEM_UTIL=0.84` (the production DeepSeek
   value) is the safe point: 0.86 completed the decode/concurrency probes
   but aborted under host-memory pressure during large-image vision work.
   `DSV41_BOOT_MARGIN_GIB=12` and `KV_CACHE_MEMORY_BYTES=2147483648` pair
   with it.
2. **Engram staging.** The boot needs a slim Engram tree built by the kit's
   `scripts/prepare_engram_src.py` (hardlinks shards 47/48 + embed-only
   index) **plus the native `config.json`**, which the upstream download
   recipe does not fetch — grab it from the native HF/ModelScope repo.
   Without it the Engram file backend fails with
   `FileNotFoundError: /engram-src/config.json`.
3. **Pre-staged weights.** The reference run staged the EXL3 and Engram
   trees on both hosts ahead of the window and booted with
   `SKIP_SYNC=1 DSV41_TRUST_STAGED=1` (a one-line start.sh patch skips the
   du-based free-space preflight when the trees are already complete).
4. **After a crash, clear both ranks.** The worker rank container can
   outlive a dead head and pin ~112 GiB; `scripts/window-step.sh` removes
   stale `dsv41-exl3-{head,worker}` containers before booting.
5. **Prefill tuning is deliberately conservative**
   (`MAX_NUM_BATCHED_TOKENS=1536`, `LONG_PREFILL_TOKEN_THRESHOLD=1280`);
   long-prompt cold ingest is not this profile's strength.

## Layout

- `ds41.env.example` — kit configuration template (TEST-NET placeholders).
- `scripts/window-step.sh` — window driver: preflight, stop production
  service, boot, full benchmark suite, restore; idempotent, crash-recovery
  guards included. Boot with `DSV41_TRUST_STAGED=1`.
- `scripts/bench_decode_18890.py`, `scripts/bench_concurrent.py`,
  `scripts/bench_prefill_ladder.py`, `scripts/summarize_ds41.py` — probes
  and summarizer used for the receipt.
- `scripts/run-hermes-real-tasks-ds41.sh` — agent real-task leg (reads
  task prompts from a local jobs file at runtime; no prompts in-tree).
- `BENCHMARK-RESULTS.md`, `benchmark-results-20260917.json` — evidence.
