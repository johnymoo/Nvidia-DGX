"""modelctl command line interface.

Commands
    list                       registry overview with live states
    status  [MODEL]            detailed state (containers, health)
    ports                      live listeners vs registered ports (+unregistered)
    discover                   compose projects across hosts (+unmanaged)
    check   MODEL              preflight conflicts for a would-be start
    validate                   models.yaml schema validation only
    start   MODEL [--stop-conflicts] [--allow-protected] [--no-wait]
    stop    MODEL [--allow-protected]
    restart MODEL [--allow-protected]
    switch  MODEL [--allow-protected] [--no-wait]

Every command supports --json: {"schema_version", "command", "generated_at",
"data"|"error"{code,message,details}}. Exit codes: 0 ok, 2 usage, 3 registry
validation, 4 conflict, 5 confirmation required, 6 host unreachable,
7 controller failure, 8 locked, 9 health timeout.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys

from tools.modelctl import SCHEMA_VERSION, __version__
from tools.modelctl import actions as actions_mod
from tools.modelctl import conflicts as conflicts_mod
from tools.modelctl import discovery
from tools.modelctl.schema import RegistryError, load_registry, validate_cross_refs
from tools.modelctl.state import build_snapshot

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REGISTRY = 3
EXIT_CONFLICT = 4
EXIT_CONFIRM = 5
EXIT_HOST = 6
EXIT_CONTROLLER = 7
EXIT_LOCKED = 8
EXIT_HEALTH = 9

_ERROR_EXITS = {
    "VALIDATION": EXIT_REGISTRY,
    "CONFLICT": EXIT_CONFLICT,
    "CONFIRMATION_REQUIRED": EXIT_CONFIRM,
    "HOST_UNREACHABLE": EXIT_HOST,
    "CONTROLLER_FAILED": EXIT_CONTROLLER,
    "LOCKED": EXIT_LOCKED,
    "HEALTH_TIMEOUT": EXIT_HEALTH,
    "UNMANAGED": EXIT_USAGE,
    "UNKNOWN_MODEL": EXIT_USAGE,
}


def default_state_dir() -> str:
    return os.environ.get("MODELCTL_STATE_DIR", os.path.expanduser("~/modelctl/var"))


def default_config() -> str:
    return os.environ.get("MODELCTL_CONFIG", os.path.expanduser("~/modelctl/models.yaml"))


def _emit(command: str, data=None, error: dict | None = None) -> int:
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "tool": "modelctl",
        "tool_version": __version__,
        "command": command,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if error is not None:
        envelope["error"] = error
        print(json.dumps(envelope, ensure_ascii=False, indent=2))
        return _ERROR_EXITS.get(error.get("code"), 1)
    envelope["data"] = data
    print(json.dumps(envelope, ensure_ascii=False, indent=2))
    return EXIT_OK


def _emit_text(lines: list[str]) -> int:
    for line in lines:
        print(line)
    return EXIT_OK


def _envelope_error(code: str, message: str, details: list | None = None) -> dict:
    return {"code": code, "message": message, "details": details or []}


# ---------------------------------------------------------------- commands
def cmd_list(args, registry) -> int:
    snapshot = build_snapshot(args.runner, registry, check_health=False)
    if args.json:
        return _emit("list", {
            "hosts": [
                {"name": h.name, "hostname": h.hostname, "reachable": snapshot.facts[h.name].reachable,
                 "error": snapshot.facts[h.name].error}
                for h in registry.hosts.values()
            ],
            "models": [snapshot.statuses[name].to_json() for name in sorted(snapshot.statuses)],
        })
    lines = [f"{'MODEL':<22} {'STATE':<10} {'PROT':<5} HOSTS"]
    for name in sorted(snapshot.statuses):
        status = snapshot.statuses[name]
        host_bits = ",".join(
            f"{h}:{i.get('state', '?')}" for h, i in status.hosts.items()
        )
        lines.append(f"{name:<22} {status.state:<10} {'yes' if status.protected else '-':<5} {host_bits}")
    return _emit_text(lines)


def _attach_stats(data, args, registry, snapshot) -> None:
    """Merge docker-stats fields into container lists (opt-in via --stats)."""
    stats_by_host = {}
    for host in registry.hosts.values():
        facts = snapshot.facts.get(host.name)
        if not facts or not facts.reachable:
            continue
        try:
            stats_by_host[host.name] = {
                s["name"]: s for s in discovery.container_stats(args.runner, host.ssh_target)
            }
        except discovery.DiscoveryError:
            stats_by_host[host.name] = {}
    hosts_data = [data] if isinstance(data, dict) else data
    for entry in hosts_data:
        for host_name, host_info in (entry.get("hosts") or {}).items():
            host_stats = stats_by_host.get(host_name) or {}
            for container in (host_info.get("containers") or {}).get("list") or []:
                stats = host_stats.get(container.get("name") or "")
                if stats:
                    container["stats"] = {
                        k: stats[k] for k in
                        ("cpu", "cpu_percent", "mem", "mem_percent",
                         "mem_used_bytes", "mem_limit_bytes", "net_io", "block_io", "pids")
                    }


def cmd_status(args, registry) -> int:
    snapshot = build_snapshot(args.runner, registry, check_health=True)
    want_stats = bool(getattr(args, "stats", False))
    if args.model:
        registry.model(args.model)  # raises RegistryError for unknown names
        data = snapshot.statuses[args.model].to_json()
        if want_stats:
            _attach_stats(data, args, registry, snapshot)
        if args.json:
            return _emit("status", data)
        return _emit_text(
            [f"{data['model']}: {data['state']}" + (" (protected)" if data["protected"] else ""),
             json.dumps(data, ensure_ascii=False, indent=2)])
    data = [snapshot.statuses[name].to_json() for name in sorted(snapshot.statuses)]
    if want_stats:
        _attach_stats(data, args, registry, snapshot)
    if args.json:
        return _emit("status", data)
    return _emit_text([
        f"{s['model']}: {s['state']}" for s in data
    ])


def cmd_ports(args, registry) -> int:
    from tools.modelctl.state import collect_host_facts
    facts = collect_host_facts(args.runner, registry)
    registered = []
    for model_name in registry.models:
        model = registry.models[model_name]
        for port in model.ports:
            host_facts = facts.get(port.host)
            listening = bool(
                host_facts and host_facts.reachable and any(
                    l.port == port.port and l.protocol == port.protocol
                    and (l.binds_wildcard() or port.binds_wildcard() or l.bind == l.bind)
                    for l in host_facts.listeners
                )
            )
            registered.append({
                "model": model_name, "host": port.host, "port": port.port,
                "protocol": port.protocol, "bind": port.bind,
                "purpose": port.purpose, "listening": listening,
                "managed": model.managed,
            })
    unregistered = []
    registered_keys = {(r["host"], r["port"], r["protocol"]) for r in registered}
    for host in registry.hosts.values():
        host_facts = facts.get(host.name)
        if not host_facts or not host_facts.reachable:
            continue
        for listener in host_facts.listeners:
            if (host.name, listener.port, listener.protocol) in registered_keys:
                continue
            unregistered.append({
                "host": host.name, "port": listener.port,
                "protocol": listener.protocol, "bind": listener.bind,
            })
    data = {"registered": registered, "unregistered": sorted(
        unregistered, key=lambda u: (u["host"], u["port"]))}
    if args.json:
        return _emit("ports", data)
    lines = [f"{'MODEL':<22} {'HOST':<8} {'BIND':<16} {'PORT':<6} {'LISTENING'}"]
    for r in registered:
        lines.append(f"{r['model']:<22} {r['host']:<8} {r['bind']:<16} {r['port']:<6} {r['listening']}")
    lines.append("")
    lines.append("unregistered listeners (reported, never managed):")
    for u in data["unregistered"]:
        lines.append(f"  {u['host']:<8} {u['bind']:<16} {u['port']}")
    return _emit_text(lines)


def cmd_discover(args, registry) -> int:
    from tools.modelctl.state import collect_host_facts
    facts = collect_host_facts(args.runner, registry)
    managed_projects = {}
    for model_name, model in registry.models.items():
        for host_name, host_spec in model.hosts.items():
            if host_spec.compose:
                managed_projects.setdefault(host_name, set()).add(host_spec.compose.project)
    hosts_out = []
    for host in registry.hosts.values():
        host_facts = facts.get(host.name)
        entry = {"host": host.name, "reachable": bool(host_facts and host_facts.reachable)}
        if host_facts and host_facts.reachable:
            projects = []
            for project in host_facts.projects:
                projects.append({
                    "name": project.name,
                    "status": project.status,
                    "config_files": list(project.config_files),
                    "managed_by": model_name if project.name in managed_projects.get(host.name, ()) else None,
                })
            entry["projects"] = projects
            entry["unmanaged_projects"] = [
                p["name"] for p in projects if p["managed_by"] is None
            ]
        else:
            entry["error"] = host_facts.error if host_facts else "host not registered"
        hosts_out.append(entry)
    if args.json:
        return _emit("discover", hosts_out)
    lines = []
    for host in hosts_out:
        lines.append(f"[{host['host']}] reachable={host['reachable']}")
        for project in host.get("projects", []):
            tag = f" (managed by {project['managed_by']})" if project["managed_by"] else " (unmanaged)"
            lines.append(f"  {project['name']:<28} {project['status']}{tag}")
    return _emit_text(lines)


def cmd_check(args, registry) -> int:
    model = registry.model(args.model)
    snapshot = build_snapshot(args.runner, registry, check_health=False)
    found = conflicts_mod.check_start(
        registry, snapshot, model, stopping=set(args.exempt or ()),
        allow_protected=args.allow_protected)
    data = {
        "model": model.name,
        "would_conflict": bool(found),
        "conflicts": [c.to_json() for c in found],
    }
    if args.json:
        return _emit("check", data)
    if not found:
        return _emit_text([f"{model.name}: no conflicts"])
    lines = [f"{model.name}: {len(found)} conflict(s)"]
    for c in found:
        lines.append(f"  [{c.kind}] {c.message}")
        lines.append(f"      resolution: {c.resolution}")
    return _emit_text(lines)


def cmd_validate(args, registry) -> int:
    errors = validate_cross_refs(registry)
    if errors:
        raise RegistryError("cross-reference validation failed", details=errors)
    data = {"config": registry.path, "hosts": sorted(registry.hosts),
            "models": sorted(registry.models)}
    if args.json:
        return _emit("validate", data)
    return _emit_text([f"OK: {registry.path} ({len(registry.models)} models, "
                       f"{len(registry.hosts)} hosts)"])


def cmd_start(args, registry) -> int:
    actor = actions_mod.Actor(args.runner, registry, args.state_dir)
    result = actor.start(args.model, stop_conflicts=args.stop_conflicts,
                         allow_protected=args.allow_protected, wait=not args.no_wait)
    return _emit("start", result) if args.json else _emit_text(
        [f"started {args.model}", f"receipt: {result['receipt_path']}"])


def cmd_stop(args, registry) -> int:
    actor = actions_mod.Actor(args.runner, registry, args.state_dir)
    result = actor.stop(args.model, allow_protected=args.allow_protected)
    return _emit("stop", result) if args.json else _emit_text(
        [f"stopped {args.model}", f"receipt: {result['receipt_path']}"])


def cmd_restart(args, registry) -> int:
    actor = actions_mod.Actor(args.runner, registry, args.state_dir)
    result = actor.restart(args.model, allow_protected=args.allow_protected)
    return _emit("restart", result) if args.json else _emit_text(
        [f"restarted {args.model}"])


def cmd_switch(args, registry) -> int:
    actor = actions_mod.Actor(args.runner, registry, args.state_dir)
    result = actor.switch(args.model, allow_protected=args.allow_protected,
                          wait=not args.no_wait)
    if args.json:
        return _emit("switch", result)
    steps = result["receipt"]["steps"]
    lines = [f"switch -> {args.model}: stopped {result['receipt']['stopping'] or 'nothing'}, "
             f"{len(steps)} step(s)"]
    lines.append(f"receipt: {result['receipt_path']}")
    return _emit_text(lines)


# ---------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="modelctl", description="unified model Compose manager")
    parser.add_argument("--config", default=default_config(), help="path to models.yaml")
    parser.add_argument("--state-dir", default=default_state_dir(), help="locks/receipts directory")
    parser.add_argument("--json", action="store_true", help="versioned JSON envelope output")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list").set_defaults(func=cmd_list)
    sub.add_parser("validate").set_defaults(func=cmd_validate)

    p = sub.add_parser("status")
    p.add_argument("model", nargs="?", default=None)
    p.add_argument("--stats", action="store_true",
                   help="attach per-container CPU/memory via docker stats (~2s per host)")
    p.set_defaults(func=cmd_status)

    sub.add_parser("ports").set_defaults(func=cmd_ports)
    sub.add_parser("discover").set_defaults(func=cmd_discover)

    p = sub.add_parser("check")
    p.add_argument("model")
    p.add_argument("--exempt", nargs="*", default=[], help="models the caller will stop first")
    p.add_argument("--allow-protected", action="store_true")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("start")
    p.add_argument("model")
    p.add_argument("--stop-conflicts", action="store_true")
    p.add_argument("--allow-protected", action="store_true")
    p.add_argument("--no-wait", action="store_true", help="do not block on the health check")
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("stop")
    p.add_argument("model")
    p.add_argument("--allow-protected", action="store_true")
    p.set_defaults(func=cmd_stop)

    p = sub.add_parser("restart")
    p.add_argument("model")
    p.add_argument("--allow-protected", action="store_true")
    p.set_defaults(func=cmd_restart)

    p = sub.add_parser("switch")
    p.add_argument("model")
    p.add_argument("--allow-protected", action="store_true")
    p.add_argument("--no-wait", action="store_true")
    p.set_defaults(func=cmd_switch)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        registry = load_registry(args.config)
    except RegistryError as exc:
        if args.json:
            return _emit(args.command, error=_envelope_error("VALIDATION", str(exc), exc.details))
        print(f"error: {exc}", file=sys.stderr)
        for detail in exc.details:
            print(f"  - {detail}", file=sys.stderr)
        return EXIT_REGISTRY

    from tools.modelctl.runner import Runner
    args.runner = Runner()

    try:
        return args.func(args, registry)
    except RegistryError as exc:
        if args.json:
            return _emit(args.command, error=_envelope_error("UNKNOWN_MODEL", str(exc), exc.details))
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except actions_mod.ActionError as exc:
        if args.json:
            return _emit(args.command, error=_envelope_error(exc.code, str(exc), exc.details))
        print(f"error [{exc.code}]: {exc}", file=sys.stderr)
        for detail in exc.details:
            print(f"  - {json.dumps(detail, ensure_ascii=False)}" if isinstance(detail, dict) else f"  - {detail}",
                  file=sys.stderr)
        return _ERROR_EXITS.get(exc.code, 1)


if __name__ == "__main__":
    sys.exit(main())
