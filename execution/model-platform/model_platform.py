#!/usr/bin/env python3
"""Shared registry, discovery, status, and conflict engine for modelctl."""

from __future__ import annotations

import ipaddress
import json
import re
import shlex
import subprocess
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


API_VERSION = "model-platform/v1"
HOST_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
PROTOCOLS = {"tcp", "udp"}
STATES = {"Running", "Partial", "Stopped", "Degraded", "Unmanaged"}
ADAPTER_TYPES = {"controller", "compose", "none"}
STATUS_PROBE_TYPES = {"controller_json"}
SAFE_RELATIVE_RE = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._/+:-]+$")


class PlatformError(RuntimeError):
    pass


class CommandError(PlatformError):
    def __init__(self, host: str, command: str, returncode: int, stderr: str):
        self.host = host
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(
            "command failed on {} ({}): {}".format(host, returncode, stderr.strip())
        )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PlatformError(message)


def load_registry(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise PlatformError(
                "models.yaml must use JSON-compatible YAML unless PyYAML is installed"
            ) from exc
        data = yaml.safe_load(text)
    validate_registry(data, schema_path=path.with_name("models.schema.json"))
    data["_path"] = str(path.resolve())
    return data


def validate_registry(
    data: Any,
    schema_path: Optional[Path] = None,
    use_jsonschema: bool = True,
) -> None:
    _require(isinstance(data, dict), "registry must be an object")
    _require(set(data) <= {"version", "api_version", "hosts", "models"}, "registry has unknown fields")
    if use_jsonschema and schema_path and schema_path.is_file():
        try:
            import jsonschema  # type: ignore
        except ImportError:
            pass
        else:
            try:
                jsonschema.Draft202012Validator(
                    json.loads(schema_path.read_text(encoding="utf-8")),
                    format_checker=jsonschema.FormatChecker(),
                ).validate(data)
            except jsonschema.ValidationError as exc:
                raise PlatformError("registry schema violation: {}".format(exc.message)) from exc
    _require(data.get("version") == 1, "registry version must be 1")
    _require(data.get("api_version") == API_VERSION, "unsupported api_version")
    hosts = data.get("hosts")
    models = data.get("models")
    _require(isinstance(hosts, dict) and hosts, "hosts must be a non-empty object")
    _require(isinstance(models, dict) and models, "models must be a non-empty object")
    for host, config in hosts.items():
        _require(bool(HOST_RE.fullmatch(host)), "invalid host alias: {}".format(host))
        _require(isinstance(config, dict), "host {} must be an object".format(host))
        _require(set(config) <= {"management_ip", "fabric_ip"}, "host {} has unknown fields".format(host))
        _require(isinstance(config.get("management_ip"), str), "host {} needs management_ip".format(host))
        ipaddress.ip_address(config["management_ip"])
        if config.get("fabric_ip"):
            ipaddress.ip_address(config["fabric_ip"])
    for model_id, model in models.items():
        _require(bool(re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", model_id)), "invalid model id: {}".format(model_id))
        _require(isinstance(model, dict), "model {} must be an object".format(model_id))
        _require(
            set(model) <= {
                "display_name", "identity", "deployments", "adapter", "availability",
                "status_probe", "endpoints", "resources", "conflicts", "protected",
            },
            "model {} has unknown fields".format(model_id),
        )
        for key in ("display_name", "deployments", "endpoints", "resources", "adapter"):
            _require(key in model, "model {} missing {}".format(model_id, key))
        deployments = model["deployments"]
        _require(isinstance(deployments, list) and deployments, "model {} needs deployments".format(model_id))
        for deployment in deployments:
            _require(isinstance(deployment, dict), "deployment must be an object")
            _require(set(deployment) <= {"host", "role", "project", "services"}, "deployment has unknown fields")
            _require(deployment.get("host") in hosts, "model {} references unknown host".format(model_id))
            _require(isinstance(deployment.get("project"), str) and deployment["project"], "deployment project is required")
            services = deployment.get("services", [])
            _require(isinstance(services, list), "deployment services must be a list")
        for endpoint in model["endpoints"]:
            validate_endpoint(model_id, endpoint, hosts)
        adapter = model["adapter"]
        _require(isinstance(adapter, dict), "model {} adapter must be an object".format(model_id))
        _require(adapter.get("type") in ADAPTER_TYPES, "invalid adapter for {}".format(model_id))
        if adapter["type"] != "none":
            _require(adapter.get("host") in hosts, "adapter host is invalid for {}".format(model_id))
            _require(isinstance(adapter.get("working_dir"), str) and adapter["working_dir"].startswith("/"), "adapter working_dir must be absolute")
        if adapter["type"] == "controller":
            _require(set(adapter) <= {"type", "host", "working_dir", "commands"}, "controller adapter has unknown fields")
            commands = adapter.get("commands")
            _require(isinstance(commands, dict), "controller commands are required")
            for action in ("check", "start", "status", "stop"):
                validate_steps(commands.get(action), "{} controller {}".format(model_id, action))
        if adapter["type"] == "compose":
            _require(set(adapter) <= {"type", "host", "working_dir", "files", "env_files", "profiles", "services"}, "compose adapter has unknown fields")
            files = adapter.get("files")
            _require(isinstance(files, list) and files, "compose files are required")
            _require(all(isinstance(item, str) and item for item in files), "compose files must be strings")
            for key in ("files", "env_files"):
                for item in adapter.get(key, []):
                    validate_relative_path(item, "{} {}".format(model_id, key))
        availability = model.get("availability", {"mutable": adapter["type"] != "none"})
        _require(isinstance(availability, dict), "availability must be an object")
        _require(set(availability) <= {"mutable", "reason"}, "availability has unknown fields")
        _require(isinstance(availability.get("mutable"), bool), "availability.mutable must be boolean")
        if availability["mutable"]:
            _require(adapter["type"] != "none", "visibility-only adapter cannot be mutable")
        elif adapter["type"] != "none":
            _require(isinstance(availability.get("reason"), str) and availability["reason"], "unavailable adapter needs a reason")
        probe = model.get("status_probe")
        if probe is not None:
            validate_status_probe(model_id, probe, hosts)
        resources = model["resources"]
        _require(isinstance(resources, dict), "resources must be an object")
        _require(set(resources) <= {"exclusive_hosts", "gpu_hosts", "claims"}, "resources has unknown fields")
        for host in resources.get("exclusive_hosts", []):
            _require(host in hosts, "unknown exclusive host {}".format(host))
        conflicts = model.get("conflicts", [])
        _require(isinstance(conflicts, list), "conflicts must be a list")
    for model_id, model in models.items():
        for conflict in model.get("conflicts", []):
            _require(conflict in models, "{} conflicts with unknown model {}".format(model_id, conflict))


def validate_steps(steps: Any, context: str) -> None:
    _require(isinstance(steps, list) and steps, "{} steps are required".format(context))
    for argv in steps:
        _require(isinstance(argv, list) and argv, "{} step must be argv".format(context))
        _require(all(isinstance(arg, str) and arg for arg in argv), "{} argv must contain strings".format(context))
        validate_executable(argv[0], context)


def validate_executable(value: str, context: str) -> None:
    _require(bool(SAFE_RELATIVE_RE.fullmatch(value)), "{} executable must be a safe relative path or command".format(context))


def validate_relative_path(value: str, context: str) -> None:
    _require(isinstance(value, str) and bool(SAFE_RELATIVE_RE.fullmatch(value)), "{} must contain safe relative paths".format(context))


def validate_status_probe(model_id: str, probe: Any, hosts: Dict[str, Any]) -> None:
    _require(isinstance(probe, dict), "{} status_probe must be an object".format(model_id))
    _require(set(probe) <= {"type", "host", "working_dir", "command", "state_field", "running_value", "model_field", "revision_field", "run_id_field", "rank_fields", "verified_hosts"}, "status_probe has unknown fields")
    _require(probe.get("type") in STATUS_PROBE_TYPES, "invalid status_probe type")
    _require(probe.get("host") in hosts, "status_probe host is invalid")
    _require(isinstance(probe.get("working_dir"), str) and probe["working_dir"].startswith("/"), "status_probe working_dir must be absolute")
    command = probe.get("command")
    _require(isinstance(command, list) and command and all(isinstance(item, str) and item for item in command), "status_probe command must be argv")
    validate_executable(command[0], "{} status_probe".format(model_id))
    for key in ("state_field", "model_field", "revision_field", "run_id_field"):
        if key in probe:
            _require(isinstance(probe[key], str) and probe[key], "{} must be a string".format(key))
    _require(isinstance(probe.get("running_value", "running"), (str, bool)), "running_value must be scalar")
    _require(all(isinstance(item, str) and item for item in probe.get("rank_fields", [])), "rank_fields must be strings")
    _require(all(item in hosts for item in probe.get("verified_hosts", [])), "status_probe verified_hosts are invalid")


def validate_endpoint(model_id: str, endpoint: Any, hosts: Dict[str, Any]) -> None:
    _require(isinstance(endpoint, dict), "endpoint must be an object")
    _require(endpoint.get("host") in hosts, "{} endpoint host is invalid".format(model_id))
    _require(endpoint.get("protocol") in PROTOCOLS, "{} endpoint protocol is invalid".format(model_id))
    port = endpoint.get("port")
    _require(isinstance(port, int) and 1 <= port <= 65535, "{} endpoint port is invalid".format(model_id))
    _require(isinstance(endpoint.get("bind"), str) and endpoint["bind"], "{} endpoint bind is required".format(model_id))
    normalize_address(endpoint["bind"])
    health = endpoint.get("health")
    if health:
        parsed = urllib.parse.urlparse(health)
        _require(parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost"}, "health URL must use loopback http(s)")


class Runner:
    def run(self, host: str, command: str, timeout: int = 20) -> str:
        raise NotImplementedError


class SSHRunner(Runner):
    def run(self, host: str, command: str, timeout: int = 20) -> str:
        if not HOST_RE.fullmatch(host):
            raise PlatformError("invalid SSH host alias")
        completed = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, command],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        if completed.returncode:
            raise CommandError(host, command, completed.returncode, completed.stderr)
        return completed.stdout


COMPOSE_COMMAND = "docker compose ls --all --format json"
INSPECT_COMMAND = "ids=$(docker ps -aq); if [ -n \"$ids\" ]; then docker inspect $ids; else printf '[]\\n'; fi"
SOCKET_COMMAND = "ss -H -ltnup"


@dataclass(frozen=True)
class Socket:
    host: str
    protocol: str
    bind: str
    port: int
    process: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "host": self.host,
            "protocol": self.protocol,
            "bind": self.bind,
            "port": self.port,
            "process": self.process,
        }


def normalize_address(address: str) -> Tuple[str, str, bool]:
    value = address.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    if "%" in value:
        value = value.split("%", 1)[0]
    if value in {"*", "0.0.0.0"}:
        return ("ipv4", "0.0.0.0", True)
    if value in {"::", "[::]"}:
        return ("ipv6", "::", True)
    ip = ipaddress.ip_address(value)
    return ("ipv4" if ip.version == 4 else "ipv6", str(ip), False)


def addresses_conflict(left: str, right: str) -> bool:
    left_family, left_value, left_wild = normalize_address(left)
    right_family, right_value, right_wild = normalize_address(right)
    if left_wild or right_wild:
        if left_family == right_family:
            return True
        return left_family == "ipv6" or right_family == "ipv6"
    return left_family == right_family and left_value == right_value


def split_host_port(value: str) -> Tuple[str, int]:
    value = value.strip()
    if value.startswith("["):
        end = value.rfind("]:")
        _require(end >= 0, "invalid socket address: {}".format(value))
        return value[1:end], int(value[end + 2 :])
    host, port = value.rsplit(":", 1)
    return host or "0.0.0.0", int(port)


def parse_sockets(host: str, output: str) -> List[Socket]:
    sockets: List[Socket] = []
    for raw in output.splitlines():
        fields = raw.split(None, 6)
        if len(fields) < 6:
            continue
        protocol = fields[0].lower()
        if protocol not in PROTOCOLS:
            continue
        try:
            bind, port = split_host_port(fields[4])
            normalize_address(bind)
        except (PlatformError, ValueError):
            continue
        sockets.append(Socket(host, protocol, bind, port, fields[6] if len(fields) > 6 else ""))
    return sockets


def parse_compose(output: str) -> List[Dict[str, Any]]:
    if not output.strip():
        return []
    value = json.loads(output)
    if isinstance(value, dict):
        value = [value]
    _require(isinstance(value, list), "docker compose ls returned invalid JSON")
    return value


def parse_inspect(output: str) -> List[Dict[str, Any]]:
    if not output.strip():
        return []
    value = json.loads(output)
    _require(isinstance(value, list), "docker inspect returned invalid JSON")
    return value


def container_record(host: str, item: Dict[str, Any]) -> Dict[str, Any]:
    config = item.get("Config") or {}
    state = item.get("State") or {}
    labels = config.get("Labels") or {}
    compose = {
        "project": labels.get("com.docker.compose.project"),
        "service": labels.get("com.docker.compose.service"),
        "config_files": split_csv(labels.get("com.docker.compose.project.config_files")),
        "working_dir": labels.get("com.docker.compose.project.working_dir"),
    }
    published = []
    ports = (item.get("NetworkSettings") or {}).get("Ports") or {}
    for container_port, bindings in ports.items():
        if not bindings:
            continue
        protocol = container_port.rsplit("/", 1)[-1]
        for binding in bindings:
            try:
                published.append(
                    {
                        "protocol": protocol,
                        "bind": binding.get("HostIp") or "0.0.0.0",
                        "port": int(binding["HostPort"]),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
    name = (item.get("Name") or "").lstrip("/")
    return {
        "host": host,
        "id": item.get("Id"),
        "name": name,
        "image": config.get("Image"),
        "state": state.get("Status", "unknown"),
        "health": (state.get("Health") or {}).get("Status"),
        "compose": compose,
        "published_ports": published,
    }


def split_csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [item for item in value.split(",") if item]


def discover_host(host: str, runner: Runner) -> Dict[str, Any]:
    compose = parse_compose(runner.run(host, COMPOSE_COMMAND))
    containers = [container_record(host, item) for item in parse_inspect(runner.run(host, INSPECT_COMMAND))]
    sockets = parse_sockets(host, runner.run(host, SOCKET_COMMAND))
    return {"host": host, "compose_projects": compose, "containers": containers, "sockets": [item.as_dict() for item in sockets]}


def discover(registry: Dict[str, Any], runner: Runner) -> Dict[str, Any]:
    hosts: Dict[str, Any] = {}
    errors = []
    for host in registry["hosts"]:
        try:
            hosts[host] = discover_host(host, runner)
        except (CommandError, PlatformError, subprocess.TimeoutExpired) as exc:
            hosts[host] = {"host": host, "compose_projects": [], "containers": [], "sockets": []}
            errors.append({"host": host, "reason": str(exc)})
    result = {"api_version": API_VERSION, "kind": "Discovery", "hosts": hosts, "errors": errors}
    result["models"] = model_statuses(registry, result, runner=runner)
    result["unmanaged"] = unmanaged_projects(registry, result)
    return result


def project_for_host(discovery: Dict[str, Any], host: str, project: str) -> Optional[Dict[str, Any]]:
    for item in discovery["hosts"].get(host, {}).get("compose_projects", []):
        if item.get("Name") == project:
            return item
    return None


def containers_for_project(discovery: Dict[str, Any], host: str, project: str) -> List[Dict[str, Any]]:
    return [
        item
        for item in discovery["hosts"].get(host, {}).get("containers", [])
        if item.get("compose", {}).get("project") == project
    ]


def deployment_status(discovery: Dict[str, Any], deployment: Dict[str, Any]) -> Dict[str, Any]:
    host = deployment["host"]
    project = deployment["project"]
    containers = containers_for_project(discovery, host, project)
    expected = set(deployment.get("services", []))
    running = [item for item in containers if item["state"] == "running"]
    running_services = {item.get("compose", {}).get("service") for item in running}
    if expected:
        matched = len(expected & running_services)
        if matched == len(expected):
            state = "Running"
        elif matched:
            state = "Partial"
        else:
            state = "Stopped"
    elif running:
        state = "Running"
    else:
        state = "Stopped"
    project_row = project_for_host(discovery, host, project)
    config_files = []
    if project_row:
        config_files = split_csv(project_row.get("ConfigFiles"))
    if not config_files:
        for container in containers:
            config_files.extend(container.get("compose", {}).get("config_files", []))
    return {
        "host": host,
        "role": deployment.get("role"),
        "project": project,
        "state": state,
        "expected_services": sorted(expected),
        "running_services": sorted(item for item in running_services if item),
        "config_files": sorted(set(config_files)),
        "containers": containers,
    }


def health_status(model: Dict[str, Any], runner: Optional[Runner]) -> List[Dict[str, Any]]:
    results = []
    for endpoint in model.get("endpoints", []):
        health = endpoint.get("health")
        if not health or runner is None:
            continue
        command = "curl -fsS --max-time 3 {}".format(shlex.quote(health))
        try:
            body = runner.run(endpoint["host"], command, timeout=8)
            expected = model.get("identity", {}).get("served_model")
            identity_ok = True
            observed_model = None
            if expected:
                try:
                    values = json.loads(body).get("data", [])
                    observed = [item.get("id") for item in values if isinstance(item, dict)]
                    identity_ok = expected in observed
                    observed_model = expected if identity_ok else (observed[0] if observed else None)
                except (AttributeError, json.JSONDecodeError):
                    identity_ok = False
            results.append({"host": endpoint["host"], "url": health, "healthy": identity_ok, "identity_ok": identity_ok, "observed_model": observed_model})
        except (CommandError, subprocess.TimeoutExpired, PlatformError):
            results.append({"host": endpoint["host"], "url": health, "healthy": False, "identity_ok": False})
    return results


def status_probe(model: Dict[str, Any], runner: Optional[Runner]) -> Optional[Dict[str, Any]]:
    probe = model.get("status_probe")
    if not probe or runner is None:
        return None
    command = "cd {} && {}".format(shlex.quote(probe["working_dir"]), shlex.join(probe["command"]))
    try:
        document = json.loads(runner.run(probe["host"], command, timeout=20))
        _require(isinstance(document, dict), "status probe did not return an object")
        state_value = document.get(probe.get("state_field", "state"))
        running = state_value == probe.get("running_value", "running")
        identity_ok = True
        model_field = probe.get("model_field")
        expected_model = model.get("identity", {}).get("served_model")
        if model_field and expected_model:
            identity_ok = document.get(model_field) == expected_model
        revision_field = probe.get("revision_field")
        expected_revision = model.get("identity", {}).get("revision")
        if revision_field and expected_revision:
            identity_ok = identity_ok and document.get(revision_field) == expected_revision
        rank_fields = probe.get("rank_fields", [])
        ranks_ok = all(document.get(field) is True for field in rank_fields)
        run_id = document.get(probe.get("run_id_field")) if probe.get("run_id_field") else None
        if running and probe.get("run_id_field"):
            identity_ok = identity_ok and isinstance(run_id, str) and bool(run_id)
        verified = running and identity_ok and ranks_ok
        state = "Running" if verified else ("Degraded" if running else "Stopped")
        return {
            "state": state,
            "identity_ok": identity_ok,
            "ranks_ok": ranks_ok,
            "run_id": run_id,
            "verified_hosts": probe.get("verified_hosts", [probe["host"]]) if verified else [],
            "document": document,
        }
    except (CommandError, subprocess.TimeoutExpired, PlatformError, json.JSONDecodeError) as exc:
        return {"state": "Degraded", "identity_ok": False, "ranks_ok": False, "run_id": None, "verified_hosts": [], "error": str(exc)}


def adapter_capability(model: Dict[str, Any], runner: Optional[Runner]) -> Dict[str, Any]:
    availability = model.get("availability", {"mutable": model["adapter"]["type"] != "none"})
    if model["adapter"]["type"] == "none" or not availability["mutable"]:
        return {"available": False, "reason": availability.get("reason", "visibility-only")}
    if runner is None:
        return {"available": True, "reason": "not-probed"}
    adapter = model["adapter"]
    checks = ["test -d {}".format(shlex.quote(adapter["working_dir"]))]
    if adapter["type"] == "controller":
        executables = sorted({steps[0] for action in adapter["commands"].values() for steps in action})
        for executable in executables:
            if "/" in executable:
                checks.append("test -x {}".format(shlex.quote(adapter["working_dir"] + "/" + executable)))
            else:
                checks.append("command -v {} >/dev/null".format(shlex.quote(executable)))
    else:
        checks.append("command -v docker >/dev/null")
        for path in adapter.get("files", []) + adapter.get("env_files", []):
            checks.append("test -r {}".format(shlex.quote(adapter["working_dir"] + "/" + path)))
    try:
        runner.run(adapter["host"], "set -eu; " + "; ".join(checks), timeout=15)
        return {"available": True, "reason": "verified", "host": adapter["host"]}
    except (CommandError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "reason": str(exc), "host": adapter["host"]}


def model_statuses(registry: Dict[str, Any], discovery: Dict[str, Any], runner: Optional[Runner]) -> Dict[str, Any]:
    output: Dict[str, Any] = {}
    unavailable_hosts = {item["host"] for item in discovery.get("errors", [])}
    for model_id, model in registry["models"].items():
        deployments = [deployment_status(discovery, item) for item in model["deployments"]]
        states = [item["state"] for item in deployments]
        if any(item["host"] in unavailable_hosts for item in deployments):
            state = "Degraded"
        elif states and all(value == "Running" for value in states):
            state = "Running"
        elif any(value in {"Running", "Partial"} for value in states):
            state = "Partial"
        else:
            state = "Stopped"
        probe = status_probe(model, runner)
        if probe is not None:
            state = probe["state"]
        elif len(deployments) > 1 and state == "Running":
            state = "Degraded"
        health = health_status(model, runner) if state == "Running" else []
        if health and not all(item["healthy"] for item in health):
            state = "Degraded"
        verified_hosts = set(probe.get("verified_hosts", []) if probe else [])
        verified_hosts.update(item["host"] for item in health if item.get("identity_ok"))
        capability = adapter_capability(model, runner)
        output[model_id] = {
            "id": model_id,
            "display_name": model["display_name"],
            "state": state,
            "protected": bool(model.get("protected")),
            "managed": model["adapter"]["type"] != "none",
            "operable": capability["available"],
            "availability": capability,
            "identity": model.get("identity", {}),
            "deployments": deployments,
            "endpoints": model.get("endpoints", []),
            "health": health,
            "status_probe": probe,
            "verified_hosts": sorted(verified_hosts),
            "resources": model.get("resources", {}),
        }
    return output


def unmanaged_projects(registry: Dict[str, Any], discovery: Dict[str, Any]) -> List[Dict[str, Any]]:
    registered = {
        (deployment["host"], deployment["project"])
        for model in registry["models"].values()
        for deployment in model["deployments"]
    }
    output = []
    for host, host_data in discovery["hosts"].items():
        for project in host_data.get("compose_projects", []):
            name = project.get("Name")
            if (host, name) in registered:
                continue
            containers = containers_for_project(discovery, host, name)
            output.append(
                {
                    "host": host,
                    "project": name,
                    "state": "Unmanaged",
                    "compose_status": project.get("Status"),
                    "config_files": split_csv(project.get("ConfigFiles")),
                    "containers": containers,
                }
            )
    return sorted(output, key=lambda item: (item["host"], item["project"] or ""))


def all_sockets(discovery: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for host_data in discovery["hosts"].values():
        yield from host_data.get("sockets", [])


def endpoint_matches_socket(endpoint: Dict[str, Any], socket: Dict[str, Any]) -> bool:
    return (
        endpoint["host"] == socket["host"]
        and endpoint["protocol"] == socket["protocol"]
        and endpoint["port"] == socket["port"]
        and addresses_conflict(endpoint["bind"], socket["bind"])
    )


def check_model(registry: Dict[str, Any], discovery: Dict[str, Any], model_id: str, runner: Optional[Runner] = None) -> Dict[str, Any]:
    _require(model_id in registry["models"], "unknown model: {}".format(model_id))
    model = registry["models"][model_id]
    statuses = model_statuses(registry, discovery, runner) if runner is not None else (discovery.get("models") or model_statuses(registry, discovery, runner=None))
    discovery["models"] = statuses
    conflicts: List[Dict[str, Any]] = []
    target_running = statuses[model_id]["state"] in {"Running", "Partial", "Degraded"}
    for other_id in model.get("conflicts", []):
        if statuses[other_id]["state"] in {"Running", "Partial", "Degraded"}:
            conflicts.append({"type": "declared_model", "model": other_id})
    target_exclusive = set(model.get("resources", {}).get("exclusive_hosts", []))
    for other_id, other in registry["models"].items():
        if other_id == model_id or statuses[other_id]["state"] not in {"Running", "Partial", "Degraded"}:
            continue
        other_resources = other.get("resources", {})
        other_hosts = set(other_resources.get("exclusive_hosts", []))
        gpu_hosts = set(other_resources.get("gpu_hosts", []))
        overlap = target_exclusive & (other_hosts | gpu_hosts)
        if overlap:
            conflicts.append({"type": "exclusive_host", "model": other_id, "hosts": sorted(overlap)})
    for endpoint in model.get("endpoints", []):
        for socket in all_sockets(discovery):
            if not endpoint_matches_socket(endpoint, socket):
                continue
            owners = []
            for owner_id, owner in registry["models"].items():
                if any(endpoint_matches_socket(item, socket) for item in owner.get("endpoints", [])):
                    if statuses[owner_id]["state"] in {"Running", "Partial", "Degraded"}:
                        owners.append(owner_id)
            target_verified = endpoint["host"] in statuses[model_id].get("verified_hosts", [])
            if model_id in owners and target_running and target_verified:
                continue
            conflicts.append({"type": "port", "endpoint": endpoint, "listener": socket, "owners": owners})
    deduped = []
    seen = set()
    for item in conflicts:
        key = json.dumps(item, sort_keys=True, separators=(",", ":"))
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return {
        "api_version": API_VERSION,
        "kind": "Preflight",
        "model": model_id,
        "allowed": not deduped,
        "state": statuses[model_id]["state"],
        "conflicts": deduped,
    }


def status_document(registry: Dict[str, Any], discovery: Dict[str, Any], runner: Optional[Runner] = None) -> Dict[str, Any]:
    models = model_statuses(registry, discovery, runner)
    discovery["models"] = models
    discovery["unmanaged"] = unmanaged_projects(registry, discovery)
    return {
        "api_version": API_VERSION,
        "kind": "ModelStatusList",
        "models": list(models.values()),
        "unmanaged": discovery["unmanaged"],
        "errors": discovery.get("errors", []),
    }


def ports_document(registry: Dict[str, Any], discovery: Dict[str, Any], host: Optional[str] = None) -> Dict[str, Any]:
    listeners = [item for item in all_sockets(discovery) if host is None or item["host"] == host]
    declared = []
    statuses = discovery.get("models") or model_statuses(registry, discovery, runner=None)
    for model_id, model in registry["models"].items():
        for endpoint in model.get("endpoints", []):
            if host is None or endpoint["host"] == host:
                declared.append({"model": model_id, "model_state": statuses[model_id]["state"], **endpoint})
    return {"api_version": API_VERSION, "kind": "PortList", "listeners": listeners, "declared": declared}
