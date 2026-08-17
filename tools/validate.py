from __future__ import annotations

import json
import hashlib
import re
import shutil
import subprocess
import tokenize
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from tools.catalog import CatalogError, discover_recipes, discover_results, generated_outputs, read_json_object


CANONICAL_PATHS = (
    "README.md",
    "lab",
    "catalog",
    "recipes",
    "hardware",
    "benchmarks",
    "results",
    "operations",
    "tools",
    "docs",
    "examples",
    ".github",
)
PRIVACY_RULES = (
    (
        "private IPv4 address",
        re.compile(r"(?<![0-9])(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})(?![0-9])"),
    ),
    ("user home path", re.compile(r"/(?:home|Users)/(?!YOUR_USERNAME(?:/|\b)|user(?:/|\b)|example(?:/|\b))[^\s/]+/")),
    ("private host alias", re.compile(r"(?i)(?:\bssh\s+gb10(?:-2)?\b|\bHost\s+gb10(?:-2)?\b|\bdgx-[a-z0-9-]*private\b)")),
    ("private key material", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    (
        "literal credential",
        re.compile(
            r"(?i)(?:api[_-]?key|auth[_-]?token|access[_-]?token|password|secret)"
            r"\s*[=:]\s*['\"](?!dummy|example|placeholder|test-key|<)[^'\"]{8,}['\"]"
        ),
    ),
)
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
HTML_LINK_RE = re.compile(r"(?i)\b(?:href|src)\s*=\s*['\"]([^'\"]+)['\"]")


@dataclass(frozen=True)
class Finding:
    check: str
    path: str
    line: int
    message: str

    def format(self) -> str:
        location = f"{self.path}:{self.line}" if self.line else self.path
        return f"{self.check}: {location}: {self.message}"


def canonical_files(root: Path) -> list[Path]:
    if (root / ".git").exists():
        completed = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *CANONICAL_PATHS],
            cwd=root, capture_output=True, check=False
        )
        if completed.returncode == 0:
            return sorted(
                root / item.decode("utf-8")
                for item in completed.stdout.split(b"\0")
                if item and (root / item.decode("utf-8")).is_file()
            )
    files: set[Path] = set()
    for name in CANONICAL_PATHS:
        path = root / name
        if path.is_file():
            files.add(path)
        elif path.is_dir():
            for candidate in path.rglob("*"):
                if candidate.is_file() and ".git" not in candidate.parts:
                    files.add(candidate)
    return sorted(files)


def text_files(root: Path, paths: list[Path] | None = None) -> list[Path]:
    candidates = canonical_files(root) if paths is None else paths
    output = []
    for path in candidates:
        try:
            content = path.read_bytes()
            if b"\x00" in content:
                continue
            content.decode("utf-8")
        except (OSError, UnicodeError):
            continue
        output.append(path)
    return output


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def privacy_findings(root: Path, paths: list[Path] | None = None) -> list[Finding]:
    findings = []
    for path in text_files(root, paths):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        for number, line in enumerate(lines, 1):
            for name, pattern in PRIVACY_RULES:
                if pattern.search(line):
                    findings.append(Finding("privacy", _relative(root, path), number, name))
    return findings


def link_findings(root: Path, paths: list[Path] | None = None) -> list[Finding]:
    findings = []
    markdown = [
        path for path in (canonical_files(root) if paths is None else paths)
        if path.suffix.lower() in {".md", ".html", ".htm"}
    ]
    for path in markdown:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        for number, line in enumerate(lines, 1):
            patterns = [LINK_RE]
            if path.suffix.lower() in {".html", ".htm"}:
                patterns.append(HTML_LINK_RE)
            for match in (match for pattern in patterns for match in pattern.finditer(line)):
                target = match.group(1).strip().split(maxsplit=1)[0].strip("<>")
                if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                    continue
                clean = unquote(target.split("#", 1)[0].split("?", 1)[0])
                if not clean:
                    continue
                resolved = (root / clean.lstrip("/")) if clean.startswith("/") else (path.parent / clean)
                try:
                    resolved.resolve().relative_to(root.resolve())
                except ValueError:
                    findings.append(
                        Finding("links", _relative(root, path), number, f"local target escapes repository {target!r}")
                    )
                    continue
                if not resolved.exists():
                    findings.append(
                        Finding("links", _relative(root, path), number, f"missing local target {target!r}")
                    )
    return findings


def binary_findings(root: Path, paths: list[Path] | None = None) -> list[Finding]:
    findings = []
    candidates = canonical_files(root) if paths is None else paths
    text = set(text_files(root, candidates))
    binaries = [path for path in candidates if path not in text]
    policy_path = root / "catalog" / "publication-binaries.json"
    try:
        policy = read_json_object(policy_path, "publication binary policy")
    except CatalogError as exc:
        return [Finding("binary", "catalog/publication-binaries.json", 0, str(exc))]
    exact = {item.get("path"): item for item in policy.get("exact", []) if isinstance(item, dict)}
    prefixes = [item for item in policy.get("prefixes", []) if isinstance(item, dict)]
    for path in binaries:
        relative = _relative(root, path)
        item = exact.get(relative)
        if item:
            if not item.get("reason") or _sha256(path) != item.get("sha256"):
                findings.append(Finding("binary", relative, 0, "allowlisted binary reason or SHA-256 mismatch"))
            if path.suffix.lower() == ".pdf":
                raw_text = path.read_bytes().decode("latin-1", errors="ignore")
                for name, pattern in PRIVACY_RULES:
                    if pattern.search(raw_text):
                        findings.append(Finding("binary", relative, 0, f"PDF {name}"))
                for command in (["pdftotext", str(path), "-"], ["pdfinfo", str(path)]):
                    if shutil.which(command[0]) is None:
                        continue
                    try:
                        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        findings.append(Finding("binary", relative, 0, f"PDF inspection failed: {exc}"))
                        continue
                    if completed.returncode:
                        findings.append(Finding("binary", relative, 0, f"PDF inspection failed: {command[0]}"))
                        continue
                    for name, pattern in PRIVACY_RULES:
                        if pattern.search(completed.stdout):
                            findings.append(Finding("binary", relative, 0, f"PDF {name}"))
            continue
        prefix = next((entry for entry in prefixes if relative.startswith(str(entry.get("path", "")))), None)
        if prefix:
            manifest = root / str(prefix.get("manifest", ""))
            try:
                manifest_value = read_json_object(manifest, "binary prefix manifest")
            except CatalogError as exc:
                findings.append(Finding("binary", relative, 0, str(exc)))
                continue
            digest = manifest_value.get(prefix.get("manifest_field"))
            if not prefix.get("reason") or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                findings.append(Finding("binary", relative, 0, "binary prefix manifest is incomplete"))
            continue
        findings.append(Finding("binary", relative, 0, "tracked binary is not publication-allowlisted"))
    for relative, item in exact.items():
        path = root / relative
        if not path.is_file():
            findings.append(Finding("binary", relative, 0, "allowlisted binary is missing"))
    return findings


def _receipt_errors(path: Path, recipe: dict) -> list[str]:
    try:
        value = read_json_object(path, "deployment receipt")
    except CatalogError as exc:
        return [str(exc)]
    required = {"schema_version", "status", "recipe_id", "subject", "acceptance", "collected_at"}
    errors = [f"missing receipt field {name}" for name in sorted(required - set(value))]
    expected = {
        "model": recipe.get("model_id"),
        "hardware": recipe.get("hardware_id"),
        "runtime": recipe.get("runtime_id"),
        "profile": recipe.get("profile_id"),
    }
    if value.get("status") != "passed":
        errors.append("Verified receipt status must be passed")
    if value.get("recipe_id") != recipe.get("id") or value.get("subject") != expected:
        errors.append("Verified receipt identity does not match recipe")
    return errors


def metadata_findings(root: Path) -> list[Finding]:
    try:
        records = discover_recipes(root)
        results = discover_results(root)
    except CatalogError as exc:
        return [Finding("metadata", "recipes", 0, line) for line in str(exc).splitlines()]
    findings = []
    defaults: set[tuple[str, str, str]] = set()
    for record in records:
        relative = _relative(root, record.path)
        recipe = record.data
        directory = record.path.parent
        for required_name in ("README.md", "run.sh"):
            if not (directory / required_name).is_file():
                findings.append(Finding("metadata", relative, 0, f"recipe is missing {required_name}"))
        if recipe.get("default"):
            key = (
                recipe.get("hardware_id"), recipe.get("model_family"),
                recipe.get("modality"), recipe.get("runtime_id"),
            )
            if key in defaults:
                findings.append(Finding("metadata", relative, 0, f"duplicate default recipe for {key}"))
            defaults.add(key)
        for operation, spec in recipe.get("operations", {}).items():
            command = spec if isinstance(spec, list) else [spec]
            if not command or not isinstance(command[0], str):
                findings.append(Finding("metadata", relative, 0, f"operation {operation} has no command"))
                continue
            executable = (directory / command[0]).resolve()
            try:
                executable.relative_to(root.resolve())
            except ValueError:
                findings.append(Finding("metadata", relative, 0, f"operation {operation} escapes repository"))
            else:
                if not executable.is_file():
                    findings.append(Finding("metadata", relative, 0, f"operation {operation} executable is missing"))
        if recipe.get("maturity") == "Verified":
            receipts = recipe.get("evidence", {}).get("receipts", [])
            json_receipts = [directory / item for item in receipts if isinstance(item, str) and item.endswith(".json")]
            if not json_receipts:
                findings.append(Finding("metadata", relative, 0, "Verified recipe requires a canonical JSON receipt"))
            for receipt in json_receipts:
                for error in _receipt_errors(receipt, recipe):
                    findings.append(Finding("metadata", _relative(root, receipt), 0, error))
    metric_fields = {
        "ttft_seconds", "first_final_token_seconds", "response_time_seconds",
        "decode_tokens_per_second", "output_tokens_per_second_e2e",
        "aggregate_tokens_per_second", "prompt_tokens", "completion_tokens",
        "reasoning_tokens", "cached_tokens", "errors", "hardware",
    }
    for path, result in results:
        relative = _relative(root, path)
        required = {"schema_version", "result_id", "recipe_id", "suite", "workload", "metrics", "receipt", "maturity", "status"}
        for name in sorted(required - set(result)):
            findings.append(Finding("metadata", relative, 0, f"result is missing {name}"))
        metrics = result.get("metrics")
        if isinstance(metrics, dict):
            for name in sorted(metric_fields - set(metrics)):
                findings.append(Finding("metadata", relative, 0, f"metrics is missing {name}"))
            workload_concurrency = (result.get("workload") or {}).get("concurrency")
            aggregate = metrics.get("aggregate_tokens_per_second")
            if isinstance(aggregate, dict) and aggregate.get("concurrency", workload_concurrency) != workload_concurrency:
                findings.append(Finding("metadata", relative, 0, "aggregate metric concurrency differs from workload"))
            if not result.get("legacy_metric_definitions"):
                for name in metric_fields - {"errors", "hardware"}:
                    metric = metrics.get(name)
                    if metric is None:
                        findings.append(Finding("metadata", relative, 0, f"canonical metric {name} needs an N/A reason"))
                    elif isinstance(metric, dict) and metric.get("not_applicable") is not True:
                        for field in ("min", "mean", "p50", "p95", "p99", "max"):
                            value = metric.get(field)
                            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                                    findings.append(Finding("metadata", relative, 0, f"canonical metric {name}.{field} is invalid"))
    policy_path = root / "catalog" / "benchmark-policy.json"
    try:
        policy = read_json_object(policy_path, "benchmark policy")
    except CatalogError as exc:
        findings.append(Finding("metadata", _relative(root, policy_path), 0, str(exc)))
    else:
        floors = policy.get("model_group_floors")
        if not isinstance(floors, dict) or not policy.get("floor_policy_source"):
            findings.append(Finding("metadata", _relative(root, policy_path), 0, "model-group floors or policy source are missing"))
        else:
            excluded = set(policy.get("excluded_modalities", []))
            for record in records:
                recipe = record.data
                if recipe.get("modality") in excluded:
                    continue
                key = f"{recipe.get('hardware_id')}::{recipe.get('model_family')}"
                floor = floors.get(key)
                if not isinstance(floor, dict) or not floor.get("quality_id") or not isinstance(floor.get("minimum_context_tokens"), int):
                    findings.append(Finding("metadata", _relative(root, policy_path), 0, f"missing model-group floor {key}"))
    for path in sorted((root / "benchmarks" / "suites").glob("*.json")):
        try:
            suite = read_json_object(path, "benchmark suite")
            source = suite["case_source"]
            source_path = root / source["path"]
            if suite.get("id") != path.stem or not suite.get("request_contract"):
                findings.append(Finding("metadata", _relative(root, path), 0, "suite identity or request contract is incomplete"))
            if not suite.get("evaluation") or not suite.get("active_result_rule"):
                findings.append(Finding("metadata", _relative(root, path), 0, "suite evaluation or active-result rule is missing"))
            if not source_path.is_file() or _sha256(source_path) != source.get("sha256"):
                findings.append(Finding("metadata", _relative(root, path), 0, "suite case source is missing or SHA-256 mismatched"))
        except (CatalogError, KeyError, TypeError) as exc:
            findings.append(Finding("metadata", _relative(root, path), 0, f"invalid suite contract: {exc}"))
    retired = re.compile(r"\bcd\s+(?:qwen38-rtx3090|qwen36-rtx4090-vllm|qwen38-rtx4090-llamacpp|qwen38-rtx4090-vllm)\b")
    for path in text_files(root):
        if path.suffix.lower() != ".md":
            continue
        try:
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if retired.search(line):
                    findings.append(Finding("metadata", _relative(root, path), number, "retired root project path"))
        except (OSError, UnicodeError):
            continue
    return findings


def generated_findings(root: Path) -> list[Finding]:
    findings = []
    try:
        outputs = generated_outputs(root)
    except CatalogError as exc:
        return [Finding("generated", "catalog", 0, line) for line in str(exc).splitlines()]
    for path, expected in outputs.items():
        if not path.is_file():
            findings.append(Finding("generated", _relative(root, path), 0, "generated file is missing"))
            continue
        actual = path.read_text(encoding="utf-8")
        if actual != expected:
            findings.append(Finding("generated", _relative(root, path), 0, "generated file is stale"))
    return findings


def static_findings(root: Path) -> list[Finding]:
    findings = []
    for path in canonical_files(root):
        relative = _relative(root, path)
        if path.suffix == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                line = getattr(exc, "lineno", 0) or 0
                findings.append(Finding("static", relative, line, f"invalid JSON: {exc}"))
        elif path.suffix == ".py" or path.name == "lab":
            try:
                with tokenize.open(path) as handle:
                    source = handle.read()
                compile(source, str(path), "exec")
            except (OSError, SyntaxError, UnicodeError) as exc:
                findings.append(
                    Finding("static", relative, getattr(exc, "lineno", 0) or 0, f"invalid Python: {exc}")
                )
        elif path.suffix == ".sh":
            try:
                completed = subprocess.run(
                    ["bash", "-n", str(path)], capture_output=True, text=True, check=False, timeout=10
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                findings.append(Finding("static", relative, 0, f"shell syntax check failed: {exc}"))
            else:
                if completed.returncode:
                    detail = (completed.stderr or completed.stdout).strip().splitlines()
                    findings.append(
                        Finding("static", relative, 0, f"invalid shell: {detail[-1] if detail else 'bash -n failed'}")
                    )
    return findings


def run_checks(root: Path, checks: list[str]) -> list[Finding]:
    available = {
        "metadata": metadata_findings,
        "privacy": privacy_findings,
        "binary": binary_findings,
        "links": link_findings,
        "generated": generated_findings,
        "static": static_findings,
    }
    findings = []
    for name in checks:
        findings.extend(available[name](root))
    return findings
