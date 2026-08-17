+# Qwen3.5 9B / GB10 / vLLM BF16
+
+Maturity: **Reference**
+
+This profile retains the existing vLLM BF16/nightly configuration. No repository operation is mapped because the retained files do not provide a bounded lifecycle command.
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
+- Retained source: [existing repository evidence](../dgx-spark-gb10-llamacpp-9b-q4-k-m-8k/README.md)
+- Exact metadata: [recipe.yaml](recipe.yaml)
+- Recovery: return to the source profile and its documented controls; this
+  index does not authorize a live service change.
+
