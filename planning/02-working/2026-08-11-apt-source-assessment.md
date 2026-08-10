# APT Source Assessment - 2026-08-11

This was a read-only assessment. It refreshed the APT index on `gb10`, where
passwordless sudo was available, but did not install or upgrade packages. The
worker index was not refreshed because `gb10-2` requires interactive sudo.

## Decision

- Keep the current sources on `gb10`.
- On `gb10-2`, replace only the Ubuntu Ports base URI with the Tsinghua TUNA
  `ubuntu-ports` mirror during the next interactive maintenance action.
- Keep every NVIDIA, DGX, CUDA, HPC SDK, and Canonical NVIDIA PPA URI unchanged.
- Do not configure an explicit APT proxy. Current end-to-end update performance
  does not justify the additional failure mode or per-host configuration drift.
- Do not apply the available package upgrades before the current DeepSeek
  acceptance run. The kernel, driver, Docker, RDMA, and container runtime stack
  has already passed fabric and NCCL acceptance as a matched pair.

## Evidence

Both hosts run Ubuntu 24.04.4 (`noble`) on `arm64`, kernel
`6.17.0-1014-nvidia`. Neither host has an APT proxy, proxy environment
variables, or a Docker systemd proxy drop-in.

| Check | `gb10` | `gb10-2` |
| --- | --- | --- |
| Ubuntu base source | TUNA `ubuntu-ports` | official `ports.ubuntu.com` |
| `apt-get update` | succeeded against 14 repositories in 7 seconds | not run; `sudo -n` requires a password |
| Upgradable count | 550 after refresh | 406 from the existing, stale index |
| TUNA InRelease | 125 ms TTFB, 1.01 MB/s | 114 ms TTFB, 0.98 MB/s |
| Official Ports InRelease | 1.15 s TTFB, 0.11 MB/s | 1.44 s TTFB, 0.075 MB/s |

The TUNA metadata test was roughly 9-13 times faster than the official Ubuntu
Ports endpoint. NVIDIA metadata showed approximately 0.9-6.2 seconds TTFB,
but the complete `gb10` index refresh still finished in 7 seconds without an
error or timeout. That is not evidence for adding an APT proxy.

Both hosts enable the `apt-daily` and `apt-daily-upgrade` timers, but
`unattended-upgrades` is not installed and the configuration sets
`Unattended-Upgrade "0"`; package upgrades are therefore not applied
automatically.

Notable candidates include NVIDIA HWE kernel `6.17.0-1029.29`, driver
`580.173.02`, CUDA `13.0.3`, and NVIDIA Container Toolkit `1.19.1`. These are
recorded for a separate maintenance and regression cycle, not for the current
deployment.

## Proposed Worker Change

Run only after interactive sudo is available:

```bash
sudo cp -a /etc/apt/sources.list.d/ubuntu.sources \
  /etc/apt/sources.list.d/ubuntu.sources.pre-tuna
sudo sed -i \
  's|http://ports.ubuntu.com/ubuntu-ports/|https://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports/|g' \
  /etc/apt/sources.list.d/ubuntu.sources
sudo apt-get update
```

Rollback:

```bash
sudo mv /etc/apt/sources.list.d/ubuntu.sources.pre-tuna \
  /etc/apt/sources.list.d/ubuntu.sources
sudo apt-get update
```
