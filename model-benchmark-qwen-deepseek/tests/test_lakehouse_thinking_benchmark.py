#!/usr/bin/env python3
import importlib.util
import io
import sys
import unittest
import json
import urllib.error
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "lakehouse_thinking_benchmark.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("lakehouse_thinking_benchmark", SCRIPT)
assert SPEC and SPEC.loader
BENCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCH)

REPORT_SCRIPT = SCRIPT.parent / "generate_lakehouse_report.py"
REPORT_SPEC = importlib.util.spec_from_file_location("generate_lakehouse_report", REPORT_SCRIPT)
assert REPORT_SPEC and REPORT_SPEC.loader
REPORT = importlib.util.module_from_spec(REPORT_SPEC)
REPORT_SPEC.loader.exec_module(REPORT)


class LakehouseThinkingBenchmarkTests(unittest.TestCase):
    def test_case_identity_and_category_sizes(self) -> None:
        ids = [case["id"] for case in BENCH.SQL_CASES]
        ids += [case[0] for case in BENCH.PYTHON_CASES]
        ids += [case["id"] for case in BENCH.INCIDENT_CASES]
        self.assertEqual(len(ids), 18)
        self.assertEqual(len(set(ids)), 18)
        self.assertEqual(BENCH.HARNESS_ID, "lakehouse-thinking-v2")
        self.assertIn("D for delete", BENCH.SQL_CASES[0]["prompt"])

    def test_stable_toposort_oracle_uses_insertion_order_and_exceptions(self) -> None:
        code = """
def stable_toposort(graph):
    keys = list(graph)
    known = set(keys)
    if any(dep not in known for deps in graph.values() for dep in deps):
        raise ValueError('missing dependency')
    result = []
    remaining = set(keys)
    while remaining:
        ready = next((node for node in keys if node in remaining and all(dep in result for dep in graph[node])), None)
        if ready is None:
            raise ValueError('cycle')
        result.append(ready)
        remaining.remove(ready)
    return result
"""
        _, _, checks = next(item for item in BENCH.PYTHON_CASES if item[0] == "stable_toposort")
        passed, detail = BENCH.execute_python("stable_toposort", code, checks)
        self.assertTrue(passed, detail)

    def test_sql_reference_answers_execute(self) -> None:
        reference = {
            "cdc_latest_live": "WITH x AS (SELECT *,row_number() OVER(PARTITION BY id ORDER BY event_time DESC,seq DESC) n FROM cdc) SELECT id,value FROM x WHERE n=1 AND op<>'D' ORDER BY id",
            "scd2_intervals": "SELECT customer_id,status,effective_at,lead(effective_at) OVER(PARTITION BY customer_id ORDER BY effective_at) FROM changes ORDER BY customer_id,effective_at",
            "sessionize_events": "WITH a AS (SELECT *,lag(minute) OVER(PARTITION BY user_id ORDER BY minute) p FROM events), b AS (SELECT *,sum(CASE WHEN p IS NULL OR minute-p>30 THEN 1 ELSE 0 END) OVER(PARTITION BY user_id ORDER BY minute) s FROM a) SELECT user_id,s,min(minute),max(minute),count(*) FROM b GROUP BY user_id,s ORDER BY user_id,s",
            "rolling_revenue": "SELECT day,sum(revenue) OVER(ORDER BY day ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) FROM daily ORDER BY day",
            "recursive_hierarchy": "WITH RECURSIVE t(root,id,amount) AS (SELECT id,id,amount FROM nodes WHERE parent_id IS NULL UNION ALL SELECT t.root,n.id,n.amount FROM t JOIN nodes n ON n.parent_id=t.id) SELECT root,sum(amount) FROM t GROUP BY root ORDER BY root",
            "funnel_first_order": "WITH f AS (SELECT u.user_id,u.signup_day,min(o.order_day) first_order FROM users u LEFT JOIN orders o ON o.user_id=u.user_id AND o.order_day>=u.signup_day GROUP BY u.user_id,u.signup_day) SELECT count(*),sum(CASE WHEN julianday(first_order)-julianday(signup_day)<=7 THEN 1 ELSE 0 END) FROM f",
        }
        for case in BENCH.SQL_CASES:
            passed, detail = BENCH.execute_sql(case, reference[case["id"]])
            self.assertTrue(passed, (case["id"], detail))

    def test_incident_scoring_penalizes_wrong_actions(self) -> None:
        case = BENCH.INCIDENT_CASES[0]
        perfect = '{"root_cause":"cgroup_memory_limit","action_codes":["memory_max","restart_backoff"]}'
        noisy = '{"root_cause":"cgroup_memory_limit","action_codes":["memory_max","delete_logs"]}'
        self.assertEqual(BENCH.score_incident(case, perfect)[0], 1.0)
        self.assertLess(BENCH.score_incident(case, noisy)[0], 1.0)
        self.assertEqual(BENCH.score_incident(case, "not json")[0], 0.0)

    def test_deepseek_thinking_request_uses_native_switch_and_optional_auth(self) -> None:
        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        payload = {"choices": [{"message": {"content": "ok", "reasoning": "r"}, "finish_reason": "stop"}], "usage": {"completion_tokens": 2}}
        with patch.object(BENCH.urllib.request, "urlopen", return_value=Response(json.dumps(payload).encode())) as urlopen:
            BENCH.request("http://example.test/v1", "deepseek-v4-flash-0731", "test", "deepseek-thinking", 256, "test-key")
        request = urlopen.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(body["chat_template_kwargs"], {"thinking": True})
        self.assertEqual(body["top_k"], 20)
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")

    def test_online_deepseek_request_uses_official_effort_contract(self) -> None:
        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        payload = {"choices": [{"message": {"content": "ok", "reasoning_content": "r"}, "finish_reason": "stop"}], "usage": {"completion_tokens": 2}}
        with patch.object(BENCH.urllib.request, "urlopen", return_value=Response(json.dumps(payload).encode())) as urlopen:
            BENCH.request(
                "http://example.test/v1",
                "deepseek-v4-flash",
                "test",
                "deepseek-thinking",
                256,
                "test-key",
                deepseek_contract="online-api",
                deepseek_effort="low",
                deepseek_sampling="official-api",
            )
        body = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(body["thinking"], {"type": "enabled"})
        self.assertEqual(body["reasoning_effort"], "low")
        self.assertNotIn("chat_template_kwargs", body)
        self.assertNotIn("presence_penalty", body)

    def test_private_portal_can_force_effort_passthrough(self) -> None:
        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        payload = {"choices": [{"message": {"content": "ok", "reasoning": "r"}, "finish_reason": "stop"}], "usage": {"completion_tokens": 2}}
        with patch.object(BENCH.urllib.request, "urlopen", return_value=Response(json.dumps(payload).encode())) as urlopen:
            BENCH.request(
                "http://example.test/v1",
                "deepseek-v4-flash-0731",
                "test",
                "deepseek-thinking",
                256,
                deepseek_effort="max",
                force_reasoning_effort_passthrough=True,
            )
        body = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(body["reasoning_effort"], "max")
        self.assertEqual(body["allowed_openai_params"], ["reasoning_effort"])

    def test_compact_row_hashes_full_reasoning_without_changing_score_input(self) -> None:
        compacted = BENCH.compact_row({"response": "answer", "reasoning": "abcdef"}, 3, 3)
        self.assertTrue(compacted["response_evidence"]["storage_truncated"])
        self.assertTrue(compacted["reasoning_evidence"]["storage_truncated"])
        self.assertEqual(compacted["reasoning_evidence"]["chars"], 6)
        self.assertIn("full_sha256=", compacted["reasoning"])

    def test_http_error_is_recorded_as_a_scored_request_failure(self) -> None:
        with patch.object(BENCH.urllib.request, "urlopen", side_effect=urllib.error.HTTPError("http://example.test", 504, "Gateway Time-out", {}, None)):
            result = BENCH.request("http://example.test/v1", "model", "test", "off", 256)
        self.assertEqual(result["finish_reason"], "error")
        self.assertEqual(result["error"]["status"], 504)

    def test_python_sandbox_image_can_be_pinned_for_adjudication(self) -> None:
        function_globals = BENCH.run_code.__globals__
        completed = SimpleNamespace(returncode=1, stdout="", stderr="expected test failure")
        with patch.dict(function_globals["os"].environ, {"PYTHON_SANDBOX_IMAGE": "registry.example/python@sha256:test"}):
            with patch.object(function_globals["subprocess"], "run", return_value=completed) as run:
                passed, _detail = BENCH.run_code("def value(): return 1", [("value()", 1)])
        self.assertFalse(passed)
        self.assertIn("registry.example/python@sha256:test", run.call_args.args[0])

    def test_streaming_request_collects_reasoning_content_and_usage(self) -> None:
        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        events = b"\n".join(
            [
                b'data: {"choices":[{"delta":{"reasoning_content":"think"},"finish_reason":null}]}',
                b'data: {"choices":[{"delta":{"reasoning_content":"ing","content":"ok"},"finish_reason":"stop"}]}',
                b'data: {"choices":[],"usage":{"completion_tokens":3}}',
                b"data: [DONE]",
            ]
        ) + b"\n"
        with patch.object(BENCH.urllib.request, "urlopen", return_value=Response(events)) as urlopen:
            result = BENCH.request("http://example.test/v1", "model", "test", "off", 256, stream=True)
        body = json.loads(urlopen.call_args.args[0].data)
        self.assertTrue(body["stream"])
        self.assertEqual(result["reasoning"], "thinking")
        self.assertEqual(result["response"], "ok")
        self.assertEqual(result["usage"]["completion_tokens"], 3)

    def test_streaming_request_rejects_clean_early_eof(self) -> None:
        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        events = b'data: {"choices":[{"delta":{"content":"partial"},"finish_reason":null}]}\n'
        with patch.object(BENCH.urllib.request, "urlopen", return_value=Response(events)):
            result = BENCH.request("http://example.test/v1", "model", "test", "off", 256, stream=True)
        self.assertEqual(result["finish_reason"], "error")
        self.assertEqual(result["error"]["type"], "incomplete_stream")

    def test_report_input_validation(self) -> None:
        value = {
            "harness_id": "lakehouse-thinking-v1",
            "cases": [{"id": "x", "category": "sql"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            paths = {}
            for key in REPORT.LABELS:
                path = Path(directory) / f"{key}.json"
                path.write_text(json.dumps(value))
                paths[key] = path
            loaded = REPORT.load_inputs(paths)
            self.assertEqual(set(loaded), set(REPORT.LABELS))


if __name__ == "__main__":
    unittest.main()
