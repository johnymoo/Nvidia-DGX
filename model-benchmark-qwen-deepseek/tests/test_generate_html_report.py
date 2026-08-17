#!/usr/bin/env python3
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / "scripts" / "generate_html_report.py"

SPEC = importlib.util.spec_from_file_location("generate_html_report", SCRIPT)
assert SPEC and SPEC.loader
REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)


class GenerateHtmlReportTests(unittest.TestCase):
    def test_summarize_deepseek_performance_accepts_missing_sections_and_values(self) -> None:
        summary = REPORT.summarize_deepseek_performance(
            {
                "single_stream": [
                    {"label": "complete", "best": {"tokens_per_second": 12.5}},
                    {"label": "missing", "best": {}},
                ],
                "prefill": [{"target_tokens": 100, "prefill_tokens_per_second": None}],
            }
        )

        self.assertEqual(
            summary,
            {
                "single_stream": {"complete": 12.5, "missing": None},
                "concurrency": {},
                "prefill": {"100": None},
            },
        )

    def test_performance_rows_render_na_and_skip_missing_deepseek_ratio(self) -> None:
        rows = REPORT.performance_rows(
            {
                "qwen36": {"single_stream": {"case": 10.0}},
                "qwen38": {"single_stream": {"case": 5.0}},
            },
            {},
            "single_stream",
        )

        self.assertEqual(
            rows,
            "<tr><td>case</td><td>10.0</td><td>5.0</td><td>N/A</td><td>50.0%</td><td>N/A</td></tr>",
        )

    def test_report_generation_allows_omitted_deepseek_performance_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "index.html"
            command = [
                sys.executable,
                str(SCRIPT),
                "--performance",
                "data/performance-comparison.json",
                "--qwen36-quality",
                "data/qwen36-quality.json",
                "--qwen38-quality",
                "data/qwen38-quality.json",
                "--deepseek-quality",
                "data/deepseek-quality.json",
                "--quality-comparison",
                "data/quality-comparison.json",
                "--output",
                str(output),
            ]
            subprocess.run(command, cwd=PROJECT, check=True, capture_output=True, text=True)

            document = output.read_text()
            self.assertIn("<strong>N/A</strong><small>DeepSeek · 双 GB10</small>", document)
            self.assertIn("DeepSeek 性能 receipt：N/A（未提供）。", document)

    def test_report_generation_includes_rtx4090_and_thinking_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "index.html"
            command = [
                sys.executable,
                str(SCRIPT),
                "--performance", "data/performance-comparison.json",
                "--deepseek-performance", "data/deepseek-performance.json",
                "--qwen36-quality", "data/qwen36-quality.json",
                "--qwen38-quality", "data/qwen38-quality.json",
                "--deepseek-quality", "data/deepseek-quality.json",
                "--quality-comparison", "data/quality-comparison.json",
                "--qwen38-4090-quality", "../qwen38-rtx4090-vllm/receipts/quality-instruct-20260816.json",
                "--qwen38-4090-performance", "../qwen38-rtx4090-vllm/receipts/benchmark-20260816.json",
                "--qwen38-4090-thinking-quality", "../qwen38-rtx4090-vllm/receipts/quality-thinking-low-20260816.json",
                "--output", str(output),
            ]
            subprocess.run(command, cwd=PROJECT, check=True, capture_output=True, text=True)

            document = output.read_text()
            self.assertIn("RTX 4090 / Qwen3.8 FP8 性能补充", document)
            self.assertIn("RTX 4090 Thinking 模式核验", document)
            self.assertIn("宏平均 85.0%", document)
            self.assertIn("两道写作题即使使用 4 倍输出预算", document)


if __name__ == "__main__":
    unittest.main()
