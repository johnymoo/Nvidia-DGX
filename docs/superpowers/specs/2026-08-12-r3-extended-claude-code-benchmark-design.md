# R3 Extended Claude Code Benchmark Design

Date: 2026-08-12

Status: approved for continuous design and execution by the user's explicit instructions to use recommended defaults, stop asking for confirmation, add ten tasks per direction, run everything in sandboxes, execute the benchmark, and publish the final one-page report.

Baseline revision: `claude-ds-pilot-r3`

Repository baseline: `a6ec338`

Working evidence: `planning/02-working/2026-08-12-r3-extended-benchmark-discovery.md`

## Outcome

Extend the accepted R2 framework from 7 to 47 tasks while preserving the three exact Claude Code treatments:

| Treatment | Route | Model |
| --- | --- | --- |
| `online_ds` | `claude_ds` | `deepseek-v4-flash` |
| `offline_ds` | `claude_local` | `deepseek-v4-flash-0731` on two-host GB10 Patch4 |
| `qwen_local` | `claude_local` | `qwen3.6-35b-fp8` on GB10 `:8004` |

All 141 candidate attempts use Claude Code `2.1.207`, byte-equivalent per-task prompts, the same tool and sandbox policy, no network or fallback, and one clean Git sandbox per attempt. The single top-level script runs preflight, both DeepSeek treatments, the receipt-backed DeepSeek-to-Qwen transition, Qwen, 47 independent GPT judge calls, packaging, and the detailed final report.

## Approved User Stories

- `US-R3-01`: As a model evaluator, I want ten representative sandbox tasks in each of terminal use, server operations, bilingual writing, and programming so that the comparison covers routine end-to-end work rather than a small coding-only sample.
- `US-R3-02`: As a decision maker, I want every treatment to run the same 47 tasks through the same Claude Code version, prompt, tools, sandbox, time limit, grading contract, and no-fallback policy so that treatment differences are not mixed with harness differences.
- `US-R3-03`: As a decision maker, I want deterministic task checks, blind `gpt-5.6-sol/xhigh` scoring, resumable unattended execution, and one unsealed report containing every task, answer, score, and rationale so that the overnight run is complete without waiting for manual grading.
- `US-R3-04`: As a GB10 operator, I want task sandboxes to have no real-host authority and the existing receipt-backed DeepSeek/Qwen transition and protected-service checks to remain unchanged so that a broader corpus does not broaden infrastructure risk.

Baseline gate: `BASELINE_APPROVED`. Approval evidence is the user's 2026-08-12 continuous-execution delegation and explicit instruction that recommended defaults require no further confirmation.

| Story | Given | When | Then |
| --- | --- | --- | --- |
| `US-R3-01` | The accepted R2 framework | R3 corpus validation runs | Exactly 40 new original tasks exist, ten per requested direction, and all red/gold calibrations pass |
| `US-R3-02` | One 47-task manifest and three pinned treatments | The formal benchmark runs | Exactly 141 identity-validated candidate attempts use equivalent Claude Code contracts |
| `US-R3-03` | Complete candidate artifacts | Packaging runs | 47 blind GPT judgments produce a complete final rank and detailed one-page report without human input |
| `US-R3-04` | Disposable local task sandboxes and accepted GB10 service receipts | Tasks and model phases run | Tasks cannot access real hosts; only the top-level service script mutates authorized DS/Qwen state and verifies protected services |

## Approaches

### A. Manifest expansion with shared domain graders (selected)

Keep the current runner and add a hidden task-spec directory plus shared terminal, operations, writing, Python, and TypeScript grading helpers. Each task still has a fixture, visible tests, gold solution, and independent hidden cases. Fixed corpus counts become manifest-derived. This preserves one execution path while avoiding forty near-duplicate grader programs.

### B. Forty bespoke grader programs

Rejected because repeated protocol, subprocess, fact, and test logic would be difficult to calibrate consistently and would amplify maintenance mistakes.

### C. Import external benchmark repositories

Rejected because external containers, licenses, dependency installation, and environment assumptions would change the accepted sandbox contract. R3 uses original local fixtures informed by common task classes, not copied task text.

## Corpus

The original seven R2 tasks remain unchanged. The following forty tasks are added.

### Terminal Use: 10

| ID | Typical capability | Required artifact |
| --- | --- | --- |
| `terminal-log-frequency` | Parse rotated application logs and rank normalized error signatures | `solve.sh`, `report.json` |
| `terminal-nul-inventory` | Build a NUL-safe inventory for filenames containing spaces, tabs, and leading dashes | `solve.sh`, `inventory.json` |
| `terminal-csv-pipeline` | Filter and aggregate quoted CSV records with deterministic ordering | `solve.sh`, `summary.csv` |
| `terminal-safe-rename` | Produce and apply a collision-safe bulk rename plan with rollback data | `solve.sh`, `rename-plan.json` |
| `terminal-env-precedence` | Resolve defaults, dotenv, and process overrides without evaluating input | `solve.sh`, `effective-env.json` |
| `terminal-permission-audit` | Detect and remediate file-mode drift while preserving directories and links | `solve.sh`, `permission-report.tsv` |
| `terminal-archive-verify` | Verify an archive manifest and selectively extract approved members without traversal | `solve.sh`, `verification.json` |
| `terminal-process-join` | Join captured `ps`, socket, and service metadata into a stable process report | `solve.sh`, `process-report.tsv` |
| `terminal-jsonl-aggregate` | Validate JSONL, reject malformed rows, and aggregate latency/status buckets | `solve.sh`, `aggregate.json` |
| `terminal-checksum-audit` | Classify matching, missing, changed, and unexpected files from a checksum manifest | `solve.sh`, `audit.json` |

Terminal fixtures execute only inside the task directory. Hidden cases invoke `solve.sh` against alternate input directories. Prompts forbid Python/Node for these ten tasks so the corpus measures shell and standard terminal-tool use; graders enforce the executable shell artifact and behavior, not a preferred command spelling.

### Server Operations: 10

| ID | Typical capability | Required artifact |
| --- | --- | --- |
| `ops-nginx-upstream` | Diagnose timeout/connection evidence and repair a reverse-proxy fragment | `fix.conf`, `diagnosis.json` |
| `ops-systemd-restart` | Repair restart, dependency, environment, and readiness semantics in a unit | `service-fixed.unit`, `diagnosis.json` |
| `ops-logrotate-policy` | Correct unsafe rotation ownership, retention, compression, and reload behavior | `logrotate-fixed.conf`, `diagnosis.json` |
| `ops-backup-schedule` | Repair timezone, locking, retention, and failure propagation in a backup job | `backup-fixed.sh`, `schedule.txt` |
| `ops-tls-chain` | Assemble a correct certificate-chain deployment plan from supplied metadata | `deployment.json`, `rollback.md` |
| `ops-disk-pressure` | Correlate filesystem, inode, deleted-open-file, and directory evidence | `triage.json`, `remediation.md` |
| `ops-oom-cgroup` | Diagnose cgroup OOM evidence and propose bounded service memory controls | `service-fixed.unit`, `diagnosis.json` |
| `ops-proxy-health` | Repair health, connect/read timeout, forwarding-header, and retry semantics | `proxy-fixed.conf`, `diagnosis.json` |
| `ops-db-pool` | Correlate pool, database, and request metrics and produce a bounded tuning plan | `tuning.json`, `rollback.md` |
| `ops-release-rollback` | Implement atomic release-symlink rollback with prechecks and audit output | `rollback.sh`, `rollback-plan.json` |

These are realistic but fully synthetic incident bundles. No command can use SSH, Docker, systemd, sudo, host ports, or parent paths. Config syntax is checked by project-owned parsers or deterministic assertions rather than host daemons.

### Bilingual Writing: 10

| ID | Language | Form |
| --- | --- | --- |
| `writing-zh-incident` | Chinese | Incident postmortem |
| `writing-zh-change` | Chinese | Change approval memo |
| `writing-zh-customer` | Chinese | Customer-facing outage notice |
| `writing-zh-runbook` | Chinese | Concise operational runbook |
| `writing-zh-policy` | Chinese | Policy summary for non-specialists |
| `writing-en-incident` | English | Incident status update |
| `writing-en-release` | English | Release notes with compatibility limits |
| `writing-en-proposal` | English | Technical proposal and trade-offs |
| `writing-en-support` | English | Customer support response |
| `writing-en-executive` | English | Executive decision brief |

Each task supplies a stable fact packet, audience, tone, length bound, and prohibited unsupported claims. The deterministic grader checks `answer.md`, bounded length, stable identifiers/numbers, and required sections with normalized aliases. It does not grade elegance or reject a required caveat merely because it contains words such as "significant". GPT scores factual accuracy, instruction following, and clarity/style. Optional human review covers these ten new tasks plus the two existing writing tasks, but it is a separate overlay and does not block or alter the unattended baseline ranking.

### Programming: 10

| ID | Language | Capability |
| --- | --- | --- |
| `python-async-cache` | Python | Async TTL cache with single-flight loading and failure cleanup |
| `python-streaming-csv` | Python | Bounded-memory CSV aggregation with malformed-row reporting |
| `python-retry-decorator` | Python | Sync/async retry decorator with exception filters and injected sleep |
| `python-toposort` | Python | Stable dependency ordering with missing-node and cycle diagnostics |
| `python-bounded-map` | Python | Ordered bounded-concurrency map with cancellation cleanup |
| `typescript-config-merge` | TypeScript | Immutable deep merge with explicit array and undefined semantics |
| `typescript-event-emitter` | TypeScript | Typed event emitter with once/off and reentrant emission behavior |
| `typescript-url-router` | TypeScript | Route matching, decoding, precedence, and query multimap handling |
| `typescript-promise-pool` | TypeScript | Ordered promise pool with concurrency bounds and stop-on-error cleanup |
| `typescript-lru-ttl` | TypeScript | LRU cache with TTL, injected clock, overwrite, and eviction semantics |

Python uses the standard library and `unittest`. TypeScript uses Node `v25.4.0`, built-in type stripping, `node:test`, and erasable TypeScript syntax; no package install or network is permitted. Hidden graders add alternate cases and verify public API/type declarations where runtime stripping cannot.

## Grading And Ranking

Every task has an initial fixture that fails its hidden grader and a gold overlay that passes visible and hidden checks. Candidate failures remain measured results and do not abort later tasks.

The deterministic tier remains:

- `3`: all hidden checks pass;
- `2`: at least half but not all pass;
- `1`: fewer than half pass, invalid tool activity, timeout, or missing/invalid output.

The independent judge uses exact `gpt-5.6-sol/xhigh`, a fresh per-task A/B/C permutation, and the strict schema with required `candidates`, `preference`, and `rationale`. It sees task context and normalized candidate artifacts but no identities, paths, timing, hidden grades, tool counts, cost, or phase order.

For every treatment `c` and task `t`:

```text
baseline_quality(c,t) = mean(deterministic_tier(c,t), judge_layer(c,t))
```

The final baseline rank is the unweighted mean of all 47 `baseline_quality` values. Human writing scores and preferences are reported separately. They never change the unattended baseline rank, which keeps all tasks on the same two-layer contract.

## Dynamic Runner And Recovery

- All `7/14/21` count checks become `N`, `2N`, and `3N` from the validated manifest.
- DeepSeek first-treatment order is balanced across 47 tasks: 24 online-first and 23 offline-first. The forty new tasks contribute 20 of each order.
- Qwen runs all 47 tasks in manifest order after the receipt-backed transition.
- State is checkpointed after every attempt and judge. Resume validates task ID, treatment, prompt hash, model, route, Claude version, artifacts, and the current manifest/preflight contract.
- The report generator accepts any validated manifest size and renders 47 tasks, 141 answers, 47 GPT rationales, aggregate/domain/task tables, test environment, pass counts, timing, and failure classes.
- Human review, if launched later, shows only writing tasks and writes a separate overlay artifact.

## Unattended Execution And Host Safety

The top-level script remains the only normal-path entry point. It performs one preflight and one formal run. Preflight calibrates all 47 red/gold pairs, verifies tool/runtime availability, probes online Flash and the exact GPT judge, and performs read-only GB10 checks.

The formal run retains the accepted order:

1. Capture Qwen and protected-service state.
2. Start or adopt exact two-rank Patch4 DeepSeek.
3. Run 94 DeepSeek candidate attempts.
4. Stop DeepSeek through the active receipt and start captured Qwen.
5. Run 47 Qwen attempts.
6. Run 47 GPT judge calls, calculate the two-layer final rank, and render the final report.
7. Verify DeepSeek stopped, Qwen healthy, pdf2md unchanged, and trading/lexdata healthy.

Task prompts cannot access SSH, Docker, systemd, sudo, host services, network, parent directories, benchmark harnesses, hidden cases, or gold solutions. Only the project-owned outer service script touches GB10.

## Verification

Required before the formal run:

1. Manifest schema and exact domain counts: terminal 10, server operations 10, bilingual writing 10, programming 10, plus seven unchanged R2 tasks.
2. Every initial fixture fails and every gold overlay passes visible and hidden checks.
3. Shell tasks run against at least two alternate hidden input sets; traversal, injection, whitespace, malformed input, collision, and idempotency negatives are included where relevant.
4. Operations graders prove no host command or path is required.
5. Writing grader normalization tests cover equivalent date/number punctuation and required caveats without brittle substring rejection.
6. Python and TypeScript visible/hidden suites cover happy paths, boundaries, failure cleanup, and immutability/concurrency contracts.
7. Fake 141-attempt end-to-end run, 47 fake judge results, dynamic package counts, resume, sealed HTTP deny, and optional human overlay tests pass.
8. Real preflight verifies Claude Code, online Flash identity, exact GPT judge, Node TypeScript runtime, accepted GB10 contracts, and protected services.
9. Final report browser checks confirm nonblank desktop/mobile layouts, 47 tasks, 141 answers, 47 rationales, no incoherent overlap, and no horizontal overflow outside intentionally responsive tables.

## Non-Goals

R3 does not run commands on real servers as part of candidate tasks, add local Docker, install test dependencies from the network, claim statistical superiority from one repetition, replace the accepted model runtimes, expose credentials, restore DeepSeek after success, restart pdf2md, or make human scoring a completion dependency.

## Design Playback

Subject: this design at baseline `claude-ds-pilot-r3`.

| Story | Coverage | Evidence |
| --- | --- | --- |
| `US-R3-01` | Covered | Exact 10/10/10/10 task matrix and sandbox artifacts |
| `US-R3-02` | Covered | Preserved Claude Code/treatment contract and manifest-derived counts |
| `US-R3-03` | Covered | Two-layer baseline rank, 47 GPT calls, resume, and one-page report |
| `US-R3-04` | Covered | Candidate deny surface and unchanged receipt-backed host transition |

Drift score: `0`. Gate: `DESIGN_ALIGNED` under the user's explicit continuous-execution delegation.
