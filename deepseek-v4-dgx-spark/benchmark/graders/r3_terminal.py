#!/usr/bin/env python3
"""Hidden alternate-input checks for the R3 terminal-use benchmark tasks."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Callable


TASK_IDS = {
    "terminal-log-frequency",
    "terminal-nul-inventory",
    "terminal-csv-pipeline",
    "terminal-safe-rename",
    "terminal-env-precedence",
    "terminal-permission-audit",
    "terminal-archive-verify",
    "terminal-process-join",
    "terminal-jsonl-aggregate",
    "terminal-checksum-audit",
}
OUTPUTS = {
    "report.json", "inventory.json", "summary.csv", "rename-plan.json",
    "rollback.tsv", "effective-env.json", "permission-report.tsv",
    "verification.json", "process-report.tsv", "aggregate.json", "audit.json",
    "extracted",
}


def fail(message: str) -> None:
    raise AssertionError(message)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def safe_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "LANG": "C"}
    if extra:
        env.update(extra)
    return env


def clean_outputs(workspace: Path) -> None:
    for name in OUTPUTS:
        path = workspace / name
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def run(workspace: Path, input_dir: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    clean_outputs(workspace)
    return subprocess.run(
        [str(workspace / "solve.sh"), str(input_dir), *args],
        cwd=workspace,
        env=safe_env(env),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=15,
        check=False,
    )


def expect_ok(result: subprocess.CompletedProcess[str]) -> None:
    if result.returncode != 0:
        fail(f"solve.sh exited {result.returncode}: {result.stdout[-300:]}")


def read_json(workspace: Path, name: str) -> object:
    try:
        return json.loads((workspace / name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"invalid {name}: {exc}")


def case_log_frequency(workspace: Path, root: Path) -> None:
    logs = root / "logs"
    logs.mkdir()
    (logs / "app.log").write_text(
        "INFO no-op\nERROR payment failed user_id=7 request_id=one latency_ms=12\n"
        "ERROR disk full trace_id=a\n",
        encoding="utf-8",
    )
    (logs / "app.log.2").write_text(
        "ERROR payment failed user_id=8 request_id=two latency_ms=99\n",
        encoding="utf-8",
    )
    expect_ok(run(workspace, root))
    payload = read_json(workspace, "report.json")
    expected = [
        {"signature": "payment failed user_id=? request_id=? latency_ms=?", "count": 2},
        {"signature": "disk full trace_id=?", "count": 1},
    ]
    if payload != {"errors": expected}:
        fail("log ranking or normalization is incorrect")


def case_nul_inventory(workspace: Path, root: Path) -> None:
    tree = root / "tree"
    (tree / "nested").mkdir(parents=True)
    files = {"space name.txt": b"a", "-leading": b"bb", "tab\tname": b"ccc", "nested/item": b"dddd"}
    for name, contents in files.items():
        path = tree / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
    os.symlink(tree / "space name.txt", tree / "ignored-link")
    expect_ok(run(workspace, root))
    payload = read_json(workspace, "inventory.json")
    expected = [{"path": name, "bytes": len(contents)} for name, contents in sorted(files.items())]
    if payload != {"files": expected}:
        fail("inventory is not NUL-safe, complete, or deterministic")


def case_csv_pipeline(workspace: Path, root: Path) -> None:
    rows = [
        ["account", "team", "amount_cents", "status"],
        ["1", "Zulu", "9", "approved"],
        ["2", "North, East", "11", "approved"],
        ["3", "Zulu", "5", "approved"],
        ["4", "Zulu", "7", "rejected"],
    ]
    with (root / "records.csv").open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(rows)
    expect_ok(run(workspace, root))
    with (workspace / "summary.csv").open(encoding="utf-8", newline="") as handle:
        actual = list(csv.reader(handle))
    if actual != [["team", "total_cents", "rows"], ["North, East", "11", "1"], ["Zulu", "14", "2"]]:
        fail("CSV aggregation or quoting is incorrect")


def case_csv_rejects_malformed(workspace: Path, root: Path) -> None:
    (root / "records.csv").write_text("account,team,amount_cents,status\na,b,3\n", encoding="utf-8")
    if run(workspace, root).returncode == 0 or (workspace / "summary.csv").exists():
        fail("malformed CSV was accepted or left a result")


def case_safe_rename(workspace: Path, root: Path) -> None:
    media = root / "media"
    media.mkdir()
    for name, value in {"Summer Photo.JPG": "one", "summer_photo.jpg": "two", "-Draft.TXT": "three"}.items():
        (media / name).write_text(value, encoding="utf-8")
    expect_ok(run(workspace, root))
    plan = read_json(workspace, "rename-plan.json")
    operations = plan.get("operations") if isinstance(plan, dict) else None
    expected = {
        ("Summer Photo.JPG", "summer-photo.jpg"),
        ("summer_photo.jpg", "summer-photo-2.jpg"),
        ("-Draft.TXT", "draft.txt"),
    }
    actual = {(item.get("from"), item.get("to")) for item in operations or [] if isinstance(item, dict)}
    if actual != expected or len(operations or []) != 3:
        fail("rename collision plan is incorrect")
    expect_ok(run(workspace, root, "--apply"))
    if {path.name for path in media.iterdir()} != {"summer-photo.jpg", "summer-photo-2.jpg", "draft.txt"}:
        fail("rename apply overwrote or left files behind")
    expect_ok(run(workspace, root))
    if read_json(workspace, "rename-plan.json") != {"operations": []}:
        fail("rename is not idempotent")


def case_env_precedence(workspace: Path, root: Path) -> None:
    (root / "defaults.env").write_text("APP_HOST=base\nAPP_PORT=8000\nAPP_DEBUG=false\nAPP_LABEL=base\n", encoding="utf-8")
    (root / ".env").write_text("APP_PORT=8890\nAPP_LABEL=from file\n", encoding="utf-8")
    marker = workspace / "evaluated"
    expect_ok(run(workspace, root, env={"APP_PORT": "9000", "APP_LABEL": f"$(touch {marker})"}))
    if read_json(workspace, "effective-env.json") != {
        "APP_HOST": "base", "APP_PORT": "9000", "APP_DEBUG": "false", "APP_LABEL": f"$(touch {marker})",
    } or marker.exists():
        fail("environment precedence evaluated input or produced wrong values")


def case_env_rejects_invalid(workspace: Path, root: Path) -> None:
    (root / "defaults.env").write_text("APP_HOST=one\nAPP_HOST=two\n", encoding="utf-8")
    (root / ".env").write_text("APP_PORT=1\n", encoding="utf-8")
    if run(workspace, root).returncode == 0:
        fail("duplicate dotenv key was accepted")


def case_permission_audit(workspace: Path, root: Path) -> None:
    tree = root / "tree"
    (tree / "nested").mkdir(parents=True)
    (tree / "job.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (tree / "nested" / "data.txt").write_text("data\n", encoding="utf-8")
    os.chmod(tree, 0o700)
    os.chmod(tree / "nested", 0o700)
    os.chmod(tree / "job.sh", 0o600)
    os.chmod(tree / "nested" / "data.txt", 0o777)
    os.symlink(tree / "nested" / "data.txt", tree / "unchanged-link")
    original_link_mode = stat.S_IMODE(os.lstat(tree / "unchanged-link").st_mode)
    expect_ok(run(workspace, root))
    if stat.S_IMODE((tree / "job.sh").stat().st_mode) != 0o750 or stat.S_IMODE((tree / "nested" / "data.txt").stat().st_mode) != 0o640:
        fail("permission targets were not remediated")
    if stat.S_IMODE(os.lstat(tree / "unchanged-link").st_mode) != original_link_mode:
        fail("symlink mode changed")
    expect_ok(run(workspace, root))
    report = (workspace / "permission-report.tsv").read_text(encoding="utf-8")
    if "\tfixed\n" in report:
        fail("permission remediation is not idempotent")


def make_tar(path: Path, members: dict[str, bytes]) -> None:
    with tarfile.open(path, "w") as archive:
        for name, contents in members.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(contents)
            archive.addfile(entry, io.BytesIO(contents))


def case_archive_verify(workspace: Path, root: Path) -> None:
    contents = {"docs/readme.txt": b"good\n", "config/app.conf": b"port=8890\n"}
    make_tar(root / "bundle.tar", contents)
    (root / "manifest.tsv").write_text("".join(f"{sha256_bytes(value)}\t{name}\n" for name, value in contents.items()), encoding="utf-8")
    expect_ok(run(workspace, root))
    payload = read_json(workspace, "verification.json")
    if {entry["path"] for entry in payload.get("verified", [])} != set(contents) or (workspace / "extracted" / "docs" / "readme.txt").read_bytes() != b"good\n":
        fail("archive verification did not extract verified members")


def case_archive_rejects_traversal(workspace: Path, root: Path) -> None:
    make_tar(root / "bundle.tar", {"docs/ok.txt": b"ok", "../escape.txt": b"bad"})
    (root / "manifest.tsv").write_text(f"{sha256_bytes(b'ok')}\tdocs/ok.txt\n", encoding="utf-8")
    if run(workspace, root).returncode == 0 or (workspace / "escape.txt").exists():
        fail("archive traversal member was accepted")


def case_process_join(workspace: Path, root: Path) -> None:
    (root / "ps.tsv").write_text("pid\tppid\tcommand\n42\t1\tapi server\n7\t1\tworker\n", encoding="utf-8")
    (root / "services.tsv").write_text("service\tpid\tstate\nflash-api\t42\trunning\n", encoding="utf-8")
    (root / "sockets.tsv").write_text("pid\tproto\tlocal\tremote\n42\ttcp\t127.0.0.1:2\tclient-b\n42\ttcp\t127.0.0.1:1\tclient-a\n", encoding="utf-8")
    expect_ok(run(workspace, root))
    lines = (workspace / "process-report.tsv").read_text(encoding="utf-8").splitlines()
    if lines[1].split("\t")[:2] != ["7", "-"] or "tcp 127.0.0.1:1->client-a,tcp 127.0.0.1:2->client-b" not in lines[2]:
        fail("process join is not stable")


def case_process_rejects_orphan(workspace: Path, root: Path) -> None:
    (root / "ps.tsv").write_text("pid\tppid\tcommand\n7\t1\tworker\n", encoding="utf-8")
    (root / "services.tsv").write_text("service\tpid\tstate\napi\t99\trunning\n", encoding="utf-8")
    (root / "sockets.tsv").write_text("pid\tproto\tlocal\tremote\n", encoding="utf-8")
    if run(workspace, root).returncode == 0:
        fail("orphan service row was accepted")


def case_jsonl_aggregate(workspace: Path, root: Path) -> None:
    (root / "requests.jsonl").write_text('{"latency_ms":1,"status":201}\n{"status":404,"latency_ms":100}\n{"status":503,"latency_ms":500}\n', encoding="utf-8")
    expect_ok(run(workspace, root))
    if read_json(workspace, "aggregate.json") != {
        "rows": 3,
        "status_buckets": {"1xx": 0, "2xx": 1, "3xx": 0, "4xx": 1, "5xx": 1},
        "latency_buckets": {"lt_100": 1, "100_499": 1, "500_plus": 1},
        "latency_sum_ms": 601,
    }:
        fail("JSONL aggregation is incorrect")


def case_jsonl_rejects_malformed(workspace: Path, root: Path) -> None:
    (root / "requests.jsonl").write_text('{"status":200,"latency_ms":1,"extra":2}\n', encoding="utf-8")
    if run(workspace, root).returncode == 0 or (workspace / "aggregate.json").exists():
        fail("malformed JSONL was accepted or left a result")


def case_checksum_audit(workspace: Path, root: Path) -> None:
    tree = root / "tree"
    tree.mkdir()
    files = {"keep.txt": b"keep", "changed.txt": b"current", "surplus.txt": b"surplus"}
    for name, contents in files.items():
        (tree / name).write_bytes(contents)
    (root / "checksums.txt").write_text(
        f"{sha256_bytes(b'keep')}  keep.txt\n{sha256_bytes(b'old')}  changed.txt\n{sha256_bytes(b'missing')}  missing.txt\n",
        encoding="utf-8",
    )
    expect_ok(run(workspace, root))
    if read_json(workspace, "audit.json") != {"matching": ["keep.txt"], "missing": ["missing.txt"], "changed": ["changed.txt"], "unexpected": ["surplus.txt"]}:
        fail("checksum classifications are incorrect")


def case_checksum_rejects_unsafe(workspace: Path, root: Path) -> None:
    (root / "tree").mkdir()
    (root / "checksums.txt").write_text(f"{sha256_bytes(b'x')}  ../outside\n", encoding="utf-8")
    if run(workspace, root).returncode == 0:
        fail("unsafe checksum path was accepted")


CASES: dict[str, list[Callable[[Path, Path], None]]] = {
    "terminal-log-frequency": [case_log_frequency],
    "terminal-nul-inventory": [case_nul_inventory],
    "terminal-csv-pipeline": [case_csv_pipeline, case_csv_rejects_malformed],
    "terminal-safe-rename": [case_safe_rename],
    "terminal-env-precedence": [case_env_precedence, case_env_rejects_invalid],
    "terminal-permission-audit": [case_permission_audit],
    "terminal-archive-verify": [case_archive_verify, case_archive_rejects_traversal],
    "terminal-process-join": [case_process_join, case_process_rejects_orphan],
    "terminal-jsonl-aggregate": [case_jsonl_aggregate, case_jsonl_rejects_malformed],
    "terminal-checksum-audit": [case_checksum_audit, case_checksum_rejects_unsafe],
}


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(json.dumps({"schema_version": 1, "status": "failed", "passed": 0, "total": 1, "failures": ["usage: r3_terminal.py WORKSPACE TASK_ID"]}, sort_keys=True))
        return 2
    workspace = Path(argv[1]).resolve()
    task_id = argv[2]
    failures: list[str] = []
    passed = 0
    solve = workspace / "solve.sh"
    if not workspace.is_dir() or not solve.is_file() or not os.access(solve, os.X_OK):
        failures.append("solve.sh is missing or not executable")
    else:
        for index, check in enumerate(CASES.get(task_id, []), start=1):
            try:
                with tempfile.TemporaryDirectory(prefix=f".r3-terminal-{task_id}-", dir=workspace) as raw_root:
                    check(workspace, Path(raw_root))
            except Exception as exc:  # Keep each hidden check independently scored.
                failures.append(f"case {index}: {type(exc).__name__}: {exc}")
            else:
                passed += 1
    total = max(1, len(CASES.get(task_id, [])))
    if task_id not in TASK_IDS:
        failures.append(f"unknown task ID: {task_id}")
    payload = {"schema_version": 1, "status": "passed" if not failures else "failed", "passed": passed if task_id in TASK_IDS else 0, "total": total, "failures": failures}
    print(json.dumps(payload, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
