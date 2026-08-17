# Reusable Claude Code benchmark

This is the frozen benchmark used to compare Online DeepSeek Flash, private
DeepSeek V4 Flash Patch4, and private Qwen 3.6 35B through Claude Code.

## Corpus

`tasks.json` defines 47 tasks and 141 candidate attempts:

| Group | Tasks | Coverage |
|---|---:|---|
| Pilot | 7 | Mini-SWE, general knowledge, Chinese and English briefs |
| Terminal | 10 | Shell pipelines, archives, permissions, checksums and safe filenames |
| Server operations | 10 | systemd, OOM, TLS, Nginx, backup, disk and rollback |
| Writing | 10 | Five Chinese and five English operational writing tasks |
| Programming | 10 | Five Python and five TypeScript tasks |

Each task references a clean `fixtures/` workspace, a deterministic grader in
`graders/`, and a calibration answer in `solutions/`. Calibration answers are
used only by preflight and are never copied into candidate sandboxes. Domain
fragments under `r3/` can be rebuilt with `python3 merge_manifest.py`.

## Runtime contract

- All candidates use the pinned Claude Code version in `tasks.json`.
- Online DS uses `claude_ds` / `deepseek-v4-flash`.
- Private DS uses `claude_local` / `deepseek-v4-flash-0731`.
- Private Qwen uses `claude_local` / `qwen3.6-35b-fp8`.
- Each attempt gets a new temporary Git sandbox copied from its fixture.
- Claude Code runs with safe mode, empty MCP configuration, no session
  persistence, and only Bash/Edit/Read/Glob/Grep/Write tools.
- Deterministic grading runs after every attempt. GPT
  `gpt-5.6-sol/xhigh` then judges anonymous A/B/C answers with no fallback.
- Human scoring is optional and is exposed only for writing tasks.

The framework does not manage GPUs, Docker, or SSH. Three optional lifecycle
hooks activate the required private model before each phase. DeepSeek and Qwen
phases are serial so the same cluster can be reused.

## Configuration

Export the variables in `.env.example` from a private file. Required values:

| Variable | Purpose |
|---|---|
| `CODING_AGENT_TOOLCHAIN` | Repository containing executable `bin/claude` route shim |
| `CLAUDE_DS_BASE_URL` | Online DeepSeek Anthropic-compatible endpoint |
| `PRIVATE_DS_BASE_URL` | Private DeepSeek endpoint |
| `QWEN_LOCAL_BASE_URL` | Private Qwen endpoint |

Optional trusted shell hooks are `BENCHMARK_PREPARE_DEEPSEEK_CMD`,
`BENCHMARK_PREPARE_QWEN_CMD`, and `BENCHMARK_FINALIZE_CMD`. Provider tokens are
consumed by the route shim's normal environment contract; never add them to
`tasks.json`.

## Run

Offline tests and a synthetic 141-attempt report need no model access:

```bash
./run.sh test
./run.sh fake
```

`fixtures/` contains challenge inputs, not repository regression projects.
Several untouched programming fixtures are intentionally failing: the official
offline harness first confirms baseline failure, overlays the calibration
solution in an isolated temporary copy, and then requires the grader to pass.
Do not run broad `unittest` discovery inside individual challenge fixtures and
interpret those expected failures as repository regressions. The supported
repository-only check is exactly `./run.sh test`; `./run.sh fake` generates a
synthetic report but is not part of CI acceptance.

Real endpoint/judge preflight and the complete run are single commands:

```bash
./run.sh preflight
./run.sh run
```

The full run writes `review/public/index.html` for the summary and
`review/public/details.html` for every question, all three answers, scores and
GPT rationale. Attempt state and phase receipts remain under the same ignored
artifact directory. Resume or rerender with:

```bash
./run.sh resume benchmark/artifacts/runs/RUN_ID
./run.sh report benchmark/artifacts/runs/RUN_ID
./run.sh serve benchmark/artifacts/runs/RUN_ID
```

The review server binds only to `127.0.0.1`.

## Focused thinking rerun

`rerun_thinking.py` reuses a completed run, selects the frozen five-task
regression set, reruns private DeepSeek, verifies explicit thinking events and
invokes a new blind judge. Set `THINKING_RERUN_SOURCE` or pass `--source-run`.
Service activation remains the caller's responsibility.

## Dependencies and limitations

- Python 3.9+, Bash, Git, Node.js with erasable TypeScript support, Claude Code
  2.1.207, Codex CLI, and the external route shim.
- Terminal tasks target a Unix-like sandbox with standard utilities.
- One sample per model per task supports reproducibility but does not establish
  statistical superiority.
- Judge identity is checked against the local Codex session audit record.
