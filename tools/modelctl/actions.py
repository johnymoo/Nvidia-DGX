"""Controlled actions: start / stop / restart / switch.

Rules enforced here (issue #26):
- host-level lock: one mutating action at a time (flock on the state dir)
- preflight conflicts before any mutation; --allow-protected gates protected
- DeepSeek-style external controllers run their own worker-first/head-second
  choreography; modelctl delegates and never edits their compose files
- compose models are driven per host in start_order (stop: reverse)
- every action writes a JSON receipt under <state_dir>/receipts/
"""

from __future__ import annotations

import datetime as _dt
import fcntl
import json
import os
import time
from dataclasses import dataclass, field

from tools.modelctl import conflicts as conflicts_mod
from tools.modelctl import discovery
from tools.modelctl.schema import Model, Registry
from tools.modelctl.state import FleetSnapshot, STATE_STOPPED, build_snapshot

ACTION_START = "start"
ACTION_STOP = "stop"
ACTION_RESTART = "restart"
ACTION_SWITCH = "switch"


class ActionError(Exception):
    def __init__(self, code: str, message: str, details: list | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or []


@dataclass
class Step:
    seq: int
    host: str | None
    description: str
    argv: list[str]
    exit_code: int
    stdout_tail: str = ""
    stderr_tail: str = ""
    seconds: float = 0.0

    def to_json(self) -> dict:
        return {
            "seq": self.seq,
            "host": self.host,
            "description": self.description,
            "argv": self.argv,
            "exit_code": self.exit_code,
            "stdout_tail": self.stdout_tail[-400:],
            "stderr_tail": self.stderr_tail[-400:],
            "seconds": round(self.seconds, 2),
        }


@dataclass
class Receipt:
    schema_version: int = 1
    action: str = ""
    model: str = ""
    started_at: str = ""
    ended_at: str = ""
    exit_code: int = 0
    error: str | None = None
    stopping: list[str] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "action": self.action,
            "model": self.model,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "exit_code": self.exit_code,
            "error": self.error,
            "stopping": self.stopping,
            "steps": [s.to_json() for s in self.steps],
        }


class HostLock:
    """Whole-host mutation lock. One modelctl action at a time, cluster-wide
    from the primary host's point of view (remote hosts are reached only by
    the action, never concurrently by another action)."""

    def __init__(self, state_dir: str):
        os.makedirs(state_dir, exist_ok=True)
        self.path = os.path.join(state_dir, "modelctl.lock")
        self._fd = None

    def __enter__(self):
        self._fd = open(self.path, "w")
        deadline = time.monotonic() + 10
        while True:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.monotonic() > deadline:
                    raise ActionError("LOCKED", "another modelctl action is running (lock wait timed out)")
                time.sleep(0.2)

    def __exit__(self, *exc):
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            self._fd.close()
            self._fd = None
        return False


class Actor:
    """Executes actions against a registry using a Runner."""

    def __init__(self, runner, registry: Registry, state_dir: str,
                 snapshot: FleetSnapshot | None = None):
        self.runner = runner
        self.registry = registry
        self.state_dir = state_dir
        self._snapshot = snapshot
        # pre-baked snapshots (tests) stay authoritative; production actors
        # (snapshot=None) always re-discover before mutating
        self._refresh_on_action = snapshot is None

    # ---- plumbing -------------------------------------------------------
    def _host_target(self, host_name: str) -> str | None:
        return self.registry.hosts[host_name].ssh_target

    def _get_snapshot(self, fresh: bool = False) -> FleetSnapshot:
        if self._snapshot is None or (fresh and self._refresh_on_action):
            self._snapshot = build_snapshot(self.runner, self.registry, check_health=False)
        return self._snapshot

    def _run_step(self, receipt: Receipt, host_name: str | None, description: str,
                  argv: list[str], timeout: int | None = None) -> Step:
        target = self._host_target(host_name) if host_name else None
        started = time.monotonic()
        result = self.runner.run(target, argv, timeout=timeout)
        step = Step(
            seq=len(receipt.steps) + 1,
            host=host_name,
            description=description,
            argv=[str(a) for a in argv],
            exit_code=result.exit_code,
            stdout_tail=result.stdout[-400:],
            stderr_tail=result.stderr[-400:],
            seconds=time.monotonic() - started,
        )
        receipt.steps.append(step)
        return step

    def _save_receipt(self, receipt: Receipt) -> str:
        receipts_dir = os.path.join(self.state_dir, "receipts")
        os.makedirs(receipts_dir, exist_ok=True)
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        path = os.path.join(receipts_dir, f"{stamp}-{receipt.action}-{receipt.model}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(receipt.to_json(), handle, indent=2, ensure_ascii=False)
        return path

    # ---- controller adapters -------------------------------------------
    def _controller_start_argv(self, model: Model) -> tuple[str | None, list[str], str]:
        if model.controller.type == "script":
            return model.controller.host, list(model.controller.start), \
                f"controller start ({os.path.basename(model.controller.start[0])})"
        # compose adapter: per host in start_order
        raise _ComposeStepNeeded()

    def start(self, model_name: str, stop_conflicts: bool = False,
              allow_protected: bool = False, wait: bool = True,
              lock: bool = True) -> dict:
        model = self.registry.model(model_name)
        if not model.managed:
            raise ActionError("UNMANAGED", f"model '{model_name}' is visibility-only; manage it with its own tooling")

        receipt = Receipt(action=ACTION_START, model=model.name,
                          started_at=_now(), stopping=[])
        try:
            with HostLock(self.state_dir) if lock else _NoLock():
                snapshot = self._get_snapshot(fresh=True)
                existing = conflicts_mod.check_start(
                    self.registry, snapshot, model, allow_protected=allow_protected)
                if existing:
                    if not stop_conflicts:
                        raise ActionError("CONFLICT", "preflight found conflicts; nothing was changed",
                                          details=[c.to_json() for c in existing])
                    receipt.stopping = _plan_stops(self.registry, snapshot, model,
                                                   allow_protected=allow_protected)
                    for victim_name in receipt.stopping:
                        victim = self.registry.model(victim_name)
                        if victim.protected and not allow_protected:
                            raise ActionError("CONFIRMATION_REQUIRED",
                                              f"conflict resolution requires stopping protected model '{victim_name}'",
                                              details=[c.to_json() for c in existing])
                        self._stop_model(victim, receipt, wait=False)

                self._start_model(model, receipt)
                receipt.exit_code = 0
        except ActionError:
            receipt.exit_code = 1
            receipt.ended_at = _now()
            self._save_receipt(receipt)
            raise
        except Exception as exc:  # controller crash mid-action
            receipt.exit_code = 1
            receipt.error = f"{type(exc).__name__}: {exc}"
            receipt.ended_at = _now()
            self._save_receipt(receipt)
            raise ActionError("CONTROLLER_FAILED", str(exc)) from exc

        if wait:
            self._wait_health(model, receipt)
        receipt.ended_at = _now()
        path = self._save_receipt(receipt)
        return {"receipt": receipt.to_json(), "receipt_path": path}

    def stop(self, model_name: str, allow_protected: bool = False, lock: bool = True) -> dict:
        model = self.registry.model(model_name)
        if not model.managed:
            raise ActionError("UNMANAGED", f"model '{model_name}' is visibility-only; manage it with its own tooling")
        if model.protected and not allow_protected:
            raise ActionError("CONFIRMATION_REQUIRED",
                              f"model '{model_name}' is protected; pass --allow-protected to stop it")

        receipt = Receipt(action=ACTION_STOP, model=model.name, started_at=_now())
        try:
            with HostLock(self.state_dir) if lock else _NoLock():
                self._stop_model(model, receipt, wait=True)
                receipt.exit_code = 0
        except ActionError:
            receipt.exit_code = 1
            receipt.ended_at = _now()
            self._save_receipt(receipt)
            raise
        receipt.ended_at = _now()
        path = self._save_receipt(receipt)
        return {"receipt": receipt.to_json(), "receipt_path": path}

    def restart(self, model_name: str, allow_protected: bool = False, lock: bool = True) -> dict:
        stopped = self.stop(model_name, allow_protected=allow_protected, lock=lock)
        started = self.start(model_name, allow_protected=allow_protected, lock=False)
        return {"stop": stopped, "start": started}

    def switch(self, to_model_name: str, allow_protected: bool = False,
               wait: bool = True, lock: bool = True) -> dict:
        """Bring `to_model` online: stop whatever conflicts, then start it."""
        to_model = self.registry.model(to_model_name)
        if not to_model.managed:
            raise ActionError("UNMANAGED", f"model '{to_model_name}' is visibility-only")
        receipt = Receipt(action=ACTION_SWITCH, model=to_model.name, started_at=_now())
        try:
            with HostLock(self.state_dir) if lock else _NoLock():
                snapshot = self._get_snapshot(fresh=True)
                victims = _plan_stops(self.registry, snapshot, to_model,
                                      allow_protected=allow_protected)
                receipt.stopping = victims
                for victim_name in victims:
                    victim = self.registry.model(victim_name)
                    if victim.protected and not allow_protected:
                        raise ActionError("CONFIRMATION_REQUIRED",
                                          f"switch requires stopping protected model '{victim_name}'; "
                                          "pass --allow-protected to proceed")
                    self._stop_model(victim, receipt, wait=True)
                self._start_model(to_model, receipt)
        except ActionError:
            receipt.exit_code = 1
            receipt.ended_at = _now()
            self._save_receipt(receipt)
            raise
        if wait:
            try:
                self._wait_health(to_model, receipt)
            except ActionError:
                receipt.exit_code = 1
                receipt.ended_at = _now()
                self._save_receipt(receipt)
                raise
        receipt.exit_code = 0
        receipt.ended_at = _now()
        path = self._save_receipt(receipt)
        return {"receipt": receipt.to_json(), "receipt_path": path}

    # ---- model drivers ---------------------------------------------------
    def _start_model(self, model: Model, receipt: Receipt) -> None:
        if model.controller.type == "script":
            self._run_step(receipt, model.controller.host,
                           f"start via controller script on {model.controller.host}",
                           list(model.controller.start),
                           timeout=max(3600, 600 * len(model.hosts)))
            if receipt.steps and receipt.steps[-1].exit_code != 0:
                raise ActionError("CONTROLLER_FAILED",
                                  f"controller start failed on {model.controller.host}",
                                  details=[receipt.steps[-1].to_json()])
            return
        # compose adapter: worker-first per start_order
        for host_name in model.start_order:
            compose = model.hosts[host_name].compose
            argv = ["docker", "compose"]
            for env_file in compose.env_files:
                argv += ["--env-file", env_file]
            for config_file in compose.config_files:
                argv += ["-f", config_file]
            argv += ["-p", compose.project, "up", "-d"]
            self._run_step(receipt, host_name, f"compose up on {host_name} ({compose.project})", argv,
                           timeout=600)
            if receipt.steps[-1].exit_code != 0:
                raise ActionError("CONTROLLER_FAILED",
                                  f"compose up failed on {host_name}",
                                  details=[receipt.steps[-1].to_json()])

    def _stop_model(self, model: Model, receipt: Receipt, wait: bool = True) -> None:
        if model.controller.type == "script":
            self._run_step(receipt, model.controller.host,
                           f"stop via controller script on {model.controller.host}",
                           list(model.controller.stop),
                           timeout=max(1200, 300 * len(model.hosts)))
            if receipt.steps and receipt.steps[-1].exit_code != 0:
                raise ActionError("CONTROLLER_FAILED",
                                  f"controller stop failed on {model.controller.host}",
                                  details=[receipt.steps[-1].to_json()])
            return
        for host_name in model.stop_order:
            compose = model.hosts[host_name].compose
            argv = ["docker", "compose"]
            for env_file in compose.env_files:
                argv += ["--env-file", env_file]
            for config_file in compose.config_files:
                argv += ["-f", config_file]
            argv += ["-p", compose.project, "down"]
            self._run_step(receipt, host_name, f"compose down on {host_name} ({compose.project})", argv,
                           timeout=300)
            if receipt.steps[-1].exit_code != 0:
                raise ActionError("CONTROLLER_FAILED",
                                  f"compose down failed on {host_name}",
                                  details=[receipt.steps[-1].to_json()])
        if wait:
            self._wait_ports_free(model, receipt)

    # ---- waits ------------------------------------------------------------
    def _wait_health(self, model: Model, receipt: Receipt) -> None:
        if not model.health:
            return
        deadline = time.monotonic() + model.health.wait_timeout_s
        target = self._host_target(model.health.host)
        attempt = 0
        while time.monotonic() < deadline:
            attempt += 1
            if discovery.http_health(self.runner, target, model.health.url, model.health.timeout_s):
                return
            time.sleep(min(15, 2 + attempt))
        raise ActionError(
            "HEALTH_TIMEOUT",
            f"health check did not pass within {model.health.wait_timeout_s}s: {model.health.url} "
            f"(containers may still be warming up; inspect with modelctl status {model.name})",
        )

    def _wait_ports_free(self, model: Model, receipt: Receipt) -> None:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            snapshot = self._get_snapshot(fresh=True)
            host_facts = snapshot.facts
            busy = []
            for declared in model.ports:
                facts = host_facts.get(declared.host)
                if facts and facts.reachable:
                    if any(l.port == declared.port and l.protocol == declared.protocol
                           and (l.binds_wildcard() or declared.binds_wildcard() or l.bind == declared.bind)
                           for l in facts.listeners):
                        busy.append(f"{declared.host}:{declared.port}")
            if not busy:
                return
            time.sleep(2)
        # listeners can linger after down; record but do not fail the stop
        receipt.steps.append(Step(
            seq=len(receipt.steps) + 1, host=None,
            description="ports still held after stop (best-effort wait elapsed)",
            argv=[], exit_code=0,
        ))


class _NoLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _plan_stops(registry: Registry, snapshot: FleetSnapshot, model: Model,
                allow_protected: bool) -> list[str]:
    """Models that must stop before `model` can start, in stop-ready order."""
    found = conflicts_mod.check_start(registry, snapshot, model, allow_protected=allow_protected)
    names: list[str] = []
    for conflict in found:
        if conflict.other_model and conflict.kind in (
            conflicts_mod.CONFLICT_PORT, conflicts_mod.CONFLICT_GROUP,
            conflicts_mod.CONFLICT_EXPLICIT,
        ):
            if conflict.other_model not in names:
                names.append(conflict.other_model)
    # stop order per victim's own stop_order is applied in _stop_model
    return names


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
