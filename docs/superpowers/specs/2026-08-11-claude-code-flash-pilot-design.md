# Claude Code Flash Pilot Design

Date: 2026-08-11
Status: approved for continuous execution by the user
Baseline: `claude-ds-pilot-r1`

## Outcome

One project-owned command safely replaces the running Qwen service with the
accepted two-host DeepSeek V4 Flash 0731 Patch4 deployment, runs a four-task
SWE-bench Verified pilot through real Claude Code against online and private
Flash treatments, grades the generated patches with the official harness, and
leaves DeepSeek running after a successful pilot. Infrastructure failure stops
DeepSeek and restores the captured Qwen state. A benchmark task that fails its
tests is a measured result and does not abort later tasks.

The user approved baseline `claude-ds-pilot-r1`, selected architecture A, and
then explicitly authorized the coordinator to design the script, run
preflight, proceed without another confirmation when preflight passes, and fix
infrastructure issues as needed.

## User Stories

- `US-01`: As a GB10 operator, I want to safely offload Qwen and start the
  accepted two-host Patch4 DeepSeek service so that private Claude Code uses the
  exact model, with restoration of the captured Qwen state on startup failure.
  After a successful pilot, DeepSeek remains running and Qwen remains stopped
  until an explicit restore action.
- `US-02`: As a coding-model evaluator, I want the online
  `deepseek-v4-flash` and local Patch4 `deepseek-v4-flash-0731` treatments to
  run under the same Claude Code version, tool policy, task snapshots, and
  timeout, so that four SWE-bench Verified pilot tasks can be compared one
  sequential run per treatment without fallback.
- `US-03`: As a decision maker, I want per-task executable-test outcomes,
  completion state, elapsed time, tool calls, retries, and available token/cost
  evidence so that I can decide whether to expand the corpus or repetitions.

## Single-Command Architecture

The top-level entry point is
`execution/run-claude-code-flash-pilot.sh`. It supports `--preflight` and
`--run`; `--run` repeats freshness checks but reuses a content-addressed gold
calibration receipt. The user invokes one `--run` command for the real pilot.

The shell entry point owns phase transitions and SSH. It calls two internal,
deterministic components:

1. `execution/run-vllm-service.sh` reuses the accepted deployment script's
   identity, Compose, Qwen capture, worker-first/head-second startup, runtime
   assertion, diagnostics, and rollback functions. It adds persistent
   `--start`, read-only `--status`, and explicit `--stop --restore-qwen`
   operations. It never edits the existing Compose files.
2. `execution/benchmarks/claude_code_swe_pilot.py` prepares isolated task
   workspaces, invokes Claude Code subprocesses sequentially, validates their
   stream-json identity, captures patches, invokes official SWE-bench grading,
   and writes aggregate JSON and Markdown results.

No Codex/Claude implementation agent is dispatched per benchmark task. The
runner loops over a frozen manifest and directly creates the eight Claude Code
subprocesses.

## Frozen Treatments

Both treatments use the same real Claude Code binary and must report version
`2.1.207` in their init events. The runner explicitly overrides the stale
toolchain `CLAUDE_REAL_BIN` that currently points to `2.1.195`.

| Treatment | Toolchain provider | Required model | Base URL |
| --- | --- | --- | --- |
| online | `ds` / `claude_ds` semantics | `deepseek-v4-flash` | configured DS route |
| private | `local` / `claude_local` semantics | `deepseek-v4-flash-0731` | `http://192.168.88.181:8890` |

The runner uses `coding-agent-toolchain/bin/claude` with an explicit provider,
model, and real binary. No fallback model is configured. A missing token,
provider error, init model mismatch, init version mismatch, or local model/API
identity mismatch is an infrastructure failure that invalidates the run.
Tokens remain process environment only and are never written to commands,
settings, logs, receipts, or Git.

## Frozen Tasks

Harness: SWE-bench `v4.1.0` at
`726c5461e2ef52d83cf1ea2107870a8bb3328d57e`.

Dataset: SWE-bench Verified revision
`c104f840cc67f8b6eec6f759ebc8b2693d585d4a`, test parquet SHA-256
`a45b1fe4e2f0c8390b2b2938ac83e92ed5979000856808f3679c07812e9e6dcd`.

| Order | Instance | Published difficulty | Pair order |
| --- | --- | --- | --- |
| 1 | `django__django-11133` | `<15 min fix` | online, private |
| 2 | `astropy__astropy-12907` | `15 min - 1 hour` | private, online |
| 3 | `sympy__sympy-20428` | `15 min - 1 hour` | online, private |
| 4 | `pytest-dev__pytest-6197` | `1-4 hours` | private, online |

Alternating pair order balances the only order effect available in a
single-repetition pilot. Runs remain strictly sequential so local requests do
not compete for GB10 capacity. Each Claude Code subprocess has a 45-minute
wall-clock limit. The hidden test patch and gold solution are never placed in
the agent workspace or prompt.

## Claude Code Contract

Each treatment starts from its own clean checkout at the dataset `base_commit`.
The prompt contains only the public problem statement plus fixed instructions
to inspect the repository, implement the fix, run relevant tests when
available, avoid network access, and leave the best patch in the worktree.

Claude Code runs non-interactively with session persistence, user/project
customizations, MCP, web tools, subagents, and fallback disabled. Its allowed
tool surface is the built-in file/search/edit/shell set. The complete
stream-json output is retained. The runner extracts init model/version,
duration, turns, usage, model usage, cost, terminal reason, permission denials,
and `git diff --binary`.

Official executable grading is authoritative. The runner writes one prediction
file per treatment and invokes the pinned SWE-bench evaluator with one worker
and `--namespace ''` for local arm64 image builds. Claude completion text and
model self-reports do not count as task success.

## Preflight

`--preflight` is fail-fast and does not change either GB10 service state. It:

1. runs shell syntax/static tests and calibrated fake tests for start failure,
   rollback failure, identity mismatch, measured task failure, and timeout;
2. verifies SSH aliases, protected service state, free ports, fabric, model
   manifest, Patch4 source, image revision/fingerprint, and rendered Compose on
   both hosts through the accepted checks;
3. verifies the exact Claude binary, toolchain commit/provider contract, online
   model catalog, and a no-tool online Flash stream-json probe;
4. verifies Docker/disk capacity, pinned harness and dataset hashes, repository
   reachability, and clean workspace creation; and
5. grades the gold patch for all four frozen tasks on the local arm64 harness.

Gold calibration produces a receipt keyed by script, task manifest, harness,
dataset, Docker architecture, and task image hashes. `--run` accepts only a
fresh matching receipt. Any failed gold task blocks GB10 mutation and is fixed
as infrastructure, not reported as model performance.

## Real Run and Recovery

The formal run creates a UTC artifact root, refreshes all non-mutating checks,
and then executes these phases inside the one top-level process:

1. capture Qwen/protected-service state and host evidence;
2. stop only Qwen and wait for port 8004 to release;
3. start worker DeepSeek, then head DeepSeek;
4. verify API model, both ranks, Patch4 source, NCCL `NET/IB`, and absence of
   fatal NCCL/CUDA/OOM/worker-loss evidence;
5. probe private Claude Code model/version identity;
6. run all eight Claude Code task attempts in the frozen alternating order;
7. grade online and private prediction sets with the official harness;
8. verify the DeepSeek runtime and protected services again; and
9. write results and a service receipt while leaving DeepSeek running and Qwen
   stopped.

Signals and infrastructure exceptions after Qwen is stopped enter one cleanup
handler: preserve current DeepSeek logs/inspect/events, stop head then worker,
restore only the captured Qwen state, verify model `qwen3.6-35b-fp8` on port
8004, and prove pdf2md/trading/lexdata unchanged. A Claude timeout or unresolved
patch after a valid init is a measured task outcome, so the runner records it
and continues.

After a successful pilot, the explicit rollback command is the same top-level
script with `--restore-qwen`; it verifies the active service receipt before
stopping DeepSeek and restoring Qwen. `--status` is read-only.

## Evidence and Decision Output

Local evidence lives under ignored
`execution/artifacts/claude-code-pilot/<UTC>/`. The head centralizes its own
service evidence plus remotely captured worker logs, inspect, and events under
`/home/chriswang/gb10-ds4/artifacts/service/<UTC>/`.

The result schema reports each treatment separately and each task individually:
official resolved/unresolved/error, patch SHA, process exit/timeout, elapsed and
API duration, turn count, token usage, cost when provided, tool calls,
permission denials, actual model/version, and evidence paths. The summary may
show raw counts and deltas but does not claim statistical superiority from one
run per task.

The next decision is deliberately outside this run: after reviewing the pilot,
the user chooses whether to add private tasks, more public tasks, or repeated
runs.

## Alignment Playback

Subject: this design, baseline `claude-ds-pilot-r1`.

| Story | Design evidence | Status |
| --- | --- | --- |
| `US-01` | Captured-state persistent start, protected services, failure rollback, explicit restore | Covered |
| `US-02` | Exact Flash identities, same Claude Code binary/policy, four frozen tasks, sequential one-run treatment pairs | Covered |
| `US-03` | Official grading plus per-task timing/tool/usage/cost evidence and deferred expansion decision | Covered |

Drift: none. Drift score: 0. Gate: `DESIGN_ALIGNED`.

## Sources

- `planning/02-working/2026-08-11-claude-ds-local-benchmark-discovery.md`
- `planning/03-core/02-official-0731-deployment.md`
- `planning/03-core/03-operations-runbook.md`
- `planning/03-core/05-multi-model-capacity-plan.md`
- `execution/run-vllm-acceptance.sh`
- coding-agent-toolchain commit `c074ba8`
- SWE-bench `v4.1.0` and SWE-bench Verified dataset revision/hash listed above
