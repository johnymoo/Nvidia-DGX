import sys
import tempfile
import unittest
from pathlib import Path


BENCHMARKS = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BENCHMARKS / "graders"))

import r3_writing  # noqa: E402


class WritingGraderNormalizationTests(unittest.TestCase):
    task_id = "writing-zh-incident"

    def valid_text(self) -> str:
        task = r3_writing.load_tasks()[self.task_id]
        grading = task["grading"]
        lines = [f"## {heading}" for heading in grading["required_headings"]]
        lines.extend(fact["aliases"][0] for fact in grading["required_facts"])
        text = "\n".join(lines)
        padding = grading["min_length"] - r3_writing.length_of(text, grading["language"]) + 5
        return text + "\n" + ("验" * padding)

    def evaluate(self, text: str) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "answer.md").write_text(text, encoding="utf-8")
            return r3_writing.evaluate(workspace, self.task_id)

    def test_equivalent_date_and_number_punctuation_passes(self):
        text = self.valid_text()
        text = text.replace("2026-08-10", "２０２６／０８／１０")
        text = text.replace("1,842 个请求", "１，８４２ 个请求")
        result = self.evaluate(text)
        self.assertEqual(result["status"], "passed")

    def test_wrong_stable_identifier_fails(self):
        result = self.evaluate(self.valid_text().replace("INC-2026-0810", "INC-2026-0811"))
        self.assertEqual(result["status"], "failed")
        self.assertIn("incident_id", " ".join(result["failures"]))

    def test_wrong_stable_number_fails(self):
        result = self.evaluate(self.valid_text().replace("1,842 个请求", "1,843 个请求"))
        self.assertEqual(result["status"], "failed")
        self.assertIn("affected_requests", " ".join(result["failures"]))


if __name__ == "__main__":
    unittest.main()
