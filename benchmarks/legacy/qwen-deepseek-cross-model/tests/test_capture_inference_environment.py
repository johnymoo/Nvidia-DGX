import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "capture_inference_environment.py"
SPEC = importlib.util.spec_from_file_location("capture_inference_environment", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class CaptureEnvironmentTests(unittest.TestCase):
    def test_cpu_field_allowlist_excludes_security_posture(self) -> None:
        self.assertIn("Model name:", MODULE.CPU_FIELDS)
        self.assertFalse(any(field.startswith("Vulnerability") for field in MODULE.CPU_FIELDS))

    def test_committed_snapshot_excludes_host_identity_and_vulnerabilities(self) -> None:
        payload = json.loads((ROOT / "data" / "inference-environment-20260817.json").read_text())
        self.assertNotIn("hostname", payload["host"])
        self.assertNotIn("pci_bus_id", payload["host"]["gpu"])
        self.assertFalse(any(row["field"].startswith("Vulnerability") for row in payload["host"]["cpu"]))


if __name__ == "__main__":
    unittest.main()
