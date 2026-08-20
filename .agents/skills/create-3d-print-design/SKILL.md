---
name: create-3d-print-design
description: "Create end-to-end, manufacturable 3D-print designs from requirements through GPT Image 2 concepts, Three.js design review, parametric build123d/OpenCascade CAD, and a print package with per-part STEP/STL, assemblies, BOM, validation evidence, and print instructions. Use for enclosures, brackets, ducts, holders, fixtures, organizers, adapters, and multi-part printed products when dimensions, fit, airflow, assembly, strength, or FDM/FFF printability matter. Do not use for visual-only 3D art or CNC/injection-molding production design without a process-specific review."
---

# Create 3D Print Design

Turn a physical-product idea into a reviewed, parameter-driven print package. Keep concept art, review geometry, manufacturing CAD, and physical validation as distinct evidence layers.

## Operating Rules

- Ask only one question per message during requirements collection. Choose the unresolved question with the highest effect on geometry, safety, or feasibility.
- Do not ask for information that can be established from supplied files, authoritative product drawings, measurement photos, or the current project.
- Record every dimension as `verified`, `derived`, `provisional`, or `unknown`, with source and tolerance. Never silently promote a nominal web dimension to verified.
- Use millimetres in CAD and package manifests unless the user explicitly requires another unit.
- Stop at each approval gate. Do not interpret approval of appearance as approval of dimensions or manufacturing release.
- Generated images and Three.js meshes are review aids, not dimension-authoritative CAD.
- Prefer low-fastener, printable assemblies only when serviceability, load paths, thermal cycling, and repeated assembly remain credible.
- Keep the project runnable and preserve source files, not only exported meshes.

## Project Record

Create these project-local records as the workflow progresses:

```text
design/
  requirements.md
  decision-log.md
  parts.md
  dfm-review.md
  freeze.json
visuals/
cad/
tests/
output/
```

Use [deliverable-contract.md](references/deliverable-contract.md) for exact contents and status fields. Update the decision log after every approval or material design change.

## Phase 1: Requirements Baseline

1. Capture the user, application, operating environment, adjacent objects, installation/removal workflow, target printer, materials, loads, heat, airflow, electronics, cable access, appearance, budget, and desired revision level.
2. Build a dimension register covering external envelopes, keep-out zones, interfaces, hole patterns, connector bodies, cable bend space, moving/service clearances, and manufacturing tolerances.
3. Inspect supplied photos, datasheets, and existing project files. Use authoritative drawings before web listings; identify photo perspective distortion.
4. Ask one missing question at a time until no unresolved answer can materially change the overall architecture. A caliper-measurement request counts as one question.
5. State assumptions, open measurements, acceptance criteria, and the intended printer/process in `design/requirements.md`.

Gate R: Show the concise requirements baseline and ask for explicit approval. Do not create concept designs before approval unless the user explicitly asks for exploratory sketches.

## Phase 2: Concept Sketches

Read [prompt-patterns.md](references/prompt-patterns.md) and use the bundled `scripts/image2_api.py` client with `gpt-image-2`. Install the OpenAI Python package if it is missing. Read only `OPENAI_API_KEY` and optional `OPENAI_BASE_URL` from the environment or a trusted `.env`; never print either value.

1. Use verified product images as references when identity, ports, vents, proportions, or controls matter.
2. Default visual set:
   - one finished three-quarter view;
   - six orthographic faces in a consistent design sheet;
   - one transparent cutaway showing internal placement, airflow, cables, and keep-outs;
   - one exploded assembly view showing the intended assembly order;
   - a same-framing comparison sheet when two or more architectures remain viable.
3. Put invariants and rejected arrangements in the prompt. Require visible connector access, plausible cable bends, correct part count, consistent fan directions, and consistent views.
4. Save prompts under `tmp/imagegen/` and accepted images under `output/imagegen/`. Dry-run every new command shape, then call `scripts/image2_api.py` with `--timeout 900`. Keep the user informed at intervals no longer than 30 seconds.
5. Inspect the result at original resolution. Reject mechanically contradictory images even when visually attractive.

Gate C: Label all images `CONCEPT - NOT FOR DIMENSIONING`, summarize the selected direction and unresolved geometry, then obtain explicit approval before detailed modeling.

## Phase 3: Detailed Design Review

Read [threejs-review.md](references/threejs-review.md), then copy `assets/threejs-review-template/` into the project and replace its sample geometry with parameter-driven project geometry.

1. Model the complete product, purchased components, reference objects, keep-out volumes, cables, airflow paths, fasteners, and service motions at real scale.
2. Provide assembled, transparent/cutaway, exploded, and six orthographic views. Use identical part IDs and colors across views.
3. Expose the important parameters and view modes in the review UI. Include dimensions and clearance overlays for design-critical interfaces.
4. List each printed part, purchased part, quantity, material, joining method, print orientation hypothesis, and role in `design/parts.md`.
5. Check assembly order, tool access, connector access, cable bend space, intake/exhaust separation, load paths, removal order, and maintenance access.
6. Read [manufacturability-checklist.md](references/manufacturability-checklist.md) and record every applicable check with its phase, evidence, and result in `design/dfm-review.md`. Print fit coupons before large parts where clearances or source measurements remain uncertain.
7. Verify the review site on desktop and mobile with screenshots. Check that WebGL is nonblank and the model remains correctly framed in every view.

Gate D: Present the detailed model, parts list, DFM results, provisional dimensions, and required coupons. Every applicable `HARD_PRE_CAD` check must pass before full product CAD. If a check can only be resolved by a printed gauge/coupon, permit a limited gauge/coupon CAD branch and return to Gate D with its measurements; do not use that exception to model the full product. Obtain explicit approval of the structure and write `design/freeze.json` with part IDs, critical dimensions and statuses, interfaces, assembly order, airflow/load paths, service motions, and a SHA-256 digest. Any later architecture change invalidates this gate.

## Phase 4: Manufacturing CAD

Read [cad-pipeline.md](references/cad-pipeline.md) before writing CAD.

1. Use Python, build123d, and OpenCascade for parameter-driven solid modeling. Three.js is not the manufacturing kernel.
2. Define a typed parameter object as the single source of dimensional truth. Preserve provenance/status for critical dimensions next to the parameters or in the manifest.
3. Model purchased components and keep-outs separately from printable solids. Give every printable part one stable ID.
4. Create print-oriented variants without changing assembled geometry. Avoid slicer scaling as a fit-adjustment mechanism.
5. Generate fit gauges for uncertain interfaces before committing to large prints.
6. Export one STEP and one closed STL for each printable part. Export assembled STEP, exploded STEP, and reference assembly with purchased components/keep-outs.
7. Run automated checks for B-Rep validity, expected solid count, mesh closure/manifoldness, print envelope, minimum dimensions where computable, device/keep-out collisions, part collisions, and manifest completeness.
8. Add focused tests for the approved envelope, critical clearances, mirrored variants, and regressions in part count or export names.
9. Generate `reports/gate-d-conformance.json` and compare the CAD against the approved freeze: part IDs, critical dimensions, interfaces, assembly order, airflow/load paths, and service motions. Any unexplained difference invalidates Gate D.

Gate M: CAD may enter packaging only when every applicable `HARD_CAD_EXPORT` gate and automated check is `PASS`, Gate D conformance passes, and unresolved `HARD_RELEASE` evidence is explicitly recorded. A `RELEASE CANDIDATE` or `RELEASED` package cannot waive a safety- or load-critical failure; only `PROTOTYPE` may carry named prototype exceptions with owner, risk, and required test.

## Phase 5: Print Package

Generate the directory defined in [deliverable-contract.md](references/deliverable-contract.md). At minimum include:

- per-part STEP and STL in print orientation;
- native parametric CAD source and lockfile/environment definition;
- assembled, exploded, and fit-reference STEP files;
- exploded assembly illustration and numbered assembly instructions;
- BOM with printed and purchased parts, quantities, material, and alternates;
- print settings by part, support/brim notes, orientation images, and post-processing steps;
- fit gauges/coupons, validation report, dimensional inspection sheet, known risks, and revision metadata;
- checksums and a machine-readable `manifest.json`.

Run `scripts/validate_print_package.py <package-dir>`. Render STL previews and inspect them; a successful export is not visual proof of correct geometry. Zip the validated package without deleting the unpacked output.

Mark the result as one of:

- `PROTOTYPE`: dimensions or physical tests remain open;
- `RELEASE CANDIDATE`: automated checks pass and required first-article tests are specified;
- `RELEASED`: required physical fit/load/thermal/lifecycle tests are recorded and passed or explicitly non-applicable with rationale.

## Change Control

- If requirements change, return to Gate R for affected constraints.
- If architecture, part split, airflow, assembly order, or load path changes, invalidate Gates C and D as applicable.
- If only a verified parameter changes within the approved architecture, regenerate CAD, rerun checks, and update the revision without repeating concept imagery.
- Never overwrite a released package. Create a new revision and preserve the previous manifest.
