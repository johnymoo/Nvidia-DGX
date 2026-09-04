#!/usr/bin/env python3
"""Environment configuration for the eval harness.

No hostnames, IPs, or usernames live in this file or anywhere else in the
package. Everything comes from the environment, optionally seeded by a local
`.env.eval` file (gitignored via `.env.*`; see eval.env.example for the
documented keys).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

ENV_FILE_NAME = ".env.eval"
_ASSIGNMENT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ASSIGNMENT_RE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def load_dotenv(package_dir: Path | None = None) -> dict[str, str]:
    """Load `.env.eval` next to this file into os.environ, without
    overriding variables the caller already set explicitly."""
    package_dir = package_dir or Path(__file__).resolve().parent
    env_path = package_dir / ENV_FILE_NAME
    if not env_path.is_file():
        return {}
    loaded = _parse_env_file(env_path)
    for key, value in loaded.items():
        os.environ.setdefault(key, value)
    return loaded


@dataclass
class Config:
    base_url: str
    model: str
    metrics_url: str
    head_ssh: str | None
    worker_ssh: str | None
    container: str


def redact_host(url: str) -> str:
    """Replace the host[:port] part of a URL with `<host>` for anything
    written to a run's manifest.json."""
    return re.sub(r"^(https?://)[^/]+", r"\1<host>", url)


def load_config() -> Config:
    load_dotenv()
    base_url = os.environ.get("EVAL_BASE_URL")
    if not base_url:
        raise SystemExit(
            "EVAL_BASE_URL is not set. Copy execution/eval/eval.env.example to "
            "execution/eval/.env.eval and fill it in, or export EVAL_BASE_URL."
        )
    base_url = base_url.rstrip("/")
    model = os.environ.get("EVAL_MODEL")
    if not model:
        raise SystemExit("EVAL_MODEL is not set (see eval.env.example).")
    metrics_url = os.environ.get("EVAL_METRICS_URL") or f"{base_url}/metrics"
    return Config(
        base_url=base_url,
        model=model,
        metrics_url=metrics_url,
        head_ssh=os.environ.get("EVAL_HEAD_SSH") or None,
        worker_ssh=os.environ.get("EVAL_WORKER_SSH") or None,
        container=os.environ.get("EVAL_CONTAINER", ""),
    )


def menu_image_path() -> Path | None:
    load_dotenv()
    value = os.environ.get("EVAL_MENU_IMAGE")
    return Path(value) if value else None
