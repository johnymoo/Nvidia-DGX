from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class QuantizationReportTests(unittest.TestCase):
    def test_report_contains_selection_and_separate_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.html"
            summary = Path(directory) / "summary.json"
            subprocess.run(
                ["python3", str(ROOT / "scripts" / "generate_quantization_report.py"), "--output", str(output), "--summary-output", str(summary)],
                check=True,
                capture_output=True,
                text=True,
            )
            report = output.read_text()
        self.assertIn("选择 UD-Q4_K_XL + MTP2", report)
        self.assertIn("94.33 tok/s", report)
        self.assertIn("短输出交叉验证", report)
        self.assertIn("上下文档位实测", report)
        self.assertIn("245,034", report)
        self.assertIn("准确率与任务时延", report)
        self.assertIn("Dynamic GGUF 不是单一位宽", report)
        self.assertIn("@page{size:A4 landscape", report)


if __name__ == "__main__":
    unittest.main()
