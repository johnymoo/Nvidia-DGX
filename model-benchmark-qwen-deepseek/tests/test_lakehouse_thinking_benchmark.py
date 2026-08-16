#!/usr/bin/env python3
import importlib.util
import sys
import unittest
import json
import tempfile
from pathlib import Path


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

    def test_report_input_validation(self) -> None:
        value = {
            "harness_id": BENCH.HARNESS_ID,
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
