"""Regression tests for benchmark metric handling without an Ollama service."""

import importlib.util
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TEXT_BENCHMARK = load_module("text_benchmark", "benchmark_ollama_qwen36.py")
VISION_BENCHMARK = load_module("vision_benchmark", "benchmark_multimodal_qwen36.py")


class TextBenchmarkMetricTests(unittest.TestCase):
    def test_missing_none_and_zero_durations_are_safe(self):
        self.assertIsNone(TEXT_BENCHMARK.duration_seconds({}, "eval_duration"))
        self.assertIsNone(TEXT_BENCHMARK.duration_seconds({"eval_duration": None}, "eval_duration"))
        self.assertEqual(TEXT_BENCHMARK.duration_seconds({"eval_duration": 0}, "eval_duration"), 0)

        summary = TEXT_BENCHMARK.summary(
            "test",
            [
                {
                    "thinking": False,
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "client_ttft_s": 0.1,
                    "client_wall_s": 1.0,
                    "prompt_tok_s": None,
                    "decode_tok_s": None,
                    "end_to_end_tok_s": 1.0,
                },
                {
                    "thinking": False,
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "client_ttft_s": 0.2,
                    "client_wall_s": 2.0,
                    "prompt_tok_s": None,
                    "decode_tok_s": 2.0,
                    "end_to_end_tok_s": 0.5,
                },
            ],
            {},
        )

        self.assertIsNone(summary["prompt_tok_s_mean"])
        self.assertEqual(summary["decode_tok_s_mean"], 2.0)
        self.assertEqual(summary["decode_tok_s_std"], 0)
        self.assertEqual(TEXT_BENCHMARK.format_metric(None), "N/A")


class VisionBenchmarkMetricTests(unittest.TestCase):
    def test_missing_none_and_zero_durations_are_safe(self):
        self.assertIsNone(VISION_BENCHMARK.seconds({}, "eval_duration"))
        self.assertIsNone(VISION_BENCHMARK.seconds({"eval_duration": None}, "eval_duration"))
        self.assertEqual(VISION_BENCHMARK.seconds({"eval_duration": 0}, "eval_duration"), 0)

        runs = [
            {"prompt_tok_s": None, "decode_tok_s": None},
            {"prompt_tok_s": 1.5, "decode_tok_s": 2.5},
        ]
        self.assertEqual(VISION_BENCHMARK.mean_metric(runs, "prompt_tok_s"), 1.5)
        self.assertEqual(VISION_BENCHMARK.mean_metric(runs, "decode_tok_s"), 2.5)
        self.assertEqual(VISION_BENCHMARK.format_metric(None), "N/A")


if __name__ == "__main__":
    unittest.main()
