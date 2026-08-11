#!/usr/bin/env python3

import importlib
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

from graderlib import emit_setup_error, run_suite, suite_for


NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


def main():
    try:
        workspace = Path(sys.argv[1]).resolve()
        sys.path.insert(0, str(workspace))
        module = importlib.import_module("retry_policy")
    except Exception as exc:
        return emit_setup_error(exc)

    class HiddenTests(unittest.TestCase):
        def test_integer_seconds(self):
            self.assertEqual(module.parse_retry_after("0", now=NOW), 0.0)
            self.assertEqual(module.parse_retry_after(" 45 ", now=NOW), 45.0)

        def test_http_date_and_past_date(self):
            self.assertEqual(
                module.parse_retry_after("Tue, 11 Aug 2026 12:02:00 GMT", now=NOW),
                120.0,
            )
            self.assertEqual(
                module.parse_retry_after("Tue, 11 Aug 2026 11:59:00 GMT", now=NOW),
                0.0,
            )

        def test_invalid_values_are_ignored(self):
            for value in (None, "", "-1", "1.5", "tomorrow", 12):
                with self.subTest(value=value):
                    self.assertIsNone(module.parse_retry_after(value, now=NOW))

        def test_naive_http_date_is_ignored(self):
            self.assertIsNone(
                module.parse_retry_after("Tue, 11 Aug 2026 12:01:00", now=NOW)
            )

        def test_exponential_backoff_without_header(self):
            self.assertEqual(module.next_delay(3, base=1.5, cap=99, now=NOW), 12.0)

        def test_larger_delay_wins_before_cap(self):
            self.assertEqual(
                module.next_delay(3, base=2, cap=50, retry_after="20", now=NOW),
                20.0,
            )
            self.assertEqual(
                module.next_delay(4, base=2, cap=50, retry_after="3", now=NOW),
                32.0,
            )

        def test_cap_is_last(self):
            self.assertEqual(
                module.next_delay(1, base=2, cap=3, retry_after="90", now=NOW),
                3.0,
            )

        def test_negative_numeric_inputs_are_rejected(self):
            for kwargs in (
                {"attempt": -1},
                {"attempt": 0, "base": -0.1},
                {"attempt": 0, "cap": -1},
            ):
                attempt = kwargs.pop("attempt")
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    module.next_delay(attempt, **kwargs)

    return run_suite(suite_for(HiddenTests))


if __name__ == "__main__":
    raise SystemExit(main())
