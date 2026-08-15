#!/usr/bin/env python3
"""Controlled lifecycle operations for registered model adapters."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets
import shlex
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from model_platform import (
    API_VERSION,
    PlatformError,
    Runner,
    SSHRunner,
    check_model,
    discover,
    model_statuses,
)


ACTIONS = {"start", "stop", "restart"}
TOKEN_RE = re.compile(r"^[a-f0-9]{32}$")
LOCK_PATH = "/tmp/model-platform.lock"
COMMAND_TIMEOUT_SECONDS = 1800
MAX_COMMAND_OUTPUT = 16384
SECRET_RE = re.compile(r"(?i)(token|password|secret|api[_-]?key)(\s*[:=]\s*)([^\s,;]+)")


def shell_argv(argv: Sequence[str]) -> str:
    if not argv or not all(isinstance(item, str) and item for item in argv):
        raise PlatformError("adapter argv is invalid")
    return shlex.join(list(argv))


def remote_step(working_dir: str, argv: Sequence[str]) -> str:
    if not working_dir.startswith("/"):
        raise PlatformError("adapter working_dir must be absolute")
    return "cd {} && {}".format(shlex.quote(working_dir), shell_argv(argv))


def compose_base(model: Dict[str, Any]) -> List[str]:
    adapter = model["adapter"]
    project = next(
        deployment["project"]
        for deployment in model["deployments"]
        if deployment["host"] == adapter["host"]
    )
    argv = ["docker", "compose", "-p", project]
    for env_file in adapter.get("env_files", []):
        argv.extend(["--env-file", env_file])
    for compose_file in adapter["files"]:
        argv.extend(["-f", compose_file])
    for profile in adapter.get("profiles", []):
        argv.extend(["--profile", profile])
    return argv


def action_steps(model: Dict[str, Any], action: str) -> List[str]:
    adapter = model["adapter"]
    if adapter["type"] == "none":
        raise PlatformError("model is visibility-only and cannot be operated")
    if adapter["type"] == "controller":
        commands = adapter["commands"]
        if action == "restart" and "restart" not in commands:
            steps = commands["stop"] + commands["start"]
        else:
            if action not in commands:
                raise PlatformError("controller does not support {}".format(action))
            steps = commands[action]
        return [remote_step(adapter["working_dir"], argv) for argv in steps]
    base = compose_base(model)
    services = adapter.get("services", [])
    if action == "start":
        argv = base + ["up", "-d"] + services
    elif action == "stop":
        argv = base + ["stop"] + services
    else:
        argv = base + ["restart"] + services
    return [remote_step(adapter["working_dir"], argv)]


def controller_check_steps(model: Dict[str, Any]) -> List[str]:
    adapter = model["adapter"]
    if adapter["type"] == "controller":
        return [remote_step(adapter["working_dir"], argv) for argv in adapter["commands"]["check"]]
    if adapter["type"] == "compose":
        return [remote_step(adapter["working_dir"], compose_base(model) + ["config", "--quiet"])]
    return []


class HostLocks:
    def __init__(self, runner: Runner, hosts: Sequence[str], token: Optional[str] = None):
        self.runner = runner
        self.hosts = sorted(set(hosts))
        self.token = token or secrets.token_hex(16)
        if not TOKEN_RE.fullmatch(self.token):
            raise PlatformError("invalid lock token")
        self.acquired: List[str] = []

    def __enter__(self):
        try:
            for host in self.hosts:
                command = (
                    "set -eu; umask 077; mkdir {path}; "
                    "printf '%s\\n' {token} > {path}/owner"
                ).format(path=LOCK_PATH, token=shlex.quote(self.token))
                self.runner.run(host, command)
                self.acquired.append(host)
        except Exception:
            self.release()
            raise PlatformError("another model operation holds a host lock")
        return self

    def release(self) -> List[Dict[str, str]]:
        errors: List[Dict[str, str]] = []
        for host in reversed(self.acquired):
            command = (
                "set -eu; test \"$(cat {path}/owner)\" = {token}; "
                "rm -f {path}/owner; rmdir {path}"
            ).format(path=LOCK_PATH, token=shlex.quote(self.token))
            try:
                self.runner.run(host, command)
            except Exception as exc:
                errors.append({"host": host, "error": str(exc)})
        self.acquired = []
        return errors

    def __exit__(self, exc_type, exc, traceback):
        errors = self.release()
        if errors and exc is None:
            raise PlatformError("failed to release host locks: {}".format(json.dumps(errors, sort_keys=True)))


def bounded_output(value: str) -> Dict[str, Any]:
    redacted = SECRET_RE.sub(lambda match: match.group(1) + match.group(2) + "[REDACTED]", value or "")
    truncated = len(redacted) > MAX_COMMAND_OUTPUT
    if truncated:
        redacted = redacted[:MAX_COMMAND_OUTPUT]
    return {"text": redacted, "truncated": truncated, "original_chars": len(value or "")}


class LifecycleManager:
    def __init__(
        self,
        registry: Dict[str, Any],
        runner: Optional[Runner] = None,
        receipt_root: Optional[Path] = None,
    ):
        self.registry = registry
        self.runner = runner or SSHRunner()
        self.receipt_root = receipt_root or Path.home() / ".local/state/model-platform/receipts"

    def plan(self, model_id: str, action: str, snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if model_id not in self.registry["models"]:
            raise PlatformError("unknown model: {}".format(model_id))
        if action not in ACTIONS:
            raise PlatformError("unsupported action")
        model = self.registry["models"][model_id]
        if model["adapter"]["type"] == "none":
            raise PlatformError("model is visibility-only and cannot be operated")
        availability = model.get("availability", {"mutable": True})
        if not availability.get("mutable"):
            raise PlatformError("model lifecycle is unavailable: {}".format(availability.get("reason", "not enabled")))
        snapshot = snapshot or discover(self.registry, self.runner)
        observed = snapshot.get("models", {}).get(model_id, {})
        if observed.get("operable") is False:
            raise PlatformError("model lifecycle capability is unavailable: {}".format(observed.get("availability", {}).get("reason", "probe failed")))
        preflight = check_model(self.registry, snapshot, model_id)
        if action in {"start", "restart"} and not preflight["allowed"]:
            raise PlatformError("preflight blocked: {}".format(json.dumps(preflight["conflicts"], sort_keys=True)))
        hosts = self.lock_hosts(model_id)
        return {
            "api_version": API_VERSION,
            "kind": "OperationPlan",
            "model": model_id,
            "action": action,
            "protected": bool(model.get("protected")),
            "confirmation": self.confirmation(model_id, action, bool(model.get("protected"))),
            "hosts": hosts,
            "adapter_host": model["adapter"]["host"],
            "checks": controller_check_steps(model) if action in {"start", "restart"} else [],
            "steps": action_steps(model, action),
            "preflight": preflight,
            "authoritative": False,
        }

    def lock_hosts(self, model_id: str) -> List[str]:
        model = self.registry["models"][model_id]
        related = {model_id, *model.get("conflicts", [])}
        target_claims = set(model.get("resources", {}).get("claims", []))
        target_hosts = set(model.get("resources", {}).get("exclusive_hosts", []))
        for other_id, other in self.registry["models"].items():
            resources = other.get("resources", {})
            if target_claims & set(resources.get("claims", [])) or target_hosts & set(resources.get("exclusive_hosts", []) + resources.get("gpu_hosts", [])):
                related.add(other_id)
        hosts = set()
        for related_id in related:
            item = self.registry["models"][related_id]
            hosts.update(deployment["host"] for deployment in item["deployments"])
            if item["adapter"]["type"] != "none":
                hosts.add(item["adapter"]["host"])
        return sorted(hosts)

    @staticmethod
    def confirmation(model_id: str, action: str, protected: bool) -> str:
        return "PROTECTED {} {}".format(action, model_id) if protected else model_id

    def _validate_confirmation(self, model_id: str, action: str, confirm: str, allow_protected: bool) -> None:
        model = self.registry["models"].get(model_id)
        if not model:
            raise PlatformError("unknown model: {}".format(model_id))
        protected = bool(model.get("protected"))
        if protected and not allow_protected:
            raise PlatformError("protected model operations require --allow-protected")
        expected = self.confirmation(model_id, action, protected)
        if confirm != expected:
            raise PlatformError("confirmation must exactly match: {}".format(expected))

    def execute(
        self,
        model_id: str,
        action: str,
        confirm: str,
        dry_run: bool = False,
        snapshot: Optional[Dict[str, Any]] = None,
        allow_protected: bool = False,
        actor: str = "cli",
    ) -> Dict[str, Any]:
        self._validate_confirmation(model_id, action, confirm, allow_protected)
        plan = self.plan(model_id, action, snapshot=snapshot)
        if dry_run:
            return {**plan, "dry_run": True}
        receipt = self._allocate_receipt(model_id, action, actor)
        self._run_receipt(receipt["id"])
        result = self.receipt(receipt["id"])
        if result["status"] != "passed":
            raise PlatformError("operation failed; receipt={}".format(result["id"]))
        return result

    def submit(
        self,
        model_id: str,
        action: str,
        confirm: str,
        allow_protected: bool = False,
        actor: str = "web:operator",
    ) -> Dict[str, Any]:
        self._validate_confirmation(model_id, action, confirm, allow_protected)
        self.plan(model_id, action)
        receipt = self._allocate_receipt(model_id, action, actor)
        worker = threading.Thread(target=self._run_receipt, args=(receipt["id"],), daemon=True, name="model-platform-{}".format(receipt["id"]))
        worker.start()
        return receipt

    def _allocate_receipt(self, model_id: str, action: str, actor: str) -> Dict[str, Any]:
        started_at = dt.datetime.now(dt.timezone.utc)
        receipt: Dict[str, Any] = {
            "api_version": API_VERSION,
            "kind": "OperationReceipt",
            "id": "{}-{}".format(started_at.strftime("%Y%m%dT%H%M%SZ"), uuid.uuid4().hex),
            "model": model_id,
            "action": action,
            "actor": actor,
            "started_at": started_at.isoformat(),
            "status": "queued",
            "commands": [],
        }
        self._create_receipt(receipt)
        return receipt

    def _run_receipt(self, receipt_id: str) -> None:
        receipt = self.receipt(receipt_id)
        model_id = receipt["model"]
        action = receipt["action"]
        locks = HostLocks(self.runner, self.lock_hosts(model_id))
        lock_errors: List[Dict[str, str]] = []
        try:
            locks.__enter__()
            before = discover(self.registry, self.runner)
            before["models"] = model_statuses(self.registry, before, runner=self.runner)
            receipt["before"] = before
            receipt["restore_candidates"] = sorted(model for model, status in before["models"].items() if status["state"] == "Running")
            plan = self.plan(model_id, action, snapshot=before)
            plan["authoritative"] = True
            receipt["plan"] = plan
            receipt["status"] = "running"
            self._write_receipt(receipt)
            adapter_host = plan["adapter_host"]
            try:
                for command in plan["checks"] + plan["steps"]:
                    try:
                        output = self.runner.run(adapter_host, command, timeout=COMMAND_TIMEOUT_SECONDS)
                        receipt["commands"].append({"host": adapter_host, "command": command, "status": "passed", "output": bounded_output(output)})
                    except Exception as exc:
                        receipt["commands"].append({"host": adapter_host, "command": command, "status": "failed", "error": bounded_output(str(exc))})
                        raise
            finally:
                self._write_receipt(receipt)
            observed = discover(self.registry, self.runner)
            statuses = model_statuses(self.registry, observed, runner=self.runner)
            observed["models"] = statuses
            desired = "Stopped" if action == "stop" else "Running"
            actual = statuses[model_id]["state"]
            receipt["after"] = observed
            receipt["observed"] = statuses[model_id]
            receipt["status"] = "passed" if actual == desired else "failed"
            if receipt["status"] == "failed":
                receipt["error"] = "postcondition mismatch: expected {}, observed {}".format(desired, actual)
        except Exception as exc:
            receipt["status"] = "failed"
            receipt["error"] = str(exc)
        finally:
            lock_errors = locks.release()
        receipt["lock_release"] = {"passed": not lock_errors, "errors": lock_errors}
        if lock_errors:
            receipt["status"] = "degraded"
            receipt["error"] = "host lock release failed: {}".format(json.dumps(lock_errors, sort_keys=True))
        receipt["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        self._write_receipt(receipt)

    def receipt(self, receipt_id: str) -> Dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,200}", receipt_id):
            raise PlatformError("invalid receipt id")
        path = self.receipt_root / (receipt_id + ".json")
        if not path.is_file():
            raise PlatformError("receipt not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def _create_receipt(self, receipt: Dict[str, Any]) -> None:
        self.receipt_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.receipt_root, 0o700)
        path = self.receipt_root / (receipt["id"] + ".json")
        with path.open("x", encoding="utf-8") as handle:
            json.dump(receipt, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(path, 0o600)

    def _write_receipt(self, receipt: Dict[str, Any]) -> None:
        path = self.receipt_root / (receipt["id"] + ".json")
        if not path.is_file():
            raise PlatformError("receipt allocation is missing")
        temporary = self.receipt_root / (".{}.{}.tmp".format(receipt["id"], secrets.token_hex(8)))
        temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(str(temporary), str(path))
