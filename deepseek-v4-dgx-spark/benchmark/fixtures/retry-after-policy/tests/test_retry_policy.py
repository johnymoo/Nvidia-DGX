import unittest
from datetime import datetime, timezone

from retry_policy import next_delay, parse_retry_after


NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


class RetryPolicyTests(unittest.TestCase):
    def test_seconds_header(self):
        self.assertEqual(parse_retry_after(" 12 ", now=NOW), 12.0)

    def test_http_date(self):
        self.assertEqual(
            parse_retry_after("Tue, 11 Aug 2026 12:00:30 GMT", now=NOW), 30.0
        )

    def test_header_can_raise_backoff(self):
        self.assertEqual(next_delay(2, base=1, cap=30, retry_after="9", now=NOW), 9.0)

    def test_cap_is_applied_last(self):
        self.assertEqual(next_delay(2, base=2, cap=5, retry_after="20", now=NOW), 5.0)


if __name__ == "__main__":
    unittest.main()
