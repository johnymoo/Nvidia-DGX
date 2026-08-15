# Model Platform Operations

Status: implementation and read-only live verification passed on 2026-08-15.
Lifecycle commands were verified with fake SSH/Docker fixtures and live dry-runs
only. No model or protected service was started, stopped, or restarted.

## Contract

Issue #26 is implemented under `execution/model-platform`. `models.yaml` is a
JSON-compatible YAML 1.2 document so the CLI works with the Python standard
library; PyYAML is optional. `models.schema.json` documents the registry
contract, while `model_platform.py` performs mandatory cross-reference and
security validation that JSON Schema alone cannot express.

The platform is non-invasive:

- discovery reads `docker compose ls --all --format json`, structured Docker
  inspect labels, published bindings, and `ss -H -ltnup` on `gb10` and
  `gb10-2`;
- unmanaged projects are visible but never receive lifecycle actions;
- accepted model-specific controllers remain authoritative;
- start/restart fails closed on declared model, exclusive-host, resource, or
  wildcard-address port conflicts;
- lifecycle commands require action-bound confirmation, acquire atomic locks on
  target and conflict hosts before authoritative preflight, execute only
  registry-owned argv, re-observe state under lock, and write a receipt under
  `~/.local/state/model-platform/receipts`;
- the Web API binds only loopback, requires an ephemeral internal operator token
  plus CSRF for POST, accepts a fixed request schema, and has no arbitrary
  command endpoint.

Registry and API schema version are `1` and `model-platform/v1`.

## Read-Only Commands

Run from the repository root:

```bash
execution/model-platform/modelctl list
execution/model-platform/modelctl --json discover
execution/model-platform/modelctl --json capabilities
execution/model-platform/modelctl status deepseek-v4-flash-0731
execution/model-platform/modelctl --json ports --host gb10
execution/model-platform/modelctl --json check qwen38-nvfp4
```

Exit codes are `0` for success, `1` for invalid input/runtime failure, `2` when
a discovery host is unavailable, and `3` for a valid but blocked preflight.
`check` and `capabilities` never change state. A running project not represented
by a registered deployment is returned as `Unmanaged`.

## Web UI

This is an internal, loopback-only tool. Its security boundary is intentionally
small: one ephemeral operator token plus CSRF and Host/Origin checks. It does
not implement enterprise IAM, RBAC, or TLS.

```bash
MODEL_PLATFORM_WEB_TOKEN="$(openssl rand -base64 32)" \
  execution/model-platform/modelctl serve --host 127.0.0.1 --port 8787
```

Open `http://127.0.0.1:8787` and authenticate as `operator` with that token.
For an internal browser that cannot show the Basic-auth prompt, open
`http://127.0.0.1:8787/?access_token=TOKEN` once; the server redirects to a
clean URL and exchanges it for a process-local HttpOnly session cookie.
Operation POSTs return a persistent receipt ID immediately; the UI polls
queued/running/terminal state and resumes after a refresh. All discovered
Docker values are rendered as text, not HTML.

## Controlled Lifecycle

Always preview first. Unprotected models use their exact model ID:

```bash
execution/model-platform/modelctl --json start MODEL --confirm MODEL --dry-run
execution/model-platform/modelctl --json stop MODEL --confirm MODEL --dry-run
```

Protected operations require both the override and action-bound phrase:

```bash
execution/model-platform/modelctl stop qwen36-proxy \
  --allow-protected --confirm 'PROTECTED stop qwen36-proxy' --dry-run
```

Remove `--dry-run` only in an authorized maintenance window. The platform locks
all target, adapter, resource, and conflict hosts before rediscovery/preflight,
keeps the locks through postcondition verification, and records bounded,
redacted command output plus before/after state. A blocked start never stops a
conflict. DeepSeek remains controller-owned; no single rank is operated.

Trading, lexdata, pdf2md, Unsloth A/B, and MiniMax are visibility-only. Qwen3.8
is registered but lifecycle-unavailable until its immutable release and built
image identity pass the capability gate. The UI hides unavailable actions and
the core rejects direct requests.

The host lock is `/tmp/model-platform.lock`. Remove a stale lock only after
verifying no `modelctl` operation is active. A receipt with a lock-release error
is `degraded`, never successful.

## Qwen3.8 NVFP4 Profile

Registry ID `qwen38-nvfp4` targets `gb10-2:8892` with served ID
`qwen3.8-27b-nvfp4`, text/image/video modalities, 262,144 context, MTP=2, and
an exclusive `gb10-worker-gpu` claim. The pinned artifact is
`unsloth/Qwen3.8-27B-NVFP4` revision
`16b6615af3548b88e2d8e382457bc705b00479cf`.

The complete 13-file trust-root manifest is
`execution/model-platform/qwen38/model-manifest.sha256`, SHA-256
`6d979221939858d8f98c7e615028e1e468cffb3ff2d501f943646c1e12ef2cdc`.
It includes main weight SHA-256
`c473512c70eace07e2256fe9fd76596ac03e3295bee7d54cfb72676416afcc05`
and MTP SHA-256
`1d8268aa85ace093a561e3e7b63b9d390dac1cd55a90cd55b5ec509c3c9da9fe`.
Missing, extra, or changed snapshot files fail preflight.

The ARM64 runtime base is pinned to
`nvcr.io/nvidia/pytorch:26.07-py3@sha256:7531d90bcbe0e43e1f7363029c7e145ce90eebeb494a7b4695fdba0329d7c3c3`.
vLLM 0.25.0, FlashInfer 0.6.13, CUTLASS DSL 4.5.2, and uv are exact. The
Compose profile removes remote-code trust and host IPC and uses a read-only
root, dropped capabilities, and `no-new-privileges`.

Render locally:

```bash
docker compose --env-file execution/model-platform/qwen38/qwen38.env \
  -f execution/model-platform/qwen38/compose.yml config --format json
```

### Clean-Host Preparation

Verified on `gb10-2` on 2026-08-15: aarch64, NVIDIA driver `580.142`, Docker
`29.2.1`, Compose `5.0.2`, and 868 GiB free disk. Reserve at least 64 GiB for
the 23.5 GB snapshot, image, cache, and evidence. Require working NVIDIA
container runtime plus `jq`, `curl`, `sha256sum`, `ss`, `ffmpeg`, and
`modelscope`; the last read-only check found `ffmpeg` and `modelscope` absent.

Acquire only the pinned ModelScope revision:

```bash
modelscope download --model unsloth/Qwen3.8-27B-NVFP4 \
  --revision 16b6615af3548b88e2d8e382457bc705b00479cf \
  --local_dir /home/admin/models/unsloth-Qwen3.8-27B-NVFP4/16b6615af3548b88e2d8e382457bc705b00479cf
```

Install immutable releases without deleting external state:

```bash
release="$(date -u +%Y%m%dT%H%M%SZ)"
ssh gb10-2 "install -d -m 0755 /home/admin/gb10-model-platform/qwen38/releases/$release"
rsync -a execution/model-platform/qwen38/ \
  "gb10-2:/home/admin/gb10-model-platform/qwen38/releases/$release/"
ssh gb10-2 "ln -sfn releases/$release /home/admin/gb10-model-platform/qwen38/current.new && \
  mv -Tf /home/admin/gb10-model-platform/qwen38/current.new /home/admin/gb10-model-platform/qwen38/current"
ssh gb10-2 '/home/admin/gb10-model-platform/qwen38/current/build-runtime.sh'
```

Artifacts and image identity are outside releases at
`/home/admin/.local/state/model-platform/qwen38` (`0700`, files `0600`). The
build records the OCI image ID, Dockerfile hash, and dependency freeze. These
commands are not evidence that a build occurred. Lifecycle remains disabled
until a later reviewed registry change verifies the installed controller,
trusted snapshot, and build record; never invent a missing image digest.

The controller enforces `readiness deadline + cleanup margin < outer SSH
timeout`, handles `HUP`/`INT`/`TERM`, retains failure evidence, stops only its
own service, and verifies both container and `:8892` are released before the
platform unlocks.

## Stop, Rollback, And Recovery

Before a future maintenance window, save `modelctl --json discover` and the
protected/unmanaged identities before stopping anything. After Qwen is enabled,
normal stop and direct diagnostic rollback are:

```bash
execution/model-platform/modelctl stop qwen38-nvfp4 \
  --confirm qwen38-nvfp4 --dry-run
ssh gb10-2 'cd /home/admin/gb10-model-platform/qwen38/current && ./controller.sh rollback'
```

Stopping Qwen never guesses what to start. Use the operation receipt `before`
snapshot to restore exactly the captured eligible workload through its own
registered controller. For a captured DeepSeek workload, preview with:

```bash
execution/model-platform/modelctl start deepseek-v4-flash-0731 \
  --allow-protected \
  --confirm 'PROTECTED start deepseek-v4-flash-0731' --dry-run
```

Recovery completes only when that captured workload and DeepSeek, Qwen proxy
`:8004`, trading, lexdata, pdf2md, and unmanaged projects match the pre-window
snapshot. Retain receipts and external Qwen artifacts; never delete or recreate
an unmanaged project as a recovery action.

## Adding A Model

1. Add hosts, deployments, exact project/services, adapter, endpoint bindings,
   health URL, identity, resources, conflicts, and `protected` to
   `models.yaml`.
2. Use controller argv arrays for distributed or recovery-sensitive models.
   Use the Compose adapter only for a bounded single-project lifecycle.
3. Keep secrets in ignored runtime environment files; never place tokens,
   passwords, keys, or real secret values in the registry.
4. Run the focused tests, Compose render, `modelctl --json discover`, and
   `modelctl --json check MODEL`.
5. Verify unmanaged/protected identities before and after any separately
   authorized lifecycle E2E, then update this runbook with its receipt.
