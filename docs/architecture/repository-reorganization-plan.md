# Repository Reorganization Delivery Plan

Approved baseline: `repo-reorg-r2`

Execution authority: autonomous repository-only delivery. No GPU host, model
service, or NAS mutation is authorized.

## Wave 0: Converge Existing Work

1. Inventory open pull requests, issues, current main, and default branch.
2. Review PR #32 on its immutable head; fix only validated findings; run its
   repository tests and report regeneration; merge if aligned.
3. Close PR #27 as superseded without merging legacy history. Record the clean
   implementation ideas eligible for later reuse.
4. Close completed issues with merge/evidence references and classify all
   remaining issues as repository work, example-app work, or external
   maintenance.
5. Set `main` as the default branch after merge convergence.

## Wave 1: Foundation

1. Add recipe, receipt, benchmark-result, and catalog schemas.
2. Add lightweight `lab` catalog validation and dispatch commands.
3. Add catalog generation, Best Verified selection, README table generation,
   privacy scan, and link-check tooling.
4. Add shared benchmark suite metadata and report template without inventing
   new measured results.
5. Add CI for static tests, schema validation, generated-file drift, privacy,
   and links.

## Wave 2: Migrate Existing Content

1. Move model deployment projects under canonical `recipes/` paths with
   history-preserving `git mv`.
2. Add `recipe.yaml`, maturity, standard wrapper, and evidence pointers to each
   migrated project.
3. Move hardware-wide notes under `hardware/`.
4. Move cross-model benchmark assets under `benchmarks/` and `results/` where
   safe; catalog legacy in-place evidence when relocation would break
   provenance.
5. Move `memory-vector-db`, `pdf-to-markdown`, and podcast ASR under
   `examples/apps/`.
6. Move troubleshooting records under `operations/debug-notes/`.
7. Update all internal links and tests after each bounded migration.

## Wave 3: Homepage And Documentation

1. Generate the Operator First root README.
2. Publish hardware, model, benchmark, operations, and examples indexes.
3. Document contribution, maturity promotion, benchmark submission, privacy,
   and evidence requirements.
4. Add issue and pull-request templates aligned with the contracts.

## Wave 4: Convergence

1. Run all repository and project-specific static/fixture tests.
2. Render every Compose file that has a safe example environment.
3. Regenerate benchmark summaries and reports where deterministic inputs exist.
4. Run privacy, link, schema, and generated-file drift scans.
5. Clone the integration commit into a new directory and repeat no-host checks.
6. Run three-dimensional review on the frozen integration subject.
7. Apply at most one complete review fix batch and rerun invalidated evidence.
8. Merge through a pull request and verify the exact main commit.

## Recovery

- PR #32 fixes remain isolated on its source branch until merged.
- Repository restructuring is one dedicated branch and pull request.
- Before merge, failure is recovered by fixing or abandoning that branch.
- After merge, recovery uses a revert pull request for the reorganization merge
  commit; no remote deployment state is involved.
