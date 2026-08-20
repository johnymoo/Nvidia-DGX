# 3D Print Package Contract

## Canonical Layout

```text
<design>-<revision>/
  README.md
  manifest.json
  SHA256SUMS
  source/
    cad/
    pyproject.toml
    uv.lock
  design/
    freeze.json
  parts/
    <part-id>.step
    <part-id>.stl
  assemblies/
    assembled.step
    exploded.step
    fit-reference.step
  fit-gauges/
    <gauge-id>.step
    <gauge-id>.stl
  drawings/
    exploded-assembly.png
    part-orientation-sheet.png
    dimensional-inspection.pdf
  docs/
    assembly.md
    bom.csv
    print-instructions.md
    test-plan.md
    known-risks.md
  reports/
    validation.json
    gate-d-conformance.json
    dfm-review.md
```

Optional 3MF files may be included in `parts/`, but they do not replace STEP and STL unless the user explicitly changes the contract.

## Manifest

`manifest.json` uses `schema_version: "1.0"`. Its formal schema is [manifest-schema-v1.json](manifest-schema-v1.json); the package validator adds status-dependent and filesystem checks that JSON Schema alone cannot express. The manifest must contain:

- design ID, revision, status, date, units, CAD kernel and versions;
- approved overall envelope and configured printer envelope;
- non-empty parameter records with ID, value, unit, `verified/derived/provisional/unknown` status, and source/provenance;
- printed parts with ID, quantity, material, files, print orientation, bounding box, validation results, and checksum;
- purchased parts with supplier/manufacturer part number where known;
- assemblies, gauges, drawings, documents, and report paths as explicit package-relative paths;
- unresolved measurements, prototype exceptions, required physical tests, and known risks;
- DFM check records with phase, applicability, result, and evidence;
- aggregate checks with explicit booleans, not only prose.

Required aggregate check IDs are `all_parts_valid`, `all_meshes_closed`, `all_parts_within_build_volume`, `assembly_collision_free`, `keepouts_clear`, `manifest_complete`, `hard_dfm_pre_cad_pass`, `hard_dfm_cad_export_pass`, and `gate_d_conformance_pass`. Every status must include all IDs as booleans. `RELEASE CANDIDATE` and `RELEASED` require all to be `true`; `PROTOTYPE` may contain `false` with named exceptions.

Physical tests are records with `id`, `applicable`, `result`, `evidence`, and `rationale`. `RELEASED` requires `first_article_fit` plus explicit applicability decisions for `load`, `thermal`, and `lifecycle`; every applicable test must be `PASS` with a package-relative evidence file.

## BOM

The BOM must include `item_id`, `description`, `type`, `quantity`, `material_or_mpn`, `supplier`, `source_url`, `critical_dimension`, `alternate`, and `notes`. Mark provisional commercial parts and do not invent supplier SKUs.

## Print Instructions

Provide per-part orientation, nozzle, layer height, wall/perimeter count, top/bottom layers, infill and pattern, supports, brim/raft, material/drying needs, seam concerns, expected post-processing, insert installation, and estimated mass/time when available from a real slicer. Do not fabricate slicer estimates.

## Assembly Instructions

Use stable part IDs matching filenames and exploded-view callouts. State assembly order, fastener torque only when sourced, cable routing, adhesive cure time, snap insertion direction, inspection points, and disassembly/service order.

## Release Status

- `PROTOTYPE`: fit, load, thermal, lifecycle, or source dimensions remain unverified.
- `RELEASE CANDIDATE`: all required automated checks pass and the design is ready for specified first-article tests.
- `RELEASED`: required first-article fit, functional, thermal, and load/lifecycle tests are attached and passed.

No generated artifact may claim `RELEASED` solely from CAD or mesh validation.
