from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProjectTests(unittest.TestCase):
    def test_selected_artifacts_are_pinned(self) -> None:
        config = (ROOT / "config" / "qwen38.env.example").read_text()
        self.assertIn("Qwen3.8-27B-UD-Q4_K_XL.gguf", config)
        self.assertIn("MODEL_REVISION=f1bfb127c64f7072bdd2cad55f258b9c8b2910fe", config)
        self.assertRegex(config, r"LLAMA_IMAGE=.+@sha256:[0-9a-f]{64}")
        self.assertRegex(config, r"MODEL_SHA256=[0-9a-f]{64}")
        self.assertRegex(config, r"MMPROJ_SHA256=[0-9a-f]{64}")
        self.assertIn("SPEC_TYPE=draft-mtp", config)
        self.assertIn("SPEC_DRAFT_N_MAX=2", config)
        self.assertIn("SPEC_DRAFT_P_MIN=0", config)

    def test_runtime_disables_cpu_weight_offload(self) -> None:
        common = (ROOT / "scripts" / "common.sh").read_text()
        self.assertIn("--n-gpu-layers 999", common)
        self.assertIn("--ctx-size", common)
        self.assertIn("--reasoning-format deepseek", common)
        self.assertIn('--spec-type "${SPEC_TYPE}"', common)
        self.assertIn('--spec-draft-n-max "${SPEC_DRAFT_N_MAX}"', common)
        self.assertIn('--spec-draft-p-min "${SPEC_DRAFT_P_MIN}"', common)

    def test_lifecycle_checks_container_identity(self) -> None:
        common = (ROOT / "scripts" / "common.sh").read_text()
        self.assertIn("Config.Cmd == $expected_cmd", common)
        for name in ("status.sh", "stop.sh"):
            self.assertIn("verify_container", (ROOT / "scripts" / name).read_text())


if __name__ == "__main__":
    unittest.main()
