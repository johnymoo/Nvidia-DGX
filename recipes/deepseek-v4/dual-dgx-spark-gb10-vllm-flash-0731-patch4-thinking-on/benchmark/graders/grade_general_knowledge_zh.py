#!/usr/bin/env python3
"""Hidden exact-key grader for the stable Chinese QA task."""

import json
import sys
import unittest
from pathlib import Path

from graderlib import run_suite, suite_for


EXPECTED = {
    "q1": {"canberra", "堪培拉"},
    "q2": {"pacific ocean", "pacific", "太平洋"},
    "q3": {"au"},
    "q4": {"mars", "火星"},
    "q5": {"jane austen", "奥斯汀", "简奥斯汀", "简·奥斯汀"},
    "q6": {"skin", "皮肤"},
    "q7": {"100", "100c", "100°c", "100摄氏度"},
    "q8": {"366", "366 days", "366天"},
}


def main():
    workspace = Path(sys.argv[1]).resolve()

    class HiddenTests(unittest.TestCase):
        def load_answers(self):
            value = json.loads((workspace / "answers.json").read_text(encoding="utf-8"))
            self.assertIsInstance(value, dict)
            self.assertEqual(set(value), set(EXPECTED))
            return value

        def test_schema(self):
            self.load_answers()

    for key, aliases in EXPECTED.items():
        def check(self, key=key, aliases=aliases):
            value = self.load_answers()[key]
            self.assertIsInstance(value, str)
            self.assertIn(value.strip().lower(), aliases)

        setattr(HiddenTests, f"test_{key}", check)

    return run_suite(suite_for(HiddenTests))


if __name__ == "__main__":
    raise SystemExit(main())
