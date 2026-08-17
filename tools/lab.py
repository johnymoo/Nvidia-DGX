from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from tools.catalog import (
    CatalogError,
    dispatch_command,
    generated_outputs,
    latest_benchmarks,
    recipe_catalog,
)
from tools.validate import run_checks


ALL_CHECKS = ["metadata", "privacy", "binary", "links", "generated", "static"]


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="lab", description="NVIDIA deployment recipe catalog utility")
    root.add_argument("--root", type=Path, default=repository_root(), help=argparse.SUPPRESS)
    commands = root.add_subparsers(dest="command", required=True)

    listing = commands.add_parser("list", help="list canonical recipes")
    listing.add_argument("--json", action="store_true")

    best = commands.add_parser("best", help="show fail-closed Best Verified selections")
    best.add_argument("--json", action="store_true")

    generate = commands.add_parser("generate", help="generate catalog files and README fragments")
    mode = generate.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")

    validate = commands.add_parser("validate", help="run repository-only validation")
    validate.add_argument("--check", action="append", choices=ALL_CHECKS)

    run = commands.add_parser("run", help="dispatch one recipe operation")
    run.add_argument("recipe_id")
    run.add_argument("operation")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("args", nargs=argparse.REMAINDER)
    return root


def _print_recipe_table(catalog: dict) -> None:
    if not catalog["recipes"]:
        print("No canonical recipes are cataloged.")
        return
    for item in catalog["recipes"]:
        print(
            f"{item['id']}\t{item['maturity']}\t{item['hardware_id']}\t"
            f"{item['model_id']}\t{item['runtime_id']}/{item['profile_id']}"
        )


def _print_best(latest: dict) -> None:
    for item in latest["best_verified"]:
        print(f"{item['hardware_id']}\t{item['model_family']}\t{item['result_id']}")
    for item in latest.get("no_eligible_groups", []):
        print(f"{item['hardware_id']}\t{item['model_family']}\t{item['message']}")
    if not latest["best_verified"] and not latest.get("no_eligible_groups"):
        print("No eligible Verified result is available.")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "list":
            catalog = recipe_catalog(root)
            print(json.dumps(catalog, indent=2, ensure_ascii=False) if args.json else "", end="") if args.json else _print_recipe_table(catalog)
            if args.json:
                print()
            return 0
        if args.command == "best":
            latest = latest_benchmarks(root)
            print(json.dumps(latest, indent=2, ensure_ascii=False) if args.json else "", end="") if args.json else _print_best(latest)
            if args.json:
                print()
            return 0
        if args.command == "generate":
            outputs = generated_outputs(root)
            stale = [path for path, content in outputs.items() if not path.is_file() or path.read_text(encoding="utf-8") != content]
            if args.check:
                for path in stale:
                    print(f"stale: {path.relative_to(root)}", file=sys.stderr)
                return 1 if stale else 0
            for path, content in outputs.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                print(path.relative_to(root))
            return 0
        if args.command == "validate":
            checks = args.check or ALL_CHECKS
            findings = run_checks(root, checks)
            for finding in findings:
                print(finding.format(), file=sys.stderr)
            if not findings:
                print(f"validated: {', '.join(checks)}")
            return 1 if findings else 0
        if args.command == "run":
            dry_run = args.dry_run or "--dry-run" in args.args
            forwarded = [item for item in args.args if item != "--dry-run"]
            extra = forwarded[1:] if forwarded[:1] == ["--"] else forwarded
            command = dispatch_command(root, args.recipe_id, args.operation, extra)
            if dry_run:
                print(json.dumps(command))
                return 0
            return subprocess.run(command, cwd=root, env=os.environ.copy(), check=False).returncode
    except (CatalogError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 2
    return 2
