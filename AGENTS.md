# GB10 DeepSeek Deployment Workspace

## Mission

Deploy and verify `DeepSeek-V4-Flash-0731` across two NVIDIA GB10 / DGX Spark
hosts. Preserve enough evidence that another engineer can reproduce, operate,
and troubleshoot the deployment.

## Hosts

Use the exact lowercase SSH aliases from `~/.ssh/config`:

- `gb10`: head candidate, `chriswang@192.168.88.181`
- `gb10-2`: worker candidate, `admin@192.168.88.198`

Do not store credentials, private keys, tokens, or sudo passwords in this
workspace. Treat existing services on either host as user workloads. Inventory
and preserve them unless the user explicitly authorizes replacement.

## Information Flow

- `planning/01-raw`: upstream repositories, raw captures, papers, and unvetted
  research. Contents are Git-ignored except for its README.
- `planning/02-working`: checked observations, experiments, alternatives, and
  preliminary conclusions usable by implementation work.
- `planning/03-core`: current, directly executable runbooks, configuration
  contracts, recovery steps, and verified acceptance evidence.
- `execution`: project-owned scripts and small configuration templates used to
  perform or verify the deployment. Never commit secrets.

Promote information only after checking it against the live hosts or a cited
upstream source. When live state changes, update the evidence date and mark old
conclusions as superseded instead of silently rewriting history.

## Deployment Acceptance

A deployment is complete only when:

1. both hosts participate in the same distributed inference process;
2. the head exposes an OpenAI-compatible API;
3. model identity and runtime configuration match the intended 0731 checkpoint;
4. deterministic generation, concurrent requests, and a bounded soak test pass;
5. logs show both ranks and no fatal NCCL, CUDA, OOM, or worker-loss errors;
6. start, status, stop, rollback, and recovery commands are recorded in
   `planning/03-core`.
