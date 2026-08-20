# Three.js Design Review

## Purpose

The Three.js model resolves architecture, access, assembly, airflow, and appearance before expensive CAD work. It must use the same named dimensions as the requirements register where practical, but it is not the manufacturing solid model.

## Required Views

- `assembled`: complete product with purchased components;
- `transparent`: shell opacity reduced, internals and keep-outs visible;
- `exploded`: parts separated along plausible assembly paths;
- `front`, `rear`, `left`, `right`, `top`, `bottom`: orthographic views;
- optional `airflow`, `service`, or `comparison` modes when relevant.

The exploded transform must be separate from the base assembly transform. Orthographic views must not use perspective projection.

## Scene Rules

- Use millimetres as scene units and place the assembly around a stable origin.
- Keep one `THREE.Group` per part with stable `userData.partId`.
- Store authoritative review dimensions in one `DESIGN` object; do not scatter numeric literals through mesh construction.
- Give printed parts, purchased parts, keep-outs, airflow, and cables distinct configurable categories. New categories must remain visible/configurable without editing the core view-state code.
- Use `Box3` to fit the camera after mode or viewport changes.
- Provide orbit, pan, zoom, reset, view mode, part visibility, and exploded-distance controls.
- Add a scale grid or dimension overlay for critical interfaces. Never infer dimensions from screen pixels.
- Use translucent double-sided materials for cutaways and disable depth writing when needed to avoid opaque-looking transparency.
- Show connector bodies and conservative cable bend envelopes, not only cable centerlines.
- Show fans with explicit intake/exhaust arrows and avoid recirculation paths hidden by the shell.

## Review UI

Keep controls compact and work-focused. Use icon buttons with tooltips for camera actions, segmented controls for view modes, checkboxes for visibility, and a slider for exploded distance. Avoid a marketing layout.

Display:

- revision and units;
- overall envelope;
- selected part ID and dimensions;
- current provisional/verified dimension count;
- category and per-part visibility controls;
- warnings for hidden connectors, collisions, or missing measurements.

## Visual QA

Before Gate D:

1. Start the local server and load every view mode.
2. Capture desktop and mobile screenshots.
3. Confirm the WebGL canvas contains non-background pixels.
4. Confirm all parts fit the viewport and labels do not overlap controls.
5. Rotate the assembled and transparent models; inspect rear and underside access.
6. Move the exploded slider from zero to maximum; parts must separate without changing scale or identity.
7. Compare the Three.js parts list against `design/parts.md`.

## Template Use

Copy `assets/threejs-review-template/` to `visuals/`, run `npm install`, and replace `src/design.js`. Populate its category, dimension-status, part metadata, and warning records; preserve the generic view-state and camera-fit contract unless the project requires a documented extension.
