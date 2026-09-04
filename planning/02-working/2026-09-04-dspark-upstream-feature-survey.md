# Upstream DSpark feature survey (2026-09-04)

Source: shallow clone of `MiaAI-Lab/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark`
(`tmp/upstream-miaai-dspark`, depth 50, HEAD `c444d70`). Our production pin is
`d828ddd` — 13 commits behind HEAD, all from 2026-09-02/03. Cross-referenced
against our live config: `tmp/dspark-vision-live/.env.dspark` and
`docker-compose.dspark.yml`.

## Verdict table

| Feature | Expected gain for our profile | Risk | Evidence quality | Recommend? |
|---|---|---|---|---|
| `MTP_NUM_TOKENS=6`, `DRAFT_SAMPLE_METHOD=probabilistic` (current) | n/a — already optimal per upstream A/B | none | good (2 independent A/Bs) | keep as-is |
| Capture size padded to multiple of 8 (`(seqs*(k+1)+7)/8*8`) | already applied in our compose | none | good (measured +12% c=6) | already have it |
| `DSPARK_MAX_INFLIGHT_PREFILLS=2` (current) | already applied | low | good (A/B, 2026-09-02/03) | already have it |
| `DSPARK_ENABLE_SP_INDEXER=1` | −4 to −8% TTFT at ≥128K prompts, no change at ≤32K/decode | low (fail-closed, ruler-lite passed) | medium (one cluster, one A/B day) | **yes** — try, given our 20K–200K prompt tail |
| `DSPARK_ENABLE_DEEPGEMM_SM121_ALIAS=1` | prevents a boot-time hard failure, not a perf win | low if the failure mode is real; no-op if not | low (contingent on JIT-cache state) | **later** — only if first-boot logs show the `sm121_fp8_mqa_logits` JIT-cache miss (see Uncertainties) |
| `DSPARK_ENABLE_REPLICATE_MARKOV=1` | none (upstream measured c=6 aggregate 122 vs 148, a **regression**; c=1 flat) | low but pointless | good (2 A/Bs, consistent) | no |
| `DSPARK_ENABLE_ADAPTIVE_CHUNK=1` | none measured (never got past the gate) | host MemAvailable fell to ~2.3 GB (owner-less) | low | no |
| `DSPARK_ENABLE_ISSUE141_SPARSE_MLA_CHUNK=1` | mitigates a stochastic TP=2 sparse-MLA stall (silent stream truncation, not a crash) | low switch cost, but the underlying defect is unroot-caused and the fix is a workaround | low-medium (n=1 A/B pair) | **later** — enable only if/when we see the symptom (frozen batch, missing `finish_reason`, no OOM/NCCL error) |
| `DSPARK_ENABLE_ASSISTANT_FINAL_HOTFIX=1` | fixes a real failure class (trailing-assistant-turn dead state → DSML markup loop) for agent harnesses (Hermes/OpenClaw-style) | medium — only one live causal A/B exists, "no rescue claim," and one gated-ON boot already failed closed once (bug, since fixed) | low-medium | **later** — watch our own logs for the symptom before enabling |
| `DSPARK_ENABLE_ISSUE138_RESPONSES_HISTORY_COMPAT=1` | fixes a narrow Responses-API replay shape (type-less assistant `output_text`) | low, fail-closed, narrow scope | medium (offline + live verifier exist) | only if a specific client needs it |
| `DSPARK_ENABLE_ISSUE136_XGRAMMAR_HOTFIX=1` | fixes XGrammar accepting spec-decoded tokens after grammar termination (tool-call / strict-JSON correctness) | low switch cost but **"do not claim the live incident closed"** per upstream — no live canary evidence checked in yet | low (CPU/source-exact only) | **later** — worth the live canary if we use strict tool-calling with speculation |
| `DSPARK_ENABLE_ISSUE31_GPU_HOTFIX=1` | only matters if clients send `thinking_token_budget` explicitly | default-on omit-field traffic can hit a decode cliff (per the flag's own doc) | none found (no A/B numbers in this checkout) | no, unless a client actually sends the field |
| `DSPARK_ENABLE_LMCACHE=1` | ~1.8–1.9s reload of a 107K-token context vs ~65s re-prefill (persistent KV across restarts) | **high** — confirmed OOM-killed cache server on cold boot (128 GB unified memory), and a cache server dying mid-serve silently hangs the engine (not graceful) | medium (n=2 measured, but explicitly "experimental," failure paths not hardened) | no — only for an owner who accepts full-pair-restart risk |
| Stage-C runtime image | unlocks Keys concurrency patches / `VLLM_DSPARK_*` kill-switches; only proven number is 315/205 tok/s at 200K-ctx/16-slot, a different profile than ours | Compose is Anemll-shaped even under Stage-C; README says "treat the first Stage-C boot as an experiment"; upstream's own default stays on Anemll 0.1.1 | low-medium for our profile (headline numbers are for a different config) | no for production; maybe for isolated research |
| TP=3 (`start-tp3.sh`) | +capacity (16 slots, ~3x KV, ~200 tok/s aggregate @ c=16) | c=1 does **not** get faster (fixed per-step costs dominate once bytes/rank shrink) and prefill costs 4–13% up to 64K, ~22% at 128K–256K | good (live measured on this exact stack) | no — our profile isn't capacity-bound; 2-node TP=2 is better for our long-context tail |
| Newer `dspark-vllm-gx10` image tag | none available | n/a | `v0.1.1` is still the only tag on `Anemll/dspark-vllm-gx10` as of 2026-09-04 | n/a |

---

## 1. What "DSpark" is, and whether our acceptance numbers are in line

DSpark speculative decoding on this checkpoint has three moving parts, all
checkpoint-native (not a bolt-on draft model):

- **MTP/NextN layers**: Vision-Exp ships `num_nextn_predict_layers=3` (vs
  0731's `n_predict=1`). `MTP_NUM_TOKENS` (the draft depth, `k`) must be both
  `>= dspark_block_size` (checkpoint constant, 5) **and divisible by 3**, so
  the only valid small values are 6, 9, 12… (`.env.dspark:402-408`,
  `docker-compose.dspark.yml:401` capture-size formula). `k<5` silently
  truncates draft blocks on this vLLM build.
- **DSpark Markov head** (`DSparkMarkovHead` in
  `vllm/model_executor/models/qwen3_dspark.py`, shared by the DSV4 draft path
  in `models/deepseek_v4/nvidia/dspark.py`): a sequential 6-step loop that
  projects hidden states through `markov_w1` (`VocabParallelEmbedding`) and
  `markov_w2` (`ParallelLMHead`) to produce each draft step's logits. Stock
  Anemll 0.1.1 TP-shards both matrices, costing 12 serialized collectives per
  decode step (`patches/hotfix-dsv4-replicate-markov-head.py:1-13`;
  `docs/CLAUDE/fable5-1-report.md` finding #4).
- **Lightning indexer** (`sparse_attn_indexer.py`, replicated `wq_b` /
  `weights_proj`): scores compressed context for sparse-MLA top-k selection.
  Not part of the draft loop itself, but shares the prefill critical path at
  long context (`docs/PATCHES.md` "Item 6").
- `draft_sample_method` (`probabilistic` vs `greedy`) only changes how the
  draft head's logits are sampled; it's consumed by `--speculative-config`,
  not a vLLM env key.

**Acceptance numbers found upstream** (all pos0…pos5, i.e. draft position 1–6):

| Source | Prompt type | pos0…pos5 (approx.) | Implied mean accepted /6 |
|---|---|---|---|
| `fable5-1-report.md` live TP=3 probe, `bench-miaai.py` | short synthetic (256-token) | 92/74/60/41/28/21% | ≈3.2 (report states ≈3.9 from raw accepted/drafted counts, a different denominator) |
| `ab-results-2026-09-02.md`, numbered-word bench | synthetic | 90–96% pos0, ~47–51% overall | higher, not fully decomposed |
| `ab-results-2026-09-02/03.md`, natural-prose bench (8 everyday prompts) | **closest to our chat traffic** | pos0 **0.66–0.71**, overall 24.7–27% | ≈1.5–1.8 |

Our production metric — pos0…pos5 = 76/54/36/23/14/8%, mean **2.1/6** accepted
— sits **between** upstream's natural-prose live number (pos0 ~0.68, lower)
and its short-synthetic bench (pos0 ~0.92, higher). That is consistent with a
traffic mix of mostly short chat (natural-prose-like, pushing acceptance down)
plus some long/structured prompts (pushing it up), and matches upstream's own
observation that "the natural-prose acceptance … is a pre-existing
live-vs-audit gap, not a regression" and "the largest decode lever on the
lane" (`ab-results-2026-09-02.md` line 34). **Nothing here indicates a
misconfiguration on our side** — pos0=76% is a plausible number for our exact
draft config, not an outlier.

**Does upstream recommend a different `k` or drafting method for our
profile?** No.
- `greedy` vs `probabilistic`: A/B'd twice (2026-09-02 Phase-2 #12,
  2026-09-03 row D) — tie both times ("keep only if ≥ base2 at both
  temperatures; any drop ⇒ revert"; a small temp-0.6 dip reverted it).
  `probabilistic` (our current setting) stays the shipped default.
- `k>6`: not tested past 6 on this image; the same report explicitly says
  raising it is "not worth chasing" because per-position acceptance at
  positions 5–6 is already 0.28/0.21 (fast-decaying tail, so extra draft
  depth buys little and costs cudagraph/KV-store footprint). `k=3` (one MTP
  round) is rejected by the launcher's divisibility check.
- Official model cards pair `greedy` with `k=7`, but that fails Vision-Exp's
  `k % 3 == 0` check, so it doesn't apply to our checkpoint at all.

## 2. Stage-C runtime image

Stage-C (`vllm-dspark-runtime:dspark-nvfp4-stage-c`) is a **locally built**
overlay, not a published image: `./build-dspark-vllm-runtime.sh` chains
`recipe/Dockerfile.dspark-runtime-overlay` → `recipe/nvfp4/Dockerfile.stage-a`
→ `Dockerfile.stage-b` → (implied) `stage-c`, layering DSpark overlay
patches + an NVFP4 KV path onto a base image. It registers the
`VLLM_DSPARK_*` / `VLLM_DSV4_*` knobs (confidence threshold/scheduler, local
argmax, fused Markov argmax, GPU-rejected-context mask, compressed MLA,
deferred target-graph capture, B12X W4A16 tensor-core decode,
`DSPARK_SLOT_CLAMP`) that are **silently ignored** ("Unknown vLLM
environment variable detected") on Anemll 0.1.1 (`docs/ENVS.md` full matrix).

**Measured numbers** (`README.md` "Optional: Stage-C / 200K-16",
`results/RESULTS-2026-08-14.md`):

| Profile | Config | Headline |
|---|---|---|
| Keep 1M/6 | same context ceiling as ours, Keys mask on | ~182 tok/s aggregate, short-prompt microbench |
| High aggregate | `MAX_MODEL_LEN=200000`, `MAX_NUM_SEQS=16` | 315 tok/s static / 205 tok/s staggered |

Neither number is directly comparable to our 1M-ceiling / 6-slot profile —
the second (headline) number trades away 5x context length for concurrency.
No decode-tok/s-at-c=1-vs-c=6 or TTFT A/B **against Anemll 0.1.1 on identical
config** was found in this checkout; the comparison that exists is
config-vs-config, not image-vs-image at fixed config.

**Why upstream stays on Anemll by default**: (1) issue #27's
`LONG_PREFILL_TOKEN_THRESHOLD` still serializes huge cold prefills under
Stage-C too — "Stage-C does not turn 6×128K into six parallel 80s reads;" (2)
compose remains Anemll-shaped even for Stage-C (`/usr/local/bin/vllm`,
hotfixes under `/usr/local/lib/...`), so the README explicitly calls the first
Stage-C boot "an experiment," not a supported path; (3) it's a local build
(`build-dspark-vllm-runtime.sh`), so it doesn't get the digest-pin
reproducibility of the published Anemll tag.

## 3. Optional flags — one line each

See the verdict table above for purpose/risk/default/recommendation per flag;
key sourcing: `docs/ENVS.md` (env matrix), `docs/PATCHES.md` (per-issue
detail sections), `docs/CLAUDE/ab-results-2026-09-02.md` and
`ab-results-2026-09-03.md` (A/B numbers), `lmcache/README.md` (LMCache).
All ten `DSPARK_ENABLE_*` flags default to `0` upstream, matching our `.env`.
LMCache is a separate opt-in subsystem (`lmcache/`), not wired into the main
compose file at all; enabling it requires `patch-compose-lmcache.py` to
generate a derived compose file and standing up per-node
`lmcache server` containers outside Compose supervision.

## 4. What changed after our pin (`d828ddd..HEAD`, 13 commits, all 2026-09-02/03)

All content commits (the rest are merge-conflict-resolution noise from
integrating three PRs):

- **`9978275`** (correctness/ops): `.env.dspark.example` shipped
  `DEFAULT_THINKING=max` while compose defaults to `low` — anyone following
  the documented copy-paste setup got 3x latency (measured 3.4s vs 10.6s for
  a 12K-token request) silently. **Our live `.env.dspark` already has
  `DEFAULT_THINKING=low`**, so we're unaffected, but it confirms `low` is the
  intended default, not an oversight.
- **`9b15977`** (compat feature): opt-in Codex `agent_message` Responses
  compatibility (`DSPARK_ENABLE_CODEX_AGENT_MESSAGE_COMPAT`, default 0) —
  fixes a 400 loop when a Codex sub-agent turn appends a private
  `agent_message` item the Responses validator doesn't recognize. Relevant
  only if we serve Codex-style multi-agent traffic through the Responses API.
- **`def52a2`** (test/ops): "select one model alias for startup probes" — a
  fix to which `SERVED_MODEL_NAME` alias the launcher's own startup
  probe/warmup requests use when multiple space-separated aliases are
  configured. Launcher-only, not a serving behavior change.

No performance-tuning commit for TP=2 GB10 or Vision-Exp specifically exists
in this 13-commit window — the two performance-flavored artifacts
(`fable5-1-report.md`, the two `ab-results-*.md` files, `item8-fp4-kv-design.md`)
are all **already present at `d828ddd`** (their internal dates, 2026-09-02,
predate or coincide with our pin), so we already have their full content; they
are analysis/design docs rather than shipped code changes, and none of their
recommended patches (replicated Markov head, adaptive chunk, SP indexer, TC
decode) have landed as new defaults upstream since.

## 5. Newer image tags

`Anemll/dspark-vllm-gx10` (checked via `gh api repos/Anemll/dspark-vllm-gx10/tags`
and `/releases`, 2026-09-04): **`v0.1.1` is the only tag**, released
2026-07-15, source commit `47503f8e38dadd4dededca798150db2619594fce`, same
digest we're pinned to
(`sha256:a83948492cf13df455170fb42885f5ef4db54fefe0feff0f841ecbff464ac9d8`).
Its release notes describe moving B12X route-pack Triton compilation to model
startup (before cudagraph capture) to fix a long-prefill JIT crash — already
in the image we run. No `v0.1.2`/`v0.2.0` exists. The MiaAI-Lab checkout's own
`README.md`/`.env.dspark.example` still default to this same tag, i.e.
upstream has **not** moved its image pin either. `docs/ENVS.md` notes the env
audit was done "at image tag `0.1.1`" and to "re-check after image bumps" —
there have been none to re-check against.

## 6. TP=3 / 3-node option

`./start-tp3.sh` is a separate launcher (a stray `TP_SIZE=3` in `.env.dspark`
cannot silently activate it) that adds a third DGX Spark for **capacity, not
speed**: 16 concurrent slots, ~3x the KV pool (~35 GiB/rank, ~5M cached
tokens), ~200 tok/s aggregate at c=16, and slightly faster per-stream decode
at high concurrency — at the cost of prefill latency (4–13% slower up to 64K,
~22% slower at 128K–256K, because MLA replicates the full latent KV and
indexer per rank regardless of TP size, so attention work doesn't shrink with
a third GPU while the three-node all-reduce and head-count padding add
overhead). It requires passwordless SSH to the third node, the pinned image
pre-pulled there, a dedicated ConnectX `/24` link from the head, and a shared
LAN interface for Gloo/NCCL-socket/TP bootstrap (default `enP7s7`, explicitly
not `lo`). Upstream's own measurement on this exact TP=3 lane found c=1
**did not get faster than TP=2** (fixed per-step costs, not bandwidth,
dominate once bytes/rank shrink), so it's a concurrency lever, not a latency
one — not a good fit for our "mostly short chat" profile unless concurrent
user count becomes the binding constraint.

## Uncertainties

- Whether the DeepGEMM `sm121_fp8_mqa_logits` JIT-cache-miss failure mode
  actually reproduces on our fresh Vision-Exp JIT cache is unverified from
  this static read; it depends on live first-boot logs on our two nodes; our
  own `.env.dspark` comments already flag this as a W1 watch item.
- The 2.1/6 mean-accepted comparison in §1 reconstructs upstream's implied
  "mean accepted tokens" from published per-position percentages (summing
  marginal reach probabilities); upstream does not publish one clean
  apples-to-apples number for a mixed short-chat + long-prompt traffic
  profile like ours, so the "in line" conclusion is an interpolation between
  two different upstream benchmarks, not a direct match.
- The assistant-final-turn hotfix (issue #52/#120) and the issue #136
  XGrammar hotfix both have real fix rationale but **no confirmed live
  reproduction on our traffic** — upstream's own docs say not to claim
  either incident "closed" without a live canary, so recommending them is
  contingent on us first observing the symptom (DSML markup loop; grammar
  tokens surviving termination) in our own logs.
- LMCache's OOM risk sizing (`LMCACHE_L1_GB`, `LMCACHE_OOM_SCORE_ADJ`) is not
  characterized for our specific host memory profile; upstream's own
  "confirmed unified-memory cold-boot OOM" report was on a 128 GB node, which
  is close to ours, but no safe sizing recipe is given.
- Issue #141 (sparse-MLA stochastic stall) evidence is explicitly "one
  reporting pair," with "the second failing pair has not repeated that A/B" —
  its applicability to our exact traffic/config is not established either way.
- Could not directly A/B Stage-C vs Anemll 0.1.1 at a fixed config from this
  checkout alone; the two published Stage-C numbers use a different
  context/concurrency profile than ours, so the comparison in §2 is
  necessarily indirect.
