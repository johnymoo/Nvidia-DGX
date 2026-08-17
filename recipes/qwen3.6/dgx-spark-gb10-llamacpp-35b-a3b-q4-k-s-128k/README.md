+# Qwen3.6 35B-A3B Q4_K_S / GB10 / llama.cpp
+
+Maturity: **Reference**
+
+This exact profile indexes the retained llama.cpp comparison evidence. No complete lifecycle implementation is present in this profile directory.
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
+- Retained source: [existing repository evidence](../dgx-spark-gb10-vllm-27b-nvfp4-native-mtp2-128k/BENCHMARK-RESULTS.md)
+- Exact metadata: [recipe.yaml](recipe.yaml)
+- Recovery: return to the source profile and its documented controls; this
+  index does not authorize a live service change.
+
