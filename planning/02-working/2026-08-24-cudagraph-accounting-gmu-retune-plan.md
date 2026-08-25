# CUDA-Graph Accounting Fix + gmu Re-tune (2026-08-24, operator-approved)

Successor to the rejected "gmu 0.80 as-is" option. Root cause established by
the 2026-08-24 campaign (`tmp/followup-tests/20260824T124317Z/`): the compose
hardcodes `VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS: "0"`, so ~0.7-0.9 GiB of
CUDA-graph memory is never accounted during KV sizing; at gmu 0.80 the graph
capture overdrafts and the kernel logs NVRM `NV_ERR_NO_MEMORY` bursts.

Goal: enable the accounting and adopt the highest gmu that is fully clean.
UNLIKE the previous campaign, the winning arm IS ADOPTED and left running in
production. Only if BOTH arms fail is the fleet restored to the pre-campaign
baseline.

All Section 0 hard constraints, Section 1 fixed facts, drain/settle/retry
rules, backup discipline, evidence conventions, and shell hygiene of
`planning/02-working/2026-08-24-long-context-followup-test-plan.md` apply
unchanged. Budget: 6 h from first restart. Evidence:
`tmp/followup-tests/<new UTC>/` with subdirs `prep/`, `arm2-gmu080/`,
`arm1-gmu0787/` (if reached), `final/`.

## Reference numbers (from the 2026-08-24 campaign)

- Clean-boot baseline (gmu 0.78, accounting off): pool 8.81 GiB / 1,221,928
  tokens; cold prefill 1744 tok/s @64K, 1630 @130K; decode ~62 tok/s; small
  request during 130K cold prefill ~12.8 s.
- gmu 0.80 accounting off: pool 10.21 GiB / 1,471,271 tokens, but 84 NVRM
  `NV_ERR_NO_MEMORY` head / 28 worker during boot.
- vLLM boot warning: accounting-on at gmu 0.7869 is the accounting-neutral
  point vs 0.78 accounting-off.
- Expected pools with accounting ON: arm 2 (0.80) ~9.3-9.5 GiB / ~1.30M
  tokens; arm 1 (0.787) ~8.8 GiB / ~1.22M tokens.
- Currently running: run `20260824T144141Z`, baseline config, pool 7.85 GiB /
  1,188,831 tokens (unsettled-memory boot; compare new arms against the
  clean-boot numbers above, not this).

## Prep (once, both hosts, with fresh timestamped backups)

1. `execution/docker-compose.yml` on BOTH hosts: change
   `VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS: "0"` to
   `VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS: "${VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS:-0}"`.
   (`docker-compose.thinking-on.yml` needs no edit - environment maps merge.)
2. Head `execution/run-vllm-acceptance.sh`: change the exact-equality assert
   `$s.environment.VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS == "0"` to
   `== "1"`. For arm 2 additionally sed
   `--gpu-memory-utilization 0.78` -> `--gpu-memory-utilization 0.80`; note
   arm 1's `0.787` passes the original substring assert unchanged, so when
   falling back to arm 1, restore the gmu assert line to `0.78` (keep the
   `== "1"` accounting assert).
3. BOTH hosts `execution/env/common.env`: add
   `VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=1` and set
   `GPU_MEMORY_UTILIZATION` per arm.

## Arm 2 first: accounting ON + gmu 0.80

1. Set `GPU_MEMORY_UTILIZATION=0.80` both hosts. Record exact UTC boot-window
   start; drain, `--stop`, settle, `--start` (2-attempt rule).
2. Boot gate (all required):
   - boot succeeds; record run ID, pool GiB/tokens on both ranks (expect
     ~9.3-9.5 GiB; if pool is BELOW the 0.78 clean-boot 8.81 GiB, the
     estimator is over-subtracting - note it and apply judgment: if below
     ~8.5 GiB, arm 2 gives no meaningful capacity gain, treat as FAIL);
   - ZERO new NVRM `NV_ERR_NO_MEMORY` / Xid / oom events on either host
     within the boot window (`journalctl -k --since <boot start>` - filter
     strictly by timestamp; today's journal already contains old events from
     the previous campaign).
3. First-traffic gate: one small request, one 18300-word cold prefill, one
   37000-word cold prefill (fresh seeds; graph capture and DSpark buffers
   allocate on first real traffic - re-scan journals after each).
4. Soak >= 40 min (MANDATORY this time, same mixed-workload driver as the
   previous campaign's Phase B design: alternating 18300/37000-word cold
   prefills every ~6 min with fresh seeds, small request every 30 s, decode
   request every ~6 min, <= 3 in flight; monitor every 60 s: containers,
   API, journal scans on both hosts, `free -g`, filtered docker logs).
5. Perf spot-check (during or right after soak): 64K and 130K cold prefill
   tok/s within 10% of 1744/1630; decode within 10% of 62 tok/s; small
   request during a 130K cold prefill <= ~15 s.
6. PASS = boot gate + first-traffic gate + zero soak events + perf within
   tolerance. -> ADOPT arm 2 (leave running; skip arm 1), go to Finalize.
   FAIL -> capture evidence, fall back to arm 1.

## Arm 1 fallback: accounting ON + gmu 0.787

Only if arm 2 failed. Set `GPU_MEMORY_UTILIZATION=0.787` both hosts, restore
the contract gmu assert to `0.78` (keep `== "1"`), restart, same gates, soak
>= 20 min. PASS -> ADOPT arm 1, go to Finalize. FAIL -> restore ALL
pre-campaign backups (compose, contract, env), restart baseline, verify
healthy, report - adoption abandoned.

## Finalize (adopted arm stays running)

1. Verify `--status`, `/v1/models` (max_model_len 1048576 intact), smoke
   chat, small probe, `:8004` proxy, protected services - same checklist as
   the previous campaign's Section 7.
2. Confirm both hosts' `common.env`, `docker-compose.yml`, and the head
   contract are mutually consistent with the adopted arm (diff against
   backups and list the intended deltas - these are now the new production
   truth, do NOT revert them).
3. Do NOT edit the local workspace repo - the lead session syncs the repo,
   runbook, and PR after reviewing the report.

## Report

Same structure as the previous campaign's report: executive verdict per arm,
boot-gate numbers (pool GiB/tokens per rank, NVRM counts per host per
window), soak duration + event counts, perf table vs reference numbers,
timeline of every stop/start with run IDs, backup inventory, final running
config + run ID, deviations. State explicitly which arm is LIVE.

## Outcome (recorded 2026-08-25 by the lead session)

BOTH ARMS FAILED the zero-NVRM boot gate; adoption abandoned; baseline
restored byte-identical (run `20260824T175920Z`) and verified healthy.
Evidence: `tmp/followup-tests/20260824T150255Z/`.

Two findings invalidated this plan's premises:

1. **journalctl timezone bug.** Both hosts run Asia/Shanghai; bare
   `--since/--until` strings were parsed as CST, shifting every prior
   "clean" scan window 8 h off. With `TZ=UTC` corrected scans, arm 2's
   first boot showed 31 new NVRM events (not zero).
2. **The restored, untouched baseline also fails the gate** (64 events on a
   properly settled boot), and all five boots that night showed 31-122
   events with no monotonic relation to config. Boot-time NVRM bursts
   during graph capture are a host-state characteristic, not a config
   discriminator; the gate was calibrated against false-clean data.

Arm 2 (accounting on, gmu 0.80) otherwise performed excellently: pool
9.61 GiB / 1,363,371 tokens (+11.6%), flawless 42-min soak (0/98 failures,
zero post-boot events), perf at or above baseline. It was not adopted
because the evidence base for the boot gate was contaminated by
session-long memory-state drift across five restarts.

Any future retune must: reboot the hosts (operator-approved window;
co-tenant services go down) before each boot-gate measurement, measure a
same-session baseline boot first, and gate on "no worse than that baseline"
rather than "zero events". See the runbook's re-tune section for the full
decision record.
