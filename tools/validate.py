from __future__ import annotations

import json
import re
import subprocess
import tokenize
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from tools.catalog import CatalogError, discover_recipes, generated_outputs


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
TEXT_SUFFIXES = {
    "",
    ".cfg",
    ".env",
    ".html",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
PRIVACY_RULES = (
    (
        "private IPv4 address",
        re.compile(r"(?<![0-9])(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})(?![0-9])"),
    ),
    ("user home path", re.compile(r"/(?:home|Users)/(?!YOUR_USERNAME(?:/|\b)|user(?:/|\b)|example(?:/|\b))[^\s/]+/")),
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
    return [path for path in candidates if path.suffix.lower() in TEXT_SUFFIXES]


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
    markdown = [path for path in (canonical_files(root) if paths is None else paths) if path.suffix.lower() == ".md"]
    for path in markdown:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        for number, line in enumerate(lines, 1):
            for match in LINK_RE.finditer(line):
                target = match.group(1).strip().split(maxsplit=1)[0].strip("<>")
                if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                    continue
                clean = unquote(target.split("#", 1)[0].split("?", 1)[0])
                if not clean:
                    continue
                resolved = (root / clean.lstrip("/")) if clean.startswith("/") else (path.parent / clean)
                if not resolved.exists():
                    findings.append(
                        Finding("links", _relative(root, path), number, f"missing local target {target!r}")
                    )
    return findings


def metadata_findings(root: Path) -> list[Finding]:
    try:
        discover_recipes(root)
    except CatalogError as exc:
        return [Finding("metadata", "recipes", 0, line) for line in str(exc).splitlines()]
    return []


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
        "links": link_findings,
        "generated": generated_findings,
        "static": static_findings,
    }
    findings = []
    for name in checks:
        findings.extend(available[name](root))
    return findings
