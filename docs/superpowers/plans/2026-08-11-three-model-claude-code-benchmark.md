# Three-Model Claude Code Benchmark Delivery Plan

Date: 2026-08-11

Status: approved for continuous execution by the user's approval of design SHA-256 `9e358baebbc0d31e81c0dcbcf3c4355ef8f9e92f8309c8ad85169d6583cad2ad`, the user's 2026-08-11 correction that supersedes the prior judge route with exact `gpt-5.6-sol`/`xhigh`, and the prior instruction to proceed from preflight to the formal run without another confirmation.

Authority:

- Design: `docs/superpowers/specs/2026-08-11-three-model-claude-code-benchmark-design.md`
- Design commit: `dc0235c`
- Current amended design SHA-256: `b57b21e69c1e369355ab1d73a2f678b94f1e1541e4ebf43f644abfd9af08550b`; amendment authority is the user's explicit 2026-08-11 `gpt-5.6-sol`/`xhigh` correction
- Baseline: `claude-ds-pilot-r2`
- Visual authority: `.superpowers/brainstorm/23770-1786451377/content/three-treatment-side-by-side-blind-review.html`, SHA-256 `14473ffd410837a9b9c364770bc6bfaa3c50310358c75b832a07bfebbc7dfd4a`
- Repository base SHA: `dc0235c923e968ea041776d83dc5dfa1cec28070`
- Coordinator runtime: Codex
- Worktree owner: current coordinator; one writer at a time

## Goal And Completion

Implement and execute the approved seven-task, three-treatment benchmark through one validated script. Completion requires:

- all 21 Claude Code treatment attempts run sequentially with exact identities and no fallback;
- deterministic hidden grading and blind Codex `gpt-5.6-sol`/`xhigh` judging complete;
- the seven-page anonymous A/B/C human review site is running and resumable;
- the public payload contains no identity or performance clues before completion;
- both Patch4 DeepSeek ranks are stopped, Qwen `qwen3.6-35b-fp8` is healthy on `:8004`, pdf2md remains stopped, and trading/lexdata remain healthy;
- focused tests, fake end-to-end tests, preflight, formal receipt, and final service evidence pass.

Non-goals and failure semantics are inherited unchanged from the approved design. No API serving benchmark, local Docker/SWE-bench harness, private-repo corpus, repeated statistical run, or pdf2md restart is added.

## Target-Host Contract

- `gb10`: exact accepted Patch4 head/API and captured Qwen Compose contract; 119.6 GiB unified memory; ports `8890` then `8004`; no DS/Qwen co-load.
- `gb10-2`: exact accepted Patch4 worker over active RoCE fabric; lexdata must remain healthy.
- Both: kernel `6.17.0-1014-nvidia`, driver `580.142`, accepted image/revision/fingerprint, active fabric carrier, no fallback model/service.
- Current mutable fact must be rechecked before implementation claim and again by the formal script: DS service receipt `20260811T102904Z` is exact and active; Qwen is stopped but its Compose/image/model contract is recoverable.
- Host preflight failure blocks product implementation or execution until repaired within the approved contract. A second real host failure in the same maintenance window stops further host mutation.

## Wave 0: Authority And Environment

1. Validate the approved design hash, visual hash, Git base, profile catalog, and absence of BMAD routing.
2. Record fresh read-only host evidence for memory, GPU process/container state, ports, DS active receipt/API/ranks, Qwen restore contract, protected services, and fabric.
3. Approve Suggested routing from the user's continuous-execution authorization: `codex_terra` native implementer for the writer; `codex_sol` manual coordinator for final scripted execution and failure analysis.
4. Run a zero-write implementer routing preflight before dispatch.

## Wave 1: R2 Implementation

Task `R2-IMPLEMENT`, stories `US-R2-01`, `US-R2-02`, `US-R2-03`.

Scope:

- `execution/run-claude-code-flash-pilot.sh`
- `execution/run-vllm-service.sh`
- `execution/benchmarks/**`
- focused operational documentation updates only when commands or receipts change

Acceptance:

- manifest is dynamic and contains the existing four coding tasks plus general knowledge, Chinese writing, and English writing;
- runner supports `online_ds`, `offline_ds`, and `qwen_local` phases, exact identities, declared non-code artifacts, deterministic tiers, blind judge packaging, and no fallback;
- service controller supports receipt-backed DS-to-Qwen transition with bounded recovery and protected-state checks;
- local review server implements the approved three-column, three-level, seven-page sealed/reveal flow and atomic resume;
- top-level `--preflight` is non-mutating on hosts, and `--run` owns the full phase state machine;
- candidate task failures remain measured results while infrastructure failures fail closed.

Focused tests:

- Python unit/fake suite for manifest, fixtures, graders, identities, scoring, judge schema/retry, permutations, sealed HTTP deny, resume, reveal, and receipts;
- shell fake suites for current-active DS adoption, DS-to-Qwen transition, pre/post-transition recovery, protected-service drift, and top-level rollback;
- all broken fixtures fail and all gold fixtures pass;
- fake 21-attempt end-to-end run passes without Docker or external model calls;
- shell syntax, Python compile, ShellCheck when available, and `git diff --check` pass.

Risk class: `contract`. One writer owns all listed files because the runner, state machine, and receipt schema are tightly coupled.

## Wave 2: Integration And Scripted Execution

Task `R2-RUN`, dependent on `R2-IMPLEMENT`, stories `US-R2-01`, `US-R2-02`, `US-R2-03`.

1. On the stable implementation head, run the full focused suite once and verify the integrated diff against the approved design and host contract.
2. Run exactly one top-level `--preflight`. If it fails, inspect the script artifacts, repair the script/environment within the frozen design, rerun focused checks, then retry preflight.
3. After preflight passes, invoke exactly one top-level `--run`; the script owns all treatment loops, service transition, retries, health checks, judge calls, evidence, and final summary.
4. Re-enter manually only on nonzero exit, rollback, degraded/blocked receipt, timeout, or an unmodeled invariant. Never finish the normal path with per-task Agent calls or manual service commands.
5. Verify the final receipt, exact treatment/model/version evidence, protected services, DS stopped/Qwen healthy state, and browser behavior at desktop and mobile viewports.
6. Publish the review URL while identities remain sealed. Final human aggregate is expected only after the user submits all seven pages.

## Alignment And Stop Conditions

- `R2-IMPLEMENT` closes only when the coordinator independently maps tests and diff to all three baseline stories with drift score 0.
- `R2-RUN` closes only when the review site and final host state are directly observable with drift score 0.
- Provider/model/version mismatch, fallback, protected-service drift, invalid judge output after retry, unsafe receipt state, or failed Qwen recovery blocks completion.
- Measured candidate failures do not block later attempts and are not repaired by the coordinator.
- Exact next action after this Plan: initialize the Ledger, record fresh host preflight, approve the preauthorized Suggested assignments, and dispatch `R2-IMPLEMENT`.
