# DeepSeek-V4-Flash-Vision-Exp 2×GB10 Bring-up Plan (2026-09-03, rev 2)

Status: **COMPLETE — CUTOVER DONE 2026-09-03 ~02:30Z.** All gates G1–G5
passed in a single window (00:53Z–02:30Z); vision-exp is the gb10-cluster
default. Results: `2026-09-03-vision-exp-w1-w2-results.md`. W1/W2/W3 were
run consecutively in one window (stack was already serving live traffic
cleanly after W1, so closing/reopening windows would have added 3 boot
cycles of risk for no information gain).

Decision (user, 2026-09-03): deploy the **MiaAI-Lab recipe**
<https://github.com/MiaAI-Lab/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark>
on gb10 + gb10-2. Keep the production **served model name
(`deepseek-v4-flash-0731`) and vLLM port (8890)** so cutover is a
drop-in for every client. Benchmarks pass ⇒ vision-exp becomes the
default inference model on the gb10 cluster (cutover pre-authorized by
the user). Execution delegated to sonnet; idle-window ops and gate
verdicts stay with the lead session.

## Why this recipe (vs the old tonyd2wild draft)

- Purpose-built for the official `deepseek-ai/DeepSeek-V4-Flash-Vision-Exp`
  checkpoint on 2×DGX Spark: Anemll `ghcr.io/anemll/dspark-vllm-gx10:0.1.1`
  (vLLM 0.25.2.dev0+g752a3a504), TP=2 nnodes=2, `nvfp4_ds_mla` KV,
  DSpark k=6 (Vision-Exp n_predict=3 ⇒ k ≥5 and divisible by 3).
- Vision = fail-closed startup hotfix (`patches/vision_exp/`): ViT +
  Aligner from the checkpoint, OpenAI `image_url`, images on `user`
  turns only, cap 8/prompt, no video.
- The 2026-09-02 update the user quoted = `DSPARK_MAX_INFLIGHT_PREFILLS=2`
  default (4×8K wave TTFT spread 9.1 s vs 14.6 s, +12 % aggregate,
  worst stream −2.8 s) + cudagraph capture 48 (vs 42; +12 % at c=6) +
  NCCL GID auto validation fix.
- **TP=3 lane (`start-tp3.sh`) needs a third Spark (`WORKER2_HOST`) —
  not applicable to our 2-node cluster.** Default 2-node lane only.
- Expected on this stack (their 2×GB10, 2026-09-02 live): c=1 ≈56 tok/s
  (51–67), c=6 ≈139 aggregate, 128K TTFT ≈78.5 s, KV pool 17.04 GiB /
  2.33 M tokens @ util 0.835. Our 0731 production baseline: 55.4 mean /
  66.1 peak structured, prefill 1744–1772 tok/s (64K cold), ~104 GiB
  resident/host. Parity is plausible out of the box.

## Verified cluster facts (2026-09-03)

- Production: name `deepseek-v4-flash-0731`, port **8890**
  (`~/gb10-ds4/execution/docker-compose*.yml`); portal `local-portal-gu`
  occupies **8888** on gb10 ⇒ recipe default port must be overridden.
- earlyoom: inactive on gb10 (recipe requirement).
- HF cache on gb10 has Vision-Exp snapshots `31ea1118…` and `6821d6ad…`
  (refs/main → 6821d6ad); **recipe pin is `86f746b3…` — neither local
  snapshot matches.** The vision/encoding patchers are exact-source-locked
  (fail-closed at boot on drift), so revision reconciliation is a W0
  gate: fetch the pin delta, or justify repinning with evidence.
- Weights: official Vision-Exp 157 GiB on gb10; worker (gb10-2) cache
  state unknown → W0 decides local copy (rsync over CX link) vs
  `DSPARK_WORKER_HF_NFS=1`.

## Prior-optimization disposition (our repo issues/PRs)

| Ours | Disposition on the new stack |
| --- | --- |
| PR #38 `--long-prefill-token-threshold 6144` | **Do not port.** Recipe covers the same starvation problem better on identical HW: threshold 1024 + issue-#27 hotfix + `DSPARK_MAX_INFLIGHT_PREFILLS=2` (their A/B rejected 2048: −1.5 GB head RAM). |
| PR #33 `--enable-prompt-tokens-details` | Port if Anemll 0.1.1 supports the flag (W0 checks the image's arg parser); portal uses cache-hit metrics. |
| Thinking-on production contract | Map to `DEFAULT_THINKING` (recipe default `max`); W0 extracts the full production vLLM flag list and produces a flag-mapping table. |
| Issue #45 Phase B NVMe KV tier | **Defer & re-port onto the Anemll stack after cutover** (matches the #45 verdict: 70–80 % < 95 % on the old stack; the old-stack campaign is dead). |
| PR #8 eugr-pr200 config | Skip — recipe ships its own v0.27 backport set. |
| RoCE GID pitfall | Covered: recipe `NCCL_IB_GID_AUTO=1` now validates sysfs GIDs per HCA (2026-09-02 fix). Keep auto. |

## Gates (deployment-acceptance contract, AGENTS.md)

G1 boot: single TP2 pair, model id `deepseek-v4-flash-0731` on :8890,
   protected services untouched (lexdata on worker; trading + qwen
   proxy + portal on head), head MemAvailable ≥ 4 GiB after boot.
G2 correctness: temp-0 text needles deterministic + sane; vision probe
   set (caption + OCR + chart) correct via direct :8890; thinking
   contract per portal expectations; images rejected outside `user`
   role (recipe behavior, documented).
G3 performance: c=1 decode ≥ 50 tok/s (baseline −10 %); c=6 aggregate
   ≥ 125; 64K cold prefill within −15 % of 1744 tok/s; TTFT sane.
G4 stability: ≥ 40 min mixed text+vision soak, zero failed requests,
   no NVRM/NCCL/CUDA/OOM, RoCE steady.
G5 cutover: same port + same model name ⇒ zero client change; old
   production compose kept byte-exact as instant rollback
   (`run-private-ds-production.sh` path preserved).

## Phases

W0 (sonnet S1, no GPU, production untouched) — readiness:
   clone recipe to gb10 `~/dspark-vision/`; write `.env.dspark` from
   production fabric values (+ `VLLM_PORT=8890`,
   `SERVED_MODEL_NAME=deepseek-v4-flash-0731`); reconcile checkpoint
   revision vs pin `86f746b3…`; pull Anemll image both nodes (~19 GB,
   disk-checked); decide worker weights path; run `scripts/ci-validate.sh`;
   flag-mapping table (production args → recipe knobs); readiness brief.
W1 (lead opens idle window, ~1 h) — smoke: stop production →
   `./start-deepseek-v4-flash-dspark.sh` → G1 + minimal G2 (needle +
   one image) → capture KV/memory → stop → restore production.
W2 (idle window, ~2 h) — tune + bench: recipe defaults first;
   knobs only if G1/G3 miss (`GPU_MEMORY_UTILIZATION_TEXT` 0.835 vs
   co-tenant ceiling; `MAX_NUM_BATCHED_TOKENS`; `DEFAULT_THINKING`).
   Bench via recipe `scripts/benchmark-0731.py` + `ab-measure.sh` +
   our acceptance probes. G2/G3 full.
W3 — G4 soak + cutover (pre-authorized): vision stack becomes the
   default service; old compose kept as rollback; update runbook +
   issue; post-cutover NVMe-tier re-port becomes the next campaign.

Idle-window discipline unchanged (Phase B runbook): idle = zero running
requests AND static generation counter across 2 polls ≥ 60 s; never
stop mid-generation; restore production before closing any window that
does not end in an approved cutover.
