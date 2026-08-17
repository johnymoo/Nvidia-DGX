# Change approval memo task

Create `answer.md` from the task prompt. This fixture intentionally has no valid answer.

Source facts: `CHG-4821`; 2026-08-16 02:00-02:30 CST; `billing-api`, three replicas, `v2.8.4` to `v2.8.5`; one-replica ten-minute canary; error rate below 0.5%; p95 at most 350 ms; rollback to `v2.8.4`; approver Mei Lin.
