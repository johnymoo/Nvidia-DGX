# Benchmark Submission

## Required Identity

A canonical result binds the recipe ID, exact suite ID/version, workload ID,
concurrency, cache state, request parameters, deployment receipt, model/runtime
identity, and raw result path. New result bundles follow:

```text
results/<hardware>/<model>/<run-id>/
|-- result.json
|-- receipt.json
|-- manifest.sha256
|-- report.md
`-- README.md
```

## Repository-Only Packaging Workflow

1. Select one exact recipe and read its maturity, limitations, and invalidation
   conditions. Inspect operations with `./run.sh` or `./lab run ... --dry-run`.
2. On matching hardware, run the declared acceptance and a canonical suite.
   This repository delivery does not perform that step for you.
3. Copy [REPORT.md](../benchmarks/report-template/REPORT.md) into the new result
   bundle. Add sanitized raw request records or an external URL, byte count, and
   SHA-256; never add weights, private topology, credentials, or raw host logs.
4. Hash the four required bundle files:

   ```bash
   cd results/<hardware>/<model>/<run-id>
   sha256sum README.md result.json receipt.json report.md > manifest.sha256
   ```

5. Validate before opening a pull request:

   ```bash
   python3 benchmarks/runner/validate_submission.py results/<hardware>/<model>/<run-id>
   ./scripts/validate-no-host.sh
   ```

6. Use the pull-request template and state separately which checks ran on real
   hardware and which were repository-only.

## Required Performance Fields

Text and multimodal text-generation results include every field below. Use
`null` with an explanation when a field is inapplicable or unavailable; never
substitute zero.

- TTFT: request start to first non-empty streaming delta
- first-final-token: request start to the first final-answer token
- response/E2E: request start to stream completion
- decode TPS: tokens after the first token divided by decode duration
- output TPS E2E: completion tokens divided by response/E2E duration
- aggregate TPS: concurrent batch completion tokens divided by batch wall time
- prompt, completion, reasoning, and cached token counts
- error category, cache state, concurrency, and min/mean/p50/p95/p99/max
- available GPU/unified memory, RAM, power, temperature, and disk telemetry

Media generation uses `media-performance-v1`: time to first artifact, end-to-end
generation time, artifact count/duration/resolution, errors, distributions, and
available hardware telemetry. It does not enter token-TPS ranking.

## Best Verified Eligibility

The selector in `catalog/benchmark-policy.json` is deterministic and
fail-closed. A candidate needs Verified recipe and result maturity, the active
suite major version, explicit identity fields, a resolvable receipt, passing
acceptance/reliability/safety, and every ranking metric. Missing values make it
ineligible. Hardware is grouped before ranking.

## Historical Results

Legacy data may be indexed as Reference without changing its values. State the
original metric definition, workload, concurrency, and source report; set
`legacy_metric_definitions: true`; do not assign an active suite retroactively.
The complete packaging-only fixture is
[benchmarks/examples/reference-bundle](../benchmarks/examples/reference-bundle/).
