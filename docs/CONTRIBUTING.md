# Contributing

Contributions should help another operator reproduce an exact private-model
deployment or understand a bounded historical result.

## Recipe Changes

One recipe represents one exact model family/checkpoint, hardware class,
runtime, and profile. Add a JSON-compatible `recipe.yaml` under
`recipes/<model-family>/<exact-profile>/` with maturity, supported operations,
evidence, limitations, and invalidation conditions.

Do not mark a recipe Verified from static tests, a model card, screenshots, or
another hardware class. Verified requires subject-bound acceptance evidence for
the exact profile. When evidence is incomplete, use Reference; use Archived for
superseded or control profiles.

## Public Evidence

Commit sanitized receipts, compact JSON, small fixtures, reports, and hashes.
Do not commit credentials, private addresses, host aliases, user paths, private
service URLs, weights, raw logs, large traces, or generated media. External
artifacts need a URL, byte size, and SHA-256.

Preserve the difference between checkpoint identity and a served alias. Record
image digests, artifact revisions and manifests when available. Missing identity
stays missing; never infer it during review.

## Benchmark Changes

Follow [benchmark-submission.md](benchmark-submission.md). Do not rewrite old
TTFT/TPS fields into a new definition. Keep legacy evidence in place or under
`benchmarks/legacy/`, set `legacy_metric_definitions: true`, and publish a new
canonical result only after running the named suite.

## Repository Layout

- `recipes/`: exact deployment profiles and their evidence
- `hardware/`: hardware-class entry points
- `benchmarks/`: suites, schemas, report template, runners, and legacy projects
- `results/`: canonical result wrappers and bundles
- `operations/`: cross-recipe runbooks, incidents, and debug notes
- `examples/apps/`: applications that consume model services
- `catalog/`: generated machine-readable indexes

## Before Opening A Pull Request

```bash
python3 -m unittest discover -s tests -v
./lab generate --write
./lab validate
git diff --check
```

Describe what was tested on real hardware and what was only checked statically.
Include rollback/recovery notes for lifecycle changes. Do not report a host test
that was not actually run.
