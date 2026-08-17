#!/usr/bin/env python3
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / "scripts" / "generate_parameter_matrix_report.py"


def sample_run(repeat: int) -> dict:
    categories = {
        category: {"score": 0.5, "completion_tokens": 10, "length_truncations": 0, "empty_finals": 0}
        for category in ("sql", "python", "incident")
    }
    return {
        "harness_id": "lakehouse-thinking-v1",
        "status": "passed",
        "tag": "private-low",
        "treatment": "private DS / low",
        "base_url": "private-dgx-spark",
        "model": "deepseek-v4-flash-0731",
        "mode": "deepseek-thinking",
        "repeat": repeat,
        "expected_runs": 2,
        "max_tokens": 32768,
        "sampling": "DeepSeek private-vllm; official-local-general; effort=low",
        "request_config": {"deepseek_effort": "low", "max_response_chars": 32000, "max_reasoning_chars": 32000},
        "categories": categories,
        "macro_score": 0.5,
        "total_seconds": 12.5,
        "cases": [{"id": "x", "category": "sql"}],
    }


class ParameterMatrixReportTests(unittest.TestCase):
    def test_report_aggregates_complete_repeats(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for repeat in (1, 2):
                (root / f"run-{repeat}.json").write_text(json.dumps(sample_run(repeat)))
            output = root / "matrix.html"
            subprocess.run(
                [sys.executable, str(SCRIPT), "--input-dir", str(root), "--recommendation", "test", "--output", str(output)],
                check=True,
                capture_output=True,
                text=True,
            )
            document = output.read_text()
            self.assertIn("private DS / low", document)
            self.assertIn("50.0%", document)
            self.assertIn("2</td>", document)
            self.assertIn("DeepSeek 成本", document)
            self.assertIn("重复稳定性", document)


if __name__ == "__main__":
    unittest.main()
