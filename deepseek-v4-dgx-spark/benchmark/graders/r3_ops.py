#!/usr/bin/env python3
"""Deterministic hidden checks for R3 synthetic server-operations tasks.

The grader reads task-local artifacts only.  It never invokes a daemon, opens a
network connection, or executes a candidate shell artifact.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


class Checks:
    def __init__(self) -> None:
        self.total = 0
        self.failures: list[str] = []

    def require(self, condition: bool, message: str) -> None:
        self.total += 1
        if not condition:
            self.failures.append(message)

    def emit(self) -> int:
        passed = self.total - len(self.failures)
        payload = {
            "schema_version": 1,
            "status": "passed" if not self.failures else "failed",
            "passed": max(0, passed),
            "total": self.total,
            "failures": self.failures,
        }
        print(json.dumps(payload, sort_keys=True))
        return 0 if not self.failures else 1


FORBIDDEN_COMMAND = re.compile(
    r"(?im)(?:^|[;|&=]\s*|\$\(\s*|`\s*|\b(?:if\s+(?:!\s*)?|then|do|while|until|exec|command)\s+)(?:sudo|ssh|scp|sftp|docker|podman|systemctl|service|journalctl|nginx|curl|wget|nc|telnet)\b"
)
FORBIDDEN_PATH = re.compile(r"(?:^|[\s\"'=])/(?:bin|etc|var|usr|home|root|opt|tmp)(?:/|$)|(?:^|\s)~")
UNSAFE_PARENT = re.compile(r"(?:^|[\s\"'=])\.\./")
OVERCLAIM = re.compile(
    r"\b(?:guaranteed|zero[- ]downtime|fully resolved|no impact|production[- ]ready|root cause confirmed)\b",
    re.IGNORECASE,
)


def read_text(checks: Checks, workspace: Path, name: str) -> str:
    path = workspace / name
    checks.require(path.is_file() and not path.is_symlink(), f"missing regular artifact: {name}")
    if not path.is_file() or path.is_symlink():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        checks.require(False, f"cannot read {name}: {type(exc).__name__}")
        return ""


def read_json(checks: Checks, workspace: Path, name: str) -> dict[str, Any] | None:
    text = read_text(checks, workspace, name)
    if not text:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        checks.require(False, f"invalid JSON: {name}")
        return None
    checks.require(isinstance(value, dict), f"{name} must contain a JSON object")
    return value if isinstance(value, dict) else None


def strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for value_item in value for item in strings(value_item)]
    if isinstance(value, dict):
        return [item for key, value_item in value.items() for item in strings(key) + strings(value_item)]
    return []


def safe_text(checks: Checks, text: str, label: str) -> None:
    checks.require(not FORBIDDEN_COMMAND.search(text), f"{label} invokes a forbidden host command")
    checks.require(not FORBIDDEN_PATH.search(text), f"{label} references a host path")
    checks.require(not UNSAFE_PARENT.search(text), f"{label} references a parent path")
    checks.require(not re.search(r"(?im)\brm\s+-[^\n]*r", text), f"{label} uses recursive deletion")


def safe_value(checks: Checks, value: Any, label: str) -> None:
    joined = "\n".join(strings(value))
    safe_text(checks, joined, label)
    checks.require(not OVERCLAIM.search(joined), f"{label} makes an unsupported certainty claim")


def conf_syntax(checks: Checks, text: str, label: str) -> None:
    depth = 0
    valid = True
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        depth += line.count("{") - line.count("}")
        if depth < 0:
            valid = False
        if line not in {"{", "}"} and not line.endswith(("{", "}", ";")):
            valid = False
    checks.require(valid and depth == 0, f"{label} has malformed fragment syntax")


def logrotate_syntax(checks: Checks, text: str) -> None:
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    checks.require(text.count("{") == 1 and text.count("}") == 1, "logrotate-fixed.conf has unbalanced block syntax")
    checks.require("postrotate" in lines and "endscript" in lines, "logrotate-fixed.conf has malformed script block syntax")


def unit_values(checks: Checks, text: str, label: str) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    section = ""
    valid = True
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if "=" not in line or not section:
            valid = False
            continue
        key, value = line.split("=", 1)
        values.setdefault(f"{section}.{key}", []).append(value)
    checks.require(valid, f"{label} has malformed unit syntax")
    return values


def contains_values(values: dict[str, list[str]], key: str, required: list[str]) -> bool:
    rendered = " ".join(values.get(key, []))
    return all(item in rendered for item in required)


def diagnosis(
    checks: Checks,
    workspace: Path,
    incident_id: str,
    causes: set[str],
    evidence: set[str],
    max_changes: int,
) -> None:
    value = read_json(checks, workspace, "diagnosis.json")
    if value is None:
        return
    safe_value(checks, value, "diagnosis.json")
    checks.require(value.get("incident_id") == incident_id, "diagnosis.json has the wrong incident_id")
    checks.require(value.get("primary_cause") in causes, "diagnosis.json has an unsupported primary_cause")
    supplied_evidence = value.get("evidence")
    checks.require(isinstance(supplied_evidence, list) and evidence.issubset(set(supplied_evidence)), "diagnosis.json omits supplied evidence IDs")
    changes = value.get("bounded_changes")
    checks.require(isinstance(changes, list) and 1 <= len(changes) <= max_changes and all(isinstance(item, str) and item.strip() for item in changes), "diagnosis.json changes are not bounded")
    checks.require(value.get("certainty") == "evidence_limited", "diagnosis.json must preserve evidence-limited certainty")
    checks.require(value.get("scope") == "sandbox_snapshot_only", "diagnosis.json must declare the sandbox-only scope")


def check_nginx_upstream(checks: Checks, workspace: Path) -> None:
    text = read_text(checks, workspace, "fix.conf")
    safe_text(checks, text, "fix.conf")
    conf_syntax(checks, text, "fix.conf")
    for pattern, message in (
        (r"(?m)^\s*upstream\s+ledger_backend\s*\{", "missing ledger_backend upstream"),
        (r"(?m)^\s*server\s+ledger-a:9000\s+max_fails=2\s+fail_timeout=10s;", "missing bounded ledger-a upstream member"),
        (r"(?m)^\s*server\s+ledger-b:9000\s+max_fails=2\s+fail_timeout=10s;", "missing bounded ledger-b upstream member"),
        (r"(?m)^\s*proxy_pass\s+http://ledger_backend;", "missing named upstream proxy_pass"),
        (r"(?m)^\s*proxy_connect_timeout\s+2s;", "missing bounded connect timeout"),
        (r"(?m)^\s*proxy_read_timeout\s+30s;", "missing bounded read timeout"),
        (r"(?m)^\s*proxy_next_upstream\s+error\s+timeout\s+http_502\s+http_503;", "missing bounded retry conditions"),
        (r"(?m)^\s*proxy_set_header\s+X-Forwarded-For\s+\$proxy_add_x_forwarded_for;", "missing forwarding-chain header"),
    ):
        checks.require(bool(re.search(pattern, text)), message)
    diagnosis(checks, workspace, "INC-401", {"upstream_connectivity_and_read_timeout"}, {"EV-401-connect-refused", "EV-401-timeout"}, 4)


def check_systemd_restart(checks: Checks, workspace: Path) -> None:
    text = read_text(checks, workspace, "service-fixed.unit")
    safe_text(checks, text, "service-fixed.unit")
    values = unit_values(checks, text, "service-fixed.unit")
    checks.require(contains_values(values, "Unit.After", ["network-online.target", "config-ready.target"]), "unit lacks ordered dependencies")
    checks.require(contains_values(values, "Unit.Wants", ["network-online.target"]), "unit lacks soft network dependency")
    checks.require(contains_values(values, "Service.EnvironmentFile", ["./config/ledger.env"]), "unit lacks task-local environment file")
    checks.require(contains_values(values, "Service.ExecStart", ["./bin/ledger-api", "./config/ledger.toml"]), "unit lacks task-local start command")
    checks.require(contains_values(values, "Service.ExecStartPost", ["./bin/check-ready", "./runtime/ready.json"]), "unit lacks file-based readiness check")
    checks.require(contains_values(values, "Service.Restart", ["on-failure"]), "unit restart policy is not on-failure")
    checks.require(contains_values(values, "Service.RestartSec", ["5"]), "unit restart delay is missing")
    checks.require(contains_values(values, "Service.StartLimitIntervalSec", ["60"]) and contains_values(values, "Service.StartLimitBurst", ["3"]), "unit restart rate limit is missing")
    diagnosis(checks, workspace, "INC-402", {"restart_loop_missing_dependency_and_readiness"}, {"EV-402-missing-env", "EV-402-restart-loop", "EV-402-ready-file"}, 5)


def check_logrotate_policy(checks: Checks, workspace: Path) -> None:
    text = read_text(checks, workspace, "logrotate-fixed.conf")
    safe_text(checks, text, "logrotate-fixed.conf")
    logrotate_syntax(checks, text)
    for pattern, message in (
        (r"(?m)^\s*\./logs/ledger/\*\.log\s*\{", "rotation scope is not project-local"),
        (r"(?m)^\s*weekly$", "rotation is not weekly"),
        (r"(?m)^\s*rotate\s+14$", "retention is not fourteen rotations"),
        (r"(?m)^\s*compress$", "compression is missing"),
        (r"(?m)^\s*delaycompress$", "delayed compression is missing"),
        (r"(?m)^\s*create\s+0640\s+appsvc\s+appgrp$", "safe rotated-file ownership is missing"),
        (r"(?m)^\s*\.\/bin\/reload-ledger\s+--config\s+\.\/config\/ledger\.conf\s+.*\|\|\s+exit\s+1$", "reload hook does not propagate failure"),
    ):
        checks.require(bool(re.search(pattern, text)), message)
    diagnosis(checks, workspace, "INC-403", {"unsafe_rotation_ownership_and_retention"}, {"EV-403-world-readable", "EV-403-unbounded-retention", "EV-403-reload-failed"}, 4)


def check_backup_schedule(checks: Checks, workspace: Path) -> None:
    script = read_text(checks, workspace, "backup-fixed.sh")
    schedule = read_text(checks, workspace, "schedule.txt")
    safe_text(checks, script, "backup-fixed.sh")
    safe_text(checks, schedule, "schedule.txt")
    checks.require(bool(re.search(r"(?m)^set\s+-[A-Za-z]*e[A-Za-z]*u", script)), "backup script does not propagate failures")
    checks.require(bool(re.search(r"(?m)^TZ=UTC$", script)) and "export TZ" in script, "backup script does not pin UTC")
    checks.require(bool(re.search(r"(?m)^\s*(?:if\s+!\s+)?mkdir\s+['\"]?\./runtime/backup\.lock", script)), "backup script lacks a task-local lock")
    checks.require("trap" in script and "rmdir" in script and "./runtime/backup.lock" in script, "backup lock is not released")
    checks.require("./bin/snapshot" in script and "./backups/" in script, "backup script lacks task-local snapshot output")
    checks.require("./bin/prune-backups" in script and "--keep 7" in script, "backup retention is not bounded")
    checks.require("|| true" not in script and "|| :" not in script, "backup script suppresses a failure")
    checks.require(schedule.strip() == "17 2 * * * TZ=UTC ./backup-fixed.sh", "schedule must run at 02:17 UTC")


def check_tls_chain(checks: Checks, workspace: Path) -> None:
    plan = read_json(checks, workspace, "deployment.json")
    rollback = read_text(checks, workspace, "rollback.md")
    if plan is not None:
        safe_value(checks, plan, "deployment.json")
        checks.require(plan.get("incident_id") == "INC-405", "deployment.json has the wrong incident_id")
        checks.require(plan.get("chain") == ["./certs/edge-leaf.pem", "./certs/edge-intermediate.pem"], "certificate chain must be leaf then issuing intermediate")
        checks.require(plan.get("private_key") == "./secrets/edge.key", "deployment uses the wrong private key path")
        checks.require(plan.get("bundle_path") == "./runtime/tls/edge-chain.pem", "deployment uses the wrong task-local bundle path")
        verification = plan.get("verification")
        checks.require(isinstance(verification, dict) and verification.get("hostname") == "api.example.test" and verification.get("leaf_serial") == "LEAF-0731", "deployment verification does not match supplied metadata")
        checks.require(plan.get("certainty") == "evidence_limited", "deployment must preserve evidence-limited certainty")
    safe_text(checks, rollback, "rollback.md")
    checks.require("./runtime/tls/current" in rollback and "./runtime/tls/previous" in rollback, "rollback does not name local current and previous paths")
    checks.require("./bin/verify-chain" in rollback and re.search(r"\brestore\b", rollback, re.IGNORECASE) is not None, "rollback lacks verification and restore semantics")
    checks.require(not OVERCLAIM.search(rollback), "rollback makes an unsupported certainty claim")


def check_disk_pressure(checks: Checks, workspace: Path) -> None:
    triage = read_json(checks, workspace, "triage.json")
    remediation = read_text(checks, workspace, "remediation.md")
    if triage is not None:
        safe_value(checks, triage, "triage.json")
        checks.require(triage.get("incident_id") == "INC-406", "triage.json has the wrong incident_id")
        checks.require(triage.get("primary_cause") == "combined_capacity_pressure", "triage does not correlate the three capacity signals")
        constraints = triage.get("constraints")
        checks.require(isinstance(constraints, dict) and constraints.get("blocks_percent") == 95 and constraints.get("inodes_percent") == 97 and constraints.get("deleted_open_bytes") == 3221225472, "triage does not preserve the supplied capacity evidence")
        checks.require(triage.get("reclaim_scope") == ["./data/cache", "./data/tmp"], "triage reclamation scope is not bounded")
        checks.require(triage.get("protected_paths") == ["./data/current"], "triage does not protect current data")
        checks.require(triage.get("certainty") == "evidence_limited", "triage must preserve evidence-limited certainty")
    safe_text(checks, remediation, "remediation.md")
    for token, message in (("./data/cache", "remediation lacks cache scope"), ("./data/tmp", "remediation lacks temporary-data scope"), ("./data/current", "remediation does not protect current data"), ("verify", "remediation lacks verification"), ("rollback", "remediation lacks rollback")):
        checks.require(token.lower() in remediation.lower(), message)
    checks.require(not OVERCLAIM.search(remediation), "remediation makes an unsupported certainty claim")


def check_oom_cgroup(checks: Checks, workspace: Path) -> None:
    text = read_text(checks, workspace, "service-fixed.unit")
    safe_text(checks, text, "service-fixed.unit")
    values = unit_values(checks, text, "service-fixed.unit")
    checks.require(contains_values(values, "Service.MemoryHigh", ["768M"]), "MemoryHigh must be 768M")
    checks.require(contains_values(values, "Service.MemoryMax", ["1024M"]), "MemoryMax must be 1024M")
    checks.require(contains_values(values, "Service.MemorySwapMax", ["0"]), "MemorySwapMax must disable swap")
    checks.require(contains_values(values, "Service.Restart", ["on-failure"]) and contains_values(values, "Service.RestartSec", ["10"]), "restart backoff is missing")
    checks.require(contains_values(values, "Service.ExecStart", ["./bin/worker", "./config/worker.toml"]), "unit start command is not task-local")
    checks.require(contains_values(values, "Service.ExecStartPost", ["./bin/check-ready", "./runtime/worker-ready.json"]), "unit readiness check is not task-local")
    diagnosis(checks, workspace, "INC-407", {"cgroup_memory_limit_exceeded"}, {"EV-407-oom-kill", "EV-407-memory-current", "EV-407-restart"}, 4)


def check_proxy_health(checks: Checks, workspace: Path) -> None:
    text = read_text(checks, workspace, "proxy-fixed.conf")
    safe_text(checks, text, "proxy-fixed.conf")
    conf_syntax(checks, text, "proxy-fixed.conf")
    for pattern, message in (
        (r"(?m)^\s*server\s+ledger-a:9100\s+max_fails=2\s+fail_timeout=10s;", "missing ledger-a health member"),
        (r"(?m)^\s*server\s+ledger-b:9100\s+max_fails=2\s+fail_timeout=10s;", "missing ledger-b health member"),
        (r"(?m)^\s*health_check\s+interval=5s\s+fails=2\s+passes=1;", "missing bounded health policy"),
        (r"(?m)^\s*proxy_connect_timeout\s+2s;", "missing connect timeout"),
        (r"(?m)^\s*proxy_read_timeout\s+20s;", "missing read timeout"),
        (r"(?m)^\s*proxy_set_header\s+X-Request-ID\s+\$request_id;", "missing request-id forwarding"),
        (r"(?m)^\s*proxy_set_header\s+X-Forwarded-Proto\s+\$scheme;", "missing protocol forwarding"),
        (r"(?m)^\s*proxy_next_upstream\s+error\s+timeout\s+http_502\s+http_503;", "missing retry semantics"),
    ):
        checks.require(bool(re.search(pattern, text)), message)
    diagnosis(checks, workspace, "INC-408", {"health_check_and_timeout_misconfiguration"}, {"EV-408-stale-member", "EV-408-connect-timeout", "EV-408-missing-request-id"}, 4)


def check_db_pool(checks: Checks, workspace: Path) -> None:
    tuning = read_json(checks, workspace, "tuning.json")
    rollback = read_text(checks, workspace, "rollback.md")
    if tuning is not None:
        safe_value(checks, tuning, "tuning.json")
        checks.require(tuning.get("incident_id") == "INC-409", "tuning.json has the wrong incident_id")
        pool = tuning.get("pool")
        checks.require(isinstance(pool, dict) and pool.get("max_connections") == 24 and pool.get("min_idle") == 4 and pool.get("acquire_timeout_ms") == 1500 and pool.get("idle_timeout_ms") == 600000, "pool settings do not match the bounded plan")
        database = tuning.get("database")
        checks.require(isinstance(database, dict) and database.get("statement_timeout_ms") == 2000, "statement timeout is missing")
        guardrails = tuning.get("guardrails")
        checks.require(isinstance(guardrails, dict) and guardrails.get("max_pool") == 32 and guardrails.get("observe_minutes") == 15 and isinstance(guardrails.get("success_conditions"), list) and len(guardrails["success_conditions"]) >= 2, "tuning lacks bounded observation guardrails")
        checks.require(tuning.get("certainty") == "evidence_limited", "tuning must preserve evidence-limited certainty")
    safe_text(checks, rollback, "rollback.md")
    checks.require("max_connections: 16" in rollback and "./config/pool.json" in rollback, "rollback lacks the captured pool setting and safe path")
    checks.require("acquire timeout" in rollback.lower() and "rollback" in rollback.lower(), "rollback lacks an observable trigger")
    checks.require(not OVERCLAIM.search(rollback), "rollback makes an unsupported certainty claim")


def check_release_rollback(checks: Checks, workspace: Path) -> None:
    script = read_text(checks, workspace, "rollback.sh")
    plan = read_json(checks, workspace, "rollback-plan.json")
    safe_text(checks, script, "rollback.sh")
    checks.require(bool(re.search(r"(?m)^set\s+-[A-Za-z]*e[A-Za-z]*u", script)), "rollback script does not propagate failures")
    checks.require("./releases/" in script and "*\"..\"*" in script, "rollback script does not reject unsafe release paths")
    checks.require(".release-ok" in script and "test -d" in script, "rollback script lacks release prechecks")
    checks.require("readlink" in script and "./runtime/current" in script, "rollback script does not capture current target")
    checks.require("ln -s" in script and "./runtime/current.next" in script and "mv -f" in script, "rollback script lacks atomic symlink replacement")
    checks.require("./bin/verify-release" in script and "./runtime/current.restore" in script, "rollback script lacks verification rollback")
    checks.require("./runtime/rollback-audit.json.tmp" in script and "./runtime/rollback-audit.json" in script, "rollback script lacks atomic local audit output")
    if plan is not None:
        safe_value(checks, plan, "rollback-plan.json")
        checks.require(plan.get("incident_id") == "INC-410", "rollback plan has the wrong incident_id")
        checks.require(plan.get("target_release") == "./releases/2026.08.11.2", "rollback plan targets the wrong release")
        checks.require(plan.get("expected_current") == "./releases/2026.08.12.1", "rollback plan does not preserve expected current release")
        checks.require(plan.get("audit_path") == "./runtime/rollback-audit.json", "rollback plan audit path is unsafe or missing")
        prechecks = plan.get("prechecks")
        checks.require(isinstance(prechecks, list) and {"target_directory", "release_marker", "current_target"}.issubset(set(prechecks)), "rollback plan lacks required prechecks")
        checks.require(plan.get("certainty") == "evidence_limited", "rollback plan must preserve evidence-limited certainty")


TASKS = {
    "ops-nginx-upstream": check_nginx_upstream,
    "ops-systemd-restart": check_systemd_restart,
    "ops-logrotate-policy": check_logrotate_policy,
    "ops-backup-schedule": check_backup_schedule,
    "ops-tls-chain": check_tls_chain,
    "ops-disk-pressure": check_disk_pressure,
    "ops-oom-cgroup": check_oom_cgroup,
    "ops-proxy-health": check_proxy_health,
    "ops-db-pool": check_db_pool,
    "ops-release-rollback": check_release_rollback,
}


def main(argv: list[str]) -> int:
    checks = Checks()
    if len(argv) != 3:
        checks.require(False, "usage: r3_ops.py WORKSPACE TASK_ID")
        return checks.emit()
    workspace = Path(argv[1]).resolve()
    task_id = argv[2]
    checks.require(workspace.is_dir(), "workspace must be a directory")
    checks.require(task_id in TASKS, f"unknown task_id: {task_id}")
    if workspace.is_dir() and task_id in TASKS:
        try:
            TASKS[task_id](checks, workspace)
        except Exception as exc:  # The protocol remains valid for malformed candidate artifacts.
            checks.require(False, f"grader setup: {type(exc).__name__}: {exc}")
    return checks.emit()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
