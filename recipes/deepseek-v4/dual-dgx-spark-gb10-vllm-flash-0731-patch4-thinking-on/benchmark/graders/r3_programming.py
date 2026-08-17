#!/usr/bin/env python3
"""Hidden R3 programming checks selected by task ID."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import re
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path

from graderlib import emit_setup_error, run_suite, suite_for


PYTHON_TASKS = {
    "python-async-cache": "async_cache",
    "python-streaming-csv": "streaming_csv",
    "python-retry-decorator": "retry_decorator",
    "python-toposort": "toposort",
    "python-bounded-map": "bounded_map",
}
TYPESCRIPT_TASKS = {
    "typescript-config-merge",
    "typescript-event-emitter",
    "typescript-url-router",
    "typescript-promise-pool",
    "typescript-lru-ttl",
}
ROOT = Path(__file__).resolve().parents[1]
TYPESCRIPT_HIDDEN_TESTS = ROOT / "r3" / "programming" / "hidden_typescript.test.mjs"


def hidden_case(task_id, module):
    if task_id == "python-async-cache":
        class AsyncCacheHiddenTests(unittest.IsolatedAsyncioTestCase):
            async def test_ttl_single_flight_and_waiter_cancellation(self):
                now = [10.0]
                cache = module.AsyncTTLCache(5, clock=lambda: now[0])
                started = asyncio.Event()
                release = asyncio.Event()
                calls = 0

                async def load():
                    nonlocal calls
                    calls += 1
                    started.set()
                    await release.wait()
                    return "loaded"

                first = asyncio.create_task(cache.get_or_load("key", load))
                await started.wait()
                second = asyncio.create_task(cache.get_or_load("key", load))
                first.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await first
                release.set()
                self.assertEqual(await second, "loaded")
                self.assertEqual(calls, 1)
                self.assertEqual(await cache.get_or_load("key", load), "loaded")
                now[0] = 15.0
                self.assertEqual(await cache.get_or_load("key", load), "loaded")
                self.assertEqual(calls, 2)

            async def test_loader_failure_is_not_cached_or_left_in_flight(self):
                cache = module.AsyncTTLCache(1)
                calls = 0

                async def load():
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        raise RuntimeError("transient")
                    return calls

                with self.assertRaisesRegex(RuntimeError, "transient"):
                    await cache.get_or_load("key", load)
                self.assertEqual(await cache.get_or_load("key", load), 2)
                cache.invalidate("key")
                self.assertEqual(await cache.get_or_load("key", load), 3)
                cache.clear()
                self.assertEqual(await cache.get_or_load("key", load), 4)

            def test_constructor_validation(self):
                with self.assertRaises(ValueError):
                    module.AsyncTTLCache(-1)
                with self.assertRaises(TypeError):
                    module.AsyncTTLCache(True)

        return AsyncCacheHiddenTests

    if task_id == "python-streaming-csv":
        class StreamingCsvHiddenTests(unittest.TestCase):
            def test_reports_malformed_rows_with_bounded_stable_summary(self):
                result = module.aggregate_csv(
                    [
                        "category,amount,note\n",
                        'fruit,1.25,"fresh, local"\n',
                        "fruit,NaN,bad\n",
                        " ,3,blank category\n",
                        "tool,4\n",
                        "tool,2,ok\n",
                    ],
                    max_errors=2,
                )
                self.assertEqual(result.total_rows, 5)
                self.assertEqual(result.accepted_rows, 2)
                self.assertEqual(result.rejected_rows, 3)
                self.assertEqual(result.totals, (("fruit", Decimal("1.25")), ("tool", Decimal("2"))))
                self.assertEqual(
                    [(error.row_number, error.reason) for error in result.errors],
                    [(3, "invalid amount"), (4, "blank category")],
                )
                with self.assertRaises(AttributeError):
                    result.accepted_rows = 9

            def test_consumes_a_single_pass_iterable(self):
                class SinglePass:
                    def __init__(self):
                        self.iterations = 0

                    def __iter__(self):
                        self.iterations += 1
                        if self.iterations > 1:
                            raise AssertionError("input was iterated more than once")
                        yield "category,amount\n"
                        yield "a,1\n"

                lines = SinglePass()
                result = module.aggregate_csv(lines)
                self.assertEqual(lines.iterations, 1)
                self.assertEqual(result.totals, (("a", Decimal("1")),))

            def test_rejects_invalid_headers_and_error_limit(self):
                with self.assertRaises(ValueError):
                    module.aggregate_csv([])
                with self.assertRaises(ValueError):
                    module.aggregate_csv(["category,category\n"])
                with self.assertRaises(ValueError):
                    module.aggregate_csv(["amount\n", "1\n"])
                with self.assertRaises(ValueError):
                    module.aggregate_csv(["category,amount\n"], max_errors=-1)

        return StreamingCsvHiddenTests

    if task_id == "python-retry-decorator":
        class RetryDecoratorHiddenTests(unittest.IsolatedAsyncioTestCase):
            async def test_sync_backoff_filters_and_metadata(self):
                sleeps = []
                calls = 0

                @module.retry(attempts=3, delay=2, backoff=3, sleep=sleeps.append)
                def operation():
                    nonlocal calls
                    calls += 1
                    if calls < 3:
                        raise ValueError("again")
                    return "done"

                self.assertEqual(operation(), "done")
                self.assertEqual(calls, 3)
                self.assertEqual(sleeps, [2.0, 6.0])
                self.assertEqual(operation.__name__, "operation")

                filtered_sleeps = []

                @module.retry(attempts=3, exceptions=(KeyError,), sleep=filtered_sleeps.append)
                def filtered():
                    raise ValueError("do not retry")

                with self.assertRaisesRegex(ValueError, "do not retry"):
                    filtered()
                self.assertEqual(filtered_sleeps, [])

            async def test_async_retry_and_validation(self):
                calls = 0
                sleeps = []

                async def pause(delay):
                    sleeps.append(delay)

                @module.retry(attempts=3, delay=1, backoff=2, sleep=pause)
                async def operation():
                    nonlocal calls
                    calls += 1
                    if calls < 3:
                        raise LookupError("try again")
                    return calls

                self.assertEqual(await operation(), 3)
                self.assertEqual(sleeps, [1.0, 2.0])
                for attempts in (0, True):
                    with self.assertRaises((TypeError, ValueError)):
                        module.retry(attempts=attempts)
                with self.assertRaises(TypeError):
                    module.retry(attempts=2, exceptions=())

        return RetryDecoratorHiddenTests

    if task_id == "python-toposort":
        class ToposortHiddenTests(unittest.TestCase):
            def test_stable_dependency_order_and_input_immutability(self):
                graph = {
                    "publish": ("package", "test"),
                    "package": ("compile",),
                    "test": ("lint",),
                    "compile": ("lint",),
                    "lint": (),
                    "docs": (),
                }
                before = dict(graph)
                self.assertEqual(
                    module.stable_toposort(graph),
                    ["lint", "compile", "package", "test", "publish", "docs"],
                )
                self.assertEqual(graph, before)

            def test_missing_node_and_cycle_have_diagnostics(self):
                with self.assertRaises(module.MissingDependencyError) as missing:
                    module.stable_toposort({"build": ("compile",)})
                self.assertEqual(missing.exception.node, "build")
                self.assertEqual(missing.exception.dependency, "compile")

                with self.assertRaises(module.DependencyCycleError) as cycle:
                    module.stable_toposort({"a": ("b",), "b": ("c",), "c": ("a",)})
                self.assertEqual(cycle.exception.cycle, ("a", "b", "c", "a"))

            def test_dependency_iterables_are_consumed_once(self):
                def dependencies():
                    yield "leaf"

                self.assertEqual(module.stable_toposort({"root": dependencies(), "leaf": ()}), ["leaf", "root"])

        return ToposortHiddenTests

    if task_id == "python-bounded-map":
        class BoundedMapHiddenTests(unittest.IsolatedAsyncioTestCase):
            async def test_preserves_order_without_exceeding_limit(self):
                active = max_active = 0

                async def work(value):
                    nonlocal active, max_active
                    active += 1
                    max_active = max(max_active, active)
                    await asyncio.sleep((4 - value) * 0.001)
                    active -= 1
                    return value * 10

                self.assertEqual(await module.bounded_map(work, [1, 2, 3, 4], limit=2), [10, 20, 30, 40])
                self.assertLessEqual(max_active, 2)

            async def test_error_and_caller_cancellation_cancel_outstanding_work(self):
                started = []
                cancelled = []
                waiting = asyncio.Event()
                marker = RuntimeError("boom")

                async def failing_work(value):
                    started.append(value)
                    if value == 1:
                        raise marker
                    try:
                        await waiting.wait()
                    except asyncio.CancelledError:
                        cancelled.append(value)
                        raise

                with self.assertRaisesRegex(RuntimeError, "boom"):
                    await module.bounded_map(failing_work, [0, 1, 2], limit=2)
                self.assertEqual(started, [0, 1])
                self.assertEqual(cancelled, [0])

                started_event = asyncio.Event()
                cancelled_event = asyncio.Event()

                async def slow_work(value):
                    started_event.set()
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        cancelled_event.set()
                        raise

                task = asyncio.create_task(module.bounded_map(slow_work, [1, 2], limit=2))
                await started_event.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertTrue(cancelled_event.is_set())

            async def test_limit_is_positive_integer(self):
                async def identity(value):
                    return value

                for limit in (0, -1, True):
                    with self.assertRaises((TypeError, ValueError)):
                        await module.bounded_map(identity, [1], limit=limit)

        return BoundedMapHiddenTests

    raise ValueError(f"unknown Python task ID: {task_id}")


def run_typescript(workspace: Path, task_id: str) -> int:
    env = os.environ.copy()
    env["R3_PROGRAMMING_WORKSPACE"] = str(workspace)
    env["R3_PROGRAMMING_TASK_ID"] = task_id
    try:
        result = subprocess.run(
            ["node", "--test", str(TYPESCRIPT_HIDDEN_TESTS)],
            cwd=workspace,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
    except OSError as exc:
        return emit_setup_error(exc)

    output = result.stdout
    tests_match = re.search(r"^(?:#|ℹ) tests (\d+)$", output, re.MULTILINE)
    passed_match = re.search(r"^(?:#|ℹ) pass (\d+)$", output, re.MULTILINE)
    total = int(tests_match.group(1)) if tests_match else 1
    passed = int(passed_match.group(1)) if passed_match else 0
    failures = [line.strip() for line in output.splitlines() if line.startswith("not ok") or line.startswith("✖")]
    payload = {
        "schema_version": 1,
        "status": "passed" if result.returncode == 0 else "failed",
        "passed": min(passed, total),
        "total": total,
        "failures": failures or ([] if result.returncode == 0 else ["node:test hidden checks failed"]),
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if result.returncode == 0 else 1


def main() -> int:
    if len(sys.argv) != 3:
        return emit_setup_error(ValueError("usage: r3_programming.py WORKSPACE TASK_ID"))
    workspace = Path(sys.argv[1]).resolve()
    task_id = sys.argv[2]
    if not workspace.is_dir():
        return emit_setup_error(FileNotFoundError(workspace))
    if task_id in PYTHON_TASKS:
        try:
            sys.path.insert(0, str(workspace))
            module = importlib.import_module(PYTHON_TASKS[task_id])
            return run_suite(suite_for(hidden_case(task_id, module)))
        except Exception as exc:
            return emit_setup_error(exc)
    if task_id in TYPESCRIPT_TASKS:
        return run_typescript(workspace, task_id)
    return emit_setup_error(ValueError(f"unknown task ID: {task_id}"))


if __name__ == "__main__":
    raise SystemExit(main())
