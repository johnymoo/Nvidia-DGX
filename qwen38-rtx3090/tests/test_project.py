from __future__ import annotations

import importlib.util
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "receipts" / "deployment-20260815T144804Z.json"


class ProjectTests(unittest.TestCase):
    def test_receipt_schema(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "validate_receipt", ROOT / "scripts" / "validate_receipt.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        module.validate(RECEIPT)

    def test_config_matches_receipt(self) -> None:
        receipt = json.loads(RECEIPT.read_text())
        config = (ROOT / "config" / "qwen38.env.example").read_text()
        for key in (
            "MODEL_SHA256",
            "MMPROJ_SHA256",
            "LLAMA_IMAGE",
            "CTX_SIZE",
            "PARALLEL",
        ):
            self.assertRegex(config, rf"(?m)^{key}=.+$")
        self.assertIn(receipt["artifacts"]["model_sha256"], config)
        self.assertIn(receipt["artifacts"]["mmproj_sha256"], config)
        self.assertIn(receipt["artifacts"]["image_ref"], config)

    def test_no_private_environment_values(self) -> None:
        private_roots = "/" + "(?:Users|home)/"
        forbidden = re.compile(
            r"192\.168\.|10\.\d+\.\d+\.\d+|"
            rf"172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+|{private_roots}"
        )
        for path in ROOT.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                self.assertIsNone(forbidden.search(path.read_text()), str(path))


if __name__ == "__main__":
    unittest.main()
