## Decision

PROP-77 asks the architecture review to choose a bounded next step for the cache layer. The immediate decision is not a permanent platform selection. It is whether to run a 14-day Redis trial with clear observations on latency, invalidation behavior, operating cost, and rollback readiness.

## Options

The file cache has a 12 ms latency target, 15-minute invalidation, and a $90/month cost. It is the lower-cost option in the supplied comparison, but its invalidation interval is longer. The Redis cache has 4 ms latency, 60-second invalidation, and a $310/month cost. It offers shorter listed latency and invalidation values while introducing a higher monthly cost. These figures describe the proposal inputs; they are not measured business outcomes or a guarantee of production behavior.

## Recommendation and safeguards

Recommend the 14-day Redis trial because it can test whether the shorter invalidation interval is useful enough to justify the added cost. Keep the file cache available as the rollback option during the trial. Define observations before the start, review the recorded results at the end, and return to the architecture review for a separate decision. The trial is explicitly time limited. This keeps PROP-77 reversible and avoids treating the trial as prior approval for a permanent migration.
