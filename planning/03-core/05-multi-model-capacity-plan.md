# Multi-Model Capacity Plan

## Evidence Classes

**Verified:** official DeepSeek requires a dedicated two-host window and
Qwen was stopped for acceptance. Official model loading logged 79.51 GiB per
rank; whole-process peak remains unknown. A 2026-08-11 Qwen `nvidia-smi`
process row reported 45,624 MiB for `VLLM::EngineCore`; head unified memory is
119.6 GiB. BGE-M3 and privacy-filter were not found as containers or images on
either host.

**Derived:** `79.51 GiB + 45624 MiB / 1024 = 124.06 GiB`, already greater than
119.6 GiB before KV/runtime. The accepted DeepSeek profile and continuously
loaded Qwen are not feasible together on head. Whole-process peak is still
unknown, but it cannot reverse this lower-bound conclusion. BGE-M3 and
privacy-filter add no safe co-load claim because their image, device choice,
and peak are unknown.

## Recommended Profiles

1. Long-term primary: dedicate both GB10 hosts to DeepSeek. Move Qwen to a
third GPU host or other GPU node; keep `192.168.88.181:8004` as a lightweight
reverse proxy to that backend. Implement only after backend/auth contract,
health checks, timeout behavior, and rollback to the local Qwen Compose are
tested.
2. Current two-host mode: maintenance-window time slicing only. Capture/stop
Qwen, run DeepSeek, stop it, then restore and health-check Qwen.
3. BGE-M3/privacy-filter: locate existing deployments and measure peak first.
Prefer CPU or an external node if service latency is acceptable. Add hardware
when Qwen must remain continuously loaded while DeepSeek is primary, or when
measured embedding/filter demand exceeds approved headroom.

Trigger a maintenance window when Qwen health fails, a new model needs GPU or
large unified memory, DeepSeek requires a restart, or any observed host memory
headroom falls below an approved measured threshold. Treat GPU memory as
unknown on GB10 when `nvidia-smi` reports `[N/A]`; use container stats only as
host RSS evidence, not a replacement for a peak measurement.
