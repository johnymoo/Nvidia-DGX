#!/usr/bin/env python3
"""Command-line entry point for the GB10 model platform."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from model_platform import (
    API_VERSION,
    PlatformError,
    SSHRunner,
    check_model,
    discover,
    load_registry,
    ports_document,
    status_document,
)
from operations import LifecycleManager


ROOT = Path(__file__).resolve().parent


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="modelctl")
    result.add_argument("--registry", type=Path, default=ROOT / "models.yaml")
    result.add_argument("--json", action="store_true", help="emit versioned JSON")
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    sub.add_parser("discover")
    sub.add_parser("capabilities")
    status = sub.add_parser("status")
    status.add_argument("model", nargs="?")
    ports = sub.add_parser("ports")
    ports.add_argument("--host")
    check = sub.add_parser("check")
    check.add_argument("model")
    for command in ("start", "stop", "restart"):
        operation = sub.add_parser(command)
        operation.add_argument("model")
        operation.add_argument("--confirm", required=True)
        operation.add_argument("--dry-run", action="store_true")
        operation.add_argument("--allow-protected", action="store_true")
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    return result


def human(document):
    kind = document.get("kind")
    if kind == "ModelStatusList":
        for model in document["models"]:
            marker = " protected" if model["protected"] else ""
            print("{:<28} {:<10}{}".format(model["id"], model["state"], marker))
        for item in document["unmanaged"]:
            print("{:<28} {:<10} {}".format(item["project"], "Unmanaged", item["host"]))
    elif kind == "PortList":
        for item in document["listeners"]:
            print("{host:<8} {protocol:<4} {bind}:{port} {process}".format(**item))
    elif kind == "Preflight":
        print("{}: {}".format(document["model"], "ready" if document["allowed"] else "blocked"))
        for conflict in document["conflicts"]:
            print("- {}".format(json.dumps(conflict, sort_keys=True)))
    elif kind == "AdapterCapabilityList":
        for item in document["models"]:
            print("{:<28} {:<12} {}".format(item["id"], "available" if item["available"] else "unavailable", item["reason"]))
    else:
        print(json.dumps(document, indent=2, sort_keys=True))


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        registry = load_registry(args.registry)
        if args.command == "serve":
            from web import main as web_main
            web_main(["--registry", str(args.registry), "--host", args.host, "--port", str(args.port)])
            return 0
        runner = SSHRunner()
        snapshot = discover(registry, runner)
        if args.command == "discover":
            document = snapshot
        elif args.command == "capabilities":
            status = status_document(registry, snapshot, runner=runner)
            document = {
                "api_version": API_VERSION,
                "kind": "AdapterCapabilityList",
                "models": [
                    {"id": item["id"], "available": item["operable"], "reason": item["availability"].get("reason", "")}
                    for item in status["models"]
                ],
            }
        elif args.command in {"list", "status"}:
            document = status_document(registry, snapshot, runner=runner)
            if args.command == "status" and args.model:
                selected = [item for item in document["models"] if item["id"] == args.model]
                if not selected:
                    raise PlatformError("unknown model: {}".format(args.model))
                document = {"api_version": API_VERSION, "kind": "ModelStatus", "model": selected[0]}
        elif args.command == "ports":
            if args.host and args.host not in registry["hosts"]:
                raise PlatformError("unknown host: {}".format(args.host))
            document = ports_document(registry, snapshot, args.host)
        elif args.command == "check":
            document = check_model(registry, snapshot, args.model, runner=runner)
        elif args.command in {"start", "stop", "restart"}:
            document = LifecycleManager(registry, runner).execute(
                args.model, args.command, args.confirm, dry_run=args.dry_run, snapshot=snapshot,
                allow_protected=args.allow_protected,
            )
        else:
            raise PlatformError("unsupported command")
        if args.json:
            print(json.dumps(document, indent=2, sort_keys=True))
        else:
            human(document)
        if snapshot.get("errors"):
            return 2
        if document.get("kind") == "Preflight" and not document["allowed"]:
            return 3
        return 0
    except (PlatformError, OSError, json.JSONDecodeError) as exc:
        error = {"api_version": API_VERSION, "kind": "Error", "error": str(exc)}
        if args.json:
            print(json.dumps(error, sort_keys=True))
        else:
            print("modelctl: {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
