# Parametric CAD Pipeline

## Manufacturing Kernel

Use the proven GB10 enclosure stack as the default baseline:

- Python 3.9-3.12;
- `build123d==0.8.0`;
- `cadquery-ocp==7.7.2` / OpenCascade;
- `numpy==2.0.2` when geometry or mesh calculations need it;
- `matplotlib==3.9.4` for deterministic preview renders;
- `py-lib3mf==2.3.1` only when producing 3MF;
- `uv` for environment locking;
- `unittest` or the project's existing test runner.

Pin compatible versions. Build123d 0.8.0 calls APIs removed from newer OCP releases, so do not float OCP without retesting.

## Source Layout

```text
cad/
  generate.py
  parameters.py          # optional when the design is large
  test_generate.py
  README.md
pyproject.toml
uv.lock
```

Keep a typed `Params` dataclass or equivalent as the dimensional source of truth. Distinguish:

- design parameters: verified product dimensions, chosen clearances, wall thicknesses;
- process parameters: printer envelope, nozzle, expected XY/Z compensation;
- export parameters: STL chord/angular tolerance;
- review-only parameters: exploded offsets, colors, annotations.

Review-only parameters must never alter manufactured geometry.

## Part Contract

Represent each printable component with a record equivalent to:

```python
@dataclass(frozen=True)
class PartSpec:
    name: str
    assembly_shape: Shape
    print_shape: Shape
    quantity: int
    material: str
    print_orientation: str
    notes: str
```

Use stable lowercase IDs. Keep assembled and print-oriented shapes separate. Export the `print_shape` for per-part STL/STEP and the `assembly_shape` in assemblies.

## Required Generation Flow

1. Validate parameter ranges and relationships before creating solids.
2. Build purchased-component references and keep-out volumes.
3. Build each printable part as a valid solid. Prefer explicit booleans and fillets over mesh operations.
4. Build fit gauges from the same parameters as the production part.
5. Export per-part STEP/STL with deterministic paths.
6. Export assembled, exploded, and fit-reference compounds.
7. Calculate validation evidence and write `reports/validation.json`.
8. Write `manifest.json` only after all exports exist.
9. Render assembled, exploded, and per-part contact-sheet previews.
10. Compare the generated design against `design/freeze.json` and write `reports/gate-d-conformance.json` before packaging.

## Automated Evidence

For every part record:

- `valid_brep` and expected solid count;
- volume and axis-aligned bounding box;
- required print envelope versus actual print-oriented bounding box;
- STL triangle count, closed/manifold status, and degenerate facets where available;
- STEP/STL relative paths and SHA-256;
- material, quantity, orientation, support/brim note;
- critical dimensions and status/provenance references.

For every assembly record:

- part IDs and transforms;
- purchased-component references;
- pairwise collision results for explicitly expected-clearance pairs;
- keep-out and service-motion collision results;
- overall approved envelope.

Do not treat all touching parts as collisions. Maintain an allowlist of intentional interfaces and check unexpected overlap volume against a documented tolerance.

## Minimum Tests

- all printable shapes are valid and have the intended number of solids;
- all export IDs are unique and stable;
- all print-oriented parts fit the configured build volume;
- the assembled envelope matches the approved bounds;
- critical clearances stay above their parameterized minima;
- mirrored/optional parts preserve interface locations;
- devices, connectors, and cable keep-outs do not intersect printed parts;
- generated meshes are closed and manifold;
- manifest paths exist and checksums match.
- Gate D freeze digest matches and frozen part IDs, interfaces, critical dimensions, assembly order, airflow/load paths, and service motions remain conformant.

## Prototype Boundary

Geometry automation cannot verify printer calibration, real material shrinkage, fan performance, surface temperature, snap-cycle life, or handle strength. Generate coupons and test plans for those properties; keep the package at `PROTOTYPE` until the required evidence exists.
