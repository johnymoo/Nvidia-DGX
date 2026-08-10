# GB10 Host Software Comparison - 2026-08-10

This is a read-only comparison. No package, kernel, driver, daemon, swap, or
clock setting was changed while collecting it.

## Summary

The machines have matching hardware, firmware, CUDA toolkit, CPU policy, NIC
capabilities, and base OS. The important drift is the host kernel/NVIDIA stack:
`gb10-2` is on the newer NVIDIA Spark OTA baseline, while `gb10` is one OTA
generation behind. Align that critical stack before the first TP=2 acceptance
run; do not attempt to make every desktop package identical.

## Compared State

| Area | `gb10` | `gb10-2` | Assessment |
| --- | --- | --- | --- |
| Hardware / BIOS | FusionXpark GB10, firmware `00.53.02.03` | same | aligned |
| OS | Ubuntu 24.04.4, arm64 | same | aligned |
| Kernel | `6.17.0-1008-nvidia` | `6.17.0-1014-nvidia` | align head upward |
| NVIDIA driver | `580.126.09` | `580.142` | align head upward |
| CUDA toolkit | 13.0.2, nvcc 13.0.88 | same; nvcc lacks a PATH symlink | runtime aligned |
| Docker / Compose | 29.1.3 / 5.0.1 | 29.2.1 / 5.0.2 | align head during maintenance |
| NVIDIA container toolkit | 1.18.2 | 1.19.0 | align head during maintenance |
| Docker image store | classic `overlay2` | containerd `overlayfs` snapshotter | leave as-is |
| Docker log rotation | 50 MB x 10 files | not configured | copy policy to worker |
| RDMA userspace | `50.0-2ubuntu0.2` | `50.0-2build2`; newer package is candidate | align worker upward |
| CX-7 firmware | `28.45.4028` | same | aligned |
| CX-7 kernel driver | kernel 1008 `mlx5_core` | kernel 1014 `mlx5_core` | follows kernel alignment |
| PCIe bandwidth reported | 126.028 Gb/s, PCIe 5 x4 | same | hardware ceiling, not drift |
| CPU governor | performance on all 20 policies | same | aligned |
| THP | madvise / madvise defrag | same | aligned |
| NTP / timezone | synchronized / Asia/Shanghai | same | aligned |
| Secure Boot | disabled, setup mode | same | aligned |
| Swap | none | 16 GiB file, unused | standardize for benchmark |
| SSH memlock limit | about 15 GiB | unlimited | head gains unlimited via Spark OTA |
| GPU persistence / mode | enabled / default | same | aligned |
| Current GPU state | P0 under Qwen load | P8 idle | expected, not configuration drift |

## NVIDIA Spark OTA Drift

`gb10-2` has the newer Spark provisioning layer:

- `dgx-release 7.5.0` versus `7.4.0`;
- `dgx-spark-ota-update-meta 26.04.1` versus `26.02.1`;
- `nvidia-spark-repo 1.1-1`, which is absent on `gb10`;
- `/etc/security/limits.d/99-nv-spark-limits.conf`, which sets unlimited
  memlock and is absent on `gb10`.

The normal package candidates on `gb10` already include kernel 1014, driver
580.142, Docker 29.2.1, Compose 5.0.2, and NVIDIA Container Toolkit 1.19.0.
Use the NVIDIA Spark OTA/package path in a maintenance window rather than
copying individual files or running an unconstrained desktop `full-upgrade`.

## RDMA Findings

- Interface and HCA names match on both hosts:
  `enp1s0f0np0` / `rocep1s0f0`.
- `ethtool` offloads, ring sizes, and channel counts are identical.
- `ibv_devinfo` differs only in the expected per-device GUID.
- Both hosts currently expose only GID indexes 0/1 because the fabric IPv4
  address is not configured. RoCE v2 index 3 should appear after assigning the
  planned IPv4 address and must be verified before using
  `NCCL_IB_GID_INDEX=3`.
- Both boot logs report the same 126.028 Gb/s PCIe bandwidth and the same
  `Detected insufficient power on the PCIe slot (27W)` and CX-7 hotplug probe
  messages. These are symmetric platform messages, not evidence of one bad
  node, but link bandwidth and error counters still need live validation.

The nominal 200 Gb link is PCIe-limited on each Spark. Plan for a practical
ceiling around 100-120 Gb/s rather than expecting 200 Gb/s payload throughput.

## Recommended Alignment

### Required Before TP=2 Acceptance

1. In a maintenance window, update and reboot `gb10` onto kernel 1014 and
   NVIDIA driver 580.142 through the NVIDIA Spark OTA packages.
2. Align `gb10` Docker/Compose/Container Toolkit to the worker versions.
3. Update `gb10-2` RDMA userspace packages to `50.0-2ubuntu0.2`, matching the
   currently installed head packages, then re-run `ibv_devinfo`.
4. After cabling, verify carrier, MTU 9000, IPv4 GID index 3, `ib_write_bw`, and
   NCCL before starting model load.
5. Under simultaneous GPU load, compare SM clock, power, temperature, and
   throttle reasons. P0 versus P8 while one host is idle is not a failure.

### Recommended Operational Changes

- Add the head's Docker `json-file` rotation policy to the worker while
  preserving its private registry and insecure-registry entries.
- Standardize swap behavior for benchmarks. Prefer no active swap on either
  rank, or at minimum use low swappiness and fail the benchmark if `pswpin` or
  `pswpout` increases; TP=2 is lockstep and one swapping rank stalls both.
- Add `/usr/local/bin/nvcc -> /usr/local/cuda/bin/nvcc` on the worker only as a
  shell convenience. It does not affect the container runtime.

### Do Not Align Merely for Symmetry

- Do not migrate Docker storage drivers. Normalized image content is identical
  after import even though the local image IDs differ.
- Do not copy the worker's NVIDIA telemetry service to the head; it is not
  required for inference or health monitoring.
- Do not copy registry mirrors wholesale. Keep each host's local registry
  policy and align only runtime and log behavior.
- Do not lock GPU clocks preemptively. Measure both ranks under the same load
  first, then use a temporary clock lock only if one node remains abnormally
  downclocked.

## Useful Cross-Host Assets

The worker already has the Anemll vLLM 0.25.2 image used by the upstream
runtime bake-off. It is a useful diagnostic fallback because it exposes richer
DSpark acceptance metrics, but it is slower than the prepared B12X runtime and
does not need to be copied before the primary acceptance run. The head has a
broader set of CUDA/vLLM/llama.cpp images; transfer only a pinned image needed
for a defined A/B to avoid consuming the 100 Mb management link.
