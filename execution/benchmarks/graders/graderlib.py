"""Minimal JSON-emitting unittest runner for hidden benchmark checks."""

import json
import traceback
import unittest


def emit_setup_error(exc):
    payload = {
        "schema_version": 1,
        "status": "failed",
        "passed": 0,
        "total": 0,
        "failures": [f"setup: {type(exc).__name__}: {exc}"],
    }
    print(json.dumps(payload, sort_keys=True))
    return 1


def run_suite(suite):
    result = unittest.TestResult()
    suite.run(result)
    failures = []
    for test, detail in result.failures + result.errors:
        last_line = detail.strip().splitlines()[-1] if detail.strip() else "failure"
        failures.append(f"{test.id()}: {last_line}")
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    payload = {
        "schema_version": 1,
        "status": "passed" if result.wasSuccessful() else "failed",
        "passed": passed,
        "total": total,
        "failures": failures,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


def suite_for(case):
    return unittest.defaultTestLoader.loadTestsFromTestCase(case)
