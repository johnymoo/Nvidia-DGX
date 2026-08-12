"""Render compact summaries for task events."""

import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Summary:
    total: int
    ok: int
    failed: int
    duration_ms: int


def summarize(events):
    total = 0
    ok = 0
    failed = 0
    duration_ms = 0
    for event in events:
        total += 1
        if event.get("status") == "ok":
            ok += 1
        elif event.get("status") == "failed":
            failed += 1
        duration = event.get("duration_ms", 0)
        if isinstance(duration, bool) or not isinstance(duration, int) or duration < 0:
            raise ValueError("duration_ms must be a non-negative integer")
        duration_ms += duration
    return Summary(total=total, ok=ok, failed=failed, duration_ms=duration_ms)


def render_text(events):
    summary = summarize(events)
    return (
        f"total={summary.total} ok={summary.ok} failed={summary.failed} "
        f"duration_ms={summary.duration_ms}"
    )


def render_json(events):
    return json.dumps(asdict(summarize(events)), sort_keys=True, separators=(",", ":"))
