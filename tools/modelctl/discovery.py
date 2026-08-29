"""Host fact discovery: compose projects, containers, listening ports.

Read-only by contract. Every parser is fed versioned JSON/line output from
`docker compose ls --all --format json`, `docker ps -a --format '{{json .}}'`
and `ss -ltnH`, and tolerates host-network containers (no Ports field) as
well as unmapped listeners that `docker ps` cannot show.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from tools.modelctl.runner import Runner

COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
COMPOSE_SERVICE_LABEL = "com.docker.compose.service"


@dataclass
class ComposeProject:
    name: str
    status: str  # raw docker compose ls status, e.g. "running(1)" / "exited(2)"
    config_files: tuple[str, ...]
    running: bool
    exit_code: int | None

    @classmethod
    def from_ls_entry(cls, entry: dict) -> "ComposeProject":
        raw_status = str(entry.get("Status", ""))
        match = re.match(r"(running|exited|paused)\(?(\d+)?\)?", raw_status)
        running = bool(match and match.group(1) == "running")
        exit_code = int(match.group(2)) if match and match.group(2) is not None else None
        config_files = tuple(
            f.strip() for f in str(entry.get("ConfigFiles", "")).split(",") if f.strip()
        )
        return cls(name=str(entry.get("Name", "")), status=raw_status,
                   config_files=config_files, running=running, exit_code=exit_code)


@dataclass
class Container:
    id: str
    names: str
    image: str
    state: str  # running / exited / paused / created / restarting
    status: str
    project: str | None = None
    service: str | None = None
    labels: dict = field(default_factory=dict)

    @classmethod
    def from_ps_entry(cls, entry: dict) -> "Container":
        raw_labels = entry.get("Labels") or ""
        if isinstance(raw_labels, str):
            labels = dict(
                part.split("=", 1) for part in raw_labels.split(",") if "=" in part
            )
        else:  # some engines return a mapping
            labels = dict(raw_labels)
        return cls(
            id=str(entry.get("ID", "")),
            names=str(entry.get("Names", "")),
            image=str(entry.get("Image", "")),
            state=str(entry.get("State", "")),
            status=str(entry.get("Status", "")),
            project=labels.get(COMPOSE_PROJECT_LABEL),
            service=labels.get(COMPOSE_SERVICE_LABEL),
            labels=labels,
        )


@dataclass(frozen=True)
class Listener:
    bind: str  # "0.0.0.0", "127.0.0.1", "192.0.2.10" (specific), "::"...
    port: int
    protocol: str = "tcp"

    def binds_wildcard(self) -> bool:
        return self.bind in ("0.0.0.0", "::", "*", "")

    def covers(self, other_bind: str) -> bool:
        """True if this listener accepts connections addressed to other_bind."""
        if self.binds_wildcard():
            return True
        return self.bind == other_bind


def compose_projects(runner: Runner, host_target: str | None) -> list[ComposeProject]:
    result = runner.run(host_target, ["docker", "compose", "ls", "--all", "--format", "json"])
    if not result.ok:
        raise DiscoveryError(f"docker compose ls failed on host {host_target or 'local'}", result)
    return [ComposeProject.from_ls_entry(e) for e in _json_documents(result.stdout)]


def containers(runner: Runner, host_target: str | None) -> list[Container]:
    result = runner.run(host_target, ["docker", "ps", "-a", "--format", "{{json .}}"])
    if not result.ok:
        raise DiscoveryError(f"docker ps failed on host {host_target or 'local'}", result)
    return [Container.from_ps_entry(e) for e in _json_lines(result.stdout)]


_SS_LINE = re.compile(
    r"^(?P<state>\S+)\s+\S+\s+\S+\s+(?P<bind>\S+):(?P<port>\d+)\s+\S+"
)


def listeners(runner: Runner, host_target: str | None) -> list[Listener]:
    """TCP listeners via `ss -ltnH` (works unprivileged; sees host-network ports)."""
    result = runner.run(host_target, ["ss", "-ltnH"])
    if not result.ok:
        raise DiscoveryError(f"ss failed on host {host_target or 'local'}", result)
    found: list[Listener] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        match = _SS_LINE.match(line)
        if not match:
            continue
        bind = match.group("bind")
        if bind.startswith("[") and bind.endswith("]"):  # [::]
            bind = bind[1:-1]
        found.append(Listener(bind=bind, port=int(match.group("port"))))
    return found


def http_health(runner: Runner, host_target: str | None, url: str, timeout_s: int = 5) -> bool:
    """GET a health URL from the given host; returns True on HTTP 2xx."""
    result = runner.run(
        host_target,
        ["curl", "-fsS", "-o", "/dev/null", "-m", str(timeout_s), url],
        timeout=timeout_s + 5,
    )
    return result.ok


class DiscoveryError(Exception):
    def __init__(self, message: str, result=None):
        super().__init__(message)
        self.result = result


def _json_documents(stdout: str) -> list:
    """docker compose ls --format json emits one JSON array (or NDJSON)."""
    stdout = stdout.strip()
    if not stdout:
        return []
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return _json_lines(stdout)
    return parsed if isinstance(parsed, list) else [parsed]


def _json_lines(stdout: str) -> list:
    entries = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries
