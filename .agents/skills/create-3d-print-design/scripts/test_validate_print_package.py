from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from validate_print_package import REQUIRED_CHECKS, REQUIRED_FILES, sha256, validate


class PackageValidatorTest(unittest.TestCase):
    def make_package(self, root: Path) -> dict:
        for relative in REQUIRED_FILES:
            if relative in {"manifest.json", "reports/validation.json", "reports/gate-d-conformance.json"}:
                continue
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture\n")
        (root / "source/cad").mkdir(parents=True, exist_ok=True)
        (root / "source/cad/generate.py").write_text("# fixture\n", encoding="utf-8")
        (root / "parts").mkdir(parents=True, exist_ok=True)
        (root / "parts/sample.step").write_bytes(b"step\n")
        (root / "parts/sample.stl").write_bytes(b"stl\n")
        checks = {check_id: True for check_id in REQUIRED_CHECKS}
        manifest = {
            "schema_version": "1.0",
            "design": "fixture",
            "revision": "r1",
            "status": "RELEASE CANDIDATE",
            "date": "2026-08-18",
            "units": "mm",
            "cad_kernel": {"build123d": "0.8.0", "ocp": "7.7.2"},
            "approved_envelope_mm": [100, 100, 100],
            "printer_envelope_mm": [220, 220, 250],
            "parameters": [{"id": "wall_mm", "value": 2.0, "unit": "mm", "status": "verified", "source": "design/freeze.json"}],
            "parts": [{
                "id": "sample",
                "quantity": 1,
                "material": "PETG",
                "print_orientation": "flat",
                "bbox_mm": [10, 20, 30],
                "validation": {"valid_brep": True, "mesh_closed": True},
                "step": "parts/sample.step",
                "stl": "parts/sample.stl",
                "sha256": {
                    "step": sha256(root / "parts/sample.step"),
                    "stl": sha256(root / "parts/sample.stl"),
                },
            }],
            "purchased_parts": [],
            "assemblies": [
                "assemblies/assembled.step",
                "assemblies/exploded.step",
                "assemblies/fit-reference.step",
            ],
            "fit_gauges": [],
            "drawings": [
                "drawings/exploded-assembly.png",
                "drawings/part-orientation-sheet.png",
                "drawings/dimensional-inspection.pdf",
            ],
            "documents": [
                "docs/assembly.md",
                "docs/bom.csv",
                "docs/print-instructions.md",
                "docs/test-plan.md",
                "docs/known-risks.md",
            ],
            "reports": [
                "reports/validation.json",
                "reports/gate-d-conformance.json",
                "reports/dfm-review.md",
            ],
            "unresolved_measurements": [],
            "prototype_exceptions": [],
            "physical_tests": [],
            "dfm_checks": [
                {"id": "H01", "phase": "HARD_PRE_CAD", "applicable": True, "result": "PASS", "evidence": "reports/dfm-review.md"},
                {"id": "H14", "phase": "HARD_CAD_EXPORT", "applicable": True, "result": "PASS", "evidence": "reports/validation.json"},
            ],
            "checks": checks,
        }
        self.write_manifest_and_reports(root, manifest)
        return manifest

    def write_manifest_and_reports(self, root: Path, manifest: dict) -> None:
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (root / "reports/validation.json").write_text(json.dumps({"checks": manifest.get("checks")}), encoding="utf-8")
        conformance = {"freeze_sha256": sha256(root / "design/freeze.json"), "conformant": manifest.get("checks", {}).get("gate_d_conformance_pass")}
        (root / "reports/gate-d-conformance.json").write_text(json.dumps(conformance), encoding="utf-8")
        self.write_checksums(root)

    @staticmethod
    def write_checksums(root: Path) -> None:
        lines = []
        for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file() and not candidate.is_symlink() and candidate.name != "SHA256SUMS"):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest}  {path.relative_to(root)}")
        (root / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_accepts_complete_candidate_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_package(root)
            errors, warnings = validate(root)
            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_rejects_manifest_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_package(root)
            manifest["parts"][0]["step"] = "../../outside.step"
            self.write_manifest_and_reports(root, manifest)
            errors, _ = validate(root)
            self.assertTrue(any("escapes root" in error for error in errors), errors)

    def test_candidate_rejects_false_or_non_boolean_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_package(root)
            manifest["checks"]["all_parts_valid"] = False
            manifest["checks"]["all_meshes_closed"] = "PASS"
            self.write_manifest_and_reports(root, manifest)
            errors, _ = validate(root)
            self.assertTrue(any("must be boolean" in error for error in errors), errors)
            self.assertTrue(any("Failed required checks" in error for error in errors), errors)

    def test_rejects_empty_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_package(root)
            manifest["checks"] = {}
            self.write_manifest_and_reports(root, manifest)
            errors, _ = validate(root)
            self.assertTrue(any("non-empty object" in error for error in errors), errors)

    def test_released_requires_physical_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_package(root)
            manifest["status"] = "RELEASED"
            self.write_manifest_and_reports(root, manifest)
            errors, _ = validate(root)
            self.assertTrue(any("physical test decision" in error for error in errors), errors)

    def test_rejects_external_symbolic_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            self.make_package(root)
            (Path(outside) / "external.txt").write_text("outside", encoding="utf-8")
            (root / "docs/external-link").symlink_to(Path(outside) / "external.txt")
            errors, _ = validate(root)
            self.assertTrue(any("Symbolic links are not allowed" in error for error in errors), errors)

    def test_rejects_corrupt_manifest_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_package(root)
            (root / "manifest.json").write_text("{", encoding="utf-8")
            self.write_checksums(root)
            errors, _ = validate(root)
            self.assertTrue(any("Invalid JSON" in error for error in errors), errors)

    def test_rejects_duplicate_checksum_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_package(root)
            sums = root / "SHA256SUMS"
            first_line = sums.read_text(encoding="utf-8").splitlines()[0]
            sums.write_text(sums.read_text(encoding="utf-8") + first_line + "\n", encoding="utf-8")
            errors, _ = validate(root)
            self.assertTrue(any("Duplicate SHA256SUMS target" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
