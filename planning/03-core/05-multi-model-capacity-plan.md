# Multi-Model Capacity Plan

## Evidence Classes

**Verified:** official DeepSeek requires a dedicated two-host window and
Qwen was stopped for acceptance. Official model loading logged 79.51 GiB per
rank; it is not a peak. Current Qwen Docker RSS is host-side 7.333 GiB, not a
GPU/unified-memory allocation measurement. BGE-M3 and privacy-filter were not
found as containers or images on either host.

**Derived:** DeepSeek plus Qwen should be scheduled mutually exclusively until
a dedicated simultaneous-load experiment records per-rank and whole-host peak
memory, latency, and recovery. Adding BGE-M3 or privacy-filter makes no safe
co-load claim because their image, model size, device selection, and peak are
unknown.

## Recommended Profiles

1. Normal: Qwen only, keep `:8004` healthy; run pdf2md/trading/lexdata.
2. DeepSeek batch/window: capture and stop Qwen, run official acceptance or
deployment, then stop DeepSeek and restore Qwen.
3. Embedding/filter services: deploy and measure them while Qwen is active
first; add DeepSeek only after a new approved concurrency experiment.

Trigger a maintenance window when Qwen health fails, a new model needs GPU or
large unified memory, DeepSeek requires a restart, or any observed host memory
headroom falls below an approved measured threshold. Treat GPU memory as
unknown on GB10 when `nvidia-smi` reports `[N/A]`; use container stats only as
host RSS evidence, not a replacement for a peak measurement.
