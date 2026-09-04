# execution/eval

A/B evaluation harness for the DeepSeek-V4 vLLM service, per
`planning/02-working/2026-09-04-gb10-cluster-optimization-and-eval-design.md`
§5. Flat scripts, no package `__init__.py` -- run any entry point directly
(`python3 suite.py ...`) or `import config`/`import metrics`/etc. from
another script in this directory; both rely on Python inserting a script's
own directory at `sys.path[0]`.

## Setup

```
cp execution/eval/eval.env.example execution/eval/.env.eval
# edit .env.eval: EVAL_BASE_URL, EVAL_MODEL at minimum
```

`.env.eval` is gitignored (`.env.*`). No hostnames, IPs, or usernames belong
in any tracked file in this package -- `config.py` loads them from the
environment only, and `config.redact_host()` scrubs the host out of anything
written to a run's `manifest.json`.

## suite.py -- the A/B suite

```
python3 execution/eval/suite.py --tag baseline
python3 execution/eval/suite.py --tag e1-adaptive --dry-run   # print the plan, no network
```

Runs the S/M/L/N/C/T/V blocks (§5.3) against `EVAL_BASE_URL`, gated by an
idle-window check (`--force` to override; recorded in `manifest.json`).
Writes `tmp/eval/<UTC yyyymmddTHHMMZ>-<tag>/`:

- `manifest.json` -- tag, args, seeds, redacted base_url, model, git HEAD,
  contamination count
- `metrics_before.txt` / `metrics_after.txt` -- raw `/metrics` snapshots
- `results.jsonl` -- one record per sample (block, name, seed, repeat,
  temperature, prompt/completion/cached tokens, ttft_s, gen_tok_s,
  itl_p95_s, finish_reason, contaminated, per-block gate fields, error)
- `hosts.jsonl` -- head/worker MemAvailable samples every 30s (skipped with
  `--no-hosts` or if neither ssh alias is set)
- `report.md` -- KPI table (median/min/max), gate verdicts, `/metrics` delta

Useful flags: `--blocks S,M,L` (subset), `--repeats N` (override every
block's repeat count), `--scale 0.01` (shrink prompt-body token counts, for
fast tests), `--thinking off|low|high` (default: omit `chat_template_kwargs`
entirely, i.e. the production default), `--seed-base`.

## compare.py -- the adoption decision

```
python3 execution/eval/compare.py tmp/eval/<baseline-dir> tmp/eval/<candidate-dir> \
  --target decode_c1_tok_s
```

Applies §5.4's rule: adopt if the targeted primary KPI improves by >= 5%
(decode) or >= 10% (prefill at the targeted bucket) with non-overlapping
3-repeat ranges vs. baseline, and no other primary KPI regresses by > 3%
(tok/s KPIs regress downward, TTFT KPIs regress upward). Any gate failure
(needle exact, tool-call JSON 6/6, vision score vs. baseline - 2, missing
finish_reason, head MemAvailable >= 4 GiB, warm TTFT@64K <= 2s) forces
REVERT regardless of the KPI verdict. Writes `<candidate-dir>/compare.md`;
exit code 0 = ADOPT, 1 = REVERT/INCONCLUSIVE.

## Production telemetry

`scrape.sh` (needs `SCRAPE_METRICS_URL`; `once` or `loop`, default 60s) appends
one JSON line per scrape to `<out-dir>/<UTC-date>.jsonl` (`SCRAPE_OUT_DIR`,
default `tmp/eval/scrape/`). `daily_report.py --date YYYY-MM-DD` turns a
day's scrapes into TTFT/ITL tail counts, decode tok/s, acceptance,
prefix-hit ratio, KV usage max, preemptions, request_success by reason, and
boot events (a counter going backwards between scrapes).

`loghealth.sh [ssh-alias]` greps recent container logs (`EVAL_CONTAINER`,
`LOGHEALTH_SINCE`, default 30m) for DSML/CJK markup leakage, NCCL/CUDA/OOM
lines, and JIT-in-inference messages -- the symptom watch that keeps the
symptom-gated correctness workarounds off until actually needed. It cannot
detect the sparse-MLA stall (silent, no log line) or post-termination
grammar tokens (needs `finish_reason` accounting); those are covered by
`suite.py`'s `no_missing_finish_reason` gate instead.

## Run protocol (§5.5)

1. Confirm the idle window (`suite.py` does this itself before block S).
2. `suite.py --tag baseline`.
3. Operator applies exactly one `.env` change, restarts both ranks, runs
   boot gates, settles 3 min, sends one warm-up request per block.
4. `suite.py --tag <treatment>`; `compare.py <baseline-dir> <treatment-dir> --target <kpi>`.
5. Keep or revert per the verdict; either way, re-run block S once more as
   the drift check for the boot that stays. Record the run in
   `planning/03-core/11-gb10-config-ab-ledger.md`.

## Tests

```
python3 -m pytest execution/eval/tests/test_eval.py
```

Runs entirely offline against a local mock SSE server and the fixtures in
`fixtures/`; no network access outside `127.0.0.1`, no ssh.

## Known deviations from the design doc

- The real menu photo (`EVAL_MENU_IMAGE`) is not committed to this repo
  (customer data); block V and the tests fall back to a synthetic
  placeholder PNG when it is unset. Point the env var at the real photo for
  a live run that wants the real 47-field score. The menu grader itself
  (prompt, response schema, `MENU_TRUTH`) is imported by path from
  `execution/benchmarks/vision_compare.py` when that file exists; in a clean
  checkout without it, block V records an explicit skip record
  (`skipped: true`, `vision_score` gate n/a) instead of failing the suite.
- The mixed decode+prefill probe (block C) is not re-run on contamination
  like every other probe is -- a re-run would just repeat the same overlap
  measurement. The `contaminated` flag is still recorded on its one record.
- `loghealth.sh` cannot grep-detect the sparse-MLA stall or post-termination
  grammar tokens (see above); this is a spec limitation, not an
  implementation gap -- those symptoms are silent in the logs by
  construction.

## Rules added at lead review (2026-09-04)

- Contamination is judged on `num_requests_running` read both before and
  after each probe (`running_before`, `running_after` in results.jsonl);
  either being nonzero (before: above own concurrency for block C) marks the
  sample and triggers one re-run.
- A contaminated **cold** probe (blocks L and N) is re-run with a fresh seed,
  never the same body -- the same body would hit the prefix cache and record
  a warm prefill as cold. The re-run record carries
  `rerun_of_contaminated: true` and the new seed; the warm repeat in block L
  uses the body that actually ran last.
- `compute_kpis` ignores contaminated records; gates still count them.
- Needle probes use `max_tokens=256` and accept the marker in either the
  answer text or `reasoning_text` (`needle_in_text` records which), because
  the production default keeps thinking on and a short budget would be
  consumed by reasoning alone.
- Live smoke check done 2026-09-04 with two short requests: SSE fields
  (`reasoning_content`, final usage chunk with `prompt_tokens_details.
  cached_tokens`, `finish_reason`) and the `/metrics` acceptance delta
  (accepted/draft, per-position, drafts) parse correctly on vLLM 0.25.2.
