"""Preflight conflict detection (issue #26 `check`).

Conflicts are evaluated by host + bind address + protocol + port, with
wildcard handling: a listener on 0.0.0.0:P (or [::]:P) collides with any
registration of port P on that host, while a loopback listener only collides
with loopback or wildcard registrations. Exclusivity is expressed two ways:
explicit conflicts_with edges and shared conflict_groups (GPU / unified
memory domains).
"""

from __future__ import annotations

from dataclasses import dataclass

from tools.modelctl import discovery
from tools.modelctl.schema import Model, Port, Registry
from tools.modelctl.state import FleetSnapshot

CONFLICT_PORT = "port"
CONFLICT_GROUP = "group"
CONFLICT_EXPLICIT = "explicit"
CONFLICT_PROTECTED = "protected"


@dataclass
class Conflict:
    kind: str
    message: str
    resolution: str
    other_model: str | None = None
    protected: bool = False

    def to_json(self) -> dict:
        return {
            "kind": self.kind,
            "message": self.message,
            "resolution": self.resolution,
            "other_model": self.other_model,
            "protected": self.protected,
        }


def binds_conflict(bind_a: str, bind_b: str) -> bool:
    """Two socket bindings collide when equal or either side is a wildcard."""
    from tools.modelctl.schema import WILDCARD_BINDS
    if bind_a in WILDCARD_BINDS or bind_b in WILDCARD_BINDS:
        return True
    return bind_a == bind_b


def port_overlaps(port_a: Port, bind_a: str, port_b: int, bind_b: str, protocol_a: str = "tcp",
                  protocol_b: str = "tcp") -> bool:
    return (
        port_a == port_b
        and protocol_a == protocol_b
        and binds_conflict(bind_a, bind_b)
    )


def _model_ports_on_host(model: Model, host_name: str) -> list[Port]:
    return [p for p in model.ports if p.host == host_name]


def check_start(registry: Registry, snapshot: FleetSnapshot, model: Model,
                stopping: set[str] | None = None, allow_protected: bool = False) -> list[Conflict]:
    """Conflicts that would occur if `model` started right now.

    `stopping` lists models the caller intends to stop first (switch mode):
    their listeners, ports and group memberships are exempt.
    """
    stopping = set(stopping or ())
    conflicts: list[Conflict] = []

    # host reachability
    for host_name in model.hosts:
        facts = snapshot.facts.get(host_name)
        if facts is not None and not facts.reachable:
            conflicts.append(Conflict(
                kind="host_unreachable",
                message=f"host {host_name} unreachable: {facts.error}",
                resolution=f"restore SSH access to {host_name} and retry",
            ))

    running_others = [
        snapshot.statuses[name] for name in snapshot.running_models()
        if name != model.name and name not in stopping
    ]

    # 1) declared port vs live listeners (host-network and mapped alike)
    own_ports = {(p.host, p.port, p.protocol) for p in model.ports}
    for declared in model.ports:
        host_facts = snapshot.facts.get(declared.host)
        if host_facts is None or not host_facts.reachable:
            continue
        for listener in host_facts.listeners:
            if listener.port != declared.port or listener.protocol != declared.protocol:
                continue
            if not listener.covers(declared.bind) and not declared.binds_wildcard() and listener.bind != declared.bind:
                continue
            owner = _listener_owner(registry, snapshot, declared.host, listener)
            if owner == model.name:
                continue
            if owner and owner in stopping:
                continue
            if owner:
                other = snapshot.statuses.get(owner)
                conflicts.append(Conflict(
                    kind=CONFLICT_PORT,
                    message=(f"port {declared.port}/{declared.protocol} on {declared.host} "
                             f"listened by model '{owner}' ({listener.bind}) but declared by "
                             f"'{model.name}' ({declared.bind})"),
                    resolution=f"stop '{owner}' first (modelctl stop {owner})",
                    other_model=owner,
                    protected=bool(other and other.protected),
                ))
            else:
                conflicts.append(Conflict(
                    kind=CONFLICT_PORT,
                    message=(f"port {declared.port}/{declared.protocol} on {declared.host} "
                             f"is already bound by an unregistered process ({listener.bind})"),
                    resolution="identify the process (ss -ltnp) or pick a different port",
                ))
            break  # one conflict per declared port is enough

    # 2) declared port vs declared ports of models that will stay running
    for other in running_others:
        other_model = registry.models[other.model]
        for declared in model.ports:
            for other_port in _model_ports_on_host(other_model, declared.host):
                if port_overlaps(declared, declared.bind, other_port.port, other_port.bind,
                                 declared.protocol, other_port.protocol):
                    conflicts.append(Conflict(
                        kind=CONFLICT_PORT,
                        message=(f"declared port clash between '{model.name}' ({declared.bind}:"
                                 f"{declared.port}) and running '{other.model}' ({other_port.bind}:"
                                 f"{other_port.port}) on {declared.host}"),
                        resolution=f"stop '{other.model}' first (modelctl stop {other.model})",
                        other_model=other.model,
                        protected=other.protected,
                    ))

    # 3) explicit edges
    for other_name in model.conflicts_with:
        if other_name in stopping or other_name == model.name:
            continue
        if snapshot.model_running(other_name):
            other = snapshot.statuses[other_name]
            conflicts.append(Conflict(
                kind=CONFLICT_EXPLICIT,
                message=f"'{model.name}' is mutually exclusive with running '{other_name}'",
                resolution=f"stop '{other_name}' first (modelctl stop {other_name})",
                other_model=other_name,
                protected=other.protected,
            ))

    # 4) shared resource groups (GPU / unified memory domains)
    if model.conflict_groups:
        for other in running_others:
            other_model = registry.models[other.model]
            shared = sorted(set(model.conflict_groups) & set(other_model.conflict_groups))
            if shared:
                conflicts.append(Conflict(
                    kind=CONFLICT_GROUP,
                    message=(f"'{model.name}' and '{other.model}' share resource group(s) "
                             f"{', '.join(shared)} (GPU / unified memory)"),
                    resolution=f"stop '{other.model}' first (modelctl stop {other.model})",
                    other_model=other.model,
                    protected=other.protected,
                ))

    # 5) protected gate: any conflict whose resolution touches a protected model
    if not allow_protected:
        gated = {
            c.other_model for c in list(conflicts)
            if c.kind != CONFLICT_PROTECTED and c.protected and c.other_model
        }
        for other_name in sorted(gated):
            conflicts.append(Conflict(
                kind=CONFLICT_PROTECTED,
                message=f"resolving this conflict stops protected model '{other_name}'",
                resolution="re-run with --allow-protected (Web UI: typed confirmation)",
                other_model=other_name,
                protected=True,
            ))

    # de-dup by (kind, other_model, message)
    seen: set[tuple] = set()
    unique: list[Conflict] = []
    for conflict in conflicts:
        key = (conflict.kind, conflict.other_model, conflict.message)
        if key not in seen:
            seen.add(key)
            unique.append(conflict)
    return unique


def _listener_owner(registry: Registry, snapshot: FleetSnapshot, host_name: str,
                    listener: discovery.Listener) -> str | None:
    """Attribute a live listener to a RUNNING registered model by declared ports.

    A listener matching a stopped model's declared port belongs to nobody we
    manage right now -> returns None (reported as unregistered)."""
    for name, status in snapshot.statuses.items():
        if status.state not in ("running", "partial", "degraded"):
            continue
        model = registry.models[name]
        for declared in _model_ports_on_host(model, host_name):
            if declared.port == listener.port and declared.protocol == listener.protocol:
                if listener.binds_wildcard() or declared.binds_wildcard() or listener.bind == declared.bind:
                    return name
    return None
