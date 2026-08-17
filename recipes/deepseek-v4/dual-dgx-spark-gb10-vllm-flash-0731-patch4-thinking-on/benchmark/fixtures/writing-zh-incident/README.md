# Incident postmortem task

Create `answer.md` from the task prompt. This fixture intentionally has no valid answer.

Source facts: `INC-2026-0810`; 2026-08-10; 09:12 CST; order API p95 4.8 seconds; release `rel-20260810.3`; upstream connection pool exhausted; rollback at 09:31; p95 180 ms at 09:37; 1,842 affected requests; follow-ups `CR-142` and `CR-143`.
