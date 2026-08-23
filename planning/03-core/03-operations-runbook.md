# Operations Runbook

## Protected Services

Status changed 2026-08-17: `192.168.88.181:8004` is a lightweight proxy to the
private X570 Qwen3.8 MTP2 service at `192.168.88.75:18001`. Both the public and
upstream model ID are `qwen3.8-27b-mtp2`. The proxy uses base Compose
`/home/chriswang/gb10-qwen-proxy/compose.yml` plus additive override
`compose.model-id-qwen38.yml`; it uses no GB10 GPU and may stay running while
DeepSeek owns both GB10 accelerators.

The stopped local Qwen rollback Compose lives at
`/home/chriswang/.hermes/profiles/capital-avatar/deployments/qwen36-35b-nvfp4/compose.yml`.
It must not be started while the proxy owns port 8004. Capture inspect and
Compose labels before a maintenance window. Do not stop pdf2md, trading, or
lexdata for DeepSeek work.

Proxy status and restart:

```bash
ssh gb10 'cd /home/chriswang/gb10-qwen-proxy && docker compose -f compose.yml -f compose.model-id-qwen38.yml ps'
curl -fsS http://192.168.88.181:8004/v1/models
ssh gb10 'cd /home/chriswang/gb10-qwen-proxy && docker compose -f compose.yml -f compose.model-id-qwen38.yml restart proxy'
```

### Proxy Timeout Recovery

The proxy separates the short LAN connection timeout from the longer model
response idle timeout. `CONNECT_TIMEOUT_SECONDS=5` applies only while opening
the TCP connection to X570; after that connection succeeds, the socket uses
`IDLE_TIMEOUT_SECONDS=900` for request upload, first response headers, and
subsequent response/SSE reads. Do not reduce the latter to the connect timeout:
long prompts and images can legitimately take more than five seconds before
their first token.

The deployed timeout-fix evidence is retained on GB10 under
`/home/chriswang/gb10-qwen-proxy/receipts/timeout-fix-20260813T080857Z`.
The pre-fix proxy bundle is in its `baseline/` subdirectory. To return only the
proxy code to that bundle, preserving all other services:

```bash
ssh gb10 'set -eu; cd /home/chriswang/gb10-qwen-proxy; cp receipts/timeout-fix-20260813T080857Z/baseline/proxy.py proxy.py; docker compose -f compose.yml -f compose.model-id-qwen38.yml up -d --force-recreate proxy; curl -fsS http://127.0.0.1:8004/v1/models'
```

For an unavailable X570 upstream, the proxy must still return bounded HTTP 502
with `{"error":{"message":"Qwen upstream unavailable",...}}`. A failed
long request should be investigated through the proxy and X570 model logs;
do not restart Qwen, OPF, DeepSeek, or other protected services to repair the
proxy. If old client-side `CLOSE_WAIT` sockets remain after the fix, capture
their owning PIDs first and restart only the affected authorized user services:

```bash
ssh x570 'systemctl --user restart opencode-memory-ingest.service shili-harness-wiki-sync.service'
ssh x570 'ss -tanp | grep "CLOSE-WAIT.*192\\.168\\.88\\.181:8004" || true'
```

Rollback to the GB10-local FP8 model requires a bounded service interruption.
Stop the proxy first, then start the captured local Compose and allow up to 15
minutes for model loading:

```bash
ssh gb10 'cd /home/chriswang/gb10-qwen-proxy && docker compose down'
ssh gb10 'cd /home/chriswang/.hermes/profiles/capital-avatar/deployments/qwen36-35b-nvfp4 && docker compose up -d vllm-qwen36-35b-nvfp4'
curl -fsS http://192.168.88.181:8004/v1/models
```

To return to the X570 route, stop only the local Qwen service, wait for port
8004 to be free, and start the proxy:

```bash
ssh gb10 'cd /home/chriswang/.hermes/profiles/capital-avatar/deployments/qwen36-35b-nvfp4 && docker compose stop vllm-qwen36-35b-nvfp4'
ssh gb10 'cd /home/chriswang/gb10-qwen-proxy && docker compose -f compose.yml -f compose.model-id-qwen38.yml up -d proxy'
curl -fsS http://192.168.88.181:8004/v1/models
```

Do not run the legacy acceptance mode with
`ACCEPTANCE_RESTORE_QWEN_ON_SUCCESS=1` while the proxy owns port 8004; that
option attempts to restore the stopped local Qwen container. The persistent
DeepSeek service path captures the local Qwen container as stopped and leaves
the proxy untouched.

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

The acceptance script always stops DeepSeek after acceptance. Use the
persistent service controller below for a leave-running deployment; do not
substitute manual per-rank Compose commands.

## Persistent Patch4 Inference Service

Status: running. Production defaults to thinking-on through
`execution/run-private-ds-production.sh`; the active run ID is recorded in
`artifacts/service/active.json`. Current production run
`20260823T164410Z` started on 2026-08-24 (local) and records
`thinking: true`.

### Long-context TTFT scheduler profile (2026-08-24)

Portal data showed 12-83 requests/day waiting 30-352 s for the first token:
any 400K+ cold prefill monopolized the whole 8192-token chunked-prefill
budget, head-of-line blocking every other request (including ~99% cache-hit
agent turns needing only a few hundred new tokens) and pinning concurrent
decode at ~0.8 tok/s. The service now passes
`--long-prefill-token-threshold 6144`: a request with more than 6144
remaining prefill tokens is capped at 6144 per step, leaving ~2048
tokens/step for cache-hit tails, small prompts, and decode. Do not set
`--max-num-partial-prefills` on this fork - `arg_utils
_check_feature_supported` rejects it at boot, and the V1 scheduler admits
concurrent prefills purely by token budget anyway.

Measured on 2026-08-24: small requests during a 130K cold prefill return in
~11 s (previously blocked for the full prefill); solo cold prefill costs
about 4% (64K uncached: 34.6 s -> 36.2 s); decode unchanged (~62 tok/s
structured); boot KV pool 8.81 GiB / 1,221,928 tokens. Raising
`MAX_NUM_BATCHED_TOKENS` to 16384 was tried and rejected: profiled
activations grew and left 6.32 GiB KV, below the 7.3 GiB floor the frozen
1,048,576-token context requires, so the step budget stays 8192.

Rollback: remove `LONG_PREFILL_TOKEN_THRESHOLD` from
`execution/env/common.env` on both hosts (compose default then still applies
6144; also restore `execution/docker-compose.yml`,
`execution/docker-compose.thinking-on.yml`, and
`execution/run-vllm-acceptance.sh` from the `.bak-20260824T0020` copies next
to them), then restart through the production controller.

### Long-context follow-up options (proposed 2026-08-24, not yet applied)

Ranked by expected value for the remaining pain: cold prefill is
compute-bound at ~1,900 tok/s shallow to ~1,400 tok/s at 480K (both GPUs at
96% SM during prefill), and the 1.22M-token KV pool holds barely two 465K
agent sessions, so a third session still triggers a 300 s+ full re-prefill.

1. **KV pool: `GPU_MEMORY_UTILIZATION` 0.78 -> 0.80.** Buys about +2.4 GB
   (~+330K pool tokens), directly reducing eviction-driven full re-prefills.
   Blocked on operator approval: upstream issue #8 recorded 0.80 booting
   clean then dying under traffic because DSpark buffers allocate on the
   first real request. Requires a supervised window with soak traffic and
   the documented rollback.
2. **KV offload to NVMe (LMCache-class connector).** An evicted 465K session
   is ~3.7 GB of nvfp4 KV; reloading from NVMe takes seconds versus a 300 s+
   re-prefill. Eliminates the "no cache hit" class outright. Framework-level
   work: the fork's connector surface with nvfp4_ds_mla MLA KV is unproven.
3. **A/B `VLLM_USE_B12X_SPARSE_INDEXER=1`.** The image ships a tiled
   SM120-specific indexer extend/topk path (default off,
   `VLLM_B12X_NSA_EXTEND_TOPK_SUPERTILE_K=32768`) that avoids materializing
   the 256 MiB logits buffer per sub-chunk; candidate for the ~25% prefill
   decay between 64K and 254K depth. Env-only toggle, one controller restart
   per arm.
4. **Kernel-level prefill ceiling.** The flat ~1,900 tok/s base rate is
   dominated by small-M grouped MoE GEMMs and indexer MQA logits on this
   fork; treat as a deep-kernel effort with limited headroom. Do 1-3 first.
The head API is `http://192.168.88.181:8890/v1` and exposes only
`deepseek-v4-flash-0731`. The immutable runtime revision is
`f277b3dfa718a5962bed64e69e7e640a5384ec2f`, with Patch4 fingerprint
`36adbf92fe8cdd5c57609b2c5ccfa8e2fc32a340c9ee3d727be538143dda74db`.
Both ranks use TP=2 over RoCE/NCCL `NET/IB`; the frozen maximum context is
1,048,576 tokens.

The controller must run on `gb10` from the deployed release directory. It
starts worker first, then head, writes `artifacts/service/active.json`, and
preserves the stopped local Qwen state while the lightweight `:8004` X570
proxy remains running:

```bash
ssh gb10 'cd /home/chriswang/gb10-ds4 && execution/run-private-ds-production.sh --check'
ssh gb10 'cd /home/chriswang/gb10-ds4 && execution/run-private-ds-production.sh --start'
ssh gb10 'cd /home/chriswang/gb10-ds4 && execution/run-private-ds-production.sh --status'
curl -fsS http://192.168.88.181:8890/v1/models
```

Do not manually start or stop one rank while `artifacts/service/active.json`
exists. To stop both ranks and restore only the captured local-Qwen state, use:

```bash
ssh gb10 'cd /home/chriswang/gb10-ds4 && execution/run-private-ds-production.sh --stop --restore-qwen'
```

For the current run, the captured local Qwen state was stopped, so this stop
command does not replace or stop the `:8004` X570 proxy. If a conflicting
MiniMax H3 service must be restored on `gb10-2`, first stop DeepSeek through
the controller, then use the H3 project-owned launcher; never run H3 and this
DeepSeek profile concurrently on the worker.

Current evidence is centralized on the head at
`/home/chriswang/gb10-ds4/artifacts/service/20260823T164410Z`. Default OpenAI
requests return parsed `reasoning` plus final `content`; Anthropic-compatible
requests return a `thinking` block followed by a `text` block. A live
`claude_local` stream also returned the exact model identity with both block
types. The prior immutable-subject deterministic, concurrency, five-minute,
and 40-minute soak evidence remains applicable because the runtime revision,
model, topology, memory profile, and MTP settings are unchanged; only the
additive default chat-template thinking flag changed.

The first 2026-08-14 start attempt was retained as failed run
`20260814T050959Z`: immediately restarting after the old service left only
7.07 GiB available KV cache versus 7.3 GiB required for the frozen 1,048,576
context. The controller cleaned up both ranks. After unified memory returned
to baseline, the unchanged thinking-on profile started successfully on its
second authorized attempt. Do not reduce context or alter the memory profile
to work around this transient condition; allow memory to settle, then retry
through the controller.

## SSH-Only External Relay

Status: running. `gb10` maintains a reverse SSH tunnel to
`vps-tencent-tokyo` (`43.167.173.46:36392`). The VPS listener is restricted to
`127.0.0.1:18890`; ports `18890` and `8890` are not publicly exposed and no
UFW rule was added. The approved client public-key fingerprint is
`SHA256:aYpMHYmSrHCM4kMFUek2yf7A/th4JlRpk2prLeo4Xxs`.

Idempotent install, verification, restart, and removal are provided by
`execution/private-ds-ssh-relay.sh`. Run its `install` or `status` action from
this workspace; `install` reads only `SSH_PUB_KEY` from the ignored `.env`.

The external key holder creates a local forward:

```bash
ssh -NT \
  -p 36392 \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -L 127.0.0.1:8890:127.0.0.1:18890 \
  ds-client@43.167.173.46
```

Then use `http://127.0.0.1:8890/v1`. If local port 8890 is occupied, change
only the left-hand local port. The `ds-client` identity has no shell, PTY,
agent/X11 forwarding, user rc, remote forwarding, or access to other target
ports.

Operate the GB10 reverse tunnel independently of DeepSeek:

```bash
ssh gb10 'systemctl --user status private-ds-vps-tunnel.service --no-pager'
ssh gb10 'systemctl --user restart private-ds-vps-tunnel.service'
ssh gb10 'journalctl --user -u private-ds-vps-tunnel.service -n 100 --no-pager'
ssh vps-tencent-tokyo 'ss -ltn | grep 127.0.0.1:18890'
```

Stopping the relay does not stop DeepSeek:

```bash
ssh gb10 'systemctl --user stop private-ds-vps-tunnel.service'
ssh vps-tencent-tokyo 'ss -ltn | grep 127.0.0.1:18890 || true'
ssh gb10 'cd /home/chriswang/gb10-ds4 && execution/run-vllm-service.sh --status'
```

The unit is enabled under the `chriswang` user and uses the dedicated key and
known-hosts files in `~/.local/share/private-ds-vps-tunnel/`. Do not copy that
private key or add unrelated keys to the restricted VPS accounts. Full
decommissioning stops/disables the user unit first, removes only
`/etc/ssh/sshd_config.d/40-private-ds-relay.conf` and the `ds-tunnel` /
`ds-client` accounts after `sshd -t`, then verifies the existing admin SSH
connection and model services.

## Persistent Patch4 Service and Claude Code Pilot

Status: passed. Run `20260811T102815Z` completed on 2026-08-11 with baseline
`claude-ds-pilot-r1`.

Run the local preflight first. It performs static/fake checks, the accepted
two-host read-only checks, online Flash identity probing, and deterministic
project-owned sandbox calibration before any model service changes. It has no
local Docker or SWE-bench harness dependency:

```bash
cd /Users/chris/project/Shili/workspaces/dev-lite/GB10-DS
execution/run-claude-code-flash-pilot.sh --preflight
```

The formal pilot is one command. The script captures and stops Qwen, starts the
worker then head Patch4 DeepSeek ranks, directly runs `claude_ds` and
`claude_local` semantics in isolated Git sandboxes, grades both treatments, and
leaves DeepSeek running on success. Infrastructure
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

### First Pilot Result

The accepted local receipt is
`execution/artifacts/claude-code-pilot/runs/20260811T102815Z/receipt.json`.
The detailed result and Markdown summary are in the same directory. The remote
service receipt is
`/home/chriswang/gb10-ds4/artifacts/service/20260811T102904Z/service-receipt.json`.

Both treatments used Claude Code `2.1.207`. Stream evidence reported online
route `claude_ds` with `deepseek-v4-flash`, and private route `claude_local`
with `deepseek-v4-flash-0731`; no fallback, timeout, agent exit error, or model
identity mismatch occurred.

| Task | Online | Private | Online seconds | Private seconds |
| --- | --- | --- | ---: | ---: |
| `miniconfig-escaped-paths` | passed | failed | 162.232 | 147.479 |
| `retry-after-policy` | failed | passed | 131.069 | 96.626 |
| `event-summary-refactor` | passed | passed | 41.581 | 39.225 |
| `ndjson-stream-decoder` | passed | passed | 236.178 | 133.860 |

Each treatment passed three of four hidden graders. Online totaled 571.060
seconds, 54 turns, 50 tool calls, and USD 2.175609 reported cost. Private
totaled 417.190 seconds, 55 turns, 51 tool calls, and USD 2.551305 reported
cost. Provider token/cache accounting differs materially, so token totals and
reported cost are supporting telemetry rather than direct efficiency proof.
This is one repetition and does not establish statistical superiority.

The successful run leaves both Patch4 ranks and API `:8890` running while Qwen
and pdf2md remain stopped. Trading and lexdata remained healthy. Post-run API,
container, kernel-fatal, and filtered runtime-log checks passed.

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

Stop both server/RPC containers on both hosts before restoring the local Qwen
rollback Compose. Preserve logs and inspect before stopping a failed server.
The X570 proxy itself does not need GB10 GPU capacity and can remain active.
