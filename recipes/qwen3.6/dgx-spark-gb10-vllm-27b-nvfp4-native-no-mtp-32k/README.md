+# Qwen3.6 27B NVFP4 no-MTP / GB10 / vLLM
+
+Maturity: **Archived**
+
+This is the retained no-MTP control profile. It is not a current deployment recommendation and has no mapped lifecycle command.
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
+- Retained source: [existing repository evidence](../dgx-spark-gb10-vllm-27b-nvfp4-native-mtp2-128k/UNSLOTH-QWEN36-27B-NVFP4-MTP2-BENCHMARK-RESULTS.md)
+- Exact metadata: [recipe.yaml](recipe.yaml)
+- Recovery: return to the source profile and its documented controls; this
+  index does not authorize a live service change.
+
