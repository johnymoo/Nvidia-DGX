"""Deterministic retry delay policy."""


def parse_retry_after(value, now=None):
    return None


def next_delay(attempt, *, base=1.0, cap=60.0, retry_after=None, now=None):
    if attempt < 0:
        raise ValueError("attempt must be non-negative")
    return min(cap, base * (2**attempt))
