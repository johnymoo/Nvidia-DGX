# Operational runbook task

Create `answer.md` from the task prompt. This fixture intentionally has no valid answer.

Source facts: `RBK-17`; `worker-queue`; trigger above 20,000 messages for ten minutes; record request ID; check `queue_depth`, `active_workers`, `error_rate`; add two workers at a time and observe at most 15 minutes; no delete or replay; escalate `SEV-2` to `OPS-ONCALL`.
