# Prompt Patterns

Use only fields that materially improve the result. Quote exact visible text and list negative constraints explicitly.

## Physical Product Design Sheet

```text
Use case: product-mockup
Asset type: three-panel industrial-design concept sheet
Primary request: <what is being designed and what ambiguity the image resolves>
Input images: Image 1: <role>; Image 2: <role>
Verified geometry: <dimensions, count, orientation, ports, keep-out zones>
Mechanical architecture: <airflow, assembly order, cable path, removable parts>
Panel 1 FINISHED: <viewpoint and exterior details>
Panel 2 CUTAWAY/AIRFLOW: <internal components and arrow directions>
Panel 3 EXPLODED: <ordered components and alignment>
Style/medium: realistic manufacturable industrial-design render, CAD-derived geometry
Composition/framing: consistent geometry across panels, complete objects inside frame
Text (verbatim): "FINISHED", "CUTAWAY/AIRFLOW", "EXPLODED"
Constraints: <facts and decisions that must remain true>
Avoid: impossible overlaps, extra components, blocked ports, decorative mechanisms, watermark
```

## Layout or UI Clarification

```text
Use case: ui-mockup
Asset type: layout clarification
Primary request: show <screen or workflow> so <decision> is easy to evaluate
Reference images: <roles>
Required states: <normal, expanded, error, mobile, comparison>
Composition: two or three aligned panels with identical content assumptions
Text (verbatim): <exact labels>
Constraints: practical hierarchy, readable text, no invented features
```

## Side-by-Side Alternatives

```text
Use case: infographic-diagram
Primary request: compare option A and option B for <decision>
Shared invariants: <facts identical in both>
Option A: <only decisions unique to A>
Option B: <only decisions unique to B>
Composition: equal scale, viewpoint, and lighting; clearly separated panels
Constraints: do not favor either option through framing; no extra alternatives
```

## Targeted Correction

```text
Use case: precise-object-edit
Input images: Image 1 is the edit target; remaining images are references
Primary request: correct only <single defect>
Required correction: <exact change>
Invariants: preserve <geometry, composition, colors, labels, unaffected components>
Constraints: do not add components or redesign unrelated areas
```

## Validation Checklist

- Exact component count matches the prompt.
- All views depict the same design.
- Orientation and flow arrows agree.
- Ports, controls, doors, and cable paths remain accessible.
- No visual element is mistaken for a verified dimension.
- Text is legible and exact enough for its purpose.
