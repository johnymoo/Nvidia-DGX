#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("claude_code_swe_pilot.py")
SPEC = importlib.util.spec_from_file_location("claude_code_swe_pilot", MODULE_PATH)
assert SPEC and SPEC.loader
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)


def make_fake_toolchain(root: Path) -> tuple[Path, Path]:
    toolchain = root / "toolchain"
    shim = toolchain / "bin" / "claude"
    shim.parent.mkdir(parents=True)
    shim.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
model="${FAKE_MODEL:-${CLAUDE_DS_MODEL:-${CLAUDE_LOCAL_MODEL:-missing}}}"
version="${FAKE_VERSION:-2.1.207}"
printf '{"type":"system","subtype":"init","model":"%s","claude_code_version":"%s"}\\n' "$model" "$version"
if [ -n "${FAKE_SLEEP:-}" ]; then sleep "$FAKE_SLEEP"; fi
printf '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read"}]}}\\n'
printf '{"type":"result","subtype":"success","duration_ms":5,"num_turns":1,"total_cost_usd":0.01,"modelUsage":{"%s":{"inputTokens":1,"outputTokens":1}},"usage":{"input_tokens":1,"output_tokens":1},"permission_denials":[],"terminal_reason":"completed"}\\n' "$model"
""",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    subprocess.run(["git", "init", "-q", str(toolchain)], check=True)
    subprocess.run(
        ["git", "-C", str(toolchain), "config", "user.name", "Test"], check=True
    )
    subprocess.run(
        ["git", "-C", str(toolchain), "config", "user.email", "test@localhost"],
        check=True,
    )
    subprocess.run(["git", "-C", str(toolchain), "add", "bin/claude"], check=True)
    subprocess.run(["git", "-C", str(toolchain), "commit", "-qm", "fake"], check=True)
    real = root / "claude-real"
    real.write_text(
        "#!/usr/bin/env bash\necho '2.1.207 (Claude Code)'\n", encoding="utf-8"
    )
    real.chmod(0o755)
    return toolchain, real


def main() -> None:
    manifest = pilot.load_manifest()
    assert len(manifest["tasks"]) == 4
    with tempfile.TemporaryDirectory(prefix="claude-pilot-test-") as raw:
        root = Path(raw)
        toolchain, real = make_fake_toolchain(root)
        os.environ["CLAUDE_DS_TOKEN"] = "test-token"
        os.environ["CLAUDE_BASE_URL"] = "https://example.invalid"

        run = pilot.run_claude(
            treatment="online",
            prompt="test",
            cwd=root,
            timeout_seconds=5,
            toolchain=toolchain,
            real_claude=real,
            expected_version="2.1.207",
            output_path=root / "online.jsonl",
            with_tools=True,
        )
        assert run["model"] == "deepseek-v4-flash"
        assert run["tool_calls"] == ["Read"]

        os.environ["FAKE_MODEL"] = "deepseek-v4-pro"
        try:
            pilot.run_claude(
                treatment="online",
                prompt="test",
                cwd=root,
                timeout_seconds=5,
                toolchain=toolchain,
                real_claude=real,
                expected_version="2.1.207",
                output_path=root / "mismatch.jsonl",
                with_tools=False,
            )
        except pilot.InfrastructureError as exc:
            assert "model mismatch" in str(exc)
        else:
            raise AssertionError("model mismatch did not fail")
        os.environ.pop("FAKE_MODEL")

        os.environ["FAKE_SLEEP"] = "3"
        timeout = pilot.run_claude(
            treatment="private",
            prompt="test",
            cwd=root,
            timeout_seconds=1,
            toolchain=toolchain,
            real_claude=real,
            expected_version="2.1.207",
            output_path=root / "timeout.jsonl",
            with_tools=True,
        )
        assert timeout["timed_out"] is True
        assert timeout["terminal_reason"] == "timeout"
        os.environ.pop("FAKE_SLEEP")

        repo = root / "repo"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "Test"], check=True
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "test@localhost"],
            check=True,
        )
        (repo / "tracked.txt").write_text("before\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
        (repo / "tracked.txt").write_text("after\n", encoding="utf-8")
        (repo / "new.txt").write_text("new\n", encoding="utf-8")
        patch = pilot.capture_patch(repo)
        assert "tracked.txt" in patch and "new.txt" in patch

    print(json.dumps({"status": "passed", "tests": 4}))


if __name__ == "__main__":
    main()
