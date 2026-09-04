#!/usr/bin/env python3
"""Offline tests for execution/eval/. No network access outside 127.0.0.1, no
ssh: chat-completions and /metrics are served by a local mock HTTP server;
ssh-based host sampling is exercised by patching subprocess.run.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import compare  # noqa: E402
import config  # noqa: E402
import daily_report  # noqa: E402
import metrics  # noqa: E402
import probes  # noqa: E402
import suite  # noqa: E402
import workload  # noqa: E402

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "metrics-20260904.txt"

DEFAULT_METRICS_TEXT = (
    'vllm:num_requests_running{model_name="test"} 0\n'
    'vllm:generation_tokens_total{model_name="test"} 100\n'
)

NEEDLE_RE = re.compile(r"NEEDLE-\d+-[A-Z]{4}")

MENU_JSON_RESPONSE = json.dumps(
    {
        "week_start": "2026-09-01",
        "week_end": "2026-09-04",
        "daily_menus": [
            {"day_of_week": "周一", "breakfast": None, "lunch_rice": None, "lunch_main_meat": None,
             "lunch_side1": None, "lunch_side2": None, "lunch_soup": None, "fruit": None, "afternoon_snack": None},
            {"day_of_week": "周二", "breakfast": "x", "lunch_rice": None, "lunch_main_meat": "x",
             "lunch_side1": "x", "lunch_side2": "x", "lunch_soup": "x", "fruit": "x", "afternoon_snack": "x"},
            {"day_of_week": "周三", "breakfast": "x", "lunch_rice": "x", "lunch_main_meat": "x",
             "lunch_side1": "x", "lunch_side2": "x", "lunch_soup": "x", "fruit": "x", "afternoon_snack": "x"},
            {"day_of_week": "周四", "breakfast": "x", "lunch_rice": None, "lunch_main_meat": "x",
             "lunch_side1": "x", "lunch_side2": "x", "lunch_soup": "x", "fruit": "x", "afternoon_snack": "x"},
            {"day_of_week": "周五", "breakfast": "x", "lunch_rice": "x", "lunch_main_meat": "x",
             "lunch_side1": "x", "lunch_side2": None, "lunch_soup": "x", "fruit": "x", "afternoon_snack": "x"},
        ],
    },
    ensure_ascii=False,
)

# Mutable state read by the mock handler; each TestCase resets it in setUp so
# tests don't leak state into one another.
STATE = {"metrics_text": DEFAULT_METRICS_TEXT, "metrics_queue": [], "seen_prompts": set()}


def _metrics_text(num_requests_running: float = 0.0, generation_tokens_total: float = 100.0) -> str:
    return (
        f'vllm:num_requests_running{{model_name="test"}} {num_requests_running}\n'
        f'vllm:generation_tokens_total{{model_name="test"}} {generation_tokens_total}\n'
    )


def _base_url() -> str:
    return f"http://127.0.0.1:{SERVER.server_port}"


def _metrics_url() -> str:
    return f"{_base_url()}/metrics"


def _cfg() -> config.Config:
    return config.Config(
        base_url=_base_url(), model="test-model", metrics_url=_metrics_url(),
        head_ssh=None, worker_ssh=None, container="test-container",
    )


def _make_args(**overrides) -> argparse.Namespace:
    base = dict(dry_run=False, repeats=None, thinking="off", scale=0.01, menu_image_override=None)
    base.update(overrides)
    return argparse.Namespace(**base)


def _stub_result() -> dict:
    return {"usage": {}, "cached_tokens": None, "ttft_s": 0.01, "gen_tok_s": 1.0,
            "itl_p95_s": None, "finish_reason": "stop", "error": None}


def _prompt_text(messages: list[dict]) -> str:
    if not messages:
        return ""
    content = messages[-1].get("content")
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return content or ""


def _has_image(messages: list[dict]) -> bool:
    content = messages[-1].get("content") if messages else None
    return isinstance(content, list) and any(isinstance(p, dict) and p.get("type") == "image_url" for p in content)


def _default_chat_chunks(body: dict) -> list[dict]:
    """Fakes an OpenAI-compatible streaming response. Tool-schema requests get
    a tool_call; image requests get a menu-shaped JSON reply; a prompt with a
    NEEDLE-<seed>-<letters> marker gets that marker echoed back (simulating a
    correct model); everything else gets a fixed short reply. Repeating an
    identical prompt (same text + same tools-or-not) reports cached_tokens ==
    prompt_tokens the second time, simulating a real prefix-cache warm hit."""
    messages = body.get("messages") or []
    prompt_text = _prompt_text(messages)
    prompt_tokens = max(1, len(prompt_text.split()))
    key = (prompt_text, bool(body.get("tools")))
    cached = prompt_tokens if key in STATE["seen_prompts"] else 0
    STATE["seen_prompts"].add(key)

    chunks: list[dict] = []
    if body.get("tools"):
        chunks.append({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": ""}},
        ]}}]})
        chunks.append({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '{"location": "Boston, US"}'}},
        ]}}]})
        chunks.append({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]})
        completion_tokens = 3
    elif _has_image(messages):
        pieces = [MENU_JSON_RESPONSE[i:i + 40] for i in range(0, len(MENU_JSON_RESPONSE), 40)]
        for piece in pieces:
            chunks.append({"choices": [{"delta": {"content": piece}}]})
        chunks.append({"choices": [{"delta": {}, "finish_reason": "stop"}]})
        completion_tokens = max(1, len(MENU_JSON_RESPONSE) // 4)
    else:
        m = NEEDLE_RE.search(prompt_text)
        words = [m.group(0)] if m else ["The", "answer", "is", "forty-two", "."]
        for w in words:
            chunks.append({"choices": [{"delta": {"content": w + " "}}]})
        chunks.append({"choices": [{"delta": {}, "finish_reason": "stop"}]})
        completion_tokens = len(words)

    chunks.append({"choices": [], "usage": {
        "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "prompt_tokens_details": {"cached_tokens": cached},
    }})
    return chunks


class MockHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if self.path == "/metrics":
            text = STATE["metrics_queue"].pop(0) if STATE["metrics_queue"] else STATE["metrics_text"]
            self._send(200, text.encode(), "text/plain")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {}
        if self.path != "/v1/chat/completions":
            self._send(404, b"not found", "text/plain")
            return
        # Streamed close-delimited (no Content-Length): a small per-chunk
        # sleep guarantees successive token timestamps differ, so gen_tok_s /
        # itl calculations in probes.stream_request never divide by zero.
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        for chunk in _default_chat_chunks(body):
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
            time.sleep(0.005)
        self.wfile.write(b"data: [DONE]\n\n")
        self.close_connection = True

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def setUpModule():
    global SERVER, SERVER_THREAD
    SERVER = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
    SERVER_THREAD = threading.Thread(target=SERVER.serve_forever, daemon=True)
    SERVER_THREAD.start()


def tearDownModule():
    SERVER.shutdown()
    SERVER.server_close()


def _reset_state() -> None:
    STATE["metrics_text"] = DEFAULT_METRICS_TEXT
    STATE["metrics_queue"] = []
    STATE["seen_prompts"] = set()


# --- Pure parsing / generation, no server -----------------------------------
class MetricsParseTests(unittest.TestCase):
    def test_load_fixture_known_values(self):
        snap = metrics.load(FIXTURE_PATH)
        self.assertEqual(metrics.num_requests_running(snap), 0.0)
        self.assertEqual(metrics.sum_metric(snap, "vllm:generation_tokens_total"), 316896.0)
        success = metrics.by_label(snap, "vllm:request_success_total", "finished_reason")
        self.assertEqual(success["stop"], 804.0)
        self.assertEqual(success["length"], 140.0)

    def test_delta_and_bucket_deltas(self):
        before = metrics.snapshot(
            'vllm:spec_decode_num_accepted_tokens_total{engine="0"} 500\n'
            'vllm:spec_decode_num_draft_tokens_total{engine="0"} 600\n'
            'vllm:spec_decode_num_drafts_total{engine="0"} 100\n'
            'vllm:prefix_cache_hits_total{engine="0"} 50\n'
            'vllm:prefix_cache_queries_total{engine="0"} 60\n'
            'vllm:time_to_first_token_seconds_bucket{le="1.0"} 5\n'
            'vllm:time_to_first_token_seconds_bucket{le="+Inf"} 8\n'
        )
        after = metrics.snapshot(
            'vllm:spec_decode_num_accepted_tokens_total{engine="0"} 700\n'
            'vllm:spec_decode_num_draft_tokens_total{engine="0"} 850\n'
            'vllm:spec_decode_num_drafts_total{engine="0"} 140\n'
            'vllm:prefix_cache_hits_total{engine="0"} 70\n'
            'vllm:prefix_cache_queries_total{engine="0"} 85\n'
            'vllm:time_to_first_token_seconds_bucket{le="1.0"} 9\n'
            'vllm:time_to_first_token_seconds_bucket{le="+Inf"} 15\n'
        )
        d = metrics.delta(before, after)
        self.assertAlmostEqual(d["acceptance"], 200 / 250)
        self.assertAlmostEqual(d["prefix_hit_ratio"], 20 / 25)
        self.assertEqual(d["ttft_bucket_delta"]["1.0"], 4)
        self.assertEqual(d["ttft_bucket_delta"]["+Inf"], 7)

    def test_host_mem_available_bytes_parses_without_real_ssh(self):
        fake_stdout = (
            "              total        used        free      shared  buff/cache   available\n"
            "Mem:    270000000000 50000000000 10000000000   100000000 20000000000 219000000000\n"
        )
        with mock.patch.object(metrics.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout=fake_stdout)
            value = metrics.host_mem_available_bytes("fake-alias")
        self.assertEqual(value, 219000000000)
        mock_run.assert_called_once()

    def test_host_mem_available_bytes_returns_none_on_failure(self):
        with mock.patch.object(metrics.subprocess, "run", side_effect=OSError("no such host")):
            value = metrics.host_mem_available_bytes("fake-alias")
        self.assertIsNone(value)


class WorkloadTests(unittest.TestCase):
    def test_rand_words_is_seeded_and_deterministic(self):
        self.assertEqual(workload.rand_words(5, seed=1), workload.rand_words(5, seed=1))
        self.assertNotEqual(workload.rand_words(5, seed=1), workload.rand_words(5, seed=2))

    def test_tokens_to_words_uses_calibration(self):
        self.assertEqual(workload.tokens_to_words(3540), 1000)

    def test_make_marker_format(self):
        self.assertRegex(workload.make_marker(42), r"^NEEDLE-42-[A-Z]{4}$")

    def test_build_needle_body_places_marker_near_middle(self):
        marker = workload.make_marker(7)
        words = workload.build_needle_body(400, 7, marker, frac=0.5).split()
        self.assertIn(marker, words)
        idx = words.index(marker)
        self.assertTrue(0.3 * len(words) <= idx <= 0.7 * len(words))

    def test_load_menu_image_placeholder_is_valid_png(self):
        self.assertTrue(workload.load_menu_image(None).startswith(b"\x89PNG\r\n\x1a\n"))

    def test_prompt_set_sizes(self):
        self.assertEqual(len(workload.SHORT_CHAT_PROMPTS), 8)
        self.assertEqual(len(workload.TOOL_PROMPTS), 6)


class ConfigTests(unittest.TestCase):
    ENV_KEYS = ("EVAL_BASE_URL", "EVAL_MODEL", "EVAL_METRICS_URL", "EVAL_HEAD_SSH", "EVAL_WORKER_SSH", "EVAL_CONTAINER")

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in self.ENV_KEYS}
        for k in self.ENV_KEYS:
            os.environ.pop(k, None)
        # A developer-local .env.eval would re-seed the popped vars via
        # load_config()'s setdefault; test the env-only path in isolation.
        self._saved_dotenv = config.load_dotenv
        config.load_dotenv = lambda *a, **k: {}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        config.load_dotenv = self._saved_dotenv

    def test_load_config_requires_base_url(self):
        with self.assertRaises(SystemExit):
            config.load_config()

    def test_load_config_defaults_and_types(self):
        os.environ["EVAL_BASE_URL"] = "http://example.invalid:9999/"
        os.environ["EVAL_MODEL"] = "test-model"
        os.environ["EVAL_CONTAINER"] = "some-container"
        cfg = config.load_config()
        self.assertEqual(cfg.base_url, "http://example.invalid:9999")
        self.assertEqual(cfg.metrics_url, "http://example.invalid:9999/metrics")
        self.assertIsNone(cfg.head_ssh)
        self.assertEqual(cfg.container, "some-container")

    def test_redact_host(self):
        self.assertEqual(config.redact_host("http://10.1.2.3:8000/v1"), "http://<host>/v1")


# --- Tests against the mock server -------------------------------------------
class ProbesTests(unittest.TestCase):
    def setUp(self):
        _reset_state()

    def test_stream_request_plain_content_and_usage(self):
        result = probes.stream_request(_base_url(), "test-model", [{"role": "user", "content": "hello"}], max_tokens=50)
        self.assertIsNone(result["error"])
        self.assertEqual(result["finish_reason"], "stop")
        self.assertEqual(result["text"].strip(), "The answer is forty-two .")
        self.assertGreater(result["ttft_s"], 0)
        self.assertIsNotNone(result["gen_tok_s"])
        self.assertEqual(result["cached_tokens"], 0)

    def test_stream_request_cached_tokens_on_identical_repeat(self):
        messages = [{"role": "user", "content": "repeat me please"}]
        first = probes.stream_request(_base_url(), "test-model", messages, max_tokens=50)
        second = probes.stream_request(_base_url(), "test-model", messages, max_tokens=50)
        self.assertEqual(first["cached_tokens"], 0)
        self.assertGreater(second["cached_tokens"], 0)

    def test_stream_request_tool_calls(self):
        result = probes.stream_request(
            _base_url(), "test-model", [{"role": "user", "content": "what's the weather"}],
            max_tokens=50, tools=list(workload.TOOLS), tool_choice="auto",
        )
        self.assertEqual(result["finish_reason"], "tool_calls")
        self.assertEqual(len(result["tool_calls"]), 1)
        self.assertEqual(result["tool_calls"][0]["function"]["name"], "get_weather")
        args = json.loads(result["tool_calls"][0]["function"]["arguments"])
        self.assertEqual(args["location"], "Boston, US")

    def test_stream_request_connection_error(self):
        result = probes.stream_request(
            "http://127.0.0.1:1", "test-model", [{"role": "user", "content": "x"}], max_tokens=10, timeout=2,
        )
        self.assertIsNotNone(result["error"])
        self.assertIsNone(result["ttft_s"])

    def test_needle_pass(self):
        self.assertTrue(probes.needle_pass("NEEDLE-1-ABCD", "prefix NEEDLE-1-ABCD suffix"))
        self.assertFalse(probes.needle_pass("NEEDLE-1-ABCD", "nope"))

    def test_fetch_num_requests_running(self):
        STATE["metrics_text"] = _metrics_text(num_requests_running=3)
        self.assertEqual(probes.fetch_num_requests_running(_metrics_url()), 3.0)

    def test_idle_window_ok_true(self):
        STATE["metrics_text"] = _metrics_text(num_requests_running=0, generation_tokens_total=42)
        ok, _reason = probes.idle_window_ok(_metrics_url(), poll_gap_s=0.01)
        self.assertTrue(ok)

    def test_idle_window_ok_false_when_running(self):
        STATE["metrics_text"] = _metrics_text(num_requests_running=2, generation_tokens_total=42)
        ok, reason = probes.idle_window_ok(_metrics_url(), poll_gap_s=0.01)
        self.assertFalse(ok)
        self.assertIn("num_requests_running", reason)

    def test_idle_window_ok_false_when_tokens_move(self):
        STATE["metrics_queue"] = [
            _metrics_text(num_requests_running=0, generation_tokens_total=10),
            _metrics_text(num_requests_running=0, generation_tokens_total=20),
        ]
        ok, reason = probes.idle_window_ok(_metrics_url(), poll_gap_s=0.01)
        self.assertFalse(ok)
        self.assertIn("moved", reason)


class CtxSampleContaminationTests(unittest.TestCase):
    def setUp(self):
        _reset_state()

    def test_non_c_block_reruns_once_on_any_running_request(self):
        STATE["metrics_text"] = _metrics_text(num_requests_running=1)
        ctx = suite.Ctx(_cfg(), _make_args(), suite.SeedAllocator(1))
        calls = []

        def request_fn():
            calls.append(1)
            return _stub_result()

        ctx.sample(block="S", name="x", seed=None, repeat=1, temperature=0.0, request_fn=request_fn)
        self.assertEqual(len(calls), 2)
        self.assertEqual([r["contaminated"] for r in ctx.results], [True, False])

    def test_block_c_uses_own_concurrency_as_threshold(self):
        # before-poll sees our own 3 streams, after-poll sees the engine idle
        STATE["metrics_queue"] = [_metrics_text(num_requests_running=3)]
        STATE["metrics_text"] = _metrics_text(num_requests_running=0)
        ctx = suite.Ctx(_cfg(), _make_args(), suite.SeedAllocator(1))
        ctx.sample(block="C", name="c4", seed=None, repeat=1, temperature=0.0,
                   request_fn=_stub_result, own_concurrency=4)
        self.assertEqual(len(ctx.results), 1)
        self.assertFalse(ctx.results[0]["contaminated"])
        self.assertEqual(ctx.results[0]["running_before"], 3)
        self.assertEqual(ctx.results[0]["running_after"], 0)

        STATE["metrics_queue"] = [_metrics_text(num_requests_running=5)]
        ctx2 = suite.Ctx(_cfg(), _make_args(), suite.SeedAllocator(1))
        ctx2.sample(block="C", name="c4", seed=None, repeat=1, temperature=0.0,
                    request_fn=_stub_result, own_concurrency=4)
        self.assertEqual(len(ctx2.results), 2)
        self.assertTrue(ctx2.results[0]["contaminated"])

    def test_foreign_request_after_the_call_marks_contaminated(self):
        STATE["metrics_queue"] = [_metrics_text(num_requests_running=0)]
        STATE["metrics_text"] = _metrics_text(num_requests_running=1)
        ctx = suite.Ctx(_cfg(), _make_args(), suite.SeedAllocator(1))
        ctx.sample(block="S", name="x", seed=None, repeat=1, temperature=0.0, request_fn=_stub_result)
        self.assertEqual([r["contaminated"] for r in ctx.results], [True, False])

    def test_cold_probe_rerun_uses_a_fresh_seed_and_kpis_skip_contaminated(self):
        STATE["metrics_text"] = _metrics_text(num_requests_running=1)
        alloc = suite.SeedAllocator(500)
        ctx = suite.Ctx(_cfg(), _make_args(), alloc)
        seeds_seen = []

        def factory(seed: int):
            seeds_seen.append(seed)
            return _stub_result, (lambda result: {"warm": False})

        seed = alloc.next()
        request_fn, gate_fn = factory(seed)
        rec = ctx.sample(block="L", name="prefill_64K", seed=seed, repeat=1, temperature=0.0,
                         request_fn=request_fn, gate_fn=gate_fn, probe_factory=factory)
        self.assertEqual(len(seeds_seen), 2)
        self.assertNotEqual(seeds_seen[0], seeds_seen[1])
        self.assertEqual(rec["seed"], seeds_seen[1])
        self.assertTrue(rec["rerun_of_contaminated"])
        for r in ctx.results:
            r.update(prompt_tokens=64000, ttft_s=20.0 if r["contaminated"] else 40.0)
        kpis = suite.compute_kpis(ctx.results)
        self.assertEqual(kpis["prefill_cold_tok_s@64K"]["n"], 1)
        self.assertAlmostEqual(kpis["prefill_cold_tok_s@64K"]["median"], 64000 / 40.0)


class SuiteBlocksAgainstMockServerTests(unittest.TestCase):
    """Runs every block runner (S/M/L/N/C/T/V) against the mock server with
    --scale shrinking body sizes, then checks the KPI/gate computations that
    read their output. This exercises workload -> probes -> suite end to end,
    including the needle/tool-call/vision gates and the mixed decode+prefill
    probe (which sleeps a real 2s, per its fixed offset in suite.py)."""

    def setUp(self):
        _reset_state()

    def test_all_blocks_produce_expected_kpis_and_gates(self):
        args = _make_args()
        ctx = suite.Ctx(_cfg(), args, suite.SeedAllocator(90000))

        args.repeats = 1
        suite.run_block_s(ctx)
        args.repeats = 2
        suite.run_block_m(ctx)
        args.repeats = 1
        suite.run_block_l(ctx)
        suite.run_block_n(ctx)
        suite.run_block_c(ctx)
        suite.run_block_t(ctx)
        suite.run_block_v(ctx)

        kpis = suite.compute_kpis(ctx.results)
        gates = suite.compute_gates(ctx.results)

        self.assertIn("decode_c1_tok_s", kpis)
        self.assertGreater(kpis["decode_c1_tok_s"]["median"], 0)
        self.assertEqual(kpis["decode_c1_tok_s"]["n"], 8)  # 8 block-S prompts at temp 0.0
        for label in ("32K", "64K", "128K"):
            self.assertIn(f"prefill_cold_tok_s@{label}", kpis)
        self.assertIn("ttft_warm@64K", kpis)
        self.assertIn("ttft_warm@8K", kpis)
        self.assertIn("aggregate_tok_s_c2", kpis)
        self.assertIn("aggregate_tok_s_c4", kpis)

        self.assertTrue(gates["needle_64K_exact"])
        self.assertTrue(gates["needle_128K_exact"])
        self.assertTrue(gates["tool_call_json_6_6"])
        if workload.vision_compare() is not None:
            self.assertIsInstance(gates["vision_score"], int)
            self.assertTrue(0 < gates["vision_score"] <= 47)
        else:  # clean checkout: the customer-derived grader file is absent
            v_records = [r for r in ctx.results if r["block"] == "V"]
            self.assertTrue(v_records and v_records[0].get("skipped"))
            self.assertIn("vision_compare.py not found", v_records[0].get("error", ""))
            self.assertIsNone(gates["vision_score"])
        self.assertTrue(gates["no_missing_finish_reason"])
        self.assertTrue(gates["warm_ttft_64K_le_2s"])

        report = suite.render_report_md("smoke", ctx.results, DEFAULT_METRICS_TEXT, DEFAULT_METRICS_TEXT)
        self.assertIn("# Eval report: smoke", report)
        self.assertIn("decode_c1_tok_s", report)


class SuiteMainIntegrationTests(unittest.TestCase):
    def setUp(self):
        _reset_state()
        self._saved = {k: os.environ.get(k) for k in ("EVAL_BASE_URL", "EVAL_MODEL", "EVAL_METRICS_URL", "EVAL_HEAD_SSH", "EVAL_WORKER_SSH")}
        os.environ["EVAL_BASE_URL"] = _base_url()
        os.environ["EVAL_MODEL"] = "test-model"
        os.environ["EVAL_METRICS_URL"] = _metrics_url()
        os.environ.pop("EVAL_HEAD_SSH", None)
        os.environ.pop("EVAL_WORKER_SSH", None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_dry_run_prints_plan_without_network(self):
        argv = ["suite.py", "--tag", "dryrun", "--dry-run", "--blocks", "S,N", "--scale", "0.01", "--repeats", "1"]
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(buf):
            exit_code = suite.main()
        self.assertEqual(exit_code, 0)
        plan = json.loads(buf.getvalue())
        self.assertEqual(plan["tag"], "dryrun")
        self.assertGreater(plan["total_requests"], 0)
        self.assertIn("<host>", plan["base_url"])

    def test_real_run_writes_expected_run_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["suite.py", "--tag", "smoke", "--blocks", "S", "--repeats", "1",
                     "--scale", "0.01", "--no-hosts", "--idle-poll-gap", "0.01", "--out-dir", tmp]
            buf = io.StringIO()
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(buf):
                exit_code = suite.main()
            self.assertEqual(exit_code, 0)

            run_dirs = list(Path(tmp).iterdir())
            self.assertEqual(len(run_dirs), 1)
            run_dir = run_dirs[0]
            self.assertTrue(run_dir.name.endswith("-smoke"))
            manifest = json.loads((run_dir / "manifest.json").read_text())
            self.assertEqual(manifest["tag"], "smoke")
            self.assertIn("<host>", manifest["base_url"])
            results = (run_dir / "results.jsonl").read_text().strip().splitlines()
            self.assertEqual(len(results), 16)  # 8 prompts x 2 temps x 1 repeat
            self.assertTrue((run_dir / "report.md").is_file())


# --- compare.py decision logic -----------------------------------------------
def _write_results_jsonl(path: Path, gen_tok_s_values: list, extra_records: list | None = None) -> None:
    records = [
        {"block": "S", "name": f"s{i % 8}", "seed": None, "repeat": i, "temperature": 0.0,
         "prompt_tokens": 300, "cached_tokens": 0, "completion_tokens": 100,
         "ttft_s": 0.2, "gen_tok_s": v, "itl_p95_s": 0.01, "finish_reason": "stop",
         "contaminated": False, "error": None}
        for i, v in enumerate(gen_tok_s_values)
    ]
    records += extra_records or []
    with (path / "results.jsonl").open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


class CompareDecisionTests(unittest.TestCase):
    def test_target_threshold(self):
        self.assertEqual(compare.target_threshold("decode_c1_tok_s"), 0.05)
        self.assertEqual(compare.target_threshold("prefill_cold_tok_s@64K"), 0.10)
        with self.assertRaises(SystemExit):
            compare.target_threshold("ttft_warm@8K")

    def test_decide_adopts_on_clear_non_overlapping_improvement(self):
        kpis_a = {"decode_c1_tok_s": {"median": 100.0, "min": 95.0, "max": 105.0, "n": 3}}
        kpis_b = {"decode_c1_tok_s": {"median": 110.0, "min": 108.0, "max": 112.0, "n": 3}}
        decision = compare.decide(kpis_a, kpis_b, "decode_c1_tok_s")
        self.assertEqual(decision["verdict"], "ADOPT")

    def test_decide_reverts_on_overlapping_ranges(self):
        kpis_a = {"decode_c1_tok_s": {"median": 100.0, "min": 90.0, "max": 110.0, "n": 3}}
        kpis_b = {"decode_c1_tok_s": {"median": 110.0, "min": 100.0, "max": 118.0, "n": 3}}
        decision = compare.decide(kpis_a, kpis_b, "decode_c1_tok_s")
        self.assertEqual(decision["verdict"], "REVERT")

    def test_decide_reverts_on_other_primary_kpi_regression(self):
        kpis_a = {
            "decode_c1_tok_s": {"median": 100.0, "min": 95.0, "max": 105.0, "n": 3},
            "prefill_cold_tok_s@64K": {"median": 50.0, "min": 48.0, "max": 52.0, "n": 3},
        }
        kpis_b = {
            "decode_c1_tok_s": {"median": 110.0, "min": 108.0, "max": 112.0, "n": 3},
            "prefill_cold_tok_s@64K": {"median": 40.0, "min": 38.0, "max": 42.0, "n": 3},
        }
        decision = compare.decide(kpis_a, kpis_b, "decode_c1_tok_s")
        self.assertEqual(decision["verdict"], "REVERT")
        self.assertTrue(decision["regressions"])

    def test_main_end_to_end_adopt(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline_dir, candidate_dir = Path(tmp) / "baseline", Path(tmp) / "candidate"
            baseline_dir.mkdir()
            candidate_dir.mkdir()
            _write_results_jsonl(baseline_dir, [95.0, 100.0, 105.0])
            _write_results_jsonl(candidate_dir, [108.0, 110.0, 112.0])
            argv = ["compare.py", str(baseline_dir), str(candidate_dir), "--target", "decode_c1_tok_s"]
            with mock.patch.object(sys, "argv", argv):
                exit_code = compare.main()
            self.assertEqual(exit_code, 0)
            self.assertIn("**ADOPT**", (candidate_dir / "compare.md").read_text())

    def test_main_end_to_end_gate_failure_forces_revert(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline_dir, candidate_dir = Path(tmp) / "baseline", Path(tmp) / "candidate"
            baseline_dir.mkdir()
            candidate_dir.mkdir()
            _write_results_jsonl(baseline_dir, [95.0, 100.0, 105.0])
            failed_needle = [{
                "block": "N", "name": "needle_64K", "seed": 1, "repeat": 1, "temperature": 0.0,
                "prompt_tokens": 64000, "cached_tokens": 0, "completion_tokens": 8, "ttft_s": 1.0,
                "gen_tok_s": None, "itl_p95_s": None, "finish_reason": "stop", "contaminated": False,
                "error": None, "needle_pass": False, "marker": "NEEDLE-1-ABCD",
            }]
            _write_results_jsonl(candidate_dir, [108.0, 110.0, 112.0], extra_records=failed_needle)
            argv = ["compare.py", str(baseline_dir), str(candidate_dir), "--target", "decode_c1_tok_s"]
            with mock.patch.object(sys, "argv", argv):
                exit_code = compare.main()
            self.assertEqual(exit_code, 1)
            self.assertIn("**REVERT**", (candidate_dir / "compare.md").read_text())


# --- daily_report.py -----------------------------------------------------------
class DailyReportTests(unittest.TestCase):
    @staticmethod
    def _snapshot_text(gen_tokens, accepted, draft, drafts, hits, queries, success_stop) -> str:
        return (
            f'vllm:num_requests_running{{engine="0"}} 0\n'
            f'vllm:generation_tokens_total{{engine="0"}} {gen_tokens}\n'
            f'vllm:spec_decode_num_accepted_tokens_total{{engine="0"}} {accepted}\n'
            f'vllm:spec_decode_num_draft_tokens_total{{engine="0"}} {draft}\n'
            f'vllm:spec_decode_num_drafts_total{{engine="0"}} {drafts}\n'
            f'vllm:prefix_cache_hits_total{{engine="0"}} {hits}\n'
            f'vllm:prefix_cache_queries_total{{engine="0"}} {queries}\n'
            f'vllm:inter_token_latency_seconds_bucket{{le="0.05"}} {drafts}\n'
            f'vllm:inter_token_latency_seconds_bucket{{le="+Inf"}} {drafts}\n'
            f'vllm:request_success_total{{engine="0",finished_reason="stop"}} {success_stop}\n'
            f'vllm:kv_cache_usage_perc{{engine="0"}} 10.0\n'
        )

    def test_boot_event_detection_and_kpis(self):
        rows = [
            {"ts": "t0", "ok": True, "text": self._snapshot_text(1000, 500, 600, 100, 50, 60, 20)},
            {"ts": "t1", "ok": True, "text": self._snapshot_text(1500, 700, 850, 140, 70, 85, 25)},
            {"ts": "t2", "ok": False, "text": None},
            # a restart: generation_tokens_total drops 1500 -> 200
            {"ts": "t3", "ok": True, "text": self._snapshot_text(200, 720, 870, 145, 71, 86, 26)},
        ]
        report = daily_report.daily_report(rows)
        self.assertEqual(report["scrapes"], 4)
        self.assertEqual(report["ok_scrapes"], 3)
        self.assertEqual(report["scrape_failures"], 1)
        self.assertEqual(len(report["boot_events"]), 1)
        self.assertAlmostEqual(report["generation_tokens"], 700.0)  # (1500-1000) + 200 post-restart
        self.assertAlmostEqual(report["acceptance"], 220 / 270)
        self.assertIsNotNone(report["decode_tok_s"])
        self.assertEqual(report["request_success_by_reason"]["stop"], 6)
        self.assertEqual(report["kv_cache_usage_perc_max"], 10.0)

    def test_fewer_than_two_scrapes_reports_error(self):
        report = daily_report.daily_report([{"ts": "t0", "ok": True, "text": self._snapshot_text(1, 1, 1, 1, 1, 1, 1)}])
        self.assertIn("error", report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
