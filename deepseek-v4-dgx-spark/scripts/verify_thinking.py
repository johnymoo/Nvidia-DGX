#!/usr/bin/env python3
"""Verify DeepSeek thinking in rendered Compose JSON or Claude Code JSONL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, TextIO


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_compose(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        service = payload["services"]["vllm-dspark"]
        command = " ".join(service["command"])
        environment = service.get("environment", {})
    except (KeyError, TypeError) as exc:
        raise ValueError("rendered Compose JSON is missing vllm-dspark") from exc

    enabled = '{"thinking":true}' in command
    disabled = '{"thinking":false}' in command
    marker = environment.get("DSPARK_THINKING")
    if not enabled or disabled or marker != "true":
        raise ValueError(
            "Compose render must contain only thinking:true and "
            "DSPARK_THINKING=true"
        )
    return {
        "status": "passed",
        "mode": "compose",
        "thinking": True,
        "service": "vllm-dspark",
    }


def inspect_stream(path: Path) -> dict[str, Any]:
    assistant_events = thinking_blocks = thinking_token_events = 0
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
        if not isinstance(event, dict):
            continue
        if event.get("type") == "system" and event.get("subtype") == "thinking_tokens":
            thinking_token_events += 1
        if event.get("type") != "assistant":
            continue
        assistant_events += 1
        for block in (event.get("message") or {}).get("content") or []:
            if block.get("type") in {"thinking", "redacted_thinking"}:
                thinking_blocks += 1
    return {
        "path": str(path),
        "assistant_events": assistant_events,
        "thinking_blocks": thinking_blocks,
        "thinking_token_events": thinking_token_events,
    }


def verify_streams(paths: list[Path]) -> dict[str, Any]:
    streams = [inspect_stream(path) for path in paths]
    missing = [stream["path"] for stream in streams if stream["thinking_blocks"] < 1]
    if missing:
        raise ValueError("thinking block missing from: " + ", ".join(missing))
    return {
        "status": "passed",
        "mode": "streams",
        "stream_count": len(streams),
        "thinking_block_count": sum(item["thinking_blocks"] for item in streams),
        "thinking_token_event_count": sum(
            item["thinking_token_events"] for item in streams
        ),
        "streams": streams,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)
    compose = subparsers.add_parser("compose")
    compose.add_argument("rendered_json", type=Path)
    streams = subparsers.add_parser("streams")
    streams.add_argument("jsonl", type=Path, nargs="+")
    return parser.parse_args()


def main(stdout: TextIO = sys.stdout, stderr: TextIO = sys.stderr) -> int:
    args = parse_args()
    try:
        result = (
            verify_compose(read_json(args.rendered_json))
            if args.mode == "compose"
            else verify_streams(args.jsonl)
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}), file=stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), file=stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
