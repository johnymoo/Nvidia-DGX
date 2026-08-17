# Benchmark Validation Adapter

`validate_submission.py` validates suite source hashes and packaged result
bundles. It is deliberately hostless: it never contacts an endpoint or runs
model inference. A contributor runs the actual workload on matching hardware,
then uses this adapter to verify the sanitized bundle before submission.

```bash
python3 benchmarks/runner/validate_submission.py --all
python3 benchmarks/runner/validate_submission.py results/<hardware>/<model>/<run-id>
```

Canonical suite identity applies only to a new run that records the exact
suite, workload, request parameters, cache state, concurrency, raw evidence,
and receipt hash. It is never assigned retroactively to historical results.
