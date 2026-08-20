#!/usr/bin/env python3
"""Validate the structure, release gates, and internal paths of a print package."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


REQUIRED_FILES = (
    "README.md",
    "manifest.json",
    "source/pyproject.toml",
    "source/uv.lock",
    "design/freeze.json",
    "docs/assembly.md",
    "docs/bom.csv",
    "docs/print-instructions.md",
    "docs/test-plan.md",
    "docs/known-risks.md",
    "reports/validation.json",
    "reports/gate-d-conformance.json",
    "reports/dfm-review.md",
    "assemblies/assembled.step",
    "assemblies/exploded.step",
    "assemblies/fit-reference.step",
    "drawings/exploded-assembly.png",
    "drawings/part-orientation-sheet.png",
    "drawings/dimensional-inspection.pdf",
)

REQUIRED_MANIFEST_KEYS = (
    "schema_version",
    "design",
    "revision",
    "status",
    "date",
    "units",
    "cad_kernel",
    "approved_envelope_mm",
    "printer_envelope_mm",
    "parameters",
    "parts",
    "purchased_parts",
    "assemblies",
    "fit_gauges",
    "drawings",
    "documents",
    "reports",
    "unresolved_measurements",
    "prototype_exceptions",
    "physical_tests",
    "dfm_checks",
    "checks",
)

REQUIRED_CHECKS = (
    "all_parts_valid",
    "all_meshes_closed",
    "all_parts_within_build_volume",
    "assembly_collision_free",
    "keepouts_clear",
    "manifest_complete",
    "hard_dfm_pre_cad_pass",
    "hard_dfm_cad_export_pass",
    "gate_d_conformance_pass",
)

REQUIRED_PATH_COLLECTIONS = (
    "assemblies",
    "fit_gauges",
    "drawings",
    "documents",
    "reports",
)

REQUIRED_COLLECTION_PATHS = {
    "assemblies": {
        "assemblies/assembled.step",
        "assemblies/exploded.step",
        "assemblies/fit-reference.step",
    },
    "drawings": {
        "drawings/exploded-assembly.png",
        "drawings/part-orientation-sheet.png",
        "drawings/dimensional-inspection.pdf",
    },
    "documents": {
        "docs/assembly.md",
        "docs/bom.csv",
        "docs/print-instructions.md",
        "docs/test-plan.md",
        "docs/known-risks.md",
    },
    "reports": {
        "reports/validation.json",
        "reports/gate-d-conformance.json",
        "reports/dfm-review.md",
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, errors: list[str]) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"Invalid JSON {path}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"Expected JSON object: {path}")
        return {}
    return value


def package_path(root: Path, relative: object, errors: list[str], label: str) -> Path | None:
    if not isinstance(relative, str) or not relative:
        errors.append(f"Invalid package path for {label}: {relative!r}")
        return None
    unresolved = root / relative
    if unresolved.is_symlink():
        errors.append(f"Symbolic links are not allowed for {label}: {relative}")
        return None
    candidate = unresolved.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        errors.append(f"Package path escapes root for {label}: {relative}")
        return None
    return candidate


def item_path(item: object) -> object:
    return item.get("path") if isinstance(item, dict) else item


def validate_path_collection(root: Path, manifest: dict, key: str, errors: list[str]) -> None:
    values = manifest.get(key)
    if not isinstance(values, list):
        errors.append(f"Manifest {key} must be a list")
        return
    declared: set[str] = set()
    for index, item in enumerate(values):
        relative = item_path(item)
        if isinstance(relative, str):
            declared.add(relative)
        path = package_path(root, relative, errors, f"{key}[{index}]")
        if path is not None and not path.is_file():
            errors.append(f"Manifest path does not exist for {key}[{index}]: {relative}")
    missing = sorted(REQUIRED_COLLECTION_PATHS.get(key, set()) - declared)
    if missing:
        errors.append(f"Manifest {key} omits required paths: " + ", ".join(missing))


def validate_parameters(manifest: dict, errors: list[str]) -> None:
    parameters = manifest.get("parameters")
    if not isinstance(parameters, list) or not parameters:
        errors.append("Manifest parameters must be a non-empty list")
        return
    seen: set[str] = set()
    for index, record in enumerate(parameters):
        label = f"parameters[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{label} must be an object")
            continue
        parameter_id = record.get("id")
        if not isinstance(parameter_id, str) or not parameter_id:
            errors.append(f"{label} missing id")
        elif parameter_id in seen:
            errors.append(f"Duplicate parameter id: {parameter_id}")
        else:
            seen.add(parameter_id)
        for key in ("value", "unit", "status", "source"):
            if key not in record:
                errors.append(f"{label} missing {key}")
        if record.get("status") not in {"verified", "derived", "provisional", "unknown"}:
            errors.append(f"Invalid parameter status for {label}: {record.get('status')!r}")


def validate_purchased_parts(manifest: dict, errors: list[str]) -> None:
    parts = manifest.get("purchased_parts")
    if not isinstance(parts, list):
        errors.append("Manifest purchased_parts must be a list")
        return
    for index, record in enumerate(parts):
        label = f"purchased_parts[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{label} must be an object")
            continue
        for key in ("id", "description", "quantity"):
            if key not in record:
                errors.append(f"{label} missing {key}")


def validate_checks(manifest: dict, status: object, errors: list[str], warnings: list[str]) -> None:
    checks = manifest.get("checks")
    if not isinstance(checks, dict) or not checks:
        errors.append("Manifest checks must be a non-empty object")
        return
    for check_id in REQUIRED_CHECKS:
        if check_id not in checks:
            errors.append(f"Manifest missing required check: {check_id}")
        elif type(checks[check_id]) is not bool:
            errors.append(f"Manifest check must be boolean: {check_id}")
    failures = sorted(check_id for check_id in REQUIRED_CHECKS if checks.get(check_id) is False)
    if status in {"RELEASE CANDIDATE", "RELEASED"} and failures:
        errors.append("Failed required checks for release status: " + ", ".join(failures))
    elif failures:
        warnings.append("Prototype has failed required checks: " + ", ".join(failures))


def validate_dfm(manifest: dict, status: object, errors: list[str]) -> None:
    records = manifest.get("dfm_checks")
    if not isinstance(records, list) or not records:
        errors.append("Manifest dfm_checks must be a non-empty list")
        return
    seen: set[str] = set()
    for index, record in enumerate(records):
        label = f"dfm_checks[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{label} must be an object")
            continue
        check_id = record.get("id")
        phase = record.get("phase")
        applicable = record.get("applicable")
        result = record.get("result")
        if not isinstance(check_id, str) or not check_id:
            errors.append(f"{label} missing id")
        elif check_id in seen:
            errors.append(f"Duplicate DFM check id: {check_id}")
        else:
            seen.add(check_id)
        if phase not in {"HARD_PRE_CAD", "HARD_CAD_EXPORT", "HARD_RELEASE", "RECOMMENDED", "CONFIG"}:
            errors.append(f"Invalid DFM phase for {label}: {phase!r}")
        if type(applicable) is not bool:
            errors.append(f"DFM applicable must be boolean for {label}")
        if result not in {"PASS", "FAIL", "NA", "BLOCKED"}:
            errors.append(f"Invalid DFM result for {label}: {result!r}")
        if applicable is True and phase in {"HARD_PRE_CAD", "HARD_CAD_EXPORT"} and result != "PASS":
            errors.append(f"Applicable {phase} check did not pass: {check_id}")
        if status == "RELEASED" and applicable is True and phase == "HARD_RELEASE" and result != "PASS":
            errors.append(f"Applicable HARD_RELEASE check did not pass: {check_id}")
        if applicable is True and phase.startswith("HARD_") and not record.get("evidence"):
            errors.append(f"Applicable hard DFM check missing evidence: {check_id}")


def validate_physical_tests(root: Path, manifest: dict, status: object, errors: list[str]) -> None:
    tests = manifest.get("physical_tests")
    if not isinstance(tests, list):
        errors.append("Manifest physical_tests must be a list")
        return
    by_id = {test.get("id"): test for test in tests if isinstance(test, dict) and isinstance(test.get("id"), str)}
    if status != "RELEASED":
        return
    for test_id in ("first_article_fit", "load", "thermal", "lifecycle"):
        record = by_id.get(test_id)
        if not isinstance(record, dict):
            errors.append(f"RELEASED package missing physical test decision: {test_id}")
            continue
        applicable = record.get("applicable")
        if type(applicable) is not bool:
            errors.append(f"Physical test applicable must be boolean: {test_id}")
            continue
        if test_id == "first_article_fit" and applicable is not True:
            errors.append("first_article_fit must be applicable for RELEASED")
        if applicable:
            if record.get("result") != "PASS":
                errors.append(f"Applicable physical test did not pass: {test_id}")
            evidence = record.get("evidence")
            path = package_path(root, evidence, errors, f"physical_tests.{test_id}.evidence")
            if path is not None and not path.is_file():
                errors.append(f"Physical test evidence missing: {evidence}")
        elif not record.get("rationale"):
            errors.append(f"Non-applicable physical test missing rationale: {test_id}")


def validate_parts(root: Path, manifest: dict, errors: list[str]) -> None:
    parts = manifest.get("parts")
    if not isinstance(parts, list) or not parts:
        errors.append("Manifest parts must be a non-empty list")
        return
    seen: set[str] = set()
    for index, part in enumerate(parts):
        label = f"parts[{index}]"
        if not isinstance(part, dict):
            errors.append(f"{label} must be an object")
            continue
        part_id = part.get("id")
        if not isinstance(part_id, str) or not part_id:
            errors.append(f"{label} missing id")
            continue
        if part_id in seen:
            errors.append(f"Duplicate part id: {part_id}")
        seen.add(part_id)
        checksums = part.get("sha256")
        if not isinstance(checksums, dict):
            errors.append(f"Part {part_id} missing sha256 object")
            checksums = {}
        for extension in ("step", "stl"):
            relative = part.get(extension)
            path = package_path(root, relative, errors, f"{part_id}.{extension}")
            if path is not None:
                if not path.is_file():
                    errors.append(f"Missing {extension.upper()} for {part_id}: {relative}")
                elif checksums.get(extension) != sha256(path):
                    errors.append(f"Part checksum mismatch for {part_id}.{extension}")
        for key in ("quantity", "material", "print_orientation", "bbox_mm", "validation"):
            if key not in part:
                errors.append(f"Part {part_id} missing {key}")


def validate_reports(root: Path, manifest: dict, errors: list[str]) -> None:
    validation = load_json(root / "reports/validation.json", errors)
    report_checks = validation.get("checks")
    manifest_checks = manifest.get("checks")
    if isinstance(report_checks, dict) and isinstance(manifest_checks, dict):
        for check_id in REQUIRED_CHECKS:
            if report_checks.get(check_id) != manifest_checks.get(check_id):
                errors.append(f"Validation report disagrees with manifest check: {check_id}")
    else:
        errors.append("Validation report must contain checks object")

    freeze_path = root / "design/freeze.json"
    conformance = load_json(root / "reports/gate-d-conformance.json", errors)
    if conformance.get("freeze_sha256") != sha256(freeze_path):
        errors.append("Gate D conformance freeze_sha256 does not match design/freeze.json")
    if type(conformance.get("conformant")) is not bool:
        errors.append("Gate D conformance must contain boolean conformant")
    elif conformance.get("conformant") is not manifest.get("checks", {}).get("gate_d_conformance_pass"):
        errors.append("Gate D conformance result disagrees with manifest")


def validate_checksums(root: Path, errors: list[str]) -> None:
    sums_path = root / "SHA256SUMS"
    if not sums_path.is_file():
        errors.append("Missing required file: SHA256SUMS")
        return
    checksum_targets: set[Path] = set()
    for line_number, line in enumerate(sums_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        fields = line.split(maxsplit=1)
        if len(fields) != 2:
            errors.append(f"Malformed SHA256SUMS line {line_number}")
            continue
        expected, relative = fields[0], fields[1].lstrip(" *")
        path = package_path(root, relative, errors, f"SHA256SUMS line {line_number}")
        if path is None:
            continue
        if path in checksum_targets:
            errors.append(f"Duplicate SHA256SUMS target: {relative}")
        checksum_targets.add(path)
        if not path.is_file():
            errors.append(f"Checksum target missing: {relative}")
        elif sha256(path) != expected.lower():
            errors.append(f"Checksum mismatch: {relative}")

    package_files: set[Path] = set()
    for raw_path in root.rglob("*"):
        if raw_path == sums_path:
            continue
        if raw_path.is_symlink():
            errors.append(f"Symbolic links are not allowed: {raw_path.relative_to(root)}")
        elif raw_path.is_file():
            package_files.add(raw_path.resolve())
    unchecked = sorted(str(path.relative_to(root)) for path in package_files - checksum_targets)
    if unchecked:
        errors.append("Files missing from SHA256SUMS: " + ", ".join(unchecked))


def validate(root: Path) -> tuple[list[str], list[str]]:
    root = root.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    for relative in REQUIRED_FILES:
        if not (root / relative).is_file():
            errors.append(f"Missing required file: {relative}")
    cad_sources = list((root / "source/cad").glob("*.py")) if (root / "source/cad").is_dir() else []
    if not cad_sources:
        errors.append("Missing parametric CAD source: source/cad/*.py")

    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return errors, warnings
    manifest = load_json(manifest_path, errors)
    for key in REQUIRED_MANIFEST_KEYS:
        if key not in manifest:
            errors.append(f"Manifest missing key: {key}")
    if manifest.get("schema_version") != "1.0":
        errors.append(f"Unsupported manifest schema_version: {manifest.get('schema_version')!r}")
    status = manifest.get("status")
    if status not in {"PROTOTYPE", "RELEASE CANDIDATE", "RELEASED"}:
        errors.append(f"Invalid release status: {status!r}")
    for key in ("approved_envelope_mm", "printer_envelope_mm"):
        value = manifest.get(key)
        if not isinstance(value, list) or len(value) != 3 or not all(isinstance(axis, (int, float)) and axis > 0 for axis in value):
            errors.append(f"Manifest {key} must contain three positive numbers")
    validate_parameters(manifest, errors)
    validate_purchased_parts(manifest, errors)
    if not isinstance(manifest.get("unresolved_measurements"), list):
        errors.append("Manifest unresolved_measurements must be a list")
    if not isinstance(manifest.get("prototype_exceptions"), list):
        errors.append("Manifest prototype_exceptions must be a list")
    elif status in {"RELEASE CANDIDATE", "RELEASED"} and manifest.get("prototype_exceptions"):
        errors.append(f"{status} package cannot contain prototype_exceptions")
    if status == "RELEASED" and manifest.get("unresolved_measurements"):
        errors.append("RELEASED package cannot contain unresolved_measurements")

    validate_parts(root, manifest, errors)
    for key in REQUIRED_PATH_COLLECTIONS:
        validate_path_collection(root, manifest, key, errors)
    validate_checks(manifest, status, errors, warnings)
    validate_dfm(manifest, status, errors)
    validate_physical_tests(root, manifest, status, errors)
    if all((root / relative).is_file() for relative in ("reports/validation.json", "reports/gate-d-conformance.json", "design/freeze.json")):
        validate_reports(root, manifest, errors)
    validate_checksums(root, errors)
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    root = args.package.resolve()
    if not root.is_dir():
        print(f"ERROR: package directory does not exist: {root}", file=sys.stderr)
        return 2
    errors, warnings = validate(root)
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    print(f"Checked {root}: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
