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

```bash
cd /home/chriswang/gb10-ds4
ACCEPTANCE_SKIP_PRESTART_CHECK=1 \
ACCEPTANCE_KEEP_QWEN_STOPPED_ON_FAILURE=1 \
ACCEPTANCE_RESTORE_QWEN_ON_SUCCESS=1 \
ACCEPTANCE_PRESERVE_DEEPSEEK_CONTAINERS=1 \
timeout --foreground 10800 execution/run-vllm-acceptance.sh --run
```
On failure inspect `monitor.log`, final logs, inspect JSON, and Docker events
in that run artifact before changing any setting. Keep the timeout override
active; do not activate the memory-profile override without explicit approval.

Status uses `docker ps -a`, receipt JSON, `curl :8890/v1/models` during the
window, and Qwen `curl http://192.168.88.181:8004/v1/models` after recovery.
The success path stops DeepSeek on both hosts. With the documented
`ACCEPTANCE_RESTORE_QWEN_ON_SUCCESS=1`, it forces Qwen service
`vllm-qwen36-35b-nvfp4` healthy even when the captured state was stopped;
without that override the script preserves the captured state.
`ACCEPTANCE_KEEP_QWEN_STOPPED_ON_FAILURE=1` deliberately defers Qwen restore
on acceptance failure for the maintenance window. If sudo is genuinely needed
for host fabric or maintenance, use the restricted project wrappers; never
store or request a password here.

```bash
ssh gb10 'docker ps -a; tail -100 /home/chriswang/gb10-ds4/artifacts/acceptance/<UTC>/monitor.log'
ssh gb10 'jq . /home/chriswang/gb10-ds4/artifacts/acceptance/<UTC>/receipt.json'
ssh gb10-2 'docker ps -a'
```

The acceptance script always stops DeepSeek after acceptance. It is not a
validated leave-running production launcher; persistent start is a gap, not a
manual multi-command production procedure.

## Persistent Patch4 Service and Claude Code Pilot

Status: candidate pending the first `claude-ds-pilot-r1` real-run receipt.

Run the local preflight first. It performs static/fake checks, the accepted
two-host read-only checks, online Flash identity probing, and official
SWE-bench gold calibration before any model service changes:

```bash
cd /Users/chris/project/Shili/workspaces/dev-lite/GB10-DS
execution/run-claude-code-flash-pilot.sh --preflight
```

The formal pilot is one command. The script captures and stops Qwen, starts the
worker then head Patch4 DeepSeek ranks, runs the frozen Claude Code task loop,
grades both treatments, and leaves DeepSeek running on success. Infrastructure
failure automatically stops DeepSeek and restores the captured Qwen state.

```bash
execution/run-claude-code-flash-pilot.sh --run
```

Status is read-only. The explicit rollback stops DeepSeek and restores only the
captured Qwen state, then verifies the protected services:

```bash
execution/run-claude-code-flash-pilot.sh --status
execution/run-claude-code-flash-pilot.sh --restore-qwen
```

The head service controller is
`/home/chriswang/gb10-ds4/execution/run-vllm-service.sh`. Its active-state
receipt is `/home/chriswang/gb10-ds4/artifacts/service/active.json`. Do not
manually start or stop one DeepSeek rank while this receipt exists. Local pilot
evidence is under ignored `execution/artifacts/claude-code-pilot/runs/<UTC>/`;
the head artifact named in `active.json` centralizes both-rank runtime evidence.

## Unsloth A/B

Use base `execution/unsloth/docker-compose.yml` plus the additive
`docker-compose.reasoning-off.yml`. Worker RPC binds only fabric
`192.168.192.198:50052`; head RPC is loopback `127.0.0.1:50053`; API is 8891.
Start worker RPC, then head RPC, then exactly one server profile. Stop target
before DSpark; keep RPC running between profiles. The reasoning override makes
OpenAI `content` usable rather than consuming responses in reasoning_content.

```bash
# Worker first, on gb10-2
cd /home/admin/gb10-ds4
docker compose --env-file execution/unsloth/env/common.env --env-file execution/unsloth/env/node.env \
  -f execution/unsloth/docker-compose.yml -f execution/unsloth/docker-compose.reasoning-off.yml up -d rpc

# Then head RPC and one profile, on gb10
cd /home/chriswang/gb10-ds4
docker compose --env-file execution/unsloth/env/common.env --env-file execution/unsloth/env/node.env \
  -f execution/unsloth/docker-compose.yml -f execution/unsloth/docker-compose.reasoning-off.yml up -d rpc
docker compose --env-file execution/unsloth/env/common.env --env-file execution/unsloth/env/node.env \
  -f execution/unsloth/docker-compose.yml -f execution/unsloth/docker-compose.reasoning-off.yml --profile target up -d server-target
curl -fsS http://127.0.0.1:8891/v1/models
```

Switch by stopping `server-target` and starting `server-dspark` with the same
two `-f` files and env files. Status is `docker ps -a`, `docker logs`,
`ss -ltnp`, and the API smoke above. Stop `server-dspark rpc` on head and
`rpc` on worker with the same Compose command before Qwen recovery.

```bash
cd /home/chriswang/.hermes/profiles/capital-avatar/deployments/qwen36-35b-nvfp4
docker compose -f compose.yml up -d vllm-qwen36-35b-nvfp4
curl -fsS http://192.168.88.181:8004/v1/models
```

Stop both server/RPC containers on both hosts before restoring Qwen. Preserve
logs and inspect before stopping a failed server.
