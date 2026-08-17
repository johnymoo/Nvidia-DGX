#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
BENCHMARK_PATH = SCRIPT_DIR / "lakehouse_thinking_benchmark.py"
SPEC = importlib.util.spec_from_file_location("lakehouse_thinking_benchmark", BENCHMARK_PATH)
assert SPEC and SPEC.loader
BENCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCH)


def corrected_stable_toposort(case: dict) -> tuple[float, dict]:
    _, _, checks = next(item for item in BENCH.PYTHON_CASES if item[0] == "stable_toposort")
    passed, detail = BENCH.execute_python("stable_toposort", case.get("response") or "", checks)
    return float(passed), {"passed": passed, "executor_tail": detail}


def adjudicate(record: dict, source: str) -> dict:
    scores: dict[str, list[float]] = {name: [] for name in ("sql", "python", "incident")}
    overrides = []
    for case in record["cases"]:
        score = float(case["score"])
        status = "unchanged"
        reason = None
        detail = None
        if case["id"] == "cdc_latest_live":
            status = "excluded"
            reason = "v1 prompt did not define the I/U/D operation codes, so the original answer cannot be fairly graded"
        elif case["id"] == "stable_toposort":
            status = "rescored"
            reason = "v1 expected order contradicted dict insertion-order tie breaking and did not execute exception checks"
            score, detail = corrected_stable_toposort(case)
            scores[case["category"]].append(score)
        else:
            scores[case["category"]].append(score)
        overrides.append(
            {
                "id": case["id"],
                "category": case["category"],
                "status": status,
                "original_score": float(case["score"]),
                "adjudicated_score": None if status == "excluded" else score,
                "reason": reason,
                "detail": detail,
            }
        )
    categories = {
        name: {
            "score": statistics.fmean(values),
            "passed": sum(value == 1.0 for value in values),
            "total": len(values),
        }
        for name, values in scores.items()
    }
    return {
        "tag": record["tag"],
        "source_file": source,
        "original_macro_score": record["macro_score"],
        "macro_score": statistics.fmean(item["score"] for item in categories.values()),
        "categories": categories,
        "case_overrides": overrides,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    runs = []
    for path in sorted(args.input_dir.glob("*.json")):
        record = json.loads(path.read_text())
        if record.get("harness_id") == "lakehouse-thinking-v1" and record.get("status") == "passed":
            runs.append(adjudicate(record, path.name))
    if not runs:
        raise RuntimeError(f"No completed lakehouse-thinking-v1 evidence in {args.input_dir}")
    output = {
        "schema_version": 1,
        "source_harness": "lakehouse-thinking-v1",
        "adjudication": "2026-08-17-contract-review-v1",
        "policy": {
            "cdc_latest_live": "excluded from SQL score because the prompt omitted operation-code semantics",
            "stable_toposort": "rescored against corrected insertion-order oracle plus executed missing-dependency and cycle checks",
            "raw_evidence_mutated": False,
        },
        "runs": runs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
