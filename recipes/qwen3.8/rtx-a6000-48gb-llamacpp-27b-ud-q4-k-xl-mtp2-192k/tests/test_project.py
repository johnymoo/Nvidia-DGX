from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProjectTests(unittest.TestCase):
    def test_identity_is_pinned_and_private_by_default(self) -> None:
        config = (ROOT / "config" / "qwen38.env.example").read_text()
        self.assertIn("PUBLISH_HOST=127.0.0.1", config)
        self.assertIn("ALLOW_UNAUTHENTICATED_LAN=false", config)
        self.assertIn("PORT=8006", config)
        self.assertIn("CTX_SIZE=196608", config)
        self.assertRegex(config, r"LLAMA_IMAGE=.+@sha256:[0-9a-f]{64}")
        self.assertRegex(config, r"MODEL_SHA256=[0-9a-f]{64}")
        self.assertRegex(config, r"MMPROJ_SHA256=[0-9a-f]{64}")

    def test_runtime_and_hardware_are_explicit(self) -> None:
        common = (ROOT / "scripts" / "common.sh").read_text()
        self.assertIn("NVIDIARTXA6000,49140", common)
        self.assertIn("--n-gpu-layers 999", common)
        self.assertIn('--spec-type "${SPEC_TYPE}"', common)
        self.assertIn("ALLOW_UNAUTHENTICATED_LAN", common)

    def test_benchmark_uses_repository_harness(self) -> None:
        benchmark = (ROOT / "scripts" / "benchmark.sh").read_text()
        harness = (ROOT / "../../../benchmarks/legacy/qwen-deepseek-cross-model").resolve()
        self.assertTrue(harness.is_dir())
        self.assertIn("../../../benchmarks/legacy/qwen-deepseek-cross-model", benchmark)

    def test_lifecycle_checks_container_identity(self) -> None:
        common = (ROOT / "scripts" / "common.sh").read_text()
        self.assertIn("Config.Cmd == $expected_cmd", common)
        for name in ("status.sh", "stop.sh"):
            self.assertIn("verify_container", (ROOT / "scripts" / name).read_text())


if __name__ == "__main__":
    unittest.main()
