# GB10 DeepSeek Deployment Workspace

This workspace records a verified two-node GB10 deployment of
`DeepSeek-V4-Flash-0731` and an isolated llama.cpp/Unsloth A/B evaluation.

## Current State

- Official vLLM/DSpark 0731 + Patch4 acceptance passed on 2026-08-11.
- Qwen is the active protected workload on `gb10:8004` as
  `qwen3.6-35b-fp8`.
- DeepSeek and Unsloth containers are stopped; their evidence remains on the
  hosts. pdf2md, trading, and lexdata remain user workloads.

Start with [core runbooks](planning/03-core/README.md). Raw sources remain
under `planning/01-raw` and are not Git-tracked.
