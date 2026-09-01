# D1a vendored-subtree tooling

Reproduces and validates the D1a KV-offload subtree overlay (2026-09-01).
See planning/02-working/2026-09-01-d1a-vendored-subtree-execution.md for the
full record; the overlay output lives in the (gitignored, rsync-synced)
pipeline tree planning/01-raw/upstream-dspark/recipe/overlay/ with provenance
in vllm-d1a-kv-offload.MANIFEST.tsv.

- `assemble.py` — rebuilds the 66-file overlay from upstream pin
  f5e441de10bd (clone at /tmp/vllm-upstream) + apply-test baseline
  ea1e779 + fork shims/backports. Output: tmp/kv-offload-d1a/overlay/.
- `audit_imports.py [stage_dir]` — symbol-level vllm.* import audit of the
  overlay against the image; remaining rows are known tool artifacts
  (verified in-container).
- `equiv_test.py` — page-size equivalence test; run INSIDE the engine
  container (docker cp + /opt/env/bin/python) with the overlay interface,
  layout, and spec-registry files alongside. 109/109 at D1a time.
