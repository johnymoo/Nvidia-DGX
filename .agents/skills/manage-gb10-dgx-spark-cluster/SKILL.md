---
name: manage-gb10-dgx-spark-cluster
description: Safely inventory, operate, recover, and verify the two-node GB10 DGX Spark inference cluster.
---

# Manage GB10 DGX Spark Cluster

Use for `gb10` and `gb10-2`. Begin read-only with `free -h`, `swapon --show`,
`nvidia-smi`, `docker ps/stats/inspect`, `ss`, `rdma link show`, and fabric
carrier/IP checks. Treat `nvidia-smi [N/A]` as unknown GPU memory, not zero.
Read [operations](references/operations.md) for volatile paths and contracts.

## Guardrails

- Preserve Qwen `:8004`, pdf2md, trading, and lexdata unless an authorized
  maintenance window says otherwise.
- Never edit an existing Compose file. Create a named additive override only
  when required and approved; render it on both hosts before use.
- Official DeepSeek is worker-first/head-second, saves logs/inspect/events
  before cleanup, and restores only the captured Qwen state.
- Unsloth worker RPC is fabric-only. Run target and DSpark serially and retain
  failed-profile evidence before stopping it.
- Ask for sudo only when a host command demonstrably requires it; use project
  wrappers and never handle passwords.

## Evidence

Write UTC artifacts on both hosts with config render, service states,
logs/inspect/events, receipt, and benchmark JSON. Do not commit artifacts or
real env files. Consult the core runbooks for acceptance and capacity facts.
