# GB10 config A/B ledger

One row per evaluated boot of the private DS service (2-node TP=2,
`deepseek-v4-flash-0731` alias). Design and gates:
`planning/02-working/2026-09-04-gb10-cluster-optimization-and-eval-design.md`
§4-§6. Harness: `execution/eval/` (`suite.py`, `compare.py`). Run dirs live
under `tmp/eval/` and are not committed; copy the `report.md` KPI table into
the row's notes when a verdict is recorded.

Rules that every row must respect:

- Exactly one launch-flag change per treatment boot, with the `.env.dspark`
  backup name recorded; stop/start recreate (not `restart`).
- Baseline and treatment measured in the same idle window whenever possible;
  otherwise note the gap.
- Verdict per §5.4: adopt only if the targeted primary KPI improves ≥ 5 %
  (decode) or ≥ 10 % (prefill bucket) with non-overlapping repeat ranges and
  no other primary KPI regresses > 3 %, and every gate passes.

## Boots and verdicts

| Date (UTC) | Tag | Change (`.env.dspark` diff) | Targeted KPI | Δ vs baseline | Gates | Verdict | Run dir | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-09-04 | E4-ops | none (worker `~/dspark-vision` → git checkout at `d828ddd`; 4 missing `patches/` files restored) | — | — | boot-time hotfix set byte-identical (patches sha match) | applied, no restart needed | — | design doc §9; no launch flag touched |
| — | E0-baseline | none | all primary KPIs | — | — | pending idle window | — | first run of `suite.py --tag baseline` |

## Current production launch (reference for diffs)

`d828ddd` compose + `.env.dspark` as audited 2026-09-04:
`LONG_PREFILL_TOKEN_THRESHOLD=1024`, `MAX_NUM_BATCHED_TOKENS=8192`,
`MAX_NUM_SEQS=6`, `MTP_NUM_TOKENS=6`, `DRAFT_SAMPLE_METHOD=probabilistic`,
`GPU_MEMORY_UTILIZATION_TEXT=0.835`, `DEFAULT_THINKING=low`,
`DSPARK_MAX_INFLIGHT_PREFILLS=2`, all `DSPARK_ENABLE_*=0`,
`DSPARK_SUPPRESS_STOPS_IN_REASONING=1`.
