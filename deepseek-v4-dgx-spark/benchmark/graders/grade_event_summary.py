#!/usr/bin/env python3

import dataclasses
import importlib
import sys
import unittest
from pathlib import Path
from unittest import mock

from graderlib import emit_setup_error, run_suite, suite_for


def main():
    try:
        workspace = Path(sys.argv[1]).resolve()
        sys.path.insert(0, str(workspace))
        module = importlib.import_module("event_summary")
    except Exception as exc:
        return emit_setup_error(exc)

    class HiddenTests(unittest.TestCase):
        def test_summary_is_frozen_dataclass(self):
            self.assertTrue(dataclasses.is_dataclass(module.Summary))
            summary = module.Summary(1, 1, 0, 4)
            with self.assertRaises(dataclasses.FrozenInstanceError):
                summary.total = 2

        def test_one_shot_iterable(self):
            events = iter(
                [
                    {"status": "ok", "duration_ms": 3},
                    {"status": "failed", "duration_ms": 4},
                ]
            )
            self.assertEqual(module.summarize(events), module.Summary(2, 1, 1, 7))

        def test_unknown_and_missing_fields(self):
            summary = module.summarize([{}, {"status": "other"}, {"status": "ok"}])
            self.assertEqual(summary, module.Summary(3, 1, 0, 0))

        def test_inputs_are_not_mutated(self):
            events = [{"status": "ok", "duration_ms": 1}]
            before = [dict(event) for event in events]
            module.summarize(events)
            self.assertEqual(events, before)

        def test_invalid_durations(self):
            for duration in (True, -1, 1.5, "2"):
                with self.subTest(duration=duration), self.assertRaises(ValueError):
                    module.summarize([{"duration_ms": duration}])

        def test_render_text_delegates(self):
            expected = module.Summary(2, 1, 1, 9)
            with mock.patch.object(module, "summarize", return_value=expected) as called:
                self.assertEqual(
                    module.render_text(iter(())),
                    "total=2 ok=1 failed=1 duration_ms=9",
                )
                called.assert_called_once()

        def test_render_json_delegates_and_is_exact(self):
            expected = module.Summary(2, 1, 1, 9)
            with mock.patch.object(module, "summarize", return_value=expected) as called:
                self.assertEqual(
                    module.render_json(iter(())),
                    '{"duration_ms":9,"failed":1,"ok":1,"total":2}',
                )
                called.assert_called_once()

        def test_regular_output_is_preserved(self):
            events = [{"status": "ok", "duration_ms": 2}, {"status": "failed"}]
            self.assertEqual(
                module.render_text(events), "total=2 ok=1 failed=1 duration_ms=2"
            )

    return run_suite(suite_for(HiddenTests))


if __name__ == "__main__":
    raise SystemExit(main())
