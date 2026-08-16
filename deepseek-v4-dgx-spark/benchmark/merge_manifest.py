#!/usr/bin/env python3
"""Merge validated R3 domain fragments into the benchmark manifest."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "tasks.json"
FRAGMENTS = {
    "terminal": ROOT / "r3" / "terminal" / "tasks.json",
    "server_ops": ROOT / "r3" / "ops" / "tasks.json",
    "writing": ROOT / "r3" / "writing" / "tasks.json",
    "programming": ROOT / "r3" / "programming" / "tasks.json",
}


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> None:
    manifest = read_json(MANIFEST)
    original = [task for task in manifest["tasks"] if "r3_domain" not in task]
    if len(original) != 7:
        raise SystemExit(f"expected seven unchanged R2 tasks, found {len(original)}")

    added: list[dict[str, Any]] = []
    for domain, path in FRAGMENTS.items():
        value = read_json(path)
        tasks = value["tasks"] if isinstance(value, dict) else value
        if not isinstance(tasks, list) or len(tasks) != 10:
            raise SystemExit(f"{domain}: expected exactly ten tasks")
        for task in tasks:
            if task.get("r3_domain") not in {None, domain}:
                raise SystemExit(f"{task.get('task_id')}: conflicting r3_domain")
            task["r3_domain"] = domain
            if domain == "writing" and "language" not in task:
                task["language"] = task.get("grading", {}).get("language")
        added.extend(tasks)

    all_tasks = original + added
    ids = [task.get("task_id") for task in all_tasks]
    if len(all_tasks) != 47 or len(set(ids)) != 47 or any(not isinstance(task_id, str) or not task_id for task_id in ids):
        raise SystemExit("merged task IDs are incomplete or duplicated")
    domain_counts = {domain: sum(task.get("r3_domain") == domain for task in all_tasks) for domain in FRAGMENTS}
    if domain_counts != {domain: 10 for domain in FRAGMENTS}:
        raise SystemExit(f"invalid domain counts: {domain_counts}")
    new_starts = [task["treatment_order"][0] for task in added]
    if new_starts.count("online_ds") != 20 or new_starts.count("offline_ds") != 20:
        raise SystemExit("new DeepSeek ordering is not balanced 20/20")
    writing = [task for task in added if task["r3_domain"] == "writing"]
    programming = [task for task in added if task["r3_domain"] == "programming"]
    if {language: sum(task.get("language") == language for task in writing) for language in ("zh", "en")} != {"zh": 5, "en": 5}:
        raise SystemExit("writing language split must be 5/5")
    if {language: sum(task.get("language") == language for task in programming) for language in ("python", "typescript")} != {"python": 5, "typescript": 5}:
        raise SystemExit("programming language split must be 5/5")

    manifest["schema_version"] = 3
    manifest["baseline_revision"] = "claude-ds-pilot-r3"
    audit = [entry for entry in manifest.setdefault("audit_history", []) if entry.get("revision") != "claude-ds-pilot-r3"]
    audit.append(
        {
            "date": "2026-08-12",
            "revision": "claude-ds-pilot-r3",
            "change": "Added forty sandbox tasks across terminal, server operations, bilingual writing, and Python/TypeScript programming.",
        }
    )
    manifest["audit_history"] = audit
    manifest["corpus_contract"] = {
        "task_count": 47,
        "attempt_count": 141,
        "new_domain_counts": domain_counts,
        "writing_languages": {"zh": 5, "en": 5},
        "programming_languages": {"python": 5, "typescript": 5},
        "human_review_required": False,
    }
    manifest["tasks"] = all_tasks
    atomic_json(MANIFEST, manifest)
    print(json.dumps({"status": "merged", "tasks": len(all_tasks), "domains": domain_counts}, sort_keys=True))


if __name__ == "__main__":
    main()
