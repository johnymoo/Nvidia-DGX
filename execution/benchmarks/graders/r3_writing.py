#!/usr/bin/env python3
"""Deterministic structural grader for the R3 bilingual writing tasks."""

import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any


TASKS_PATH = Path(__file__).resolve().parents[1] / "r3" / "writing" / "tasks.json"
SCHEMA_VERSION = 1


def normalized_text(value: str) -> str:
    """Fold case, width, whitespace, and equivalent date/number punctuation."""
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.translate(str.maketrans({character: "-" for character in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"}))
    return re.sub(r"[\s\-_/.,:;，、：；()\[\]{}]+", "", value)


def markdown_headings(text: str) -> set[str]:
    headings = set()
    for line in text.splitlines():
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if match:
            headings.add(normalized_text(match.group(1)))
    return headings


def length_of(text: str, language: str) -> int:
    normalized = unicodedata.normalize("NFKC", text)
    if language == "zh":
        return len(re.findall(r"[\u3400-\u9fff]", normalized))
    if language == "en":
        return len(re.findall(r"[A-Za-z0-9]+(?:[.'/-][A-Za-z0-9]+)*", normalized))
    raise ValueError(f"unsupported writing language: {language}")


def load_tasks() -> dict[str, dict[str, Any]]:
    payload = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or payload.get("domain") != "writing":
        raise ValueError("invalid R3 writing task metadata")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("R3 writing task metadata must contain a task list")
    indexed = {task.get("task_id"): task for task in tasks if isinstance(task, dict)}
    if len(indexed) != len(tasks) or any(not task_id for task_id in indexed):
        raise ValueError("R3 writing task IDs must be non-empty and unique")
    return indexed


def evaluate(workspace: Path, task_id: str) -> dict[str, Any]:
    try:
        task = load_tasks()[task_id]
        grading = task["grading"]
        language = grading["language"]
        lower = grading["min_length"]
        upper = grading["max_length"]
        required_headings = grading["required_headings"]
        required_facts = grading["required_facts"]
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
        return result([], [f"setup: {type(exc).__name__}: {exc}"], total=4)

    answer = workspace / "answer.md"
    if not answer.is_file():
        return result([], ["answer.md is missing", "answer length cannot be checked", "required headings cannot be checked", "required facts cannot be checked"], total=4)
    try:
        text = answer.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError as exc:
        return result(["answer artifact"], [f"answer.md is not valid UTF-8: {exc}", "answer length cannot be checked", "required headings cannot be checked", "required facts cannot be checked"], total=4)

    passed: list[str] = ["answer artifact"]
    failures: list[str] = []
    length = length_of(text, language)
    if lower <= length <= upper:
        passed.append("normalized length")
    else:
        failures.append(f"normalized {language} length {length} is outside {lower}-{upper}")

    headings = markdown_headings(text)
    missing_headings = [heading for heading in required_headings if normalized_text(heading) not in headings]
    if not missing_headings:
        passed.append("required headings")
    else:
        failures.append("missing required headings: " + ", ".join(missing_headings))

    normalized_answer = normalized_text(text)
    missing_facts = []
    for fact in required_facts:
        aliases = fact.get("aliases", [])
        if not any(normalized_text(alias) in normalized_answer for alias in aliases):
            missing_facts.append(fact.get("id", "unnamed fact"))
    if not missing_facts:
        passed.append("required facts")
    else:
        failures.append("missing required facts: " + ", ".join(missing_facts))
    return result(passed, failures, total=4)


def result(passed_checks: list[str], failures: list[str], *, total: int) -> dict[str, Any]:
    passed = min(len(passed_checks), total)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "passed" if not failures and passed == total else "failed",
        "passed": passed,
        "total": total,
        "failures": failures,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        payload = result([], ["usage: r3_writing.py WORKSPACE TASK_ID"], total=4)
    else:
        payload = evaluate(Path(argv[1]).resolve(), argv[2])
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
