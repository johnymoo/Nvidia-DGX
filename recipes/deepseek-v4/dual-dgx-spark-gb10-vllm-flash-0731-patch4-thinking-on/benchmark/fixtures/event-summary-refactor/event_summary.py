"""Render compact summaries for task events."""

import json


def render_text(events):
    total = len(events)
    ok = sum(1 for event in events if event.get("status") == "ok")
    failed = sum(1 for event in events if event.get("status") == "failed")
    duration_ms = sum(event.get("duration_ms", 0) for event in events)
    return f"total={total} ok={ok} failed={failed} duration_ms={duration_ms}"


def render_json(events):
    payload = {
        "total": len(events),
        "ok": sum(1 for event in events if event.get("status") == "ok"),
        "failed": sum(1 for event in events if event.get("status") == "failed"),
        "duration_ms": sum(event.get("duration_ms", 0) for event in events),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
