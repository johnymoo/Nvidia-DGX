# GB10 cluster: optimization headroom and evaluation-system design (2026-09-04)

Status: lead approved §8 items 3 and 4 on 2026-09-04 ("都可以，先做吧");
items 1 and 2 still open. E4 (worker git checkout) is DONE — see §9. The
harness is being built under `execution/eval/` (§5.2). No launch-flag
change has been applied. Companion evidence: `2026-09-04-gb10-cluster-audit.md` (read-only
host audit), `2026-09-04-dspark-upstream-feature-survey.md` (upstream
evidence per flag), live `/metrics` snapshot 2026-09-04 ~00:55Z
(`tmp/live-metrics-20260904.txt`), live config copies in
`tmp/dspark-vision-live/`.

## 0. TL;DR

1. **DSpark speculative decoding is already ON in production.** The launch
   passes `--speculative-config {"method":"dspark","num_speculative_tokens":6,
   "draft_sample_method":"probabilistic"}` and `/metrics` shows 101,893 draft
   steps, 611,358 draft tokens, 215,529 accepted since boot (mean 2.11 accepted
   of 6 per step, i.e. ≈3.1 tokens per decode step). What is *not* on is the
   set of optional DSpark hotfix flags (`DSPARK_ENABLE_*`, all 0), the
   locally-built "Stage-C" runtime, LMCache, and TP=3. Upstream evidence says:
   one of those flags is worth trying (SP indexer, long prompts only), one is a
   measured regression (replicated Markov head), the rest are either
   symptom-gated fixes or unproven for our traffic profile.
2. **Decode is close to what this stack can give.** Single-stream decode is
   ~38 tok/s averaged over the day (82 ms per step × 3.1 tokens) and 47-50
   tok/s on well-accepted text; acceptance (76/54/36/23/14/8 % per draft
   position) sits inside upstream's measured band for chat traffic. `k` is
   pinned to 6 by the Vision-Exp checkpoint (must be ≥5 and divisible by 3),
   greedy drafting tied in two upstream A/Bs. No cheap decode lever exists.
3. **The real headroom is long-prompt prefill.** 11 % of requests carry
   ≥10K prompt tokens and they own the entire TTFT tail (7 requests >10 s,
   2 in the 40-80 s bucket, out of 944). Every prefill step is capped at
   1,024 tokens (`--long-prefill-token-threshold 1024`, a per-step chunk cap
   in vLLM V1) even when the request is alone on the engine. On a
   bandwidth-bound MoE with ~75 GiB of expert weights per rank, each 1,024-token
   step re-reads essentially all expert weights; a first-principles estimate
   puts the weight-read floor at ~0.28 s per step, i.e. a hard ceiling of
   ~3,700 tok/s and a realistic 1.5-2× gap between 1K and 8K chunks for a lone
   long prefill. This is the one change that could move a 60 s TTFT to ~35 s.
   It has never been measured on this stack and the upstream adaptive variant
   tripped host memory; it needs the harness in §5 before anything is flipped.
4. **Host memory is the binding safety constraint**, not GPU compute: 6 GiB
   (head) / 8 GiB (worker) MemAvailable with the service idle. Any change that
   grows workspace (bigger chunks, LMCache, extra containers) must be gated on
   MemAvailable ≥ 4 GiB on the head under load.
5. **We cannot currently answer "did a change help" without guessing.** The
   repo's benchmark scripts are pinned to the old stack; the pieces we need
   (streaming TTFT, `/metrics` delta with acceptance, repeats, needle, image
   probe) exist but are scattered across five unrelated scripts and two
   reference trees, none of them production-shaped. §5 designs a
   small, reusable evaluation system (A/B harness + production KPI scraper +
   correctness guardrails) and §6 proposes the first four experiments.

## 1. The cluster as configured (facts, condensed from the audit)

| Item | Value |
| --- | --- |
| Hosts | 2 × DGX Spark GB10 (119 GiB unified memory each, 20 cores, governor `performance`), direct 200 GbE RoCE link, MTU 9000, 0.83 ms ping RTT, 0 drops |
| Stack | MiaAI-Lab tree @ `d828ddd` (13 commits behind upstream HEAD, none performance-relevant), image `dspark-vllm-gx10:0.1.1` (only tag that exists), vLLM `0.25.2.dev0+g752a3a504`, torch 2.11+cu130, flashinfer 0.6.15, NCCL 2.30.7 |
| Model | `DeepSeek-V4-Flash-Vision-Exp` @ `86f746b`, served as `deepseek-v4-flash-0731`; 80.04 GiB weights per rank (main + 3 MTP/draft layers), TP=2, PP=1 |
| KV | `nvfp4_ds_mla`, block 256, **12.17 / 12.31 GiB available KV per rank**, 1,095,187 full-attention tokens (1.81 M incl. SWA layers), max concurrency 1.72× at 1 M context, `gpu-memory-utilization 0.835` |
| Scheduler | `max-num-seqs 6`, `max-num-batched-tokens 8192`, `long-prefill-token-threshold 1024`, chunked prefill, async scheduling, prefix caching (`VLLM_PREFIX_CACHE_RETENTION_INTERVAL=4096`), `DSPARK_MAX_INFLIGHT_PREFILLS=2`, plus in-image hotfixes #27 (partial-prefill cap enforced) and #43 (decode-lane fairness) |
| Spec decode | DSpark, k=6, probabilistic draft; CUDA graphs captured at 1,2,4,8,16,24,32,40,48 (no truncation on this boot) |
| Decode kernels | `--moe-backend flashinfer_b12x` (B12X MXFP4 MoE), flashinfer sampler, flashinfer autotune cache hit (24 configs) |
| Thinking | default `{"thinking":true,"reasoning_effort":"low"}`; request overrides win |
| Hotfixes at boot | 15 applied unconditionally on both ranks (identical order); all opt-in `DSPARK_ENABLE_*` = 0 |
| Boot cost | weights 202 s (head) / 145 s (worker), engine init 23 s, graph capture ~5 s → **~4-5 min to healthy** on a warm JIT cache (the old fork needed 13-16 min) |
| Ops hygiene gaps | worker `~/dspark-vision` is not a git checkout; head has 4 extra files in `patches/`; two Triton kernels JIT-compile on first production request after each boot; `max_num_scheduled_tokens=8162` advisory; 4 unknown `VLLM_BUILD_*` env vars |

Other user workloads present and to be preserved: head `qwen36-8004-proxy`,
`tradingagents-ashare`, `ollama`, `1panel`, `sing-box`; worker `lexdata-ai`.

## 2. Live workload model (one boot, 2026-09-03 15:53Z → 09-04 00:55Z, 944 requests)

Derived from the `/metrics` histograms; this is the population the evaluation
workload must mirror.

| Dimension | Distribution |
| --- | --- |
| Prompt tokens | ≤1K: **81 %** · 1K-10K: 8 % · 10K-50K: 8 % · 50K-200K: 2.2 % · none >200K; mean 5,096 |
| Generation tokens | median ~150, mean 336, 92 % ≤ 2K; 15 % of requests end on `length` (client `max_tokens` caps of 50-200, i.e. title/summary side-calls) |
| Concurrency | 76 % of engine steps carry one request's 7-token verify batch; ≤4 % carry two; >2 concurrent is rare. Queue time is nil (939/944 < 0.3 s) |
| Prefix cache | 83 % of prompt tokens hit (3.99 M of 4.81 M); only 818,828 tokens were actually prefilled |
| TTFT | 64 % ≤ 0.5 s · 86 % ≤ 1 s · 96 % ≤ 2.5 s · 99.3 % ≤ 10 s · tail: 3 in 10-20 s, 2 in 20-40 s, 2 in 40-80 s |
| Decode step time | 58 % ≤ 75 ms · 88 % ≤ 100 ms · 99 % ≤ 150 ms; mean 82.4 ms/step at 3.11 tokens/step |
| Acceptance per draft position | 76 / 54 / 36 / 23 / 14 / 8 % (mean 2.11 of 6); engine log shows 2.2-6.3 depending on content |
| Errors / preemptions | 0 / 0 |

Reading: the service is a lightly loaded, single-stream, short-chat service
with a long-prompt tail from agent harnesses. User-perceived quality is set by
(a) single-stream decode speed, (b) cold TTFT on the 10K-200K prompts, and
(c) prefix-cache reliability across a session. Aggregate throughput at c=6 —
the number most upstream A/Bs optimise — is nearly irrelevant here.

## 3. Where the time goes, and what that says about headroom

**Decode (per step, c=1).** A verify step scores 7 tokens through the full
model. On GB10 the step is memory-bandwidth-bound: LPDDR5x ≈ 273 GB/s per
host, and each rank reads the shared weights plus every expert any of the 7
tokens routes to. The observed 82 ms/step is consistent with reading on the
order of 15-20 GiB of NVFP4 weights per step; cross-host all-reduce over the
RoCE link is a few ms of that (message sizes are ~100 KB; latency-bound).
Consequences:

- More accepted tokens per step is the only lever that scales decode, and
  acceptance is a property of the draft head + content (upstream: "the
  largest decode lever on the lane", no fix shipped). k=9 would add ≈0.08
  tokens/step (positions 6-8 extrapolate to 4.5/2.5/1.4 %) for 3 more verify
  tokens — a net loss. Greedy drafting: upstream tie. Replicated Markov head:
  upstream regression at c=6, flat at c=1.
- Stage-C's `VLLM_DSPARK_*` knobs (confidence-threshold early stop, fused
  argmax, deferred capture) are the only remaining decode ideas; they need a
  local image build and have no like-for-like number vs Anemll 0.1.1. Research
  track, not production.
- Verdict: expect ≤5 % from configuration alone; do not spend idle windows on
  decode flags first.

**Prefill (cold, long prompt).** The chunk cap makes a lone 100K prompt run
as ~98 steps of 1,024 tokens. Per step the MoE layers touch essentially every
expert (1,024 tokens × top-k routing over the expert set), so each step
re-streams the rank's expert weights. Estimate (not yet measured on this
stack): ~75 GiB of the 80 GiB per rank are expert weights → ≈0.28 s per step
of pure weight traffic → ≥27 s of the TTFT of a 100K prompt is weight
re-reading; at 8K chunks that floor drops to ~3.4 s. Compute (2 × active
params × tokens) and the Lightning indexer (grows with context) set the rest.
Upstream's live TP=2 numbers for long cold prefills are in the 1.6-1.8K tok/s
range on the old fork; on this stack we have no measurement.

- The fairness hotfixes (#27, #43) exist because large chunks starve decode
  lanes when prefill and decode share the engine. With our concurrency
  profile that sharing is rare, but when it happens the decode user sees the
  whole chunk time as one inter-token gap (8K chunk ≈ 2-3 s). So the right
  shape is *adaptive*: big chunks only when no decode lane is active (that is
  what upstream's `hotfix-dsv4-adaptive-prefill-chunk.py` does), or a static
  middle value (2,048 / 4,096) that halves or quarters the weight re-read
  while bounding the worst inter-token gap at ~0.6-1.2 s.
- Upstream's adaptive A/B booted clean but head `MemAvailable` fell to 2.3 GB
  (from 3.8-5.2 GB) and they parked it. Why extra host-visible memory appears
  is unknown ("owner not found"). On GB10 the profiler already sizes
  activation workspace for `max_num_batched_tokens=8192`, so the growth is
  probably pinned/host-side buffers or JIT workspaces, which is exactly what
  the harness's MemAvailable gate is for.
- `DSPARK_ENABLE_SP_INDEXER=1` (sequence-parallel Lightning indexer for
  prefill chunks ≥ 8,192 compressed keys ≈ 32K tokens) is the second prefill
  lever: upstream measured −4 to −8 % TTFT at ≥128K, nothing at ≤32K, exact
  top-k merge, fail-closed patch, ruler-lite passed. Small but real for the
  2.2 % XL bucket.
- Verdict: the prefill side has a plausible 1.5-2× for the ≥10K bucket
  (chunk cap) plus a further 4-8 % at ≥128K (SP indexer). This is where idle
  windows should go, and it must be measured, not assumed.

**Memory.** Weights 80 GiB + KV 12 GiB + workspace ≈ 99 GiB of the 0.835 ×
119 GiB budget; host has 6-8 GiB left. Trading `gpu-memory-utilization` for
host headroom is expensive because KV is the only elastic term: −0.035 in the
ratio frees ~4 GiB host-side but removes a third of the KV pool
(1.095 M → ~0.72 M tokens), which would hurt the 83 % prefix-hit rate for
long sessions. Keep 0.835 unless the harness shows a change needs headroom,
and then buy the minimum.

**Prefix cache / KV tier.** With 7 requests per day above 10 s TTFT, the
Phase B NVMe tier (issue #45) and LMCache stay shelved; the KPI scraper in §5
is what will tell us if that tail grows.

## 4. Candidate changes, ranked for this traffic

Ordering = expected user-visible gain × evidence quality ÷ risk. "Gate" is
what the harness must show before adoption. All are single-flag boots with a
`.env.dspark.bak-<UTC>` and stop/start recreate (a `docker compose restart`
does not undo boot-time patches).

| # | Change | Mechanism | Expected (our profile) | Risk | Evidence | Gate |
| --- | --- | --- | --- | --- | --- | --- |
| E0 | none — baseline measurement | — | establishes cold prefill tok/s at 8K/32K/64K/128K, c=1 decode, acceptance, MemAvailable on this stack | none | we have no numbers for 0.25.2 + Vision-Exp | — |
| E1 | `LONG_PREFILL_TOKEN_THRESHOLD` 1024 → 2048 → 4096 (static sweep), then upstream adaptive chunk | fewer expert-weight re-reads per prefilled token | up to 1.5-2× cold prefill at ≥32K if weight-bound; TTFT tail 60 s → ~35 s | decode-lane ITL spike during concurrent long prefill (bounded by chunk size); host memory (upstream saw 2.3 GB) | first-principles + upstream memory observation; no tok/s number exists | cold prefill tok/s +≥20 % at 64K; c=2 mixed ITL p95 ≤ 1.5 s at 2048, ≤ 3 s at 4096; head MemAvailable ≥ 4 GiB; needle exact |
| E2 | `DSPARK_ENABLE_SP_INDEXER=1` | TP ranks each score a slice of compressed keys, exact top-k merge | −4 to −8 % TTFT at ≥128K; 0 at ≤32K | new code path in the sparse-attention selector; fail-closed at boot | upstream A/B (one cluster, one day), ruler-lite passed | needle exact at 64K/128K; no decode delta; TTFT at 128K ≤ 0.96× baseline |
| E3 | boot hygiene bundle: extend warmup to cover `_prepare_dflash_inputs_kernel` / `_topk_topp_kernel`; `MAX_NUM_BATCHED_TOKENS` 8192 → 8448 to silence the 8162 advisory; drop the 4 `VLLM_BUILD_*` env vars | removes first-request JIT spike per boot; no steady-state effect | first-request latency after restart only | none | audit log lines | boot gates only |
| E4 | **DONE 2026-09-04** (§9): worker `~/dspark-vision` is a git checkout at the pinned commit; the 4 head-only `patches/` files restored; `patches/` sha-identical on both hosts | provenance for rollback | reliability, not speed | none | audit anomalies 1-2 | byte-identical boot-time hotfix set — verified |
| E5 | `DRAFT_SAMPLE_METHOD=greedy` | draft head argmax instead of sampling | ± few % acceptance; upstream tie | output-distribution change at temp>0 | two upstream A/Bs, tie | accepted/step ≥ baseline at temp 0 and 0.6 |
| — | `DSPARK_ENABLE_REPLICATE_MARKOV=1` | replicated draft head, fewer collectives | none (c=1 flat) | measured regression at c=6 | upstream, twice | do not run |
| — | `DSPARK_ENABLE_ISSUE141_SPARSE_MLA_CHUNK`, `ASSISTANT_FINAL_HOTFIX`, `ISSUE136_XGRAMMAR`, `ISSUE138`, `ISSUE31`, `DEEPGEMM_SM121_ALIAS` | correctness workarounds | none unless the symptom appears | each changes runtime bytes | symptom-gated per upstream | enable only on observed symptom (log watch in §5.3) |
| — | Stage-C runtime image + `VLLM_DSPARK_*` knobs | decode-path kill-switches, Keys concurrency patches | unknown for c=1/1 M-ctx; the 315/205 tok/s headline is a 200K/16-slot profile | local build, "treat first boot as an experiment" | no like-for-like number | research lane only, after E0-E2 |
| — | LMCache (`DSPARK_ENABLE_LMCACHE`) / Phase B NVMe tier | KV persistence beyond the 12 GiB pool | 107K reload 65 s → 1.9 s, but only 0.7 % of requests are in the tail | OOM on cold boot; server death hangs engine | issue #45 decision | re-entry conditions in issue #45 |
| — | TP=3 | +capacity, ~3× KV | c=1 not faster; prefill 4-22 % slower | new node, new link | upstream live numbers | not for this profile |
| — | `gpu-memory-utilization` change | KV vs host headroom | −1/3 KV per −0.035 | prefix-hit loss | arithmetic above | only as a mitigation inside E1 |

Answer to "would enabling DSpark pay off": DSpark is enabled and is already
delivering ≈3.1 tokens per step. Among the *remaining* DSpark options, only E2
has positive evidence and it is small; E1 is not a DSpark feature at all but
is the largest plausible win on this cluster.

## 5. Evaluation system design

### 5.1 Goals and non-goals

Goals: (1) decide config changes on measurements taken in an idle window with
a production-shaped workload, repeated, with correctness guardrails; (2) see
in production telemetry whether an adopted change moved the user-facing KPIs;
(3) run without touching the service beyond sending requests — the operator
performs config changes and restarts by hand per the runbook.

Non-goals: model-quality benchmarking (R3/R4 handle that), multi-model
comparison (`vision_compare.py` handles that), load testing at c>4 (not our
profile).

### 5.2 Components

```
execution/eval/                       (new; reuses primitives from existing scripts)
  workload.py        prompt generators: seeded random-word bodies (3.54 tok/word calibration
                     from d0_probes.py), needle insertion (b2_probe.py pattern), short-chat set,
                     tool-call set, one image probe (vision_compare.py menu image)
  probes.py          streaming client: TTFT, per-token timestamps, usage incl. cached_tokens
                     (from d0_probes.stream_request), idle-window guard, contamination check
  metrics.py         /metrics snapshot + delta (spec_decode_*, prefix_cache_*, ttft/itl histograms,
                     kv_cache_usage, request_success_total); host MemAvailable via ssh `free -b`
  suite.py           the A/B suite (5.4) → tmp/eval/<UTC>-<tag>/{manifest.json, metrics_before.txt,
                     metrics_after.txt, results.jsonl, hosts.jsonl, report.md}
  compare.py         two run dirs → side-by-side table with median/min/max and gate verdicts
  scrape.sh          60 s /metrics scraper (runs on the VPS relay host, appends JSONL, daily rotate)
  daily_report.py    production KPIs per day from the scrape: TTFT by bucket, decode tok/s,
                     acceptance, prefix hit, tail counts, error/preemption counts
  loghealth.sh       symptom watch (read-only docker logs grep): DSML markup loops, grammar
                     tokens after termination, sparse-MLA stall signature, JIT-in-inference,
                     NCCL/CUDA/OOM — feeds the "enable only on symptom" flags
```

Existing scripts stay as they are. What is reusable and from where (per the
tooling inventory of 2026-09-04):

| Need | Existing base | Note |
| --- | --- | --- |
| streaming TTFT + per-token timing + `cached_tokens` | `execution/kv-offload-d0/d0_probes.py::stream_request` | already SSE with `include_usage` |
| seeded random-word bodies, 3.54 tok/word | `d0_probes.py::rand_words`, `execution/kv-offload-phase-b/b2_probe.py` | needle marker pattern in `b2_probe` |
| `/metrics` before/after delta incl. acceptance | `planning/01-raw/upstream-dspark/benchmarks/keys-concurrency/bench_concurrent.py::metrics` (acceptance = Δaccepted/Δdraft; concurrency sweep in `run_round`) and `run-hermes-private-ds-cron-rerun.sh::write_server_delta` | both target old endpoints/model names; port, do not run as-is; verify metric names on 0.25.2 (they match the live snapshot) |
| repeats + median summary | `execution/benchmarks/vision_compare.py::summarize_trials` | also the menu-image probe and its 47-field scorer |
| cold prefill cells (24.9K / 77.8K, `max_tokens=1` wall time) | `execution/benchmarks/bench_full.py::run_prefill` | non-streaming, pinned to the old fork's tags; the cell idea carries over, the script does not |
| real-task A/B with `/metrics` bracketing | `execution/benchmarks/run-hermes-real-tasks-ab.sh` | keep as the "real agent workload" complement to the synthetic suite (run it once per adopted change, not per treatment) |

`soak.py`/`correctness.py`/`agent_sanity_bench.py` are old-stack pinned,
non-streaming and metric-blind; they are superseded for this purpose.

### 5.3 Workload specification (mirrors §2)

| Block | Prompts | Purpose | Repeats |
| --- | --- | --- | --- |
| S — short chat | 8 prompts, 200-900 tokens, `max_tokens` 400, temp 0 and 0.6, thinking low (production default) | c=1 decode tok/s, acceptance on natural prose | 3 each |
| M — medium | 2 × 8K random-word bodies with a question, `max_tokens` 256 | TTFT warm/cold at 8K, decode at moderate context | 3 |
| L/XL — cold prefill | fresh-seed bodies at 32K, 64K, 128K tokens, `max_tokens` 8 | cold TTFT → prefill tok/s; then byte-identical repeat → warm TTFT (prefix-cache function) | 3 cold seeds each, 1 warm repeat |
| N — needle | 64K and 128K bodies with a marker mid-prompt, temp 0, `max_tokens` 256 (thinking stays at the production default, so the marker may be quoted inside reasoning; both count) | correctness veto (exact marker quote) | 2 |
| C — concurrency | c=2 and c=4 of block-S prompts; and "mixed": one 64K cold prefill started 2 s after a c=1 decode stream | aggregate tok/s, per-stream spread, decode ITL p95 during a long prefill (the E1 fairness gate) | 2 |
| T — tool calls | 6 harness-style prompts with a JSON tool schema, `tool_choice` auto | tool-call JSON validity, reasoning tags parse | 1 |
| V — vision | the 1209×853 menu image with the production prompt and schema | 47-field score must not regress; exercises encoder + mm hashing | 1 |

Total wall time ≈ 25-35 min per run on this stack (dominated by the cold
128K prefills; the dry-run plan is 82 requests, ≈1.4 M prompt tokens). Every
probe records `num_requests_running` before and after; a sample with foreign
traffic (before > own concurrency, or after > 0) is marked `contaminated`
and re-run once — cold probes (L, N) with a fresh seed, since the same body
would hit the prefix cache. KPIs exclude contaminated samples; gates keep
them.

Harness status 2026-09-04: implemented in `execution/eval/` (Sonnet build,
lead review, 37 offline tests passing). Live smoke check with two short
requests confirmed the SSE fields and the `/metrics` acceptance delta parse
on vLLM 0.25.2 (one 200-token counting request: 46 draft steps, 153/276
accepted, 3.33 accepted per step, 55 tok/s client-side). Local `.env.eval`
(gitignored) points at the head, the two ssh aliases and the real menu photo
under `tmp/`. Ready for E0 in an idle window: `python3 execution/eval/suite.py
--tag baseline`.

### 5.4 KPIs and gates

Primary (decide adoption):
- `decode_c1_tok_s` — median over block S (temp 0), tokens per second from
  first token to last token (excludes TTFT).
- `prefill_cold_tok_s@{32K,64K,128K}` — prompt tokens ÷ cold TTFT, median of 3
  fresh seeds.
- `ttft_warm@{8K,64K}` — repeat of an identical prompt; must show
  `cached_tokens ≥ 0.9 × prompt_tokens`.

Secondary (explain, do not decide): accepted tokens per step and per-position
acceptance from the `/metrics` delta; c=2/c=4 aggregate tok/s and max/min
per-stream ratio; ITL p95 of the decode stream during the mixed probe; boot
time; KV GiB per rank and `kv_cache_size_tokens`; head/worker `MemAvailable`
min during the run.

Gates (any failure = reject the change):
- needle exact at 64K and 128K; tool-call JSON valid 6/6; vision score ≥
  baseline − 2 fields; no `finish_reason` missing; no ERROR/Traceback/NCCL/CUDA
  lines added to either rank's log; head `MemAvailable` ≥ 4 GiB at all samples;
  warm TTFT at 64K ≤ 2 s (prefix cache intact).

Decision rule: adopt if the targeted primary KPI improves by ≥ 5 % (decode) or
≥ 10 % (prefill at the targeted bucket) with the three repeats' ranges not
overlapping the baseline's, and no other primary KPI regresses by > 3 %.
Otherwise revert the boot. Record every run in
`planning/03-core/11-gb10-config-ab-ledger.md` (new): date, tag, `.env` diff,
verdict, run dir.

### 5.5 Run protocol (per treatment)

1. Idle window confirmed by rule (`num_requests_running == 0`, and
   `generation_tokens_total` static across two polls ≥ 60 s apart); announce
   the maintenance window through the existing channel.
2. `suite.py --tag baseline` on the running boot (E0 is just this step).
3. Operator: back up `.env.dspark` → edit exactly one flag → `stop` → `start`
   (recreate) on both ranks → boot gates (both ranks healthy, KV GiB within
   ±0.2 of baseline unless the change is expected to move it, no new warning
   types, MemAvailable) → 3 min settle → one warm-up request per block.
4. `suite.py --tag <treatment>`; `compare.py <baseline-dir> <treatment-dir>`.
5. Keep or revert per §5.4; either way re-run block S once after the decision
   as the drift check for the boot that stays.

Idle-window budget: boot ≈ 5 min + settle 3 min + suite 30 min → ≈ 40 min per
treatment, ≈ 75 min for baseline + one treatment + revert. All windows so far
have been found in the local night (traffic in §2 is trickle after ~23:00Z).

### 5.6 Production KPI telemetry

`scrape.sh` on the VPS relay host (`curl 127.0.0.1:18890/metrics` every 60 s
→ `metrics/<date>.jsonl`, rotated daily, pulled into `tmp/eval/scrape/`).
`daily_report.py` turns counter deltas into: requests/day by prompt bucket,
TTFT histogram and the >10 s / >30 s tail counts, decode tok/s (from
`inter_token_latency` and accepted/step), acceptance per position, prefix-hit
ratio, `kv_cache_usage_perc` max, preemptions, errors, boot events (counter
resets). The report before/after an adopted change is the real-world
confirmation the A/B cannot give. Adding the cron on the VPS is a small change
to a host we already use as a relay; it needs the lead's OK (AGENTS.md treats
host services as user workloads).

### 5.7 Correctness guardrails (why they are not optional)

Three of the candidates change attention-selector or scheduler code paths
(E1 adaptive variant, E2, Stage-C). The failure mode is silent (wrong tokens,
truncated streams, grammar tokens after termination), not a crash, and the
draft/verify loop can mask small divergences. The needle, tool-call and
vision blocks are the veto; `loghealth.sh` is the ongoing watch that also
tells us when a symptom-gated hotfix has become justified.

### 5.8 Effort

Harness (workload/probes/metrics/suite/compare): ~1 day, mostly lifting
`d0_probes.stream_request`, `b2_probe` needle generation and
`vision_compare` menu scoring into one package; scraper + daily report: ~½ day;
ledger + runbook text: ~½ day. Suitable for a Sonnet implementation pass with
lead review; the production runs need the operator and an idle window.

## 6. Proposed first campaign

| Step | Window | What | Success looks like |
| --- | --- | --- | --- |
| E0 | 1 × 35 min, no restart | baseline suite on the current boot | numbers for cold prefill tok/s at 32/64/128K, c=1 decode, acceptance, MemAvailable; the doc's estimates in §3 confirmed or corrected |
| E1a | 1 × 40 min | `LONG_PREFILL_TOKEN_THRESHOLD=2048` | ≥ +20 % cold prefill at 64K, mixed-probe ITL p95 ≤ 1.5 s, MemAvailable ≥ 4 GiB |
| E1b | 1 × 40 min (only if E1a passed) | `4096`, then upstream adaptive chunk if 4096 passes | as above with ITL p95 ≤ 3 s for the static value; adaptive must hold ITL p95 ≤ baseline + 0.3 s and MemAvailable ≥ 4 GiB — this is the gate upstream failed |
| E2 | 1 × 40 min | `DSPARK_ENABLE_SP_INDEXER=1` on top of the E1 winner | TTFT at 128K ≤ 0.96× E1 result, needle exact, decode unchanged |
| E3/E4 | fold into the E2 boot | warmup shapes, batched-tokens advisory, env noise; worker git checkout | boot log clean of the three warning types; `git status` clean on both hosts |

Expected outcome if §3 holds: TTFT for the 10K-200K bucket down 30-50 %, XL
tail (40-80 s) into the 20-40 s bucket, no change to short-chat behaviour. If
E0 shows cold prefill already ≥ 3,000 tok/s at 64K the weight-read theory is
wrong and E1 is dropped after one boot.

## 7. Deferred / not recommended

Replicated Markov head (measured regression), TP=3 (capacity lever, c=1 not
faster, prefill slower), Stage-C runtime (no like-for-like evidence; research
lane after the harness exists), LMCache and Phase B NVMe tier (issue #45
re-entry conditions), `gpu-memory-utilization` changes (KV is the only
elastic term), symptom-gated hotfixes (enable on observed symptom via
`loghealth.sh`).

## 8. Open questions for the lead

1. OK to add the 60 s `/metrics` scraper cron on the VPS relay host?
2. Idle-window policy for E0-E2: local night, one treatment per night, or a
   single longer window?
3. ~~Should the harness live under `execution/eval/` (new) or extend
   `execution/benchmarks/`?~~ — approved: `execution/eval/` (new).
4. ~~Whether the worker host's `~/dspark-vision` may be converted to a git
   checkout.~~ — approved and done (§9).

## 9. E4 execution record (2026-09-04, worker `~/dspark-vision`)

Finding before the change: the worker directory was a *deployment subset*
of the pinned commit, not a divergent copy — every file present
(`docker-compose.dspark.yml`, `patches/*` 30 files, `recipe/…`) was
byte-identical to `d828ddd`; 155 of the commit's 192 tracked files were
simply absent (docs, scripts, `recipe/overlay`, the 4 head-only `patches/`
files). `.env.dspark` is gitignored upstream and was never a candidate.

Procedure (no existing file modified; container stayed `running healthy`
throughout; every step reversible by `rm -rf .git` + deleting the added
files):

1. `git init -b main`, `git remote add origin <upstream>`, `git fetch
   --depth 80 origin main` (GitHub reachable from the worker; `d828ddd` is
   on `main`).
2. `git reset --mixed d828ddd` — sets HEAD/index to the pin, working tree
   untouched. `git status` then reported **zero modified files**, only
   missing ones, which is the drift result.
3. `git checkout d828ddd -- .gitignore`, then restored all missing tracked
   files except `vllm_patch_gb10/` (see residual).
4. Verified `patches/` parity: identical sha256 over the sorted file list
   and contents on both hosts (`19b74d3f…da1`). Boot-time hotfix set
   unchanged (the 4 restored `patches/` files are not in the compose
   hotfix chain).

Residual: `vllm_patch_gb10/` on the worker is an empty root-owned
directory that Docker created as a bind-mount source; the 5 tracked files
under it show as `D` in `git status`. It is unused on both ranks
(`ENABLE_VLLM_GB10_PATCH` defaults to 0; the compose only `pip install -e`
it when set to 1, and `import vllm_gb10_hybrid_nvfp4` fails inside both
containers). Fixing the ownership needs sudo, which is out of scope;
left as-is and recorded here. `artifacts/` is untracked on both hosts.

Audit anomalies 1 and 2 (`2026-09-04-gb10-cluster-audit.md`) are closed by
this record.
