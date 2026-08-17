from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BenchmarkSafetyTests(unittest.TestCase):
    def test_online_matrix_requires_endpoint_and_opt_in(self) -> None:
        script = (ROOT / "benchmark" / "run_pro_quick_matrix.sh").read_text()
        self.assertIn("BASE_URL=${ONLINE_DS_BASE_URL:-}", script)
        self.assertIn("ONLINE_DS_ALLOW_EXTERNAL", script)
        self.assertNotIn("coding.onlyservice.io", script)

    def test_agent_focus_requires_external_opt_in_and_task_success(self) -> None:
        script = (ROOT / "benchmark" / "run_pro_agent_focus.py").read_text()
        self.assertIn('parser.add_argument("--base-url", required=True)', script)
        self.assertIn('parser.add_argument("--allow-external", action="store_true")', script)
        self.assertIn('all(item["task_status"] == "passed"', script)
        self.assertNotIn("coding.onlyservice.io", script)

    def test_report_records_raw_agent_input_provenance(self) -> None:
        script = (ROOT / "benchmark" / "generate_pro_comparison_report.py").read_text()
        self.assertIn('"raw_input_sha256": agent_raw_sha256', script)
        self.assertIn('"raw_input_committed": False', script)


if __name__ == "__main__":
    unittest.main()
