+# Qwen3.6 35B-A3B NVFP4 MTP3 / GB10 / vLLM
+
+Maturity: **Reference**
+
+This profile records the retained NVFP4/MTP3 256K benchmark evidence. It does not claim an active canonical benchmark run.
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
+- Retained source: [existing repository evidence](../dgx-spark-gb10-vllm-27b-nvfp4-native-mtp2-128k/NVFP4-BENCHMARK-RESULTS.md)
+- Exact metadata: [recipe.yaml](recipe.yaml)
+- Recovery: return to the source profile and its documented controls; this
+  index does not authorize a live service change.
+
