from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "receipts" / "deployment-20260815T144804Z.json"


class ProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location(
            "validate_receipt", ROOT / "scripts" / "validate_receipt.py"
        )
        cls.validator = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(cls.validator)

    def test_receipt_schema(self) -> None:
        self.validator.validate(RECEIPT)

    def test_validator_rejects_wrong_pinned_identities(self) -> None:
        receipt = json.loads(RECEIPT.read_text())
        for field in ("model_sha256", "mmproj_sha256", "image_ref"):
            changed = copy.deepcopy(receipt)
            changed["artifacts"][field] = "0" * 64
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "wrong"):
                self.validator.validate_data(changed)

    def test_lifecycle_scripts_verify_ownership_and_runtime(self) -> None:
        common = (ROOT / "scripts" / "common.sh").read_text()
        start = (ROOT / "scripts" / "start.sh").read_text()
        for script in ("status.sh", "stop.sh"):
            self.assertIn("verify_container", (ROOT / "scripts" / script).read_text())
        self.assertIn('"${SCRIPT_DIR}/status.sh"', (ROOT / "scripts" / "accept.sh").read_text())
        self.assertIn("verify_single_gpu", start)
        self.assertIn("--gpus device=0", start)
        self.assertIn("PROFILE_LABEL", start)
        self.assertIn("Config.Cmd == $expected_cmd", common)

    def _write_test_env(self, root: Path) -> Path:
        model_root = root / "models"
        state_root = root / "state"
        (state_root / "logs").mkdir(parents=True)
        model_root.mkdir()
        values = {
            "MODEL_ROOT": model_root,
            "STATE_ROOT": state_root,
            "MODEL_REPO": "example/model",
            "MODEL_REVISION": "revision",
            "MODELSCOPE_REVISION": "master",
            "MODEL_FILE": "model.gguf",
            "MODEL_BYTES": "1",
            "MODEL_SHA256": "0" * 64,
            "MMPROJ_FILE": "mmproj.gguf",
            "MMPROJ_BYTES": "1",
            "MMPROJ_SHA256": "1" * 64,
            "MODEL_ALIAS": "qwen-test",
            "LLAMA_IMAGE": "example/image@sha256:" + "2" * 64,
            "CONTAINER_NAME": "qwen-test",
            "PUBLISH_HOST": "127.0.0.1",
            "PORT": "18002",
            "CTX_SIZE": "131072",
            "PARALLEL": "2",
            "GPU_HEADROOM_MIB": "3072",
        }
        path = root / "test.env"
        path.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
        return path

    def test_multiple_gpus_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env_file = self._write_test_env(Path(temporary))
            command = f'''source "{ROOT / "scripts/common.sh"}"
nvidia-smi() {{ printf '%s\n' 'NVIDIA GeForce RTX 3090, 24576' 'NVIDIA GeForce RTX 3090, 24576'; }}
verify_single_gpu
'''
            result = subprocess.run(
                ["bash", "-c", command],
                env={**os.environ, "QWEN38_ENV": str(env_file)},
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exactly one", result.stderr)

    def test_stop_refuses_foreign_same_name_container(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env_file = self._write_test_env(root)
            call_log = root / "docker-calls"
            command = f'''docker() {{
  printf '%s\n' "$*" >>"$CALL_LOG"
  if [[ "$1 $2" == "container inspect" ]]; then return 0; fi
  if [[ "$1 $2" == "image inspect" ]]; then printf 'sha256:wrong\n'; return 0; fi
  if [[ "$1" == "inspect" ]]; then printf '[]\n'; return 0; fi
  return 0
}}
export -f docker
source "{ROOT / "scripts/stop.sh"}"
'''
            result = subprocess.run(
                ["bash", "-c", command],
                env={
                    **os.environ,
                    "QWEN38_ENV": str(env_file),
                    "CALL_LOG": str(call_log),
                },
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            calls = call_log.read_text()
            self.assertNotIn("rm -f", calls)
            self.assertIn("does not match this profile", result.stderr)

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
