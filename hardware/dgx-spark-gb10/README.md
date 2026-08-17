# NVIDIA DGX Spark / GB10

The catalog contains single-GB10 and dual-GB10 recipes. Check `hardware_id`
before use: `dgx-spark-gb10` and `dgx-spark-gb10-pair` are different classes.

GB10 uses ARM64 and unified memory. Runtime image architecture, CUDA support,
available unified memory, disk capacity, and multi-host networking are part of
each recipe's acceptance boundary. Do not infer dual-host readiness from a
single-host result.

List matching entries with:

```bash
./lab list | grep dgx-spark-gb10
```
