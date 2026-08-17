from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from tools.catalog import dispatch_command, latest_benchmarks, recipe_catalog


ROOT = Path(__file__).resolve().parents[1]


class RepositoryContractTests(unittest.TestCase):
    def test_every_recipe_has_readme_wrapper_and_contained_operations(self) -> None:
        for recipe in recipe_catalog(ROOT)["recipes"]:
            directory = ROOT / Path(recipe["metadata_path"]).parent
            self.assertTrue((directory / "README.md").is_file(), recipe["id"])
            wrapper = directory / "run.sh"
            self.assertTrue(wrapper.is_file(), recipe["id"])
            completed = subprocess.run(["bash", str(wrapper)], capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, recipe["id"])
            for operation in recipe["operations"]:
                command = dispatch_command(ROOT, recipe["id"], operation, [])
                Path(command[0]).resolve().relative_to(ROOT.resolve())

    def test_minimax_accept_is_live_smoke_not_static_test(self) -> None:
        recipes = {item["id"]: item for item in recipe_catalog(ROOT)["recipes"]}
        operation = recipes["minimax-h3.gb10.comfyui-trained-max-15s"]["operations"]["accept"]
        self.assertIn("run-smoke.sh", operation[0])
        self.assertNotIn("test-recipe.sh", operation[0])

    def test_verified_recipes_have_exact_canonical_receipts(self) -> None:
        for recipe in recipe_catalog(ROOT)["recipes"]:
            if recipe["maturity"] != "Verified":
                continue
            directory = ROOT / Path(recipe["metadata_path"]).parent
            receipts = [item for item in recipe["evidence"]["receipts"] if item.endswith(".json")]
            self.assertTrue(receipts, recipe["id"])
            for relative in receipts:
                receipt = json.loads((directory / relative).read_text())
                self.assertEqual(receipt["status"], "passed")
                self.assertEqual(receipt["recipe_id"], recipe["id"])
                self.assertEqual(
                    receipt["subject"],
                    {
                        "model": recipe["model_id"],
                        "hardware": recipe["hardware_id"],
                        "runtime": recipe["runtime_id"],
                        "profile": recipe["profile_id"],
                    },
                )

    def test_deepseek_control_profile_is_isolated_and_archived(self) -> None:
        recipes = {item["id"]: item for item in recipe_catalog(ROOT)["recipes"]}
        on = recipes["deepseek-v4.dual-gb10.vllm-flash-0731-patch4-thinking-on"]
        off = recipes["deepseek-v4.dual-gb10.vllm-flash-0731-patch4-thinking-off"]
        self.assertNotEqual(on["profile_id"], off["profile_id"])
        self.assertEqual(on["maturity"], "Reference")
        self.assertEqual(off["maturity"], "Archived")
        self.assertFalse(off["default"])
        self.assertEqual(off["evidence"]["receipts"], [])
        selected = {item["recipe_id"] for item in latest_benchmarks(ROOT)["best_verified"]}
        self.assertNotIn(off["id"], selected)

    def test_no_current_reference_result_is_promoted(self) -> None:
        latest = latest_benchmarks(ROOT)
        self.assertEqual(latest["best_verified"], [])
        self.assertTrue(latest["reference_results"])

    def test_governance_snapshot_covers_current_open_work(self) -> None:
        snapshot = (ROOT / "docs/governance/open-work-20260818.md").read_text()
        for identifier in ("#11", "#13", "#15", "#23", "#26", "#34", "#27", "#32"):
            self.assertIn(identifier, snapshot)
        self.assertIn("no open pull requests", snapshot.lower())
        self.assertIn("default branch was `main`", snapshot.lower())

    def test_no_host_entrypoint_has_no_live_actions(self) -> None:
        script = (ROOT / "scripts/validate-no-host.sh").read_text()
        for forbidden in ("docker compose up", "docker run", "lab run", "ssh ", "run.sh run", "run.sh fake"):
            self.assertNotIn(forbidden, script.lower())
        self.assertIn("./run.sh test", script)
        self.assertIn("config --quiet", script)


if __name__ == "__main__":
    unittest.main()
