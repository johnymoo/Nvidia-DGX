from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProjectTests(unittest.TestCase):
    def test_compose_enforces_resource_boundaries(self) -> None:
        compose = (ROOT / "compose.yaml").read_text()
        self.assertIn("--cpu-offload-gb", compose)
        self.assertRegex(compose, r"--cpu-offload-gb\s+?- \"0\"")
        self.assertIn("mem_limit: ${HOST_MEMORY_LIMIT}", compose)
        self.assertIn("memswap_limit: ${HOST_MEMORY_LIMIT}", compose)
        self.assertIn("restart: unless-stopped", compose)
        self.assertIn("count: 1", compose)

    def test_default_is_non_thinking_but_reasoning_parser_is_enabled(self) -> None:
        compose = (ROOT / "compose.yaml").read_text()
        self.assertIn("--reasoning-parser", compose)
        self.assertIn("'{\"enable_thinking\": false}'", compose)

    def test_config_pins_images_and_model_identity(self) -> None:
        config = (ROOT / "config" / "qwen38.env.example").read_text()
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

    def test_receipts_are_valid_and_sanitized(self) -> None:
        forbidden = re.compile(r"/(?:home|Users)/|192\.168\.|10\.\d+\.\d+\.\d+")
        for path in sorted((ROOT / "receipts").glob("*.json")):
            value = json.loads(path.read_text())
            self.assertEqual(value.get("status"), "passed", path.name)
            self.assertIsNone(forbidden.search(path.read_text()), path.name)

    def test_shell_scripts_use_strict_mode(self) -> None:
        for path in sorted((ROOT / "scripts").glob("*.sh")):
            self.assertIn("set -euo pipefail", path.read_text(), path.name)


if __name__ == "__main__":
    unittest.main()
