## Summary

INC-API-204 affected catalog-api on 2026-08-11 from 13:20-13:46 UTC. During that interval, the service returned a 7.2% 503 rate. The current incident record identifies an upstream connection pool capped at 40 as the supplied cause. This update is intended to give engineering and support teams the same bounded status, rather than extend the evidence beyond the incident record.

## Impact

The observed impact was the elevated 503 rate for catalog-api during the stated window. The packet does not provide a customer count or a data-loss finding, so neither is included here. Support should use the incident ID and time window when correlating reports, and should avoid inferring impacts not covered by the record.

## Current status

The mitigation raised the cap to 80 and recycled affected workers. Those actions address the documented condition for this event. They do not, by themselves, establish a permanent fix or a broader reliability conclusion.

## Next steps

RCA-204 remains the tracking record for follow-up analysis. A load test is due by 2026-08-15 to exercise the relevant pool behavior under controlled conditions. The incident update should be revised when that work produces new evidence.
