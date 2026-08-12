# DeepSeek V4 dual-DGX Spark documentation

These documents describe the reusable deployment and evaluation contract. All
addresses and hostnames are placeholders; keep real infrastructure data in
untracked `.env` files.

| Document | Contents |
|---|---|
| [Cluster topology](cluster-topology.md) | Two-node roles, data/control planes, startup order and failure boundaries |
| [Workflows](workflows.md) | Deployment, validation, benchmark, model transition and recovery workflows |
| [Parameter guide](parameters.md) | vLLM, distributed, NCCL/RDMA, MTP, MLA KV and thinking settings |
| [References](references.md) | Model downloads, pinned upstream repositories and primary documentation |

The executable source of truth remains `docker-compose.yml`,
`docker-compose.thinking-on.yml`, and `benchmark/tasks.json`. When a document
and a rendered configuration disagree, stop and reconcile them before launch.
