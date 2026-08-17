#!/usr/bin/env python3
"""Hidden factual and non-overclaiming grader for the English pilot brief."""

import re
import sys
import unittest
from pathlib import Path

from graderlib import run_suite, suite_for


REQUIRED = (
    "2.1.207", "deepseek-v4-flash", "deepseek-v4-flash-0731", "3/4",
    "571.060", "417.190", "token", "cache", "cost", "one repetition",
)
FORBIDDEN = ("is the overall winner", "statistically significant", "significance result")


def main():
    workspace = Path(sys.argv[1]).resolve()

    class HiddenTests(unittest.TestCase):
        def text(self):
            return (workspace / "answer.md").read_text(encoding="utf-8").strip()

        def test_word_count(self):
            words = re.findall(r"[A-Za-z0-9][A-Za-z0-9.'/-]*", self.text())
            self.assertGreaterEqual(len(words), 170)
            self.assertLessEqual(len(words), 230)

        def test_required_facts(self):
            text = self.text().lower()
            for fact in REQUIRED:
                with self.subTest(fact=fact):
                    self.assertIn(fact.lower(), text)

        def test_no_winner_or_significance_claim(self):
            text = self.text().lower()
            for phrase in FORBIDDEN:
                with self.subTest(phrase=phrase):
                    self.assertNotIn(phrase, text)

    return run_suite(suite_for(HiddenTests))


if __name__ == "__main__":
    raise SystemExit(main())
