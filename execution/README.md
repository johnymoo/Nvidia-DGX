# Execution Assets

Place project-owned deployment and verification scripts here. Scripts must be
idempotent where practical, fail on missing required values, avoid embedded
credentials, preserve unrelated services, and emit enough evidence to audit a
run.

## Files

- `docker-compose.yml`: immutable base for the accepted two-node vLLM/DSpark
  0731 deployment. Use only with the documented additive override.
- `docker-compose.f277b3d-timeout.yml`: additive f277b3d override used with
  the base Compose file by the acceptance owner. It sets the upstream engine
  readiness timeout and unbuffered Python logging without changing model or
  scheduler parameters.
- `docker-compose.f277b3d-memory-profile.yml`: inactive diagnostic artifact
  retained from investigating NVRM warmup allocations. The acceptance owner
  uses the base memory-profiling setting unless an explicitly approved run
  selects this override.
- `env/*.env.example`: common, head, and worker settings. Copy to untracked
  `common.env` and `node.env` on each host.
- `prepare-docker.sh`: verify Docker or, under sudo, grant the deployment user
  Docker access without reinstalling the existing stack.
- `configure-fabric.sh`: fail-closed NetworkManager setup for a cabled CX-7
  port; refuses to modify a port without physical carrier.
- `build-runtime.sh`: verify or build the pinned vLLM/DSpark/NVFP4 runtime.
- `render-compose.sh`: render and validate Compose without starting anything.
- `preflight.sh`: read-only live host/model/fabric/image checks.
- `run-vllm-acceptance.sh`: single-entry official 0731 + Patch 4 distributed
  acceptance owner. Run it only on `gb10` from
  `/home/chriswang/gb10-ds4`; it controls `gb10-2` through the worker SSH
  contract in the real head env. The 2026-08-11 formal run passed; use `--run`
  only in an authorized maintenance window:

  ```bash
  cd /home/chriswang/gb10-ds4
  execution/run-vllm-acceptance.sh --check
  # After maintenance-window approval only:
  execution/run-vllm-acceptance.sh --run
  ```

  `--check` is zero-mutation and verifies both hosts, the pinned 74-line
  manifest SHA, model file-count/byte-count, config/index SHA, fixed shard
  samples 1/24/48, image revision/fingerprint, Patch 4 source, exact Compose
  render, free ports, and the Qwen recovery contract. It references the full
  2026-08-10 manifest verification under each host's `artifacts/` directory
  instead of rereading the complete 334 GB two-host model on every check.
  `--run` captures dated evidence
  below `artifacts/acceptance/<UTC>/` on both hosts, stops only a previously
  running Qwen vLLM, starts worker then head, performs correctness,
  performance, and a fixed 40-minute concurrency-4 soak, then always stops
  DeepSeek and restores Qwen to its original state. Its `receipt.json` exit
  status and process exit code are coupled; rollback failures are final
  failures.
- `benchmarks/`: pinned-f277b3d correctness, agent sanity, full performance,
  soak clients, and the no-service mock harness for the acceptance owner.
- `worker-maintenance.sh`: root-owned, host-locked worker maintenance wrapper.
  Its `remove-swap` action permanently and fail-closed removes only
  `/swap.img`; its `apt-use-tuna` action changes only Ubuntu base-source URIs
  in `ubuntu.sources` and refreshes APT indexes without package upgrades.
- `install-worker-maintenance-sudoers.sh`: interactive `admin`-only installer
  for the worker wrapper and its restricted NOPASSWD allowlist. Run it only on
  `gb10-2` from its project directory:

  ```bash
  sudo /home/admin/gb10-ds4/execution/install-worker-maintenance-sudoers.sh
  ```

  After installation, run the following NOPASSWD commands in order:

  ```bash
  sudo /usr/local/sbin/gb10-ds4-worker-maintenance remove-swap
  sudo /usr/local/sbin/gb10-ds4-worker-maintenance apt-use-tuna
  sudo /usr/local/sbin/gb10-ds4-worker-maintenance check
  ```

  Each mutating action writes timestamped pre-change evidence below
  `/var/backups/gb10-ds4-worker-maintenance`.
- `sync-assets.sh`: direct head-to-worker source, model, and image transfer.
- `load-runtime-archives.sh`: verify and import the staged vLLM and Unsloth
  image archives on the worker, then enforce normalized image-content
  fingerprints across Docker storage backends.
- `finalize-prelink-assets.sh`: wait for detached transfers, import worker
  images, verify the official model byte-for-byte, and enforce both-node image
  content without starting inference.
- `model-manifest.sh`: create or verify a recursive SHA-256 model manifest.
- `unsloth/`: isolated llama.cpp CUDA/RDMA image, exact Q4 model downloader,
  two-RPC Compose, image transfer, env templates, rendering, and preflight for
  the Unsloth A/B.

The Unsloth/llama.cpp route intentionally has a separate Compose file rather
than weakening the vLLM contract with conditional commands.

The A/B run passed for both target and DSpark profiles. Add
`unsloth/docker-compose.reasoning-off.yml` to the base Unsloth Compose: it
only sets `LLAMA_ARG_REASONING=off` so OpenAI responses carry usable content.
Do not edit either base Compose file; create an explicit new override for a
future approved experiment.
