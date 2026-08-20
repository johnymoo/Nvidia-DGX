#!/usr/bin/env python3
"""Generate or edit one image with GPT Image 2 without exposing credentials."""

from __future__ import annotations

import argparse
import base64
import binascii
from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.request import urlopen
from urllib.parse import urlsplit


ALLOWED_ENV_KEYS = {"OPENAI_API_KEY", "OPENAI_BASE_URL"}
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_IMAGE_BYTES = 50 * 1024 * 1024


def load_allowed_env(path: Path, env: dict[str, str]) -> None:
    """Load only API credentials from a dotenv file without executing it."""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not ENV_KEY_RE.fullmatch(key) or key not in ALLOWED_ENV_KEYS:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        env.setdefault(key, value)


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    prompt_group = parser.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument("--prompt")
    prompt_group.add_argument("--prompt-file", type=Path)
    parser.add_argument("--model", default="gpt-image-2")
    parser.add_argument("--size", default="1536x1024")
    parser.add_argument("--quality", choices=["low", "medium", "high", "auto"], default="medium")
    parser.add_argument("--output-format", choices=["png", "jpeg", "webp"], default="png")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate or edit one GPT Image 2 image.")
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Dotenv file containing OPENAI_API_KEY and optional OPENAI_BASE_URL.",
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)

    generate_parser = subparsers.add_parser("generate")
    add_common_arguments(generate_parser)

    edit_parser = subparsers.add_parser("edit")
    add_common_arguments(edit_parser)
    edit_parser.add_argument("--image", type=Path, action="append", required=True)

    return parser.parse_args()


def resolve_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file is not None:
        try:
            prompt = args.prompt_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemExit(f"Cannot read prompt file {args.prompt_file}: {exc}") from exc
    else:
        prompt = args.prompt
    prompt = prompt.strip()
    if not prompt:
        raise SystemExit("Prompt must not be empty")
    return prompt


def request_summary(args: argparse.Namespace, prompt: str) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "operation": args.operation,
        "model": args.model,
        "prompt": prompt,
        "size": args.size,
        "quality": args.quality,
        "output_format": args.output_format,
        "out": str(args.out),
        "timeout": args.timeout,
    }
    if args.operation == "edit":
        summary["images"] = [str(path) for path in args.image]
    return summary


def validate_image_bytes(payload: bytes, output_format: str) -> bytes:
    signatures = {
        "png": payload.startswith(b"\x89PNG\r\n\x1a\n"),
        "jpeg": payload.startswith(b"\xff\xd8\xff"),
        "webp": payload.startswith(b"RIFF") and payload[8:12] == b"WEBP",
    }
    if not signatures[output_format]:
        raise SystemExit(f"Image API response is not valid {output_format} data")
    return payload


def response_bytes(response: Any, output_format: str) -> bytes:
    data = getattr(response, "data", None)
    if not data:
        raise SystemExit("Image API returned an empty data array")
    item = data[0]
    encoded = getattr(item, "b64_json", None)
    if encoded:
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise SystemExit("Image API returned invalid base64 image data") from exc
        if len(payload) > MAX_IMAGE_BYTES:
            raise SystemExit("Image API response exceeds the 50 MiB limit")
        return validate_image_bytes(payload, output_format)
    image_url = getattr(item, "url", None)
    if image_url:
        if urlsplit(image_url).scheme not in {"http", "https"}:
            raise SystemExit("Image API returned a URL with an unsupported scheme")
        with urlopen(image_url, timeout=120) as stream:
            payload = stream.read(MAX_IMAGE_BYTES + 1)
        if len(payload) > MAX_IMAGE_BYTES:
            raise SystemExit("Downloaded image exceeds the 50 MiB limit")
        return validate_image_bytes(payload, output_format)
    raise SystemExit("Image API returned neither b64_json nor a URL")


def validate_output_path(path: Path, output_format: str) -> None:
    valid_suffixes = {
        "png": {".png"},
        "jpeg": {".jpg", ".jpeg"},
        "webp": {".webp"},
    }
    if path.suffix.lower() not in valid_suffixes[output_format]:
        expected = ", ".join(sorted(valid_suffixes[output_format]))
        raise SystemExit(f"Output for {output_format} must use one of: {expected}")


def main() -> int:
    args = parse_args()
    prompt = resolve_prompt(args)
    validate_output_path(args.out, args.output_format)
    if args.timeout <= 0:
        raise SystemExit("Timeout must be greater than zero")

    if args.operation == "edit":
        if len(args.image) > 16:
            raise SystemExit("The Image API accepts at most 16 reference images")
        missing = [str(path) for path in args.image if not path.is_file()]
        if missing:
            raise SystemExit(f"Reference images not found: {', '.join(missing)}")
        oversized = [str(path) for path in args.image if path.stat().st_size > MAX_IMAGE_BYTES]
        if oversized:
            raise SystemExit(f"Reference images exceed 50 MiB: {', '.join(oversized)}")

    if args.out.exists() and not args.force:
        raise SystemExit(f"Output already exists: {args.out}; pass --force to replace it")

    if args.dry_run:
        print(json.dumps(request_summary(args, prompt), indent=2, ensure_ascii=False))
        return 0

    env = os.environ.copy()
    env_file = args.env_file
    if env_file is None and "OPENAI_API_KEY" not in env:
        default_env = Path.cwd() / ".env"
        if default_env.is_file():
            env_file = default_env
    if env_file is not None:
        if not env_file.is_file():
            raise SystemExit(f"Environment file not found: {env_file}")
        load_allowed_env(env_file, env)

    api_key = env.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is not set")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise SystemExit("Install the OpenAI package: python3 -m pip install openai") from exc

    client_kwargs: dict[str, Any] = {
        "api_key": api_key,
        "timeout": args.timeout,
        "max_retries": 2,
    }
    if env.get("OPENAI_BASE_URL"):
        client_kwargs["base_url"] = env["OPENAI_BASE_URL"]
    client = OpenAI(**client_kwargs)

    request: dict[str, Any] = {
        "model": args.model,
        "prompt": prompt,
        "n": 1,
        "size": args.size,
        "quality": args.quality,
        "output_format": args.output_format,
    }

    try:
        if args.operation == "generate":
            response = client.images.generate(**request)
        else:
            with ExitStack() as stack:
                request["image"] = [stack.enter_context(path.open("rb")) for path in args.image]
                response = client.images.edit(**request)
    except Exception as exc:
        raise SystemExit(f"Image API request failed: {exc}") from exc

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(response_bytes(response, args.output_format))
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
