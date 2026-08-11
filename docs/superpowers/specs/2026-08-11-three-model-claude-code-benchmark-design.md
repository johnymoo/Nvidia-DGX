# Three-Treatment Claude Code Benchmark Design

Date: 2026-08-11

Status: approved; judge contract amended by the user's explicit 2026-08-11 correction to exact Codex `gpt-5.6-sol`/`xhigh`

Baseline revision: `claude-ds-pilot-r2`

Repository baseline: `7ef1804e8b3a3948338e1e82b18f54976ee9bf34`

## Outcome

One validated project-owned command runs a seven-task Claude Code benchmark across three treatments: online DeepSeek Flash, private Patch4 DeepSeek Flash, and private Qwen 3.6 35B. It uses the same real Claude Code binary/version, tools, sandbox policy, task prompt, and timeout for every treatment, forbids fallback, and runs all 21 attempts sequentially.

The command completes the online/private DeepSeek phase, stops both DeepSeek ranks through the active service receipt, force-starts the captured Qwen Compose service, runs Qwen, grades all candidates, invokes an identity-blind model judge, and creates a local seven-page anonymous A/B/C review site. Success leaves DeepSeek stopped and Qwen healthy.

This document defines design only. Benchmark code, fixtures, graders, service commands, and the review server are implementation work outside this phase.

## Approved Baseline

The authoritative evidence is the user's explicit 2026-08-11 instructions, including the final UI decisions "三组并列吧，否则工作量太大" and "分数就 3 档". The following three stories are frozen exactly:

- `US-R2-01`: As a GB10 operator, I want one validated command to finish the online/private DeepSeek phase, stop both Patch4 DeepSeek ranks, start the captured Qwen Docker service, and leave Qwen healthy so that the benchmark follows the authorized model transition without manual per-step operation.
- `US-R2-02`: As a model evaluator, I want online DeepSeek Flash, private Patch4 DeepSeek Flash, and private Qwen 3.6 35B to run the same seven tasks through the same Claude Code version, sandbox policy, prompts, and time limits without fallback so that their end-to-end performance is comparable.
- `US-R2-03`: As a decision maker, I want deterministic hidden grading, an identity-blind independent model judge, and a seven-page anonymous A/B/C human review with three-level scores and delayed reveal so that I can compare all three treatments without provider or performance cues biasing qualitative scoring.

Baseline gate: `BASELINE_APPROVED`. There is no unresolved product decision. This early story approval is distinct from the final rendered-document gate: `DESIGN_ALIGNED` confirms coverage, but implementation planning cannot begin until the user approves the current design file's SHA-256.

| Story | Given | When | Then |
| --- | --- | --- | --- |
| `US-R2-01` | Exact healthy Patch4 DeepSeek or its validated stopped-service start contract, plus captured Qwen Compose state | The operator invokes the formal command | The command owns the DeepSeek phase and receipt-backed Qwen transition; success leaves DS stopped and Qwen healthy |
| `US-R2-02` | One unique seven-task manifest and three exact routes | The corpus runs | Every treatment receives equivalent clean sandboxes and identical Claude Code contracts in 21 sequential, no-fallback attempts |
| `US-R2-03` | Three measured candidate artifacts per task | Grading and review run | Hidden grading, blind judge scoring, and blind human scoring remain separated until delayed reveal |

## Approaches

### A. Extend the existing single command (recommended)

Keep one top-level shell orchestrator and evolve the Python runner into manifest-driven, phase-selectable modules. The shell owns SSH, service state, transitions, recovery, and phase receipts. Python owns sandbox attempts, grading, blind packaging, judging, scoring, and the standard-library review server. Internal phase selection supports tests and receipt-based resume; the normal operator workflow remains one command.

This reuses the accepted r1 controller, runner, fixtures, provider shim, and evidence conventions while directly satisfying the user's one-script constraint.

### B. Separate manual phase scripts

Rejected because manual DeepSeek, transition, Qwen, judge, and review commands make ordering, resume, and cleanup ambiguous and can combine mismatched candidate sets.

### C. External/containerized benchmark platform

Rejected because a local Docker or SWE-bench platform adds dataset, image, orchestration, and deployment contracts without improving this seven-task Claude Code comparison. It conflicts with the approved no-local-Docker direction.

## Architecture

The existing `execution/run-claude-code-flash-pilot.sh` remains the conceptual single entry point. Implementation may deliberately replace its name, but must not add a parallel normal-path driver.

1. **Shell orchestrator:** owns `preflight -> deepseek -> transition -> qwen -> judge -> package`, phase receipts, signals, and phase-aware recovery.
2. **Service adapter:** extends the accepted `execution/run-vllm-service.sh` contract to adopt or start exact DeepSeek, stop both ranks through `active.json`, and force-start captured Qwen without editing Compose.
3. **Manifest runner:** evolves `execution/benchmarks/claude_code_sandbox_pilot.py`; validates the manifest, prepares clean sandboxes, invokes Claude Code, checks identity, captures artifacts/telemetry, and runs hidden graders.
4. **Blind package/scoring module:** normalizes artifacts, creates independent persisted judge and human permutations, validates judge JSON, seals mappings, and calculates scores.
5. **Local review server:** uses Python's standard library, binds to loopback, serves allowlisted public data, persists ratings atomically, and reveals identities only after completion.

No implementation agent is dispatched per benchmark task. One runner loops over all tasks and directly starts Claude Code subprocesses. There is no local Docker benchmark harness; the existing remote Qwen Docker service is an operational dependency.

## Treatments and Claude Code Contract

| Treatment ID | Route | Base URL | Required model |
| --- | --- | --- | --- |
| `online_ds` | `claude_ds` | Configured online DS origin | `deepseek-v4-flash` |
| `offline_ds` | `claude_local` override | `http://192.168.88.181:8890` | `deepseek-v4-flash-0731` |
| `qwen_local` | `claude_local` | `http://192.168.88.181:8004` | `qwen3.6-35b-fp8` |

Private DeepSeek additionally requires image `gb10-ds4-vllm:f277b3d-nvfp4`, vLLM revision `f277b3dfa718a5962bed64e69e7e640a5384ec2f`, normalized fingerprint `36adbf92fe8cdd5c57609b2c5ccfa8e2fc32a340c9ee3d727be538143dda74db`, Patch4, and two-node TP=2.

The manifest pins the same real Claude Code binary/version for all treatments; the existing accepted contract is Claude Code `2.1.207`. Preflight records the binary path/hash, version, coding-agent-toolchain commit, and shim hash. The formal run revalidates them.

Provider, model, and base URL are explicit process-scoped settings. No fallback is configured. Init model/version mismatch, unexpected `modelUsage`, provider identity failure, or catalog/API mismatch is infrastructure failure. Tokens remain process environment only and never enter argv, settings, logs, receipts, or Git.

Each attempt starts from a clean treatment-specific sandbox and receives byte-identical task instructions, output contract, tool policy, and timeout. The allowed surface is the existing built-in file/search/edit/shell set; network, MCP, Chrome, subagents, session persistence, and fallback are disabled. Each attempt has a 900-second wall-clock limit.

## Seven-Task Corpus

The four existing mini-SWE tasks and their fixtures, prompts, graders, and gold solutions remain unchanged. Three non-code tasks write a declared answer artifact in a clean sandbox. Their hidden graders enforce schema, facts, length, and forbidden claims, not prose elegance.

| Order | Task | Contract | DeepSeek order |
| --- | --- | --- | --- |
| 1 | `miniconfig-escaped-paths` | Existing bug-fix mini-SWE task | `online_ds`, `offline_ds` |
| 2 | `retry-after-policy` | Existing feature mini-SWE task | `offline_ds`, `online_ds` |
| 3 | `event-summary-refactor` | Existing refactor mini-SWE task | `online_ds`, `offline_ds` |
| 4 | `ndjson-stream-decoder` | Existing debug-and-test mini-SWE task | `offline_ds`, `online_ds` |
| 5 | `general-knowledge-zh-qa` | Answer eight stable Chinese-language questions in `answers.json`, keyed `q1`-`q8`: Australia's capital, largest ocean, gold's chemical symbol, the Red Planet, author of *Pride and Prejudice*, largest human organ, boiling point of pure water at sea level in Celsius, and days in a leap year. Hidden aliases accept equivalent Chinese/English forms while requiring exactly one answer per key and no extra keys | `online_ds`, `offline_ds` |
| 6 | `patch4-acceptance-zh-brief` | Write 220-320 Chinese characters from fixed facts: run `20260811T002139Z`, date 2026-08-11, model `deepseek-v4-flash-0731` with Patch4, two hosts/TP=2/RoCE/NCCL `NET/IB`, passed correctness/tool/agent/concurrency/40-minute c4 soak, 621 requests, 223,268 generated tokens, zero empty/garbled/HTTP-error responses. Forbid production-SLA, Qwen-co-load, or superiority claims | `offline_ds`, `online_ds` |
| 7 | `first-pilot-result-en-brief` | Write 170-230 English words from fixed facts: Claude Code `2.1.207`; online `deepseek-v4-flash` and private `deepseek-v4-flash-0731`; each passed 3/4 hidden graders; elapsed 571.060 and 417.190 seconds; provider token/cache/cost accounting differs; one repetition proves neither efficiency nor statistical superiority. Forbid an overall winner or significance claim | `online_ds`, `offline_ds` |

The manifest contains exactly seven unique IDs. Fact packets, aliases, prompts, paths, graders, and timeouts are immutable inputs included in the preflight key. Hidden aliases/checks and gold answers never enter candidate sandboxes or prompts.

The seven DeepSeek pairs are balanced as closely as an odd corpus permits: four start online and three offline. After transition, Qwen runs all seven in manifest order. All 21 attempts are sequential with no model concurrency. Qwen's fixed third position is a known phase-order limitation.

For coding tasks, the review artifact is the patch plus concise normalized changed-file context. For QA it is a normalized rendering of `answers.json`; for writing it is `answer.md`. Hidden test output is not exposed before scoring.

## Formal Run

1. **Read-only preflight:** run static, fake, unit, and calibration checks. Accept the exact healthy active Patch4 receipt or validate the stopped-service start contract. Current run `20260811T102904Z`, API `:8890`, and model `deepseek-v4-flash-0731` are eligible only after fresh receipt/rank/API/log/protected-service checks.
2. **DeepSeek:** adopt exact active DS or start worker then head through the controller; verify both ranks/API; run all 14 `online_ds`/`offline_ds` attempts in frozen order.
3. **Transition:** reverify DS, preserve diagnostics, stop head and worker through the active receipt, then force-start the captured Qwen Compose service using its captured path, service, labels, image, command, and port contract. Require healthy `qwen3.6-35b-fp8` on `:8004`.
4. **Qwen:** only now run the first real Qwen Claude probe, validate init identity/version, and execute all seven `qwen_local` attempts.
5. **Judge:** invoke one anonymous independent judge call per task and persist validated results without exposing them to the human UI.
6. **Package/review:** create immutable evidence, public/sealed review packages, the resumable site, and the receipt; print and open the loopback URL. Benchmark-ready success means DS stopped, Qwen healthy, and human review ready. Final quality remains pending until human completion.

`pdf2md`, trading, and lexdata are captured before mutation and checked at each service boundary. For the current state, pdf2md remains stopped while trading and lexdata remain healthy. Success changes only the authorized DS/Qwen state.

## Failure and Recovery

A timeout, nonzero Claude exit, missing/invalid candidate artifact, or failed hidden checks after valid treatment identity is a measured result; it is scored and later tasks continue. Candidate-caused missing output is measured. A calibrated grader process/schema failure is infrastructure failure.

Provider/model/version mismatch, fallback evidence, invalid judge output after retry, unsafe/ambiguous service state, protected-service drift, or invalid phase receipt is infrastructure failure.

- Before Qwen transition, infrastructure failure stops both DS ranks through the active receipt and restores the receipt's captured pre-DeepSeek Qwen/protected-service state.
- During or after transition, DS remains stopped. The command attempts bounded Qwen start/health recovery from the captured Compose contract and never restarts DS automatically.
- Failed Qwen recovery yields `degraded` or `blocked`, never `passed`.
- Signals use the same phase-aware cleanup. Recovery is bounded, idempotent against receipts, and never replaced by undocumented manual steps.

Final success leaves DS stopped, Qwen healthy, pdf2md unchanged, and trading/lexdata unchanged.

## Deterministic and Subjective Scoring

Each hidden grader returns positive `passed` and `total` check counts. The deterministic tier per candidate/task is:

- tier `3`: all checks pass;
- tier `2`: at least half but not all checks pass;
- tier `1`: fewer than half pass, or candidate timeout/missing artifact/candidate-level error.

A grader protocol/schema error is infrastructure failure, not a fabricated score.

The judge is a direct noninteractive Codex CLI invocation using exact model
`gpt-5.6-sol` with reasoning effort `xhigh`; it is not a treatment and does not
use a Claude route. Preflight binds the returned Codex thread ID to its runtime
`turn_context` and requires the observed model, effort, read-only sandbox, and
noninteractive approval policy to match the frozen contract. No fallback is
allowed.

For each task, the judge receives task context and three review artifacts under a fresh persisted random A/B/C permutation independent of the human permutation. It receives no treatment, route, path, order, hidden-grade, timing, tool, token, or cost evidence.

Judge JSON contains integer `1/2/3` scores for each candidate on:

- factual or technical accuracy;
- instruction following;
- clarity and style;

and one overall preference `A/B/C/tie`. It may include a short content-only rationale. Validation rejects missing/extra candidates, non-integers, out-of-range values, identity speculation, and malformed JSON. One bounded retry receives only schema-correction instructions; a second invalid output is infrastructure failure.

For candidate `c` and task `t`:

```text
deterministic_tier(c,t) = hidden pass-ratio tier
judge_layer(c,t)        = mean(accuracy, following, clarity/style)
human_layer(c,t)        = mean(accuracy, following, clarity/style)
quality(c,t)            = mean(deterministic_tier, judge_layer, human_layer)
```

All values stay on the 1-3 scale. Final quality is computed only after human completion. Treatment aggregate quality is the unweighted mean of seven per-task quality scores; layer means are also reported. JSON retains full precision and display rounding is consistent.

Judge and human preference wins/ties are reported separately and never alter numeric scores. Timing, tools, tokens, and provider-reported cost are supporting telemetry revealed only after human completion.

## Human Review Site

The UI authority is:

`.superpowers/brainstorm/23770-1786451377/content/three-treatment-side-by-side-blind-review.html`

Its SHA-256 is `14473ffd410837a9b9c364770bc6bfaa3c50310358c75b832a07bfebbc7dfd4a`. Browser verification covered a 1440 x 1000 desktop viewport and a 390 x 844 mobile viewport; the mobile layout had no horizontal overflow. Implementation follows it for layout, hierarchy, interaction, and responsiveness without reinterpreting the selected design. Its lineage is the approved Option A prototype listed in Sources.

The site has exactly seven task pages. Each shows the prompt at top and Answer A/B/C side by side on desktop; mobile stacks A, then B, then C coherently. Each answer has the same three required criteria, each scored on exactly three levels:

| Score | Meaning |
| ---: | --- |
| `1` | Materially incorrect, incomplete, or unclear |
| `2` | Acceptable with limited errors or weaknesses |
| `3` | Correct, complete, and clear |

The reviewer also selects overall `A/B/C/tie`. Progress shows completed tasks out of seven. `Submit and next` is disabled until all nine criterion ratings and the overall preference are set, then atomically persists and opens the next unrated task. Restart/refresh resumes from persisted ratings.

Each task's random treatment permutation is persisted. The public payload contains only prompt/context, anonymous artifacts, score labels, and progress. It contains no identity, route, attempt order, speed, cost, tokens, tools, stream, hidden-grade, judge, or revealing path clues.

The sealed mapping is outside the served root and inaccessible through generic routes/listing. Ratings use temporary file, flush/fsync, and atomic rename. After all seven pages, the server emits a separate reveal payload joining sealed mappings to ratings/scores, revealing identities and aggregates. Raw sealed files remain unserved.

The standard-library server binds to `127.0.0.1`; its URL is printed and opened after benchmark packaging. It is a local operational review tool, not a hosted/authenticated/multi-user product.

## Evidence

Each content-addressed run root retains:

- manifest, prompts, runner, Claude binary, toolchain, preflight, and service identities;
- per-attempt stream, patch/answer, hidden grading, timing/tools/tokens/cost, and observed model/version;
- phase receipts for preflight, DS, transition, Qwen, judge, package, and final services;
- normalized candidate artifacts and independent judge/human permutations;
- public package, sealed mapping, judge results, atomic human ratings, reveal package, aggregate JSON/Markdown, and final receipt;
- both-rank logs/inspect/events, API/rank/NCCL and fatal CUDA/OOM/worker-loss checks, Qwen health, and protected-service evidence.

The public package is immutable once review starts. Ratings are separate mutable atomic state. Sealed mappings and telemetry stay outside the public allowlist. Receipt hashes bind public data, mappings, judge results, ratings, and aggregates. Secrets are never persisted.

## Preflight and Testing

Preflight is read-only on both GB10 hosts and requires:

1. Shell/static checks plus manifest/parser/scoring/judge/server unit tests.
2. Exactly seven unique tasks, valid safe paths, three exact treatments, balanced DS order, and equal prompt/policy/timeout hashes.
3. Fake stopped-to-DS, exact-active-DS adoption, DS-active-to-Qwen, pre/post-transition failures, bounded Qwen recovery, stale receipt, partial rank, protected drift, and idempotent cleanup tests.
4. Every broken coding fixture and invalid/missing non-code artifact fails; every gold solution/answer passes all checks.
5. Exact online Flash identity plus negative Pro/default, fallback, provider, model-usage, and version tests.
6. Codex `gpt-5.6-sol`/`xhigh` runtime pinning plus judge schema, retry, and blinding tests.
7. Current DS receipt or stopped start contract, accepted image/revision/fingerprint, topology/fabric, ranks/API/logs, and protected services.
8. Captured stopped Qwen Compose path/labels/service/image/command/port/model contract without starting Qwen.
9. Public/sealed separation, persisted permutations, atomic resume, reveal gate, score math, and denied sealed/telemetry HTTP access.

A real Qwen Claude probe occurs only after Qwen starts in the formal transition.

Implementation verification additionally requires all fixture red/gold calibration, a fake sequential 21-attempt end-to-end run, identity/fallback negatives, judge retry tests, sealed/reveal tests, score tests, and browser checks on desktop/mobile for seven pages, three-column/stacked layouts, controls, progress, submit-next, resume, completion, and reveal.

The formal receipt must prove both DS ranks stopped, Qwen `qwen3.6-35b-fp8` healthy on `:8004`, pdf2md still stopped, and trading/lexdata healthy.

## Non-Goals and Limits

This is not an API throughput, TTFT, or serving benchmark. It does not claim statistical superiority from one repetition, include private-repo tasks, deploy externally, add auth/multi-user review, restore DS after success, restart pdf2md, or add a local Docker/SWE-bench harness.

Qwen always runs after DS because they cannot safely co-load, so phase order remains a confound. The judge is subjective rather than ground truth, and one human rating set does not estimate inter-rater agreement. Layer-separated reporting and the no-superiority rule keep those accepted limits visible; they are not unresolved product decisions.

## Design Playback

Subject: this design at baseline `claude-ds-pilot-r2`.

| Stable story, quoted verbatim | Evidence | Status |
| --- | --- | --- |
| `US-R2-01`: As a GB10 operator, I want one validated command to finish the online/private DeepSeek phase, stop both Patch4 DeepSeek ranks, start the captured Qwen Docker service, and leave Qwen healthy so that the benchmark follows the authorized model transition without manual per-step operation. | One shell state machine, active/stopped DS handling, receipt-backed transition, forced captured-Compose Qwen start, DS-stopped/Qwen-healthy receipt | Covered |
| `US-R2-02`: As a model evaluator, I want online DeepSeek Flash, private Patch4 DeepSeek Flash, and private Qwen 3.6 35B to run the same seven tasks through the same Claude Code version, sandbox policy, prompts, and time limits without fallback so that their end-to-end performance is comparable. | Exact routes/models, seven tasks, identical Claude contract, balanced DS order, 21 sequential attempts, identity/no-fallback gates | Covered |
| `US-R2-03`: As a decision maker, I want deterministic hidden grading, an identity-blind independent model judge, and a seven-page anonymous A/B/C human review with three-level scores and delayed reveal so that I can compare all three treatments without provider or performance cues biasing qualitative scoring. | Tier math, blind Codex `gpt-5.6-sol`/`xhigh`, independent permutations, seven A/B/C pages, three-level criteria, sealed delayed reveal | Covered |

Drift: none. Drift score: `0`. Gate: `DESIGN_ALIGNED`.

## Sources

- `docs/superpowers/specs/2026-08-11-claude-code-flash-pilot-design.md`, SHA-256 `14bb97de808c561646aa6db6b708346c7c9f770fab2ba12001fd786633c20c41`
- `planning/02-working/2026-08-11-claude-ds-local-benchmark-discovery.md`, SHA-256 `8d122094e335a1b56a11d2d1aa525f38e3d16f33155c70aee9d32dd91cc7817b`
- `planning/03-core/02-official-0731-deployment.md`
- `planning/03-core/03-operations-runbook.md`
- `planning/03-core/05-multi-model-capacity-plan.md`
- `execution/run-vllm-service.sh`
- `execution/run-claude-code-flash-pilot.sh`
- `execution/benchmarks/claude_code_sandbox_pilot.py`
- `execution/benchmarks/claude-code-sandbox-pilot-tasks.json`
- coding-agent-toolchain commit `c074ba8f6858f3646b0f6f27435b48c1678d33b8`: `bin/claude`, `shell/claude.sh`, `.env.example`, `README.md`, and `llm-deployment.md`
- approved Option A prototype `.superpowers/brainstorm/23770-1786451377/content/blind-review-layout-options.html`, SHA-256 `fe9e5f246dd43d335ff740bf36d1d59f847a0bf6d9036272ff7f16436998c118`
- updated UI authority `.superpowers/brainstorm/23770-1786451377/content/three-treatment-side-by-side-blind-review.html`, SHA-256 `14473ffd410837a9b9c364770bc6bfaa3c50310358c75b832a07bfebbc7dfd4a`
- user-provided live read-only state and approval evidence from 2026-08-11
