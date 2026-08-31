"""Model state computation over discovered host facts.

State vocabulary (issue #26): running | partial | stopped | degraded, plus
unmanaged visibility-only models and unknown hosts (unreachable).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tools.modelctl import discovery
from tools.modelctl.runner import Runner
from tools.modelctl.schema import Model, Registry

STATE_RUNNING = "running"
STATE_PARTIAL = "partial"
STATE_STOPPED = "stopped"
STATE_DEGRADED = "degraded"
STATE_UNKNOWN = "unknown"  # host unreachable


@dataclass
class HostFacts:
    host: str
    reachable: bool
    error: str | None = None
    projects: list = field(default_factory=list)
    containers: list = field(default_factory=list)
    listeners: list = field(default_factory=list)


@dataclass
class ModelStatus:
    model: str
    state: str
    managed: bool
    protected: bool
    hosts: dict[str, dict] = field(default_factory=dict)
    health: dict | None = None
    description: str = ""
    kind: str = ""

    def to_json(self) -> dict:
        return {
            "model": self.model,
            "state": self.state,
            "managed": self.managed,
            "protected": self.protected,
            "description": self.description,
            "kind": self.kind,
            "hosts": self.hosts,
            "health": self.health,
        }


@dataclass
class FleetSnapshot:
    """Everything read-only commands need, gathered once per invocation."""

    registry: Registry
    facts: dict[str, HostFacts] = field(default_factory=dict)
    statuses: dict[str, ModelStatus] = field(default_factory=dict)

    def running_models(self) -> list[str]:
        return sorted(
            name for name, status in self.statuses.items()
            if status.state in (STATE_RUNNING, STATE_PARTIAL, STATE_DEGRADED)
        )

    def model_running(self, name: str) -> bool:
        status = self.statuses.get(name)
        return bool(status and status.state in (STATE_RUNNING, STATE_PARTIAL, STATE_DEGRADED))


def collect_host_facts(runner: Runner, registry: Registry) -> dict[str, HostFacts]:
    facts: dict[str, HostFacts] = {}
    for host in registry.hosts.values():
        target = host.ssh_target
        try:
            projects = discovery.compose_projects(runner, target)
            containers = discovery.containers(runner, target)
            listeners = discovery.listeners(runner, target)
            facts[host.name] = HostFacts(
                host=host.name, reachable=True, projects=projects,
                containers=containers, listeners=listeners,
            )
        except discovery.DiscoveryError as exc:
            facts[host.name] = HostFacts(host=host.name, reachable=False, error=str(exc))
    return facts


def model_status(model: Model, facts: dict[str, HostFacts], check_health: bool = True,
                 runner: Runner | None = None, registry: Registry | None = None) -> ModelStatus:
    """Compose per-host container facts into a single model state."""
    status = ModelStatus(
        model=model.name,
        state=STATE_STOPPED,
        managed=model.managed,
        protected=model.protected,
        description=model.description,
        kind=model.kind,
    )

    running_hosts: list[str] = []
    unreachable_hosts: list[str] = []
    for host_name, host_spec in model.hosts.items():
        host_facts = facts.get(host_name)
        host_info: dict[str, Any] = {"role": host_spec.role}
        if host_facts is None or not host_facts.reachable:
            unreachable_hosts.append(host_name)
            host_info["reachable"] = False
            host_info["error"] = host_facts.error if (host_facts and host_facts.error) else "host not registered"
            status.hosts[host_name] = host_info
            continue

        host_info["reachable"] = True
        project_name = host_spec.compose.project if host_spec.compose else None
        model_containers = []
        if project_name:
            model_containers = [
                c for c in host_facts.containers
                if (c.project or _project_from_config_files(c, host_facts)) == project_name
            ]
            project = next((p for p in host_facts.projects if p.name == project_name), None)
            host_info["compose_project"] = ({
                "name": project.name,
                "status": project.status,
                "config_files": list(project.config_files),
            } if project else {
                "name": project_name,
                "status": "unregistered",
                "config_files": [],
            })
        running_here = [c for c in model_containers if c.state == "running"]
        expected = model.expected_containers.get(host_name)
        host_info["containers"] = {
            "total": len(model_containers),
            "running": len(running_here),
            "expected": expected,
            "list": [
                {"name": c.names, "state": c.state, "status": c.status, "service": c.service}
                for c in model_containers
            ],
        }
        if running_here:
            running_hosts.append(host_name)
            host_info["state"] = STATE_RUNNING
        elif model_containers:
            host_info["state"] = STATE_STOPPED
        else:
            host_info["state"] = STATE_STOPPED
        status.hosts[host_name] = host_info

    if not running_hosts:
        status.state = STATE_STOPPED
    elif unreachable_hosts or len(running_hosts) < len(
            [h for h, i in status.hosts.items() if i.get("reachable")]):
        status.state = STATE_PARTIAL
    else:
        status.state = STATE_RUNNING

    # expected-container refinement: declared count not met -> degraded/partial
    if status.state == STATE_RUNNING:
        for host_name, info in status.hosts.items():
            containers_info = info.get("containers") or {}
            expected = containers_info.get("expected")
            if expected is not None and containers_info.get("running", 0) not in (0, expected):
                status.state = STATE_DEGRADED
                break

    # health probe (only meaningful when the model looks up)
    if model.health and check_health and status.state == STATE_RUNNING \
            and runner is not None and registry is not None:
        target = registry.hosts[model.health.host].ssh_target
        ok = discovery.http_health(runner, target, model.health.url, model.health.timeout_s)
        status.health = {"url": model.health.url, "ok": ok}
        if not ok:
            status.state = STATE_DEGRADED
    elif model.health:
        status.health = {"url": model.health.url, "ok": None, "checked": False}

    return status


def _project_from_config_files(container, host_facts) -> str | None:
    # Containers created by `docker run` have no compose project label; they are
    # never attributed to a registered model (unmanaged -> reported, not owned).
    return None


def build_snapshot(runner: Runner, registry: Registry, check_health: bool = True) -> FleetSnapshot:
    snapshot = FleetSnapshot(registry=registry)
    snapshot.facts = collect_host_facts(runner, registry)
    for model in registry.models.values():
        snapshot.statuses[model.name] = model_status(
            model, snapshot.facts, check_health=check_health, runner=runner, registry=registry)
    return snapshot
