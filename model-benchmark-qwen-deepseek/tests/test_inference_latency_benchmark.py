#!/usr/bin/env python3
import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "inference_latency_benchmark.py"
SPEC = importlib.util.spec_from_file_location("inference_latency_benchmark", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class FakeResponse:
    def __init__(self, lines: list[bytes]):
        self.lines = lines

    def __enter__(self):
        return iter(self.lines)

    def __exit__(self, *_args):
        return False


class InferenceLatencyBenchmarkTests(unittest.TestCase):
    def test_online_profile_uses_native_thinking_contract(self) -> None:
        for effort in ("low", "high", "max"):
            body = MODULE.request_body("ds", f"deepseek-online-{effort}", 2048)
            self.assertEqual(body["thinking"], {"type": "enabled"})
            self.assertEqual(body["reasoning_effort"], effort)
            self.assertNotIn("temperature", body)

    def test_private_profile_uses_local_sampling(self) -> None:
        for effort in ("high", "max"):
            body = MODULE.request_body("ds", f"deepseek-private-{effort}", 2048)
            self.assertEqual(body["chat_template_kwargs"], {"thinking": True})
            self.assertEqual(body["temperature"], 1.0)
            self.assertEqual(body["reasoning_effort"], effort)
            self.assertEqual(body["allowed_openai_params"], ["reasoning_effort"])

    @mock.patch.object(MODULE.time, "perf_counter", side_effect=[1.0, 1.2, 2.2])
    @mock.patch.object(MODULE.urllib.request, "urlopen")
    def test_stream_metrics_include_reasoning_ttft(self, urlopen, _clock) -> None:
        events = [
            {"choices": [{"delta": {"reasoning_content": "think"}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": "answer"}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 20}},
        ]
        lines = [f"data: {json.dumps(event)}\n".encode() for event in events] + [b"data: [DONE]\n"]
        urlopen.return_value = FakeResponse(lines)
        result = MODULE.stream_request("http://unit/v1", "model", "qwen38-low", 100, 30, None)
        self.assertEqual(result["first_token_kind"], "reasoning")
        self.assertAlmostEqual(result["ttft_seconds"], 0.2)
        self.assertAlmostEqual(result["response_seconds"], 1.2)
        self.assertAlmostEqual(result["decode_tokens_per_second"], 20.0)

    def test_summary_reports_sample_statistics(self) -> None:
        runs = [
            {"ttft_seconds": 1.0, "response_seconds": 3.0, "decode_tokens_per_second": 10.0, "usage": {"completion_tokens": 20}},
            {"ttft_seconds": 2.0, "response_seconds": 4.0, "decode_tokens_per_second": 20.0, "usage": {"completion_tokens": 40}},
        ]
        result = MODULE.summary(runs)
        self.assertEqual(result["successful_runs"], 2)
        self.assertEqual(result["ttft_seconds"]["mean"], 1.5)
        self.assertEqual(result["completion_tokens_mean"], 30)

    @mock.patch.object(MODULE.time, "perf_counter", side_effect=[1.0, 2.0, 3.0])
    @mock.patch.object(MODULE.urllib.request, "urlopen")
    def test_clean_early_eof_is_an_error(self, urlopen, _clock) -> None:
        event = {"choices": [{"delta": {"content": "partial"}, "finish_reason": None}]}
        urlopen.return_value = FakeResponse([f"data: {json.dumps(event)}\n".encode()])
        result = MODULE.stream_request("http://unit/v1", "model", "qwen38-low", 100, 30, None)
        self.assertEqual(result["error"]["type"], "incomplete_stream")


if __name__ == "__main__":
    unittest.main()
