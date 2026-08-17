# Deployment and benchmark workflows

## Prepare once

1. Download the pinned official checkpoint on the head and verify its revision.
2. Transfer the exact model tree to the worker and compare a complete SHA-256
   manifest, including all shards and configuration/tokenizer files.
3. Build or import the same Patch4 runtime image on both nodes and compare its
   OCI source revision and normalized content fingerprint.
4. Copy this project to both nodes, create node-local `.env` files, and render
   Compose without starting containers.
5. Verify the fabric carrier, MTU, peer reachability, RDMA ACTIVE state, GID,
   Docker GPU access, `/dev/infiniband`, model files and API port availability.

Do not use model startup as a substitute for these checks. Fail before stopping
another GPU workload whenever immutable inputs or fabric state do not match.

## Start DeepSeek

```text
capture existing GPU service state
             |
stop conflicting GPU services
             |
render and verify worker/head Compose
             |
start worker rank 1
             |
start head rank 0
             |
wait for API + both-rank evidence
             |
run identity, deterministic and concurrent checks
```

For thinking-on, render both Compose files and run `verify_thinking.py` against
the result before startup. The override replaces the complete command because
Compose does not merge command list elements individually.

Minimum live checks are `/health`, `/v1/models`, a deterministic generation,
tool-call parsing, concurrent requests, a bounded soak, both rank logs, and
NCCL `NET/IB` evidence without socket fallback. Save the rendered configuration
and image/model identities with the logs.

## Stop or roll back

Stop head then worker. Confirm the API is closed and both distributed ranks are
gone before restoring the previously captured GPU service. Recovery must be
based on that captured state; do not assume a service was running before the
maintenance window.

Rollback means returning to a previously verified image/config/model tuple,
not changing one speculative parameter while retaining the failed service.
Keep the failed render, inspect data and logs for diagnosis.

## Claude Code benchmark

The reusable framework under `benchmark/` runs the complete corpus in one
script, not one manually dispatched agent per task:

```text
offline corpus/grader calibration
             |
Claude Code + online DS identity probe
             |
Online DS and Private DS: 47 tasks each
             |
service hook: stop/offload DeepSeek, activate Qwen
             |
Private Qwen: 47 tasks
             |
GPT xhigh blind A/B/C judging: 47 tasks
             |
optional human scores for writing only
             |
summary page + complete detail page
```

Each candidate gets the same instruction, Claude Code version, tool allowlist,
timeout and fresh Git sandbox. The runner verifies model identity and forbids a
fallback model. Executable graders are primary evidence; the GPT judge adds
content quality scoring and a rationale. Provider token and cost accounting are
not directly comparable.

Use `benchmark/run.sh preflight` before a real run, then
`benchmark/run.sh run`. The service lifecycle hooks are deliberately external:
the benchmark can reuse any validated cluster controller without embedding SSH
aliases, Docker assumptions or private addresses.

## Thinking regression workflow

Thinking is enabled by the chat template parameter and proven from actual
Claude Code stream events. The reasoning parser alone only structures thinking
that the model already emitted.

The focused rerun selects five frozen tasks where the prior private DeepSeek
score was below Online DS, runs private DeepSeek with thinking enabled, requires
at least one thinking block per stream, and compares old private, thinking-on
private and original online answers with a new blind judge. This diagnostic is
directional; one rerun per task is not a significance claim.
