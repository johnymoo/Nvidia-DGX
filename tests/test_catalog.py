from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.catalog import (
    CatalogError,
    best_verified_fragment,
    dispatch_command,
    generated_outputs,
    latest_benchmarks,
    read_json_object,
    recipe_catalog,
    render_readme,
)


FIXTURE = Path(__file__).parent / "fixtures" / "catalog-repo"


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        shutil.copytree(FIXTURE, self.root, dirs_exist_ok=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_recipe_catalog_reads_json_compatible_yaml_deterministically(self) -> None:
        recipes = recipe_catalog(self.root)["recipes"]
        self.assertEqual([item["id"] for item in recipes], ["model.reference", "model.verified"])
        self.assertEqual(recipes[1]["metadata_path"], "recipes/model/verified/recipe.yaml")

    def test_recipe_reader_rejects_non_json_yaml(self) -> None:
        path = self.root / "bad.yaml"
        path.write_text("id: not-json\n")
        with self.assertRaisesRegex(CatalogError, "JSON-compatible subset"):
            read_json_object(path, "recipe metadata")

    def test_best_verified_is_fail_closed_and_uses_declared_tie_breakers(self) -> None:
        latest = latest_benchmarks(self.root)
        self.assertEqual([item["result_id"] for item in latest["best_verified"]], ["run-b"])
        self.assertEqual([item["result_id"] for item in latest["reference_results"]], ["run-ref"])
        rejected = {item["result_id"]: item["reasons"] for item in latest["ineligible_verified"]}
        self.assertIn("run-incomplete", rejected)
        self.assertTrue(any("safety" in reason for reason in rejected["run-incomplete"]))
        self.assertTrue(any("receipt" in reason for reason in rejected["run-incomplete"]))
        self.assertTrue(any("ttft" in reason for reason in rejected["run-incomplete"]))

    def test_reference_recipe_is_never_promoted(self) -> None:
        latest = latest_benchmarks(self.root)
        selected = {item["recipe_id"] for item in latest["best_verified"]}
        self.assertNotIn("model.reference", selected)

    def test_manual_override_requires_reason_and_an_eligible_result(self) -> None:
        policy_path = self.root / "catalog/benchmark-policy.json"
        policy = json.loads(policy_path.read_text())
        policy["manual_overrides"] = [
            {
                "hardware_id": "gpu-a",
                "model_family": "model-family",
                "result_id": "run-a",
                "reason": "Prefer the lower TTFT for this published profile.",
            }
        ]
        policy_path.write_text(json.dumps(policy))
        selected = latest_benchmarks(self.root)["best_verified"][0]
        self.assertEqual(selected["result_id"], "run-a")
        self.assertIn("lower TTFT", selected["manual_override_reason"])

        policy["manual_overrides"][0]["reason"] = ""
        policy_path.write_text(json.dumps(policy))
        with self.assertRaisesRegex(CatalogError, "non-empty reason"):
            latest_benchmarks(self.root)

    def test_receipt_identity_mismatch_is_ineligible(self) -> None:
        receipt = self.root / "results/gpu-a/model/run-a/receipt.json"
        receipt.write_text('{"status":"passed","recipe_id":"another.recipe"}\n')
        latest = latest_benchmarks(self.root)
        rejected = {item["result_id"]: item["reasons"] for item in latest["ineligible_verified"]}
        self.assertIn("receipt recipe_id does not match", " ".join(rejected["run-a"]))

    def test_readme_renderer_only_replaces_explicit_markers(self) -> None:
        source = "# Lab\n\n<!-- BEGIN GENERATED:best-verified -->\nold\n<!-- END GENERATED:best-verified -->\n"
        fragment = best_verified_fragment(latest_benchmarks(self.root))
        rendered = render_readme(source, {"best-verified": fragment})
        self.assertIn("run-b", rendered)
        self.assertNotIn("\nold\n", rendered)
        self.assertEqual(render_readme("# No markers\n", {"best-verified": fragment}), "# No markers\n")

    def test_generated_outputs_are_stable(self) -> None:
        (self.root / "README.md").write_text("# Fixture\n")
        outputs = generated_outputs(self.root)
        first = {path.relative_to(self.root): content for path, content in outputs.items()}
        second = {path.relative_to(self.root): content for path, content in generated_outputs(self.root).items()}
        self.assertEqual(first, second)
        self.assertEqual(json.loads(first[Path("catalog/recipes.json")])["schema_version"], 1)

    def test_dispatch_resolves_only_repository_commands(self) -> None:
        command = dispatch_command(self.root, "model.verified", "status", ["--brief"])
        self.assertEqual(Path(command[0]).name, "status.sh")
        self.assertEqual(command[-1], "--brief")

    def test_dispatch_rejects_commands_outside_repository(self) -> None:
        recipe = self.root / "recipes/model/verified/recipe.yaml"
        value = json.loads(recipe.read_text())
        value["operations"]["status"] = "/bin/true"
        recipe.write_text(json.dumps(value))
        with self.assertRaisesRegex(CatalogError, "escapes the repository"):
            dispatch_command(self.root, "model.verified", "status", [])


if __name__ == "__main__":
    unittest.main()
