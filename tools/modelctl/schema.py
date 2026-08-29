"""models.yaml loading + validation for modelctl.

The registry is declarative and secret-free: any key that looks like a
credential (token/password/secret/api_key) is rejected outright.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from tools.modelctl import SCHEMA_VERSION

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - exercised via HAS_YAML flag
    yaml = None

HAS_YAML = yaml is not None

WILDCARD_BINDS = {"0.0.0.0", "::", "*", ""}
VALID_BINDS = WILDCARD_BINDS | {"127.0.0.1"}
VALID_PROTOCOLS = {"tcp", "udp"}
VALID_ROLES = {"head", "worker", "standalone"}
VALID_CONTROLLER_TYPES = {"compose", "script", "none"}

SECRET_KEY_RE = re.compile(r"(passw|secret|token|api_?key|credential)", re.IGNORECASE)


class RegistryError(Exception):
    """models.yaml is missing, unreadable, or invalid."""

    def __init__(self, message: str, details: list[str] | None = None):
        super().__init__(message)
        self.details = details or []


@dataclass(frozen=True)
class Host:
    name: str
    hostname: str  # `hostname -s` value used to detect "am I this host"
    ssh_target: str | None  # None -> local host
    labels: tuple[str, ...] = ()

    @property
    def is_local_default(self) -> bool:
        return self.ssh_target is None


@dataclass(frozen=True)
class Port:
    host: str
    port: int
    protocol: str = "tcp"
    bind: str = "0.0.0.0"
    purpose: str = ""

    def binds_wildcard(self) -> bool:
        return self.bind in WILDCARD_BINDS


@dataclass(frozen=True)
class Health:
    host: str
    url: str
    timeout_s: int = 5
    wait_timeout_s: int = 60


@dataclass(frozen=True)
class ComposeRef:
    project: str
    config_files: tuple[str, ...]
    env_files: tuple[str, ...] = ()
    workdir: str | None = None


@dataclass(frozen=True)
class Controller:
    type: str  # compose | script | none
    # script controller
    host: str | None = None
    start: tuple[str, ...] = ()
    stop: tuple[str, ...] = ()
    status: tuple[str, ...] = ()
    # compose controller is derived from the per-host ComposeRef entries


@dataclass(frozen=True)
class HostSpec:
    role: str = "standalone"
    compose: ComposeRef | None = None


@dataclass(frozen=True)
class Model:
    name: str
    description: str
    kind: str
    managed: bool
    protected: bool
    hosts: dict[str, HostSpec]
    start_order: tuple[str, ...]
    stop_order: tuple[str, ...]
    ports: tuple[Port, ...]
    health: Health | None
    conflict_groups: tuple[str, ...]
    conflicts_with: tuple[str, ...]
    controller: Controller
    expected_containers: dict[str, int]
    notes: str = ""


@dataclass(frozen=True)
class Registry:
    hosts: dict[str, Host]
    models: dict[str, Model]
    path: str | None = None

    def model(self, name: str) -> Model:
        try:
            return self.models[name]
        except KeyError:
            raise RegistryError(f"unknown model: {name}", details=[f"registered: {', '.join(sorted(self.models))}"])


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def _reject_secrets(node, path: str, errors: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            key_str = str(key)
            if SECRET_KEY_RE.search(key_str):
                errors.append(f"{path}.{key_str}: secret-like keys are forbidden in models.yaml")
            else:
                _reject_secrets(value, f"{path}.{key_str}", errors)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _reject_secrets(value, f"{path}[{index}]", errors)


def load_registry(path: str) -> Registry:
    """Load + validate a models.yaml. Raises RegistryError on any problem."""
    if not HAS_YAML:
        raise RegistryError(
            "PyYAML is required to read models.yaml",
            details=["install with: pip install pyyaml  (or apt install python3-yaml)"],
        )
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except FileNotFoundError:
        raise RegistryError(f"registry file not found: {path}")
    except yaml.YAMLError as exc:
        raise RegistryError(f"registry file is not valid YAML: {path}", details=[str(exc)])

    errors: list[str] = []
    _reject_secrets(raw, "$", errors)
    if errors:
        raise RegistryError("models.yaml must not contain secrets", details=errors)
    if not isinstance(raw, dict):
        raise RegistryError("models.yaml must be a mapping at the top level")

    _require(raw.get("schema_version") == SCHEMA_VERSION, f"schema_version must be {SCHEMA_VERSION}", errors)
    _reject_secrets(raw, "$", errors)

    hosts = _parse_hosts(raw.get("hosts"), errors)
    models = _parse_models(raw.get("models"), hosts, errors)
    if not errors:
        errors.extend(validate_cross_refs(Registry(hosts=hosts, models=models, path=str(path))))
    if errors:
        raise RegistryError(f"models.yaml validation failed with {len(errors)} error(s)", details=errors)
    return Registry(hosts=hosts, models=models, path=path)


def _parse_hosts(node, errors: list[str]) -> dict[str, Host]:
    _require(isinstance(node, dict) and bool(node), "hosts: must be a non-empty mapping", errors)
    if not isinstance(node, dict):
        return {}
    hosts: dict[str, Host] = {}
    for name, spec in node.items():
        spec = spec or {}
        hostname = spec.get("hostname")
        _require(bool(hostname), f"hosts.{name}.hostname: required", errors)
        ssh_target = spec.get("ssh_target")
        _require(ssh_target is None or isinstance(ssh_target, str) and "@" in ssh_target,
                 f"hosts.{name}.ssh_target: must be user@host (or omitted for the local host)", errors)
        labels = tuple(spec.get("labels") or ())
        hosts[name] = Host(name=name, hostname=str(hostname), ssh_target=ssh_target, labels=tuple(labels))
    return hosts


def _parse_compose(model_name: str, host_name: str, node, errors: list[str]) -> ComposeRef | None:
    if node is None:
        return None
    _require(isinstance(node, dict), f"models.{model_name}.hosts.{host_name}.compose: must be a mapping", errors)
    if not isinstance(node, dict):
        return None
    project = node.get("project")
    config_files = node.get("config_files") or []
    _require(bool(project), f"models.{model_name}.hosts.{host_name}.compose.project: required", errors)
    _require(isinstance(config_files, list) and bool(config_files),
             f"models.{model_name}.hosts.{host_name}.compose.config_files: must be a non-empty list", errors)
    env_files = tuple(node.get("env_files") or ())
    return ComposeRef(
        project=str(project),
        config_files=tuple(str(p) for p in config_files),
        env_files=tuple(str(p) for p in env_files),
        workdir=node.get("workdir"),
    )


def _parse_models(node, hosts: dict[str, Host], errors: list[str]) -> dict[str, Model]:
    _require(isinstance(node, dict) and bool(node), "models: must be a non-empty mapping", errors)
    if not isinstance(node, dict):
        return {}
    models: dict[str, Model] = {}
    for name, spec in node.items():
        spec = spec or {}
        _require(isinstance(spec, dict), f"models.{name}: must be a mapping", errors)
        if not isinstance(spec, dict):
            continue
        model_errors_before = len(errors)
        model = _parse_model(name, spec, hosts, models, errors)
        if len(errors) == model_errors_before:
            models[name] = model
    return models


def _parse_model(name, spec, hosts, models, errors):
    for field_name in ("description", "kind"):
        _require(bool(spec.get(field_name)), f"models.{name}.{field_name}: required", errors)
    managed = bool(spec.get("managed", True))
    protected = bool(spec.get("protected", False))

    hosts_spec_raw = spec.get("hosts") or {}
    _require(isinstance(hosts_spec_raw, dict) and bool(hosts_spec_raw),
             f"models.{name}.hosts: must be a non-empty mapping", errors)
    host_specs: dict[str, HostSpec] = {}
    for host_name, host_spec in (hosts_spec_raw or {}).items():
        _require(host_name in hosts, f"models.{name}.hosts.{host_name}: not a registered host", errors)
        host_spec = host_spec or {}
        role = host_spec.get("role", "standalone")
        _require(role in VALID_ROLES, f"models.{name}.hosts.{host_name}.role: must be one of {sorted(VALID_ROLES)}", errors)
        compose = _parse_compose(name, host_name, host_spec.get("compose"), errors)
        host_specs[host_name] = HostSpec(role=role, compose=compose)

    # controller
    controller_raw = spec.get("controller") or {}
    _require(isinstance(controller_raw, dict), f"models.{name}.controller: must be a mapping", errors)
    ctype = controller_raw.get("type", "none")
    _require(ctype in VALID_CONTROLLER_TYPES, f"models.{name}.controller.type: must be one of {sorted(VALID_CONTROLLER_TYPES)}", errors)
    if managed and ctype == "none":
        _require(False, f"models.{name}: managed models need a controller (compose|script); use managed:false for visibility-only", errors)
    if not managed:
        _require(ctype == "none" or not controller_raw,
                 f"models.{name}: unmanaged models must not declare a controller", errors)
    controller_host = controller_raw.get("host")
    if ctype == "script":
        _require(controller_host in hosts, f"models.{name}.controller.host: must be a registered host", errors)
        for action in ("start", "stop", "status"):
            argv = controller_raw.get(action) or []
            _require(isinstance(argv, list) and bool(argv),
                     f"models.{name}.controller.{action}: must be a non-empty argv list", errors)
    if ctype == "compose":
        missing = [h for h, hs in host_specs.items() if hs.compose is None]
        _require(not missing, f"models.{name}: compose controller requires compose config on hosts: {missing}", errors)

    # ordering
    start_order = spec.get("start_order") or list(host_specs.keys())
    stop_order = spec.get("stop_order") or list(reversed(start_order))
    _require(sorted(start_order) == sorted(host_specs),
             f"models.{name}.start_order: must list exactly the model hosts", errors)
    _require(sorted(stop_order) == sorted(host_specs),
             f"models.{name}.stop_order: must list exactly the model hosts", errors)
    roles = {h: hs.role for h, hs in host_specs.items()}
    if "worker" in roles.values() and "head" in roles.values():
        _require(start_order.index(_first(roles, "worker")) < start_order.index(_first(roles, "head")),
                 f"models.{name}.start_order: worker must start before head", errors)
        _require(stop_order.index(_first(roles, "head")) < stop_order.index(_first(roles, "worker")),
                 f"models.{name}.stop_order: head must stop before worker", errors)

    # ports
    ports: list[Port] = []
    for index, port_spec in enumerate(spec.get("ports") or []):
        port_spec = port_spec or {}
        host_name = port_spec.get("host")
        _require(host_name in hosts, f"models.{name}.ports[{index}].host: not a registered host", errors)
        port = port_spec.get("port")
        _require(isinstance(port, int) and 1 <= port <= 65535,
                 f"models.{name}.ports[{index}].port: must be an integer in 1..65535", errors)
        protocol = port_spec.get("protocol", "tcp")
        _require(protocol in VALID_PROTOCOLS, f"models.{name}.ports[{index}].protocol: must be tcp|udp", errors)
        bind = str(port_spec.get("bind", "0.0.0.0"))
        ports.append(Port(host=host_name, port=port, protocol=protocol, bind=bind,
                          purpose=str(port_spec.get("purpose", ""))))

    # health
    health = None
    health_raw = spec.get("health")
    if health_raw:
        health_host = health_raw.get("host")
        _require(health_host in hosts, f"models.{name}.health.host: not a registered host", errors)
        _require(bool(health_raw.get("url")), f"models.{name}.health.url: required", errors)
        health = Health(
            host=health_host,
            url=str(health_raw["url"]),
            timeout_s=int(health_raw.get("timeout_s", 5)),
            wait_timeout_s=int(health_raw.get("wait_timeout_s", 60)),
        )

    expected_raw = spec.get("expected_containers") or {}
    expected: dict[str, int] = {}
    for host_name, count in expected_raw.items():
        _require(host_name in host_specs, f"models.{name}.expected_containers.{host_name}: not a model host", errors)
        _require(isinstance(count, int) and count >= 1,
                 f"models.{name}.expected_containers.{host_name}: must be a positive integer", errors)
        expected[host_name] = count

    groups = tuple(spec.get("conflict_groups") or ())
    conflicts = tuple(spec.get("conflicts_with") or ())

    controller = Controller(
        type=ctype,
        host=controller_host,
        start=tuple(controller_raw.get("start") or ()),
        stop=tuple(controller_raw.get("stop") or ()),
        status=tuple(controller_raw.get("status") or ()),
    )
    return Model(
        name=name,
        description=str(spec.get("description", "")),
        kind=str(spec.get("kind", "service")),
        managed=managed,
        protected=protected,
        hosts=host_specs,
        start_order=tuple(start_order),
        stop_order=tuple(stop_order),
        ports=tuple(ports),
        health=health,
        conflict_groups=groups,
        conflicts_with=conflicts,
        controller=controller,
        expected_containers=expected,
        notes=str(spec.get("notes", "")),
    )


def _first(roles: dict[str, str], role: str) -> str:
    for host_name, host_role in roles.items():
        if host_role == role:
            return host_name
    return ""


def validate_cross_refs(registry: Registry) -> list[str]:
    """Second-pass checks that need the full model set (called by load for CLI)."""
    errors: list[str] = []
    for model in registry.models.values():
        for other in model.conflicts_with:
            if other not in registry.models:
                errors.append(f"models.{model.name}.conflicts_with: unknown model {other}")
        if model.controller.type == "script" and model.controller.host:
            if model.controller.host not in registry.hosts:
                errors.append(f"models.{model.name}.controller.host: unknown host {model.controller.host}")
    return errors
