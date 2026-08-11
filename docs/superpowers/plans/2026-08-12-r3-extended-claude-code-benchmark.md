# R3 Extended Claude Code Benchmark Implementation Plan

Date: 2026-08-12

Status: approved for continuous execution by the user's explicit instruction to use recommended defaults without further confirmation.

Authority:

- Design: `docs/superpowers/specs/2026-08-12-r3-extended-claude-code-benchmark-design.md`
- Design SHA-256: `47efeec9b70cb0e2d3257cf4fb140e658f4ce3c5e5686bb5af09ab6e950ae865`
- Baseline: `claude-ds-pilot-r3`
- Repository base: `a6ec338`
- Coordinator runtime: Codex
- Track: Ledger, because execution spans a large corpus, two GB10 hosts, model transitions, long-running checkpoints, and browser delivery

## Completion

R3 is complete only when:

- the manifest contains the unchanged seven R2 tasks plus exactly 10 terminal, 10 server-operations, 10 writing, and 10 programming tasks;
- all 47 initial fixtures fail and all 47 gold overlays pass visible and hidden grading;
- all fixed corpus counts are manifest-derived and fake 141-attempt E2E passes;
- one formal script run produces 141 exact-identity Claude Code attempts and 47 validated `gpt-5.6-sol/xhigh` judgments without fallback;
- final baseline ranking uses deterministic plus GPT layers for all 47 tasks;
- the final report shows the test environment, 47 tasks, 141 model answers, hidden results, GPT scores/preferences/rationales, domain aggregates, timing, and failure classes;
- DeepSeek is stopped on both hosts, Qwen is healthy on `:8004`, pdf2md remains stopped, and trading/lexdata are healthy.

## Wave 1: Corpus And Graders

Stories: `US-R3-01`, `US-R3-02`, `US-R3-04`.

Scope:

- extend the task manifest to schema revision R3;
- add forty fixtures and gold overlays;
- add hidden task specs/cases and shared terminal, operations, writing, Python, and TypeScript grader support;
- add a deterministic corpus generator only when it reduces repeated mechanical files; generated outputs remain checked and committed;
- preserve the original seven task files byte-for-byte.

Acceptance:

- exact domain/language counts match the design;
- every task uses safe relative paths and a unique ID;
- terminal tasks enforce shell artifacts and alternate hidden inputs without requiring a preferred command spelling;
- operations tasks never require host services or privileged commands;
- writing checks accept normalized facts and do not reproduce the R2 brittle phrase failures;
- Python and TypeScript gold suites pass with local standard runtimes and no downloaded dependencies;
- red/gold calibration passes for 47 tasks.

## Wave 2: Dynamic Runner, Scoring, And Report

Stories: `US-R3-02`, `US-R3-03`.

Scope:

- replace fixed task/attempt/judge/human counts in Python and shell with validated manifest-derived values;
- preserve per-attempt and per-judge checkpoint resume;
- change the unattended baseline score to deterministic-plus-GPT for every task;
- make human writing ratings an optional separate overlay;
- generalize the report renderer to 47 tasks and domain aggregates.

Acceptance:

- fake run reports 47 tasks, 141 attempts, 47 judges, and no required human submissions;
- strict judge schema, identity audit, retry, sealed mapping, and fallback negatives still pass;
- incomplete candidate artifacts remain measured failures while harness/grader failures remain infrastructure failures;
- report structure contains 47 task sections, 141 answer panels, and 47 GPT rationales.

## Wave 3: Integrated Verification

Stories: all R3 stories.

1. Run Python compile, shell syntax, `git diff --check`, manifest validation, all red/gold calibrations, fake E2E, resume, scoring, report, and service-controller fake suites.
2. Confirm no candidate fixture or prompt contains hidden cases, gold outputs, treatment identity, or host credentials.
3. Run exactly one top-level read-only preflight. Repair only real blockers, then rerun the affected focused checks and preflight.
4. Record the immutable implementation SHA and preflight receipt.

## Wave 4: Formal Scripted Execution

Stories: `US-R3-02`, `US-R3-03`, `US-R3-04`.

1. Invoke exactly one top-level formal benchmark command.
2. Let the script own DeepSeek start/adoption, 94 DS attempts, DS-to-Qwen transition, 47 Qwen attempts, 47 judges, packaging, final report, health checks, and recovery.
3. Re-enter only for nonzero exit, degraded/blocked receipt, bounded retry exhaustion, or a newly observed invariant.
4. Resume only from validated checkpoints; never manually run individual benchmark tasks.
5. Verify the final report in the browser and leave its loopback URL open.

## P0 Boundaries

Only these stop continuous execution:

- benchmark distortion such as leaked hidden cases, inconsistent prompts/tools, wrong counts, or biased scoring inputs;
- provider/model/version mismatch or fallback;
- credentials or real-host access entering candidate sandboxes/artifacts;
- unsafe/ambiguous GB10 service state, protected-service drift, fatal GPU/OOM/worker loss, or failed Qwen recovery;
- failure of the current runnable preflight, fake E2E, or final report integrity.

All non-P0 style, refactor, and optional-human-UI findings are deferred, matching the user's explicit instruction to ignore non-P0 and security issues for this non-production benchmark.

## Exact Next Action

Implement Wave 1 in the current worktree with one writer, run full red/gold calibration, then continue directly into Wave 2 without another user confirmation.
