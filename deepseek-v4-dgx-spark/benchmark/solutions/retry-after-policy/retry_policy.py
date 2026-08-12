"""Deterministic retry delay policy."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def parse_retry_after(value, now=None):
    if value is None or not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    if value.isdecimal():
        return float(value)
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        return None
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        return None
    return max(0.0, (parsed - now).total_seconds())


def next_delay(attempt, *, base=1.0, cap=60.0, retry_after=None, now=None):
    if attempt < 0 or base < 0 or cap < 0:
        raise ValueError("attempt, base, and cap must be non-negative")
    delay = base * (2**attempt)
    header_delay = parse_retry_after(retry_after, now=now)
    if header_delay is not None:
        delay = max(delay, header_delay)
    return min(cap, delay)
