# NVIDIA Private Model Deployment Lab: Repository Design

Status: approved for implementation on 2026-08-17

Baseline: `repo-reorg-r2`

## Purpose

This repository is an open-source, operator-first record of private model
deployment and verification on NVIDIA hardware. A reader with matching hardware
should be able to clone the repository, select a recipe, reproduce the recorded
configuration, run its acceptance checks, and compare the result with a
hardware-bound benchmark record.

Applications remain useful examples but are not part of the deployment core.
They live under `examples/apps/`.

## User Stories

### US-1: Open-source operator

As an operator with matching NVIDIA hardware, I want to start from a clone and
follow a standard recipe through preparation, start, acceptance, benchmark,
stop, and recovery, so that I can determine whether the deployment actually
works on my machine.

- Given a Verified recipe and its matching hardware, when the standard recipe
  workflow is executed, then the operator gets a healthy API, model identity
  evidence, acceptance result, benchmark result, and deployment receipt.
- A recipe without subject-bound hardware evidence is Reference or Archived,
  never Verified.

### US-2: Benchmark reader

As a benchmark reader, I want common suites, runners, schemas, and report
templates, so that results are comparable within explicit model, hardware,
quantization, runtime, and suite-version boundaries.

- Given different model and hardware profiles, when a benchmark runs, then it
  records TTFT, first final token for reasoning models, end-to-end latency,
  decode/output/aggregate TPS, token counts, cache data, errors, distributions,
  and hardware telemetry.
- Unsupported capabilities are N/A and excluded from applicable averages.
- Unlike hardware is displayed side by side but never ranked as one efficiency
  leaderboard.

### US-3: Repository maintainer

As a maintainer, I want one information architecture for recipes, receipts,
benchmarks, and debug experience, so that contributions are reviewable,
reproducible, and safe to publish.

- Every open issue and pull request receives a merge, close, supersede, defer,
  or external-maintenance disposition with evidence.
- Private addresses, host aliases, user paths, credentials, weights, and raw
  private logs are not committed.
- Existing application projects move under `examples/apps/`.

### US-4: Homepage reader

As a new repository visitor, I want an operator-first README, so that I can find
the shortest valid deployment path and the best verified result for my hardware
and model.

The homepage order is:

1. quick start and verification;
2. Best Verified benchmark by hardware and model;
3. hardware recipe index;
4. operations and debug notes;
5. application examples.

## Delivery Boundary

This reorganization uses only files and evidence already present in the
repository or incoming open pull requests. It does not connect to GPU hosts,
start or stop model services, reload NAS services, or run real model inference.
Static checks, fixture tests, schema validation, report regeneration, and
Compose rendering do not upgrade a recipe to Verified.

Issues that require a maintenance window remain open with an explicit external
action and acceptance contract.

## Information Architecture

```text
/
|-- README.md
|-- catalog/
|   |-- recipes.json
|   `-- latest-benchmarks.json
|-- recipes/
|   `-- <model-family>/<hardware-runtime-profile>/
|       |-- recipe.yaml
|       |-- README.md
|       |-- run.sh
|       |-- config/
|       |-- scripts/
|       |-- tests/
|       `-- receipts/
|-- hardware/
|   |-- dgx-spark-gb10/
|   |-- rtx3090-24gb/
|   `-- rtx4090-48gb/
|-- benchmarks/
|   |-- suites/
|   |-- runner/
|   |-- schemas/
|   `-- report-template/
|-- results/<hardware>/<model>/<run-id>/
|-- operations/
|   |-- runbooks/
|   |-- incidents/
|   `-- debug-notes/
|-- tools/
|-- docs/
`-- examples/apps/
```

Historical projects may initially retain their internal layout after `git mv`.
They receive a canonical `recipe.yaml` and maturity classification before any
deeper profile split. This preserves history and avoids inventing unverified
commands during migration.

## Maturity

- **Verified**: subject-bound deployment receipt and real acceptance evidence
  exist for the exact model, hardware class, runtime, and profile.
- **Reference**: instructions or scripts are useful, but the repository lacks
  current complete acceptance evidence.
- **Archived**: retained for debug, historical comparison, or superseded
  configuration; no current-run claim.

Migration never upgrades maturity. When evidence is incomplete or ambiguous,
the lower maturity wins.

## Recipe Contract

Canonical recipes expose these operations when the historical implementation
supports them:

```text
doctor, prepare, start, status, accept, benchmark, stop, recover
```

The standard `run.sh` delegates to existing project scripts. Unsupported
operations fail with a clear non-zero result; migration does not manufacture
missing lifecycle behavior.

`recipe.yaml` records:

- recipe, model, hardware, runtime, and maturity IDs;
- artifact revision, manifest, image digest, and quantization when known;
- driver, memory, disk, and operating-system requirements;
- supported acceptance and benchmark suites;
- known limitations and invalidation conditions;
- latest receipt and benchmark result references.

The root `lab` tool is a small catalog/schema/dispatch utility. It does not
replace model-specific controllers or manage remote services.

## Evidence Contract

An immutable result bundle has:

```text
results/<hardware>/<model>/<run-id>/
|-- result.json
|-- receipt.json
|-- manifest.sha256
|-- report.md
`-- README.md
```

Receipts bind deployment identity and acceptance. Results bind benchmark suite,
runner, request parameters, raw metrics, and receipt hash. Historical evidence
that cannot be safely relocated may remain in place and be cataloged by path;
the catalog must state that it is legacy evidence.

Committed evidence is limited to sanitized receipts, compact JSON, small test
fixtures, Markdown reports, and manifests. Weights, secrets, large logs, traces,
and generated media are excluded. External large artifacts require URL, byte
size, and SHA-256.

## Benchmark Contract

Versioned suites are:

- `performance-v1`: mandatory for generation recipes;
- `core-text-v1`: deterministic text, JSON, math, and constrained writing;
- `long-context-v1`: bounded context levels;
- `multimodal-v1`: optional image/video input;
- `coding-ops-v1`: programming, terminal, and operations tasks;
- `media-generation-v1`: separate image/video generation evaluation.

Client-observable metrics are mandatory. Runtime-specific server metrics are
optional adapters.

The canonical definitions are:

- TTFT: request start to first non-empty streaming delta;
- first-final-token: request start to first final-answer token for reasoning;
- E2E: request start to stream completion;
- decode TPS: completion tokens after first token divided by decode duration;
- output TPS E2E: completion tokens divided by E2E;
- aggregate TPS: concurrent batch completion tokens divided by batch wall time.

Every case records prompt, completion, reasoning, and cached tokens when
available; error category; cold/hot cache state; concurrency; and
min/mean/p50/p95/p99/max. Hardware telemetry includes available GPU or unified
memory, RAM, power, temperature, and disk measurements when evidence exists.

## Best Verified Selection

The homepage groups by `hardware_id + model_family`. Quantizations and runtimes
compete only inside that group and remain visible in the selected row.

A candidate must pass deployment acceptance, use the active benchmark-suite
major version, satisfy the model-group quality and context floor, and have no
reliability or safety regression. Eligible candidates are ordered by aggregate
TPS, then decode TPS, then TTFT. A manual override requires a machine-readable
reason. Different hardware is never ranked.

This implementation may catalog existing best results but does not recalculate
or promote them from incomplete historical evidence.

## Homepage

The root README follows the approved Operator First prototype. Generated tables
are checked against `catalog/latest-benchmarks.json`. Each benchmark row links
to its receipt and full report and identifies prototype, legacy, Reference, or
Verified status honestly.

## Open Work Governance

- Merge PR #32 only after focused review and repository-only verification.
- Close PR #27 as superseded; do not merge its private-topology history.
- Close completed issues only after binding the merged commit or retained
  evidence.
- Keep rank-switch, NAS reload, and other live changes open as external
  maintenance tasks.
- Set the repository default branch to `main` after the open-PR convergence.

## Validation

Repository validation includes:

- schema and catalog checks;
- recipe entry-point syntax and fixture tests;
- existing project unit tests;
- Compose rendering with example configuration;
- benchmark/report deterministic regeneration where supported;
- privacy and broken-link scans;
- a fresh clone static smoke that lists recipes, validates metadata, and runs
  all no-host checks.

No validation step in this delivery performs model inference.
