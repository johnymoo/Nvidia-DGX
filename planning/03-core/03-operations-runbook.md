# Operations Runbook

## Protected Services

Qwen Compose lives at
`/home/chriswang/.hermes/profiles/capital-avatar/deployments/qwen36-35b-nvfp4/compose.yml`.
It serves `qwen3.6-35b-fp8` on `192.168.88.181:8004`. Capture its inspect and
Compose labels before a maintenance window. Do not stop pdf2md, trading, or
lexdata for DeepSeek work.

## Official DeepSeek

Read-only check:

```bash
cd /home/chriswang/gb10-ds4
execution/run-vllm-acceptance.sh --check
```

An authorized run is `execution/run-vllm-acceptance.sh --run`; it owns Qwen
capture, worker-first/head-second startup, evidence, cleanup, and recovery.
On failure inspect `monitor.log`, final logs, inspect JSON, and Docker events
in that run artifact before changing any setting. Keep the timeout override
active; do not activate the memory-profile override without explicit approval.

Status uses `docker ps -a`, receipt JSON, `curl :8890/v1/models` during the
window, and Qwen `curl http://192.168.88.181:8004/v1/models` after recovery.
The success path stops DeepSeek on both hosts and restores Qwen only if it was
captured running. If sudo is genuinely needed for host fabric or maintenance,
use the restricted project wrappers; never store or request a password here.

## Unsloth A/B

Use base `execution/unsloth/docker-compose.yml` plus the additive
`docker-compose.reasoning-off.yml`. Worker RPC binds only fabric
`192.168.192.198:50052`; head RPC is loopback `127.0.0.1:50053`; API is 8891.
Start worker RPC, then head RPC, then exactly one server profile. Stop target
before DSpark; keep RPC running between profiles. The reasoning override makes
OpenAI `content` usable rather than consuming responses in reasoning_content.

Stop both server/RPC containers on both hosts before restoring Qwen. Preserve
logs and inspect before stopping a failed server.
