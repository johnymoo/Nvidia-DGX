# Benchmark Report: <result-id>

## Identity

- Recipe: `<recipe-id>`
- Hardware / model / runtime / profile: `<exact identities>`
- Suite / workload: `<suite@version>` / `<workload-id>`
- Receipt and SHA-256: `<path>` / `<sha256>`
- Cache / concurrency / samples: `<state>` / `<n>` / `<n>`

## Acceptance

State model identity, deployment acceptance, reliability, safety, quality floor,
and context floor. Link each claim to the receipt or raw record.

## Performance

| Metric | min | mean | p50 | p95 | p99 | max | Definition |
|---|---:|---:|---:|---:|---:|---:|---|
| TTFT (s) | | | | | | | first non-empty streaming delta |
| First final token (s) | | | | | | | reasoning models only |
| Response/E2E (s) | | | | | | | request to stream completion |
| Decode TPS | | | | | | | tokens after first delta / decode interval |
| Output TPS E2E | | | | | | | completion tokens / E2E |
| Aggregate TPS | | | | | | | batch completion tokens / batch wall time |

Use `N/A: <reason>` when a metric is inapplicable. Never use zero for missing
data. Record prompt, completion, reasoning, cached tokens, errors, and hardware
telemetry below the table.

## Quality And Context

Record the configured floor IDs, thresholds, measured values, and status. A
missing floor makes the result ineligible for Best Verified.

## Raw Evidence

- Raw request records: `<path>`
- Manifest: `manifest.sha256`
- Sanitization performed: `<commands/checks>`
- Invalidation conditions: `<list>`

## Limitations

Describe workload scope, unavailable telemetry, and comparison boundaries.
