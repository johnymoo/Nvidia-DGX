from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import cmp_to_key
from pathlib import Path
from typing import Any, Iterable


RECIPE_REQUIRED = (
    "schema_version",
    "id",
    "model_family",
    "model_id",
    "hardware_id",
    "runtime_id",
    "profile_id",
    "modality",
    "maturity",
    "operations",
    "evidence",
    "limitations",
    "invalidation_conditions",
)
MATURITIES = {"Verified", "Reference", "Archived"}
MODALITIES = {
    "text-generation",
    "multimodal-generation",
    "media-generation",
    "embedding",
    "application",
}
README_MARKERS = {
    "best-verified": (
        "<!-- BEGIN GENERATED:best-verified -->",
        "<!-- END GENERATED:best-verified -->",
    ),
    "recipes": (
        "<!-- BEGIN GENERATED:recipes -->",
        "<!-- END GENERATED:recipes -->",
    ),
    "reference-results": (
        "<!-- BEGIN GENERATED:reference-results -->",
        "<!-- END GENERATED:reference-results -->",
    ),
}


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class RecipeRecord:
    path: Path
    data: dict[str, Any]


def read_json_object(path: Path, kind: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CatalogError(
            f"{path}: {kind} must use the JSON-compatible subset of YAML: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise CatalogError(f"{path}: {kind} must be a JSON object")
    return value


def validate_recipe(data: dict[str, Any], path: Path) -> list[str]:
    errors = [f"{path}: missing required field {name}" for name in RECIPE_REQUIRED if name not in data]
    if data.get("schema_version") != 1:
        errors.append(f"{path}: schema_version must be 1")
    if data.get("maturity") not in MATURITIES:
        errors.append(f"{path}: maturity must be one of {sorted(MATURITIES)}")
    if data.get("modality") not in MODALITIES:
        errors.append(f"{path}: unsupported modality {data.get('modality')!r}")
    if "operations" in data and not isinstance(data["operations"], dict):
        errors.append(f"{path}: operations must be an object")
    evidence = data.get("evidence")
    if not isinstance(evidence, dict):
        errors.append(f"{path}: evidence must be an object")
    else:
        for name in ("receipts", "benchmarks"):
            if not isinstance(evidence.get(name), list):
                errors.append(f"{path}: evidence.{name} must be an array")
    for name in ("limitations", "invalidation_conditions"):
        if name in data and not isinstance(data[name], list):
            errors.append(f"{path}: {name} must be an array")
    return errors


def discover_recipes(root: Path) -> list[RecipeRecord]:
    records: list[RecipeRecord] = []
    errors: list[str] = []
    seen: dict[str, Path] = {}
    for path in sorted((root / "recipes").glob("**/recipe.yaml")):
        try:
            data = read_json_object(path, "recipe metadata")
        except CatalogError as exc:
            errors.append(str(exc))
            continue
        errors.extend(validate_recipe(data, path))
        recipe_id = data.get("id")
        if isinstance(recipe_id, str):
            if recipe_id in seen:
                errors.append(f"{path}: duplicate recipe id {recipe_id!r}; first seen at {seen[recipe_id]}")
            else:
                seen[recipe_id] = path
        records.append(RecipeRecord(path=path, data=data))
    if errors:
        raise CatalogError("\n".join(errors))
    return records


def recipe_catalog(root: Path) -> dict[str, Any]:
    recipes = []
    for record in discover_recipes(root):
        item = dict(record.data)
        item["metadata_path"] = record.path.relative_to(root).as_posix()
        recipes.append(item)
    recipes.sort(key=lambda item: item["id"])
    return {"schema_version": 1, "recipes": recipes}


def discover_results(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    results = []
    errors = []
    seen: dict[str, Path] = {}
    for path in sorted((root / "results").glob("**/result.json")):
        try:
            data = read_json_object(path, "benchmark result")
        except CatalogError as exc:
            errors.append(str(exc))
            continue
        result_id = data.get("result_id")
        if not isinstance(result_id, str) or not result_id:
            errors.append(f"{path}: result_id must be a non-empty string")
        elif result_id in seen:
            errors.append(f"{path}: duplicate result id {result_id!r}; first seen at {seen[result_id]}")
        else:
            seen[result_id] = path
        results.append((path, data))
    if errors:
        raise CatalogError("\n".join(errors))
    return results


def dotted(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def explicit(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return value is not None
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    return False


def status_value(value: Any) -> Any:
    return value.get("status") if isinstance(value, dict) else value


def suite_identity(result: dict[str, Any]) -> str | None:
    suite = result.get("suite")
    if not isinstance(suite, dict):
        return None
    suite_id = suite.get("id")
    version = suite.get("version")
    if not isinstance(suite_id, str) or not isinstance(version, str):
        return None
    major = version.split(".", 1)[0]
    return f"{suite_id}@{major}" if major.isdigit() else None


def receipt_reasons(root: Path, result: dict[str, Any]) -> list[str]:
    receipt = result.get("receipt")
    if not isinstance(receipt, str) or not receipt.strip():
        return ["receipt is missing"]
    path = (root / receipt).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return ["receipt escapes the repository"]
    if not path.is_file():
        return ["receipt does not resolve to a repository file"]
    try:
        value = read_json_object(path, "deployment receipt")
    except CatalogError as exc:
        return [str(exc)]
    reasons = []
    if value.get("status") != "passed":
        reasons.append("receipt status is not 'passed'")
    if value.get("recipe_id") != result.get("recipe_id"):
        reasons.append("receipt recipe_id does not match result recipe_id")
    return reasons


def eligibility_reasons(
    root: Path,
    recipe: dict[str, Any] | None,
    result: dict[str, Any],
    policy: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if recipe is None:
        return ["recipe_id does not resolve to catalog metadata"]
    if recipe.get("maturity") != policy.get("eligible_maturity", "Verified"):
        reasons.append("recipe maturity is not Verified")
    if result.get("maturity") != policy.get("eligible_maturity", "Verified"):
        reasons.append("result maturity is not explicitly Verified")
    modality = recipe.get("modality")
    if modality in set(policy.get("excluded_modalities", [])):
        reasons.append(f"modality {modality!r} is excluded from token ranking")
    expected_suite = (policy.get("active_suites") or {}).get(modality)
    actual_suite = suite_identity(result)
    if not expected_suite or actual_suite != expected_suite:
        reasons.append(f"suite {actual_suite!r} does not match active suite {expected_suite!r}")
    for field in policy.get("required_identity", []):
        value = result.get("suite") if field == "suite" else dotted(result, field)
        if not explicit(value):
            reasons.append(f"required identity {field!r} is missing")
    for field, expected in (policy.get("required_status") or {}).items():
        if status_value(dotted(result, field)) != expected:
            reasons.append(f"status {field!r} is not {expected!r}")
    reasons.extend(receipt_reasons(root, result))
    for rule in policy.get("ranking", []):
        field = rule.get("field")
        value = dotted(result, field) if isinstance(field, str) else None
        valid = isinstance(value, str) and bool(value) if field == "result_id" else (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(float(value))
        )
        if not valid:
            reasons.append(f"ranking value {field!r} is missing or invalid")
    for floor in policy.get("eligibility_floors", []):
        field = floor.get("field")
        value = dotted(result, field) if isinstance(field, str) else None
        minimum = floor.get("minimum")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < minimum:
            reasons.append(f"eligibility floor {field!r} is not satisfied")
    return reasons


def _compare_results(policy: dict[str, Any], left: dict[str, Any], right: dict[str, Any]) -> int:
    for rule in policy.get("ranking", []):
        field = rule["field"]
        a, b = dotted(left, field), dotted(right, field)
        if a == b:
            continue
        if rule.get("order") == "desc":
            return -1 if a > b else 1
        return -1 if a < b else 1
    return 0


def _result_summary(root: Path, path: Path, result: dict[str, Any], recipe: dict[str, Any]) -> dict[str, Any]:
    return {
        "result_id": result["result_id"],
        "recipe_id": result["recipe_id"],
        "hardware_id": recipe["hardware_id"],
        "model_family": recipe["model_family"],
        "model_id": recipe["model_id"],
        "runtime_id": recipe["runtime_id"],
        "profile_id": recipe["profile_id"],
        "modality": recipe["modality"],
        "suite": result["suite"],
        "workload": result["workload"],
        "metrics": result["metrics"],
        "receipt": result["receipt"],
        "report": result.get("report"),
        "result_path": path.relative_to(root).as_posix(),
    }


def latest_benchmarks(root: Path, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    if policy is None:
        policy = read_json_object(root / "catalog" / "benchmark-policy.json", "benchmark policy")
    recipes = {item["id"]: item for item in recipe_catalog(root)["recipes"]}
    groups: dict[tuple[str, str], list[tuple[Path, dict[str, Any], dict[str, Any]]]] = {}
    references = []
    ineligible = []
    known_groups = {
        (item["hardware_id"], item["model_family"])
        for item in recipes.values()
        if item.get("modality") not in set(policy.get("excluded_modalities", []))
    }
    for path, result in discover_results(root):
        recipe = recipes.get(result.get("recipe_id"))
        reasons = eligibility_reasons(root, recipe, result, policy)
        if recipe and result.get("maturity") in {"Reference", "Archived"}:
            references.append(_result_summary(root, path, result, recipe))
        elif reasons:
            ineligible.append(
                {
                    "result_id": result.get("result_id"),
                    "result_path": path.relative_to(root).as_posix(),
                    "reasons": reasons,
                }
            )
        else:
            key = (recipe["hardware_id"], recipe["model_family"])
            groups.setdefault(key, []).append((path, result, recipe))
    selected = []
    overrides = policy.get("manual_overrides", [])
    if not isinstance(overrides, list):
        raise CatalogError("benchmark policy manual_overrides must be an array")
    for key, candidates in sorted(groups.items()):
        candidates.sort(key=cmp_to_key(lambda a, b: _compare_results(policy, a[1], b[1])))
        matching = [
            item
            for item in overrides
            if isinstance(item, dict)
            and (item.get("hardware_id"), item.get("model_family")) == key
        ]
        if len(matching) > 1:
            raise CatalogError(f"multiple manual overrides exist for group {key!r}")
        override = matching[0] if matching else None
        if override:
            if not isinstance(override.get("reason"), str) or not override["reason"].strip():
                raise CatalogError(f"manual override for group {key!r} requires a non-empty reason")
            chosen = next((item for item in candidates if item[1].get("result_id") == override.get("result_id")), None)
            if chosen is None:
                raise CatalogError(
                    f"manual override {override.get('result_id')!r} is not an eligible result in group {key!r}"
                )
        else:
            chosen = candidates[0]
        path, result, recipe = chosen
        summary = _result_summary(root, path, result, recipe)
        if override:
            summary["manual_override_reason"] = override["reason"]
        selected.append(summary)
    selected_groups = {(item["hardware_id"], item["model_family"]) for item in selected}
    no_eligible = [
        {
            "hardware_id": hardware,
            "model_family": model,
            "message": policy.get("no_eligible_state", "No eligible Verified result is available."),
        }
        for hardware, model in sorted(known_groups - selected_groups)
    ]
    references.sort(key=lambda item: item["result_id"])
    ineligible.sort(key=lambda item: (str(item["result_id"]), item["result_path"]))
    output = {
        "schema_version": 1,
        "policy_id": policy.get("policy_id"),
        "best_verified": selected,
        "reference_results": references,
    }
    if no_eligible:
        output["no_eligible_groups"] = no_eligible
    if ineligible:
        output["ineligible_verified"] = ineligible
    return output


def json_text(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def _md(value: Any) -> str:
    return str(value if value is not None else "N/A").replace("|", "\\|")


def recipe_fragment(catalog: dict[str, Any]) -> str:
    lines = ["| Hardware | Model | Runtime / profile | Maturity | Recipe |", "|---|---|---|---|---|"]
    for item in catalog["recipes"]:
        lines.append(
            f"| {_md(item['hardware_id'])} | {_md(item['model_id'])} | "
            f"{_md(item['runtime_id'])} / {_md(item['profile_id'])} | {_md(item['maturity'])} | "
            f"[`{_md(item['id'])}`]({_md(Path(item['metadata_path']).parent.as_posix())}/) |"
        )
    if not catalog["recipes"]:
        lines.append("| - | - | - | - | No canonical recipes are cataloged yet. |")
    return "\n".join(lines)


def best_verified_fragment(latest: dict[str, Any]) -> str:
    lines = [
        "| Hardware | Model family | Runtime / profile | Aggregate TPS | Decode TPS | TTFT | Evidence |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for item in latest["best_verified"]:
        metrics = item["metrics"]
        report = item.get("report") or item["result_path"]
        lines.append(
            f"| {_md(item['hardware_id'])} | {_md(item['model_family'])} | "
            f"{_md(item['runtime_id'])} / {_md(item['profile_id'])} | "
            f"{_md(dotted(metrics, 'aggregate_tokens_per_second.mean'))} | "
            f"{_md(dotted(metrics, 'decode_tokens_per_second.mean'))} | "
            f"{_md(dotted(metrics, 'ttft_seconds.mean'))} | "
            f"[result]({_md(item['result_path'])}) / [receipt]({_md(item['receipt'])}) / [report]({_md(report)}) |"
        )
    for item in latest.get("no_eligible_groups", []):
        lines.append(
            f"| {_md(item['hardware_id'])} | {_md(item['model_family'])} | - | - | - | - | "
            f"{_md(item['message'])} |"
        )
    if len(lines) == 2:
        lines.append("| - | - | - | - | - | - | No eligible Verified result is available. |")
    return "\n".join(lines)


def reference_results_fragment(latest: dict[str, Any]) -> str:
    lines = [
        "| Hardware | Model | Runtime / profile | TTFT | Response | Decode TPS | Aggregate TPS | Evidence |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for item in latest["reference_results"]:
        metrics = item["metrics"]
        report = item.get("report") or item["result_path"]
        lines.append(
            f"| {_md(item['hardware_id'])} | {_md(item['model_id'])} | "
            f"{_md(item['runtime_id'])} / {_md(item['profile_id'])} | "
            f"{_md(dotted(metrics, 'ttft_seconds.mean'))} | "
            f"{_md(dotted(metrics, 'response_time_seconds.mean'))} | "
            f"{_md(dotted(metrics, 'decode_tokens_per_second.mean'))} | "
            f"{_md(dotted(metrics, 'aggregate_tokens_per_second.mean'))} | "
            f"[result]({_md(item['result_path'])}) / [source]({_md(report)}) |"
        )
    if len(lines) == 2:
        lines.append("| - | - | - | - | - | - | - | No historical Reference result is cataloged. |")
    return "\n".join(lines)


def render_readme(readme: str, fragments: dict[str, str]) -> str:
    rendered = readme
    for name, fragment in fragments.items():
        if name not in README_MARKERS:
            raise CatalogError(f"unknown README generated fragment {name!r}")
        begin, end = README_MARKERS[name]
        begin_count, end_count = rendered.count(begin), rendered.count(end)
        if begin_count == end_count == 0:
            continue
        if begin_count != 1 or end_count != 1:
            raise CatalogError(f"README must contain exactly one marker pair for {name!r}")
        start = rendered.index(begin) + len(begin)
        finish = rendered.index(end, start)
        rendered = rendered[:start] + "\n" + fragment.rstrip() + "\n" + rendered[finish:]
    return rendered


def generated_outputs(root: Path) -> dict[Path, str]:
    recipes = recipe_catalog(root)
    latest = latest_benchmarks(root)
    outputs = {
        root / "catalog" / "recipes.json": json_text(recipes),
        root / "catalog" / "latest-benchmarks.json": json_text(latest),
    }
    readme_path = root / "README.md"
    if readme_path.is_file():
        original = readme_path.read_text(encoding="utf-8")
        rendered = render_readme(
            original,
            {
                "recipes": recipe_fragment(recipes),
                "best-verified": best_verified_fragment(latest),
                "reference-results": reference_results_fragment(latest),
            },
        )
        if rendered != original or any(marker[0] in original for marker in README_MARKERS.values()):
            outputs[readme_path] = rendered
    return outputs


def dispatch_command(root: Path, recipe_id: str, operation: str, extra: Iterable[str]) -> list[str]:
    recipes = {record.data["id"]: record for record in discover_recipes(root)}
    if recipe_id not in recipes:
        raise CatalogError(f"unknown recipe {recipe_id!r}")
    record = recipes[recipe_id]
    spec = record.data["operations"].get(operation)
    if spec is None:
        raise CatalogError(f"recipe {recipe_id!r} does not support operation {operation!r}")
    if isinstance(spec, str):
        command = [spec]
    elif isinstance(spec, list) and all(isinstance(item, str) for item in spec):
        command = list(spec)
    elif isinstance(spec, dict) and isinstance(spec.get("command"), list):
        command = list(spec["command"])
    else:
        raise CatalogError(f"recipe {recipe_id!r} operation {operation!r} has an invalid command")
    if not command:
        raise CatalogError(f"recipe {recipe_id!r} operation {operation!r} has an empty command")
    if not all(isinstance(item, str) for item in command):
        raise CatalogError(f"recipe {recipe_id!r} operation {operation!r} command must contain strings")
    executable = Path(command[0])
    executable = executable.resolve() if executable.is_absolute() else (record.path.parent / executable).resolve()
    try:
        executable.relative_to(root.resolve())
    except ValueError as exc:
        raise CatalogError("operation command escapes the repository") from exc
    if not executable.is_file():
        raise CatalogError(f"operation command does not exist: {executable}")
    command[0] = str(executable)
    return command + list(extra)
