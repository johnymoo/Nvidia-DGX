# Pre-Link Preparation Runbook

Status: scripts staged and configuration-rendered on both hosts on 2026-08-10.
No distributed inference service has been started.

## Prepared Runtime Routes

- model: official `DeepSeek-V4-Flash-0731`, mixed FP8/FP4, 48 shards;
- runtime: patched vLLM/DSpark at upstream revision `f277b3d`;
- topology: TP=2 across both GB10 nodes;
- KV: `nvfp4_ds_mla`;
- context/concurrency baseline: 1,048,576 tokens, 6 sequences;
- Unsloth A/B: `UD-Q4_K_XL` + Q8 sidecar through two llama.cpp CUDA RPC
  devices over RoCE, 256K context, single stream. Runtime source is PR 26500
  head `f0c483c4`; Compose and exact-download manifest are under
  `execution/unsloth`.

Use vLLM for the first distributed acceptance run. Then execute the isolated
Unsloth A/B and select the long-term primary from local evidence.

## Unsloth A/B Preparation

Unsloth's official Spark-sized recipe recommends `UD-IQ3_XXS` for one 128 GB
system. The two-node candidate instead pins `UD-Q4_K_XL` because two Sparks
have enough aggregate memory and that quant has a published two-Spark,
200 Gb RoCE target-only baseline of 16.49 tok/s. The Q8 DSpark sidecar is then
an isolated second phase. Unsloth's advertised 119.7 tok/s result was measured
on one B200 and is not a Spark acceptance target.

Prepare the head environment under `execution/unsloth`:

```bash
cp env/common.env.example env/common.env
cp env/head.env.example env/node.env
./build-runtime.sh
./render-compose.sh env/common.env env/node.env target >/dev/null
./render-compose.sh env/common.env env/node.env dspark >/dev/null
./download-model.sh /home/chriswang/model/DeepSeek-V4-Flash-0731-GGUF
```

Prepare the worker environment and transfer the exact built image after its
Docker group access is fixed:

```bash
# On gb10-2, under execution/unsloth:
cp env/common.env.example env/common.env
cp env/worker.env.example env/node.env

# On gb10, under execution/unsloth:
./sync-image.sh env/common.env env/node.env
```

The pinned model download is currently running on `gb10` in tmux session
`gb10-unsloth-download`. It uses `huggingface_hub`/Xet with six file workers,
resumes its local cache after interruption, and verifies every file against
the pinned LFS SHA-256 before writing `SOURCE`. Check it without interrupting:

```bash
ssh gb10 'tmux capture-pane -p -S -20 -t gb10-unsloth-download'
ssh gb10 'test -f /home/chriswang/model/DeepSeek-V4-Flash-0731-GGUF/SOURCE'
```

The second command exits zero only after all five Q4 shards and the Q8 sidecar
have passed their full checksums.

Before cabling, both preflight modes are expected to report fabric failures.
The DSpark mode additionally requires the Q8 sidecar:

```bash
./preflight.sh env/common.env env/node.env target
./preflight.sh env/common.env env/node.env dspark
```

After cabling and fabric verification, start both RPC devices first. The
worker RPC listens only on `192.168.192.198:50052`; never expose it on the
management LAN because llama.cpp RPC has no authentication or encryption.

```bash
# Worker
docker compose --env-file env/common.env --env-file env/node.env \
  -f docker-compose.yml up -d rpc

# Head
docker compose --env-file env/common.env --env-file env/node.env \
  -f docker-compose.yml up -d rpc
docker compose --env-file env/common.env --env-file env/node.env \
  -f docker-compose.yml --profile target up -d server-target
```

Record target-only correctness and throughput before switching profiles:

```bash
docker compose --env-file env/common.env --env-file env/node.env \
  -f docker-compose.yml --profile target stop server-target
docker compose --env-file env/common.env --env-file env/node.env \
  -f docker-compose.yml --profile dspark up -d server-dspark
```

Both server profiles expose the OpenAI-compatible API on port 8891. They are
mutually exclusive because they bind the same port. Keep `--cache-ram 0` until
the upstream repeated-request RPC bug is resolved.

## Staged Paths

- head: `/home/chriswang/gb10-ds4`
- worker: `/home/admin/gb10-ds4`
- pinned upstream revision on both: `f277b3d`
- head-to-worker SSH over management LAN: verified

## Built vLLM A/B Baseline

The candidate image was built on `gb10` without starting a service:

- tag: `gb10-ds4-vllm:f277b3d-nvfp4`;
- image ID:
  `sha256:643acb2f8b10b9745b0de94ff2675f446b1baf6935b6f886802711e72f21c07f`;
- vLLM: `0.21.1rc1.dev339+g1967a5627bc3`;
- source label: `f277b3dfa718a5962bed64e69e7e640a5384ec2f`;
- pinned base manifest:
  `sha256:d8492e7677cf1b9aaa3344e0e6865efc468454013eee5ebabac85be90af027be`;
- Patch 4 source/import assertion: passed;
- NVFP4 stages A, B, and C: built successfully.

This proves the vLLM baseline is reproducible. It does not select it over the
Unsloth candidate and does not prove live two-node inference.

## Built Unsloth A/B Runtime

The llama.cpp CUDA/RPC image was built and self-tested on `gb10` without
starting an inference service:

- tag: `gb10-unsloth-llama:f0c483c4-rpc`;
- image ID:
  `sha256:42f458f96b761d9af4890496a60969adddc84afaf865d5a11214d5ddec7fb4f6`;
- image size: `8334475153` bytes;
- source: llama.cpp PR 26500 head
  `f0c483c4df52f82cc5795433c9e9332fb3e8aa21`;
- `llama-server --version`: `64 (f0c483c)`, Linux aarch64;
- target, DSpark, RPC, split, fit, flash-attention, and cache flags: present;
- `ggml-rpc-server`: CUDA0 and cache options present;
- runtime dependencies: `libcuda.so.1`, `libnccl.so.2`, and
  `libibverbs.so.1` resolved inside a GPU container;
- target-only and DSpark Compose profiles: rendered on `gb10` and target-only
  rendered on `gb10-2`.

The worker image transfer remains pending until `admin` has Docker daemon
access. The exact-image transfer script compares the image ID on both hosts.

## One Required Docker Action

Docker, Compose, and NVIDIA Container Toolkit are already installed and active
on `gb10-2`. Its `admin` user is not in the `docker` group. Run this from an
interactive terminal so sudo can request the local password:

```bash
ssh -t gb10-2 'sudo /home/admin/gb10-ds4/execution/prepare-docker.sh --apply admin'
```

Log out and reconnect, then verify:

```bash
ssh gb10-2 '/home/admin/gb10-ds4/execution/prepare-docker.sh --check'
```

The two runtime images are also staged as compressed archives so model and
image transfer can finish before Docker access is granted. After reconnecting,
import them on `gb10-2` with full archive and image-ID verification:

```bash
ssh gb10-2 '/home/admin/gb10-ds4/execution/load-runtime-archives.sh /home/admin/gb10-ds4/artifacts'
```

Archive identities on `gb10`:

| Archive | SHA-256 |
| --- | --- |
| `gb10-ds4-vllm-f277b3d-nvfp4.tar.zst` | `d712fb1c6ccb549aadd59c9faddd408018a19bf8d06c2821ec7875201973915e` |
| `gb10-unsloth-llama-f0c483c4-rpc.tar.zst` | `2ade8cbffd08c6452ab17d1e726470f3154d828d13674c339eccd43ae2164e5a` |

The import script also enforces normalized image-content fingerprints. Docker's
classic `overlay2` store and containerd snapshotter can assign different local
image IDs to the same imported config and rootfs, so local IDs are recorded but
are not used as the cross-store equality condition.

## Active Preparation Transfers

The following detached jobs were started on `gb10`; they survive SSH session
closure and are safe to inspect without interrupting:

| tmux session | Work |
| --- | --- |
| `gb10-vllm-model-sync` | rsync the official 0731 checkpoint to `gb10-2` |
| `gb10-image-archive-sync` | rsync both compressed runtime archives to `gb10-2` |
| `gb10-unsloth-download` | download and SHA-256 verify Q4 GGUF plus Q8 sidecar |

Inspect a job with:

```bash
ssh gb10 'tmux capture-pane -p -S -20 -t gb10-vllm-model-sync'
```

Completion criteria are: the relevant tmux session exits, the worker vLLM
preflight reports all 48 model shards present, both archive SHA-256 values match
on the worker, and the Unsloth model directory contains `SOURCE`.

The head runs `finalize-prelink-assets.sh` in tmux session
`gb10-prelink-finalizer`. It waits for all three jobs, imports both worker
images, creates and verifies a full official-model SHA-256 manifest on the
worker, checks the pinned Unsloth revision marker, and compares normalized
image content between hosts. It does not start inference.

Do not reinstall Docker. The worker already has Docker 29.2.1, Compose 5.0.2,
and NVIDIA Container Toolkit 1.19.0 with an NVIDIA runtime in daemon.json.

## Planned Fabric

Use the first matching ConnectX-7 port on each host:

| Role | Interface | RDMA HCA | Address |
| --- | --- | --- | --- |
| head | `enp1s0f0np0` | `rocep1s0f0` | `192.168.192.181/24` |
| worker | `enp1s0f0np0` | `rocep1s0f0` | `192.168.192.198/24` |

After physically connecting these ports, configure worker first and head
second in separate terminals:

```bash
ssh -t gb10-2 'sudo /home/admin/gb10-ds4/execution/configure-fabric.sh enp1s0f0np0 192.168.192.198/24 192.168.192.181'
ssh -t gb10 'sudo /home/chriswang/gb10-ds4/execution/configure-fabric.sh enp1s0f0np0 192.168.192.181/24 192.168.192.198'
```

The script refuses to change NetworkManager while carrier is absent. It sets a
9000-byte MTU, no default route, and verifies IP, RDMA/GID state, and peer ping.

## Current Preflight Baseline

The vLLM head preflight passes architecture, GB10, Docker, NVIDIA runtime, all
48 model shards, checkpoint quantization metadata, interface existence,
runtime image, and API port 8890. Expected pre-link failures are carrier, IP,
active RDMA, and peer reachability.

The vLLM worker passes architecture, GB10, interface existence, and API port
8890. Expected pre-link failures are Docker user access, model, carrier/IP,
active RDMA, peer reachability, and runtime image.

The Unsloth head target-only preflight passes Docker, runtime image, RPC port,
and API port. It fails only the expected carrier, fabric IP, active RDMA, peer
reachability, and target GGUF checks. DSpark mode adds the expected
missing-sidecar failure. The Unsloth worker target preflight currently fails
Docker access, image, carrier, fabric IP, active RDMA, and peer reachability;
its RPC port is free.

## Existing Head Workload

`gb10` currently runs a Qwen vLLM container that allocates about 46 GiB of the
119 GiB unified memory. The 0731 TP=2 deployment cannot be assumed to coexist
with it. Do not stop it during preparation. Before the first two-node launch,
obtain explicit authorization for a maintenance window, record its restart
command, stop it cleanly, and verify the rollback path.
