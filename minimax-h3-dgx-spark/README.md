# MiniMax H3 on one NVIDIA DGX Spark

Reproducible preparation, deployment controls, and a real 15-second MiniMax H3
benchmark for one NVIDIA DGX Spark / GB10.

This project pins the Gitee single-Spark recipe, verifies eleven model files by
exact byte size and SHA-256, operates ComfyUI with fail-closed PID/listener
identity, and publishes a static benchmark handbook from machine-readable JSON.

## Verified configuration

| Component | Identity |
| --- | --- |
| Gitee recipe | `9f9eca9589d4b4c0a01a8081c8c4add279e18868` |
| ComfyUI | `0764232429b8cfb10b79b6f186c8cb23e0b22897` |
| PyTorch / CUDA | `2.11.0+cu130` / 13.0 |
| Weights | 11 files, 176,195,310,067 bytes |
| Benchmark | 512x320, 362 frames, 6 steps, 24 fps |

See [BENCHMARK-RESULTS.md](./BENCHMARK-RESULTS.md) for the nine-case timing and
The machine-readable [benchmark-results.json](./benchmark-results.json) is
generated from the retained raw receipt by `sanitize-results.py` and includes
its SHA-256 plus per-case media hashes without publishing private host paths.

## Layout

```text
execution/minimax-h3/            weight and ComfyUI lifecycle scripts
execution/minimax-h3-benchmark/  15-second runner and static report server
BENCHMARK-RESULTS.md              sanitized verified results
protected-baseline.example.json  optional co-tenant preservation contract
```

Generated media, weights, logs, local receipts, and site output are ignored.

## Requirements

- NVIDIA DGX Spark / GB10 with CUDA 13.0
- Linux, Python 3.12, Git, curl, jq, rsync and `ss`
- At least 220 GB free disk for the full selected weight set and runtime
- Trusted LAN if binding ComfyUI or the report to `0.0.0.0`

## Install the pinned upstream recipe

The upstream installer may install OS/Python packages and start ComfyUI. Run it
only on a dedicated or explicitly authorized Spark. Review the pinned source
before execution.

```bash
export H3_ROOT="$HOME/minimax-h3"
./execution/minimax-h3/install-upstream-recipe.sh --root "$H3_ROOT"
```

The local scripts do not treat upstream completion markers as acceptance.
Prepare and verify every selected model object:

```bash
./execution/minimax-h3/prepare-weights.sh \
  --root "$H3_ROOT" \
  --receipt "$H3_ROOT/artifacts/verification/latest.json"

./execution/minimax-h3/verify-weights.sh --root "$H3_ROOT"
```

`weights-manifest.tsv` pins source repository, source revision, exact bytes,
SHA-256, and destination path for all eleven files.

## Configure and operate ComfyUI

The wrapper stops only the exact upstream-launched PID, pins ComfyUI and custom
node source revisions, normalizes models/workflows, and configures the twelve
workflows. To re-run only that final configuration step:

```bash
./execution/minimax-h3/configure-runtime.sh --root "$H3_ROOT"
```

Start, inspect, smoke-test and stop:

```bash
./execution/minimax-h3/start-comfyui.sh --root "$H3_ROOT"
./execution/minimax-h3/status-comfyui.sh --root "$H3_ROOT"
./execution/minimax-h3/run-smoke.sh --root "$H3_ROOT" --timeout 1800
./execution/minimax-h3/stop-comfyui.sh --root "$H3_ROOT"
```

Lifecycle ownership is PID plus `/proc` start ticks, boot ID, exact argv and
exclusive listener PID. Stop refuses a mismatch and never uses `pkill -f`.

### Optional protected co-tenant

To require an existing healthy Docker workload to remain unchanged, create a
machine-local baseline from `protected-baseline.example.json` and export:

```bash
export H3_PROTECTED_BASELINE="$HOME/minimax-h3/protected-baseline.json"
```

The baseline file is ignored. Without this variable, protection is explicitly
reported as disabled rather than referring to a repository-specific service.

## Run the 15-second benchmark

```bash
export H3_BENCH_ROOT="$HOME/minimax-h3-benchmark"
./execution/minimax-h3-benchmark/run-benchmark.sh
```

The runner requires an idle queue, resets ComfyUI execution cache before every
case, submits nine cases serially, and records:

- queue acceptance and ComfyUI execution time;
- one-second memory, RSS, GPU utilization, temperature and power samples;
- MP4 and PNG SHA-256 plus normalized decoded RGB hashes;
- same-seed decoded-frame reproducibility;
- bounded runtime/kernel fatal scans;
- exact pre/post ComfyUI and optional protected-service identity.

Start the generated static report on an unused trusted-LAN port:

```bash
./execution/minimax-h3-benchmark/start-report.sh
./execution/minimax-h3-benchmark/status-report.sh
# http://127.0.0.1:8890/
```

Use `restart-report.sh` or `stop-report.sh` for exact receipt-bound lifecycle
control. The report defaults to `0.0.0.0:8890`; it does not add TLS,
authentication or firewall policy.

## Tests

```bash
./execution/minimax-h3-benchmark/test-benchmark.sh
bash -n execution/minimax-h3/*.sh execution/minimax-h3-benchmark/*.sh
python3 -m py_compile \
  execution/minimax-h3/*.py execution/minimax-h3-benchmark/*.py
```

## Recovery

- Interrupted downloads stay in `.downloads` and resume on rerun.
- Invalid final-path fragments are quarantined under `artifacts/incomplete`.
- A process/listener identity mismatch is never resolved by a broad kill.
- Preserve failed benchmark runs; only a fully normalized passed run is
  published to the static site.

## Known limitations

- The 3600-frame input ceiling is not treated as supported. The H3 node marks
  approximately 124-362 frames as the trained range; this project benchmarks
  the 362-frame upper bound.
- The report is for trusted-LAN use unless an external authenticated reverse
  proxy is added by the operator.
- The full eleven-file set is intentionally large because it preserves all
  workflow variants selected by the pinned recipe.

## Sources

- [Gitee single-DGX-Spark recipe](https://gitee.com/alexlu0912_admin/dgxspark_comfyui_minimax_h3)
- [MiniMax H3](https://github.com/MiniMax-AI/MiniMax-H3)
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI)

This project follows the repository-wide contribution rules in
[../README.md](../README.md). Related issue: [#24](https://github.com/johnymoo/Nvidia-DGX/issues/24).
