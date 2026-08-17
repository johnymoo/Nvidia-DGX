"""Aggregate category amounts from CSV input."""

from decimal import Decimal


def aggregate_csv(lines, *, group_column="category", amount_column="amount", max_errors=10):
    rows = list(lines)
    if not rows:
        raise ValueError("CSV input is empty")
    header = rows[0].strip().split(",")
    group_index = header.index(group_column)
    amount_index = header.index(amount_column)
    totals = {}
    errors = []
    for number, raw in enumerate(rows[1:], start=2):
        try:
            cells = raw.strip().split(",")
            group = cells[group_index]
            totals[group] = totals.get(group, Decimal("0")) + Decimal(cells[amount_index])
        except Exception:
            if len(errors) < max_errors:
                errors.append((number, "invalid row"))
    return {"totals": totals, "errors": errors}
