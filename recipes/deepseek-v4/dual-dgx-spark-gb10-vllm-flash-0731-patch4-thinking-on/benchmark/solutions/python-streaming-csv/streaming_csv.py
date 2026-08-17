"""Bounded-memory CSV aggregation with deterministic malformed-row reporting."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class MalformedRow:
    row_number: int
    reason: str


@dataclass(frozen=True)
class CSVSummary:
    total_rows: int
    accepted_rows: int
    rejected_rows: int
    totals: tuple[tuple[str, Decimal], ...]
    errors: tuple[MalformedRow, ...]


def aggregate_csv(
    lines: Iterable[str],
    *,
    group_column: str = "category",
    amount_column: str = "amount",
    max_errors: int = 10,
) -> CSVSummary:
    """Aggregate CSV records in one pass, retaining only a bounded error sample."""
    if isinstance(lines, str):
        raise TypeError("lines must be an iterable of CSV lines, not one string")
    if isinstance(max_errors, bool) or not isinstance(max_errors, int):
        raise TypeError("max_errors must be an integer")
    if max_errors < 0:
        raise ValueError("max_errors must be non-negative")

    reader = csv.reader(lines)
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ValueError("CSV input is empty") from exc

    if not header or len(header) != len(set(header)):
        raise ValueError("CSV header must contain unique columns")
    try:
        group_index = header.index(group_column)
        amount_index = header.index(amount_column)
    except ValueError as exc:
        raise ValueError("CSV header is missing a required column") from exc

    totals: dict[str, Decimal] = {}
    errors: list[MalformedRow] = []
    total_rows = accepted_rows = rejected_rows = 0

    def reject(row_number: int, reason: str) -> None:
        nonlocal rejected_rows
        rejected_rows += 1
        if len(errors) < max_errors:
            errors.append(MalformedRow(row_number, reason))

    try:
        for row in reader:
            total_rows += 1
            row_number = reader.line_num
            if len(row) != len(header):
                reject(row_number, "wrong column count")
                continue
            group = row[group_index].strip()
            if not group:
                reject(row_number, "blank category")
                continue
            try:
                amount = Decimal(row[amount_index])
            except (InvalidOperation, ValueError):
                reject(row_number, "invalid amount")
                continue
            if not amount.is_finite():
                reject(row_number, "invalid amount")
                continue
            totals[group] = totals.get(group, Decimal("0")) + amount
            accepted_rows += 1
    except csv.Error as exc:
        raise ValueError(f"malformed CSV at line {reader.line_num}") from exc

    return CSVSummary(
        total_rows=total_rows,
        accepted_rows=accepted_rows,
        rejected_rows=rejected_rows,
        totals=tuple(sorted(totals.items())),
        errors=tuple(errors),
    )
