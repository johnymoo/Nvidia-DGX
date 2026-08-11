# R3 Extended Benchmark Discovery

Date: 2026-08-12

## Verified Existing Contract

- The R2 corpus has seven manifest-driven tasks, three exact treatments, one Claude Code `2.1.207` execution contract, isolated Git sandboxes, red/gold grader calibration, direct Codex `gpt-5.6-sol/xhigh` judging, receipt-backed resume, and a static final report.
- Candidate tasks have no network, MCP, subagents, parent/sibling access, or fallback.
- DeepSeek and Qwen must run serially on GB10. Success leaves DeepSeek stopped and Qwen healthy on `:8004`.
- The runner and top-level shell still contain fixed `7/14/21` assertions that must become manifest-derived before corpus expansion.
- Node `v25.4.0` is available with built-in TypeScript type stripping and the native test runner. A standalone `tsc` is not installed, so R3 TypeScript tasks must not depend on network package installation.

## User Authority

The user explicitly required:

- ten tasks in each of four directions: terminal use, server operations, bilingual writing, and programming;
- every task to execute in a disposable sandbox;
- no further confirmation, with recommended defaults authorized;
- design, implementation, execution, and the same detailed one-page report to proceed unattended.

## Design Inputs

- Preserve the existing seven tasks and add forty original fixtures: 47 tasks and 141 candidate attempts.
- Split writing into five Chinese and five English tasks.
- Split programming into five Python and five TypeScript tasks.
- Use common operational failure classes without copying public benchmark task text or fixtures.
- Keep nuanced prose evaluation in the GPT judge. Deterministic writing graders check artifact shape, bounded length, and stable facts using aliases/structured values rather than brittle phrase matching.
- Final ranking must be available without a human. Optional human writing review is reported separately and never changes the unattended baseline ranking.

