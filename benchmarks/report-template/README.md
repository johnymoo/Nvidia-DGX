# Benchmark Report Template

Every report states the recipe ID, exact hardware/model/runtime/profile, suite
version, workload, cache state, concurrency, receipt, metric definitions, raw
result path, and invalidation conditions.

Use separate sections for:

1. acceptance and identity;
2. TTFT, first-final-token, response time, decode TPS, E2E output TPS, and
   aggregate TPS;
3. prompt/completion/reasoning/cached tokens and errors;
4. min/mean/p50/p95/p99/max distributions;
5. available GPU/unified-memory, RAM, power, temperature, and disk telemetry;
6. quality/context floors and known limitations.

Unsupported metrics are `N/A`; they are never represented as zero and are
excluded from applicable averages. Different hardware may be shown side by side
but is never ranked together.

Copy [REPORT.md](REPORT.md) into each new result bundle. Validate the completed
bundle with `python3 benchmarks/runner/validate_submission.py <bundle>`.
