from __future__ import annotations

import re
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProjectTests(unittest.TestCase):
    def test_compose_enforces_resource_boundaries(self) -> None:
        compose = (ROOT / "compose.yaml").read_text()
        self.assertRegex(compose, r"--cpu-offload-gb\s+?- \"0\"")
        self.assertIn("mem_limit: ${HOST_MEMORY_LIMIT}", compose)
        self.assertIn("memswap_limit: ${HOST_MEMORY_LIMIT}", compose)
        self.assertIn("restart: unless-stopped", compose)
        self.assertIn("count: 1", compose)

    def test_default_is_non_thinking(self) -> None:
        compose = (ROOT / "compose.yaml").read_text()
        self.assertIn("--reasoning-parser", compose)
        self.assertIn("'{\"enable_thinking\": false}'", compose)

    def test_images_and_model_identity_are_pinned(self) -> None:
        config = (ROOT / "config" / "qwen36.env.example").read_text()
        self.assertIn("PUBLISH_HOST=127.0.0.1", config)
        self.assertIn("ALLOW_UNAUTHENTICATED_LAN=false", config)
        for key in ("MODELSCOPE_IMAGE", "VLLM_IMAGE"):
            self.assertRegex(config, rf"(?m)^{key}=.+@sha256:[0-9a-f]{{64}}$")
        for key in (
            "CONFIG_SHA256",
            "INDEX_SHA256",
            "CHAT_TEMPLATE_SHA256",
            "GENERATION_CONFIG_SHA256",
            "TOKENIZER_CONFIG_SHA256",
        ):
            self.assertRegex(config, rf"(?m)^{key}=[0-9a-f]{{64}}$")

    def test_no_private_address_or_offload_override(self) -> None:
        forbidden = re.compile(r"192\.168\.|10\.\d+\.\d+\.\d+")
        for path in ROOT.rglob("*"):
            if path.is_file() and path.suffix != ".pyc" and ".git" not in path.parts:
                self.assertIsNone(forbidden.search(path.read_text()), str(path))

    def test_shell_scripts_use_strict_mode(self) -> None:
        for path in sorted((ROOT / "scripts").glob("*.sh")):
            self.assertIn("set -euo pipefail", path.read_text(), path.name)

    def test_non_loopback_binding_requires_explicit_opt_in(self) -> None:
        common = (ROOT / "scripts" / "common.sh").read_text()
        self.assertIn("ALLOW_UNAUTHENTICATED_LAN", common)
        self.assertIn("Non-loopback API binding requires", common)

    def test_receipts_pass_and_are_sanitized(self) -> None:
        forbidden = re.compile(r"/(?:home|Users)/|192\.168\.|10\.\d+\.\d+\.\d+")
        for path in sorted((ROOT / "receipts").glob("*.json")):
            value = json.loads(path.read_text())
            self.assertEqual(value.get("status"), "passed", path.name)
            self.assertIsNone(forbidden.search(path.read_text()), path.name)


if __name__ == "__main__":
    unittest.main()
