+# Qwen3.6 35B-A3B Q4_K_M / RTX 4090 48 GB / Ollama
+
+Maturity: **Archived**
+
+This control profile is retained for comparison with the 27B default. It has no independently verified lifecycle or result bundle.
+
+## Use
+
+```bash
+./run.sh
+./run.sh <operation> --dry-run
+```
+
+`run.sh` lists the operations declared by `recipe.yaml`. An unsupported
+operation exits non-zero; do not infer a command from another profile.
+
+## Evidence And Recovery
+
+- Retained source: [existing repository evidence](../rtx4090-48gb-ollama-27b-q4-k-m-128k/README.md)
+- Exact metadata: [recipe.yaml](recipe.yaml)
+- Recovery: return to the source profile and its documented controls; this
+  index does not authorize a live service change.
+
