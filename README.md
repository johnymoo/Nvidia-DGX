# NVIDIA Private Model Deployment Lab

Open-source deployment recipes, benchmark evidence, operational notes, and
application examples for private models on NVIDIA hardware. A matching machine
should be able to use one exact recipe, run its own acceptance and benchmark,
and compare the outcome with a clearly scoped historical record.

This repository does not publish model weights, credentials, private topology,
or raw host logs. Static validation never upgrades a recipe or result to
Verified.

## Quick Start

```bash
git clone https://github.com/johnymoo/Nvidia-DGX.git
cd Nvidia-DGX
./lab list
./lab validate
```

1. Open the matching entry in [hardware/](hardware/).
2. Choose one exact `model + hardware + runtime + profile` recipe below.
3. Read its requirements, maturity, evidence, limitations, and invalidation
   conditions before running anything.
4. Use `./lab run <recipe-id> <operation> --dry-run` to inspect a supported
   operation, then run it without `--dry-run` on the matching machine.
5. Save a new receipt and benchmark result; do not overwrite historical data.

`lab` is a local catalog and dispatch utility. It does not SSH to hosts, manage
remote services, download weights automatically, or infer that a running API is
the intended model.

## Evidence Maturity

- **Verified**: an exact model, hardware class, runtime, and profile has
  subject-bound deployment and acceptance evidence.
- **Reference**: useful instructions or historical measurements exist, but the
  active canonical acceptance or benchmark contract is incomplete.
- **Archived**: retained for debugging or comparison; not a current-run claim.

Recipe maturity and benchmark maturity are independent. A Verified deployment
can still have only Reference benchmark results when its old suite or metric
identity is incomplete.

## Best Verified

Grouped by `hardware_id + model_family`; quantization and runtime remain visible
inside the selected row. Different hardware is never ranked together. Selection
requires a Verified recipe and result, active suite major version, explicit
workload/cache/concurrency identity, a SHA-bound exact-subject receipt, configured
model-group quality/context floors, passing acceptance/reliability/safety, and
all ranking metrics. Missing evidence fails closed.

<!-- BEGIN GENERATED:best-verified -->
| Hardware | Model family | Runtime / profile | Aggregate TPS | Decode TPS | TTFT | Evidence |
|---|---|---|---:|---:|---:|---|
| dgx-spark-gb10 | qwen3.5 | - | - | - | - | No eligible Verified result is available for this hardware and model group. |
| dgx-spark-gb10 | qwen3.6 | - | - | - | - | No eligible Verified result is available for this hardware and model group. |
| dgx-spark-gb10-pair | deepseek-v4 | - | - | - | - | No eligible Verified result is available for this hardware and model group. |
| rtx-a6000-48gb | qwen3.8 | - | - | - | - | No eligible Verified result is available for this hardware and model group. |
| rtx3090-24gb | qwen3.8 | - | - | - | - | No eligible Verified result is available for this hardware and model group. |
| rtx4090-48gb | qwen3.6 | - | - | - | - | No eligible Verified result is available for this hardware and model group. |
| rtx4090-48gb | qwen3.8 | - | - | - | - | No eligible Verified result is available for this hardware and model group. |
<!-- END GENERATED:best-verified -->

## Latest Reference Results

These are the latest Reference records for each hardware and model group. A
record may use an active canonical suite or preserve a historical workload and
its original metric definitions; neither is ranked as Best Verified. `N/A`
means the source did not record a compatible field; it never means zero.

<!-- BEGIN GENERATED:reference-results -->
| Hardware | Model | Runtime / profile | Workload | Recorded metrics | Evidence |
|---|---|---|---|---|---|
| dgx-spark-gb10-pair | DeepSeek-V4-Flash-0731 | vllm-patch4 / thinking-on-tp2 | legacy-cross-model-performance-concurrent-6; concurrency=6; cache=unknown | recorded aggregate TPS: 229.3 (recorded concurrent aggregate) | [result](results/dgx-spark-gb10-pair/deepseek-v4/reference-20260812-concurrent/result.json) / [evidence](recipes/deepseek-v4/dual-dgx-spark-gb10-vllm-flash-0731-patch4-thinking-on/BENCHMARK-RESULTS.md) |
| dgx-spark-gb10-pair | DeepSeek-V4-Flash-0731 | vllm-patch4 / thinking-on-tp2 | legacy-cross-model-performance; concurrency=1; cache=unknown | recorded generation/decode TPS: 68.8 (recorded single-stream mean) | [result](results/dgx-spark-gb10-pair/deepseek-v4/reference-20260812-single/result.json) / [evidence](recipes/deepseek-v4/dual-dgx-spark-gb10-vllm-flash-0731-patch4-thinking-on/BENCHMARK-RESULTS.md) |
| dgx-spark-gb10 | MiniMax-H3 | comfyui / trained-max-362-frames-512x320 | 362-frames-512x320-six-steps; concurrency=1; cache=cold | response: 130.5 (approximate recorded bounded wall time) | [result](results/dgx-spark-gb10/minimax-h3/reference-20260813/result.json) / [evidence](recipes/minimax-h3/dgx-spark-gb10-comfyui-trained-max-15s/BENCHMARK-RESULTS.md) |
| dgx-spark-gb10 | Qwen3.5-9B | llama.cpp / q4-k-m-8k | 1000-token-generation; concurrency=1; cache=unknown | response: 28.89 (legacy source definition); recorded generation/decode TPS: 34.6 (recorded llama.cpp speed) | [result](results/dgx-spark-gb10/qwen3.5/reference-legacy/result.json) / [evidence](recipes/qwen3.5/dgx-spark-gb10-llamacpp-9b-q4-k-m-8k/README.md) |
| dgx-spark-gb10 | Qwen3.6-35B-A3B-NVFP4 | vllm / nvfp4-mtp3-256k | legacy-16-case-generation; concurrency=1; cache=unknown | recorded generation/decode TPS: 152.1 (recorded average generation throughput) | [result](results/dgx-spark-gb10/qwen3.6/reference-20260618/result.json) / [evidence](recipes/qwen3.6/dgx-spark-gb10-vllm-27b-nvfp4-native-mtp2-128k/NVFP4-BENCHMARK-RESULTS.md) |
| rtx4090-48gb | Qwen/Qwen3.6-35B-A3B-FP8 | vllm-0.19.0 / fp8-32k-p2 | legacy-fixed-generation; concurrency=1; cache=unknown | TTFT: 0.08743 (legacy source definition); response: 17.094655 (legacy source definition); recorded generation/decode TPS: 112.18763 (legacy corrected stream decode field) | [result](results/rtx4090-48gb/qwen3.6/reference-20260817/result.json) / [evidence](benchmarks/legacy/qwen-deepseek-cross-model/report/lakehouse-thinking.html) |
| rtx3090-24gb | Qwen3.8-27B-Q3_K_S | llama.cpp / q3-k-s-128k-p2 | legacy-single-stream-generation; concurrency=1; cache=unknown | recorded generation/decode TPS: 30.1 (recorded single-stream mean); recorded_aggregate_tps: 50.8 (source summary did not record concurrency; not mapped to canonical aggregate TPS) | [result](results/rtx3090-24gb/qwen3.8/reference-20260815-single/result.json) / [evidence](benchmarks/legacy/qwen-deepseek-cross-model/README.md) |
| rtx4090-48gb | Qwen3.8-27B-UD-Q4_K_XL | llama.cpp / ud-q4-k-xl-mtp2-256k-p1 | legacy-q4-mtp2-single-stream; concurrency=1; cache=unknown | recorded generation/decode TPS: 94.33 (recorded Q4 plus MTP2 generation throughput) | [result](results/rtx4090-48gb/qwen3.8/reference-20260817/result.json) / [evidence](benchmarks/legacy/qwen-deepseek-cross-model/report/qwen38-quantization.html) |
| rtx-a6000-48gb | Qwen3.8-27B-UD-Q4_K_XL | llama.cpp / ud-q4-k-xl-mtp2-192k-p1 | qwen38-low-streaming-2048-warm-p1; concurrency=1; cache=warm | TTFT: 0.2677883333 (performance-v1@1.0.0 definition); response: 21.5902 (performance-v1@1.0.0 definition); recorded generation/decode TPS: 62.429818 (performance-v1@1.0.0 definition); recorded aggregate TPS: 61.6958400976 (performance-v1@1.0.0 definition) | [result](results/rtx-a6000-48gb/qwen3.8/reference-20260901/result.json) / [evidence](results/rtx-a6000-48gb/qwen3.8/reference-20260901/report.md) |
<!-- END GENERATED:reference-results -->

## Hardware

| Hardware class | Notes |
|---|---|
| [DGX Spark / GB10](hardware/dgx-spark-gb10/) | ARM64, unified memory; single and dual-host recipes are separate |
| [RTX 3090 24 GB](hardware/rtx3090-24gb/) | Single-GPU profiles bounded to 24 GB VRAM |
| [RTX 4090 48 GB](hardware/rtx4090-48gb/) | 48 GB reported configuration; not interchangeable with a standard 24 GB board |
| [RTX A6000 48 GB](hardware/rtx-a6000-48gb/) | Single NVIDIA RTX A6000 class with 49,140 MiB reported VRAM |

## Recipes

<!-- BEGIN GENERATED:recipes -->
| Hardware | Model | Runtime / profile | Maturity | Recipe |
|---|---|---|---|---|
| dgx-spark-gb10-pair | DeepSeek-V4-Flash-0731 | vllm-patch4 / thinking-off-tp2-control | Archived | [`deepseek-v4.dual-gb10.vllm-flash-0731-patch4-thinking-off`](recipes/deepseek-v4/dual-dgx-spark-gb10-vllm-flash-0731-patch4-thinking-off/) |
| dgx-spark-gb10-pair | DeepSeek-V4-Flash-0731 | vllm-patch4 / thinking-on-tp2 | Reference | [`deepseek-v4.dual-gb10.vllm-flash-0731-patch4-thinking-on`](recipes/deepseek-v4/dual-dgx-spark-gb10-vllm-flash-0731-patch4-thinking-on/) |
| dgx-spark-gb10 | MiniMax-H3 | comfyui / trained-max-362-frames-512x320 | Verified | [`minimax-h3.gb10.comfyui-trained-max-15s`](recipes/minimax-h3/dgx-spark-gb10-comfyui-trained-max-15s/) |
| dgx-spark-gb10 | Qwen3.5-9B | llama.cpp / q4-k-m-8k | Reference | [`qwen3.5.gb10.llamacpp-9b-q4-k-m-8k`](recipes/qwen3.5/dgx-spark-gb10-llamacpp-9b-q4-k-m-8k/) |
| dgx-spark-gb10 | Qwen3.5-9B | vllm / bf16-nightly | Reference | [`qwen3.5.gb10.vllm-9b-bf16`](recipes/qwen3.5/dgx-spark-gb10-vllm-9b-bf16/) |
| dgx-spark-gb10 | Qwen3.6-35B-A3B-UD-Q4_K_S | llama.cpp / q4-k-s-128k | Reference | [`qwen3.6.gb10.llamacpp-35b-a3b-q4-k-s-128k`](recipes/qwen3.6/dgx-spark-gb10-llamacpp-35b-a3b-q4-k-s-128k/) |
| dgx-spark-gb10 | unsloth/Qwen3.6-27B-NVFP4 | vllm / native-nvfp4-mtp2-128k | Reference | [`qwen3.6.gb10.vllm-27b-nvfp4-native-mtp2-128k`](recipes/qwen3.6/dgx-spark-gb10-vllm-27b-nvfp4-native-mtp2-128k/) |
| dgx-spark-gb10 | unsloth/Qwen3.6-27B-NVFP4 | vllm / native-nvfp4-no-mtp-32k | Archived | [`qwen3.6.gb10.vllm-27b-nvfp4-native-no-mtp-32k`](recipes/qwen3.6/dgx-spark-gb10-vllm-27b-nvfp4-native-no-mtp-32k/) |
| dgx-spark-gb10 | Qwen3.6-35B-A3B-FP8 | vllm / fp8-256k | Reference | [`qwen3.6.gb10.vllm-35b-a3b-fp8-256k`](recipes/qwen3.6/dgx-spark-gb10-vllm-35b-a3b-fp8-256k/) |
| dgx-spark-gb10 | Qwen3.6-35B-A3B-NVFP4 | vllm / nvfp4-mtp3-256k | Reference | [`qwen3.6.gb10.vllm-35b-a3b-nvfp4-mtp3-256k`](recipes/qwen3.6/dgx-spark-gb10-vllm-35b-a3b-nvfp4-mtp3-256k/) |
| rtx4090-48gb | qwen3.6:27b | ollama-0.20.2 / q4-k-m-128k-p1 | Reference | [`qwen3.6.rtx4090-48gb.ollama-27b-q4-k-m-128k`](recipes/qwen3.6/rtx4090-48gb-ollama-27b-q4-k-m-128k/) |
| rtx4090-48gb | qwen3.6:35b-a3b | ollama-0.20.2 / q4-k-m-128k-p1 | Archived | [`qwen3.6.rtx4090-48gb.ollama-35b-a3b-q4-k-m-128k`](recipes/qwen3.6/rtx4090-48gb-ollama-35b-a3b-q4-k-m-128k/) |
| rtx4090-48gb | Qwen/Qwen3.6-35B-A3B-FP8 | vllm-0.19.0 / fp8-32k-p2 | Reference | [`qwen3.6.rtx4090-48gb.vllm-35b-a3b-fp8-32k-p2`](recipes/qwen3.6/rtx4090-48gb-vllm-35b-a3b-fp8-32k-p2/) |
| rtx-a6000-48gb | Qwen3.8-27B-UD-Q4_K_XL | llama.cpp / ud-q4-k-xl-mtp2-192k-p1 | Reference | [`qwen3.8.rtx-a6000-48gb.llamacpp-27b-ud-q4-k-xl-mtp2-192k`](recipes/qwen3.8/rtx-a6000-48gb-llamacpp-27b-ud-q4-k-xl-mtp2-192k/) |
| rtx3090-24gb | Qwen3.8-27B-Q3_K_S | llama.cpp / q3-k-s-128k-p2 | Verified | [`qwen3.8.rtx3090-24gb.llamacpp-27b-q3-k-s-128k-p2`](recipes/qwen3.8/rtx3090-24gb-llamacpp-27b-q3-k-s-128k-p2/) |
| rtx4090-48gb | Qwen3.8-27B-UD-Q4_K_XL | llama.cpp / ud-q4-k-xl-mtp2-256k-p1 | Reference | [`qwen3.8.rtx4090-48gb.llamacpp-27b-ud-q4-k-xl-mtp2-256k`](recipes/qwen3.8/rtx4090-48gb-llamacpp-27b-ud-q4-k-xl-mtp2-256k/) |
| rtx4090-48gb | Qwen/Qwen3.8-27B-FP8 | vllm-0.19.0 / fp8-64k-p4 | Reference | [`qwen3.8.rtx4090-48gb.vllm-27b-fp8-64k-p4`](recipes/qwen3.8/rtx4090-48gb-vllm-27b-fp8-64k-p4/) |
<!-- END GENERATED:recipes -->

Supported operation names are `doctor`, `prepare`, `start`, `status`, `accept`,
`benchmark`, `stop`, and `recover`. Each recipe exposes only operations backed
by existing files. An absent operation is unsupported, not an invitation for
the catalog tool to guess a command.

## Benchmark Contract

New text-generation results use versioned suites in [benchmarks/suites/](benchmarks/suites/)
and the schemas in [benchmarks/schemas/](benchmarks/schemas/). They record:

- TTFT and, for reasoning models, first-final-token latency;
- response/end-to-end latency;
- decode TPS, end-to-end output TPS, and concurrent aggregate TPS;
- prompt, completion, reasoning, and cached token counts;
- cold/warm cache state, concurrency, errors, and distributions;
- available hardware memory, RAM, power, temperature, and disk telemetry.

Media generation uses `media-performance-v1`; token metrics are N/A and media
does not enter token-TPS ranking. Historical suites live under
[benchmarks/legacy/](benchmarks/legacy/) and retain their original definitions.
Submission requirements are in [docs/benchmark-submission.md](docs/benchmark-submission.md).

## Operations And Debug

Cross-recipe notes live in [operations/](operations/). Model-specific lifecycle
and recovery steps stay with the exact recipe. Live maintenance work such as a
rank switch or NAS reload remains in GitHub issues until a maintenance window
and real acceptance evidence exist.

## Application Examples

Application projects are under [examples/apps/](examples/apps/). They consume
model services but are not deployment recipes and do not inherit recipe
maturity.

## Contributing

Read [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) before adding a recipe,
benchmark, receipt, debug note, or application. Pull requests run repository-only
fixture, schema, generated-file, privacy, link, and static checks. Contributors
with matching hardware provide the real deployment and benchmark evidence.

```bash
python3 -m unittest discover -s tests -v
./lab generate --check
./lab validate
```
