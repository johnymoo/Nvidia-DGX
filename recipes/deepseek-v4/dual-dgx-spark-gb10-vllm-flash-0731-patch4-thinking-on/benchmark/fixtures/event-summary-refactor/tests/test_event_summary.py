import unittest

import event_summary


EVENTS = [
    {"status": "ok", "duration_ms": 7},
    {"status": "failed", "duration_ms": 5},
    {"status": "skipped"},
]


class EventSummaryTests(unittest.TestCase):
    def test_text_format_is_preserved(self):
        self.assertEqual(
            event_summary.render_text(EVENTS),
            "total=3 ok=1 failed=1 duration_ms=12",
        )

    def test_json_format_is_preserved(self):
        self.assertEqual(
            event_summary.render_json(EVENTS),
            '{"duration_ms":12,"failed":1,"ok":1,"total":3}',
        )

    def test_summary_accepts_generator(self):
        summary = event_summary.summarize(event for event in EVENTS)
        self.assertEqual((summary.total, summary.ok, summary.failed), (3, 1, 1))


if __name__ == "__main__":
    unittest.main()
