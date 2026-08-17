#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def validate_suites(root: Path) -> list[str]:
    errors = []
    for path in sorted((root / "benchmarks/suites").glob("*.json")):
        try:
            suite = load(path)
            source = suite["case_source"]
            source_path = root / source["path"]
            if suite.get("id") != path.stem:
                errors.append(f"{path}: id does not match filename")
            if not isinstance(suite.get("version"), str) or not suite.get("request_contract"):
                errors.append(f"{path}: version or request_contract is missing")
            if not suite.get("evaluation") or not suite.get("active_result_rule"):
                errors.append(f"{path}: evaluation or active-result rule is missing")
            if not source_path.is_file() or sha256(source_path) != source.get("sha256"):
                errors.append(f"{path}: case source is missing or SHA-256 mismatched")
        except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: {exc}")
    return errors


def validate_bundle(bundle: Path) -> list[str]:
    errors = []
    required = ["README.md", "result.json", "receipt.json", "report.md", "manifest.sha256"]
    for name in required:
        if not (bundle / name).is_file():
            errors.append(f"{bundle}: missing {name}")
    if errors:
        return errors
    try:
        result = load(bundle / "result.json")
        receipt = load(bundle / "receipt.json")
        if result.get("recipe_id") != receipt.get("recipe_id"):
            errors.append(f"{bundle}: result and receipt recipe_id differ")
        expected = {}
        for line in (bundle / "manifest.sha256").read_text(encoding="utf-8").splitlines():
            digest, name = line.split("  ", 1)
            expected[name] = digest
        for name in ("README.md", "result.json", "receipt.json", "report.md"):
            if expected.get(name) != sha256(bundle / name):
                errors.append(f"{bundle}: manifest mismatch for {name}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"{bundle}: {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Hostless benchmark suite and submission validator")
    parser.add_argument("bundle", nargs="?", type=Path)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    errors = validate_suites(ROOT) if args.all else []
    bundle = args.bundle or (ROOT / "benchmarks/examples/reference-bundle" if args.all else None)
    if bundle:
        errors.extend(validate_bundle(bundle.resolve()))
    if not args.all and bundle is None:
        parser.error("provide a bundle or --all")
    for error in errors:
        print(error, file=sys.stderr)
    if not errors:
        print("benchmark submission validation passed")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
