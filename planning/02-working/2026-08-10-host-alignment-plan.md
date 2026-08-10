# GB10 Host Alignment Plan - 2026-08-10

Status: prepared from live checks on 2026-08-10. This plan does not authorize
a maintenance window. The physical CX-7 link is now present and has passed
carrier and link-local reachability checks; logical fabric configuration and
distributed inference remain gated on host alignment.

Execution result: alignment was applied and accepted on 2026-08-10. Both
hosts now run kernel `6.17.0-1014-nvidia`, driver `580.142`, Docker `29.2.1`,
Compose `v5.0.2`, Container Toolkit `1.19.0`, and RDMA userspace
`50.0-2ubuntu0.2`; fresh SSH sessions have unlimited memlock. Existing head
services and worker Lexdata were restored healthy.

## State And Scope

The target is compatible GB10 stacks for later TP=2 acceptance, not matching
every desktop package or Docker storage driver.

| Area | `gb10` head | `gb10-2` worker | Disposition |
| --- | --- | --- | --- |
| Kernel / driver | `6.17.0-1008-nvidia` / `580.126.09` | `6.17.0-1014-nvidia` / `580.142` | update head through Spark OTA, then reboot |
| Docker / Compose | `29.1.3` / `5.0.1` | `29.2.1` / `5.0.2` | update head in maintenance only |
| NVIDIA Container Toolkit | `1.18.2` | `1.19.0` | update head in maintenance only |
| RDMA userspace | `50.0-2ubuntu0.2` | `50.0-2build2`, candidate `50.0-2ubuntu0.2` | narrow worker update in maintenance |
| Docker log rotation | `json-file`, 50m x 10 | absent | stage a merged worker config, activate at maintenance restart |
| memlock | about 15 GiB; no Spark limits file | unlimited via `99-nv-spark-limits.conf` | let OTA supply head policy; no ad-hoc limit file |
| swap | none | `/swap.img`, 16 GiB, unused | leave unchanged; benchmark must show no swap activity |

Worker `admin` Docker access is fixed. Both runtime images are imported and
their normalized content fingerprints match. This supersedes stale statements
in older runbooks that say access or image import is pending.

## Physical CX-7 Baseline

The cable is installed on `enp1s0f0np0` at both ends. Read-only acceptance
showed `carrier=1`, `operstate=up`, 200,000 Mb/s, four lanes, full duplex, and
`rocep1s0f0/1 state ACTIVE physical_state LINK_UP` on both hosts. Selected
CRC, symbol, discard, transmit-error, and link-down counters were all zero.
IPv6 link-local ping passed 5/5 in both directions with 0% loss and sub-1 ms
RTT.

The head logged link activation at `21:43:50`, followed four seconds later by
NVIDIA `Xid 120` (GSP task exception) and `Xid 154` (GPU reset required). The
existing Qwen service encountered a CUDA launch failure on its next request at
`21:47` and exited; Docker could not restart it while the GPU required reset.
Temporal proximity is evidence of a possible hot-plug/platform interaction,
not proof of root cause. Do not run another GPU workload or hot-plug the
fabric before the planned kernel/driver update and reboot. Full evidence is in
`planning/02-working/2026-08-10-cx7-hotplug-gpu-incident.md`.

NetworkManager configuration, fabric IPv4 addresses, MTU 9000, RoCE GID
selection, bandwidth testing, NCCL configuration, and distributed inference
remain deferred until host alignment is complete. Neither mode of
`align-host-stack.sh` reads or changes NIC or RDMA fabric configuration. The
only RDMA action in this basic-environment phase is worker userspace package
alignment.

## Impact And Safety

Head services are Compose-managed and use `restart: unless-stopped`. Pdf2md
and TradingAgents remain healthy. Qwen is currently exited after the GPU reset
event and must not be restarted before the maintenance reboot:

| Host | Workload | Compose project / file | Service |
| --- | --- | --- | --- |
| `gb10` | Qwen (exited; GPU reset pending) | `qwen36-35b-rollback`; `/home/chriswang/.hermes/profiles/capital-avatar/deployments/qwen36-35b-nvfp4/compose.yml` | `vllm-qwen36-nvfp4` |
| `gb10` | pdf2md | `/home/chriswang/docker/pdf2md/docker-compose.yml` | `pdf2md-api` |
| `gb10` | TradingAgents | `/home/chriswang/project/TradingAgents-AShare/deploy/compose.yml` | `app` |
| `gb10-2` | Lexdata | existing Docker container | `lexdata-ai` |

Any Docker daemon restart interrupts all containers on that host. Docker
package updates can restart it. The head kernel/driver upgrade reboots the
host and interrupts all head services. Worker RDMA libraries are also deferred
to the window because later RDMA clients will load them.

`execution/align-host-stack.sh` defaults to read-only `--check` and exits `2`
when incomplete. `--apply` requires root and the exact worker hostname. It
backs up `/etc/docker/daemon.json`, structurally merges `json-file` rotation
(`50m`, `10`) while preserving `registry-mirrors`, `insecure-registries`, the
NVIDIA runtime, and any other keys, then validates with `jq` and `dockerd
--validate`. It never restarts Docker or performs package, RDMA, memlock,
swap, container, or reboot changes.

```bash
sudo /home/admin/gb10-ds4/execution/align-host-stack.sh --apply
/home/admin/gb10-ds4/execution/align-host-stack.sh --check
```

The staged policy takes effect only after an approved Docker restart.

## Exact Package Plan

Never use `apt full-upgrade`. Head preparation is deliberately split because
the currently enabled Base OS repository offers OTA meta `26.03.1`; the
worker's `26.04.1` comes from the NVIDIA Spark Updates Repository.

The first head simulation was reviewed: it upgrades only `dgx-release`, adds
`nvidia-spark-repo`, removes nothing, and leaves 248 unrelated packages
untouched. It was applied successfully; APT reported that no services or
containers required restart, and `26.04.1` is now the OTA meta candidate:

```bash
sudo apt-get install --no-install-recommends \
  dgx-release=7.5.0 nvidia-spark-repo=1.1-1
sudo apt-get update
apt-cache policy dgx-spark-ota-update-meta
```

After enabling the repository, unconstrained candidates are kernel `1029` and
driver `580.173`, not the worker's validated Spark baseline. The maintenance
command therefore pins the complete kernel `1014` / driver `580.142` family.
The exact command below has passed `apt-get -s`: 28 upgrades, 14 new packages,
one removal, no unresolved dependency, and 527 unrelated packages untouched.
The sole removal is the old NVIDIA module for kernel `6.14.0-1015`; the current
`6.17.0-1008` rollback kernel and its matching upgraded NVIDIA module remain
installed.

```bash
sudo apt-get -s --no-install-recommends install \
  dgx-spark-ota-update-meta=26.04.1 \
  linux-nvidia-hwe-24.04=6.17.0-1014.14 \
  linux-image-nvidia-hwe-24.04=6.17.0-1014.14 \
  linux-headers-nvidia-hwe-24.04=6.17.0-1014.14 \
  linux-tools-nvidia-hwe-24.04=6.17.0-1014.14 \
  linux-modules-nvidia-580-open-nvidia-hwe-24.04=6.17.0-1014.14+1000 \
  nvidia-driver-580-open=580.142-0ubuntu0.24.04.1 \
  nvidia-kernel-common-580=580.142-0ubuntu0.24.04.1 \
  nvidia-kernel-source-580-open=580.142-0ubuntu0.24.04.1 \
  nvidia-firmware-580-580.142=580.142-0ubuntu0.24.04.1 \
  libnvidia-gl-580=580.142-0ubuntu0.24.04.1 \
  libnvidia-common-580=580.142-0ubuntu0.24.04.1 \
  libnvidia-compute-580=580.142-0ubuntu0.24.04.1 \
  libnvidia-extra-580=580.142-0ubuntu0.24.04.1 \
  nvidia-compute-utils-580=580.142-0ubuntu0.24.04.1 \
  libnvidia-decode-580=580.142-0ubuntu0.24.04.1 \
  libnvidia-encode-580=580.142-0ubuntu0.24.04.1 \
  nvidia-utils-580=580.142-0ubuntu0.24.04.1 \
  xserver-xorg-video-nvidia-580=580.142-0ubuntu0.24.04.1 \
  libnvidia-cfg1-580=580.142-0ubuntu0.24.04.1 \
  libnvidia-fbc1-580=580.142-0ubuntu0.24.04.1 \
  docker-ce=5:29.2.1-1~ubuntu.24.04~noble \
  docker-ce-cli=5:29.2.1-1~ubuntu.24.04~noble \
  docker-compose-plugin=5.0.2-1~ubuntu.24.04~noble \
  nvidia-container-toolkit=1.19.0-1 \
  nvidia-container-toolkit-base=1.19.0-1 \
  libnvidia-container-tools=1.19.0-1 \
  libnvidia-container1=1.19.0-1 | tee /var/tmp/gb10-alignment-apt-simulate.txt
```

For `gb10`, these are the same NVIDIA HWE/Open driver package families present
on the worker. Do not replace the pins with current unconstrained candidates.
The maintenance installer is the reviewed command above without `-s`.

The NVIDIA snapshot PPA supplied 606 MB of the maintenance archives and was
the only slow source. Ubuntu packages already used the Tsinghua mirror. Live
5-10 MB range tests measured approximately 0.93 MB/s from the snapshot URL,
1.39 MB/s from the non-snapshot official PPA, 0.71 MB/s through Xray's local
HTTP proxy (`127.0.0.1:10809`), and 1.08 MB/s through its SOCKS endpoint
(`127.0.0.1:10808`). APT had no explicit proxy but system traffic already used
the Xray TUN path. Keep the pinned snapshot source for reproducibility; for a
stalled future fetch, a temporary APT HTTPS proxy is preferable to permanently
rewriting sources. Do not switch while dpkg is active.

For `gb10-2`, use this separate narrow plan after reviewing its simulation:

```bash
sudo apt-get -s install --only-upgrade \
  rdma-core=50.0-2ubuntu0.2 \
  libibverbs1=50.0-2ubuntu0.2 \
  ibverbs-providers=50.0-2ubuntu0.2 | tee /var/tmp/gb10-2-rdma-apt-simulate.txt
```

Run the same command without `-s` only after approval. `containerd.io` and
indirect OTA dependencies remain solver-controlled; unverified manual pins are
less safe than the reviewed dependency closure. The live simulation resolves
an 11-package RDMA closure, all from `50.0-2build2` to
`50.0-2ubuntu0.2`: `rdma-core`, `libibverbs1`, `ibverbs-providers`,
`ibverbs-utils`, `libibmad5`, `libibumad3`, `libibverbs-dev`,
`librdmacm-dev`, `librdmacm1t64`, `rdmacm-utils`, and `srptools`; it removes
nothing and leaves unrelated packages untouched.

## Maintenance Window

The coordinator must explicitly approve the window: it stops user workloads,
restarts Docker, updates the head kernel/driver, and reboots the head. Confirm
management connectivity, available disk, recovery-console access, and an
acceptable outage. Snapshot before any stop:

```bash
stamp=$(date -u +%Y%m%dT%H%M%SZ)
sudo install -d -m 0700 /var/backups/gb10-ds4-alignment/$stamp
docker ps --no-trunc > /var/backups/gb10-ds4-alignment/$stamp/docker-ps.txt
docker inspect $(docker ps -aq) > /var/backups/gb10-ds4-alignment/$stamp/docker-inspect.json
sudo cp -a /etc/docker/daemon.json /var/backups/gb10-ds4-alignment/$stamp/daemon.json
cp -a /home/chriswang/.hermes/profiles/capital-avatar/deployments/qwen36-35b-nvfp4/compose.yml /var/backups/gb10-ds4-alignment/$stamp/qwen-compose.yml
cp -a /home/chriswang/docker/pdf2md/docker-compose.yml /var/backups/gb10-ds4-alignment/$stamp/pdf2md-compose.yml
cp -a /home/chriswang/project/TradingAgents-AShare/deploy/compose.yml /var/backups/gb10-ds4-alignment/$stamp/tradingagents-compose.yml
```

On head, use `stop`, never `down`, then run the reviewed installer and reboot:

```bash
docker compose -p qwen36-35b-rollback -f /home/chriswang/.hermes/profiles/capital-avatar/deployments/qwen36-35b-nvfp4/compose.yml stop vllm-qwen36-nvfp4
docker compose -f /home/chriswang/docker/pdf2md/docker-compose.yml stop pdf2md-api
docker compose -f /home/chriswang/project/TradingAgents-AShare/deploy/compose.yml stop app
sudo apt-get install ... # exact reviewed head command above
sudo reboot
```

On worker, snapshot `lexdata-ai` logs before the RDMA update and the planned
daemon restart, then revalidate it afterwards:

```bash
docker logs --tail 500 lexdata-ai > /var/backups/gb10-ds4-alignment/$stamp/lexdata-ai.log
sudo apt-get install --only-upgrade rdma-core=50.0-2ubuntu0.2 libibverbs1=50.0-2ubuntu0.2 ibverbs-providers=50.0-2ubuntu0.2
sudo systemctl restart docker
docker ps --format 'table {{.Names}}\t{{.Status}}'
docker inspect -f '{{.Name}} {{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' lexdata-ai
```

After head returns, restart and verify the original services:

```bash
docker compose -p qwen36-35b-rollback -f /home/chriswang/.hermes/profiles/capital-avatar/deployments/qwen36-35b-nvfp4/compose.yml up -d vllm-qwen36-nvfp4
docker compose -f /home/chriswang/docker/pdf2md/docker-compose.yml up -d pdf2md-api
docker compose -f /home/chriswang/project/TradingAgents-AShare/deploy/compose.yml up -d app
docker ps --format 'table {{.Names}}\t{{.Status}}'
docker inspect -f '{{.Name}} {{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' vllm-qwen36-nvfp4 pdf2md-api tradingagents-ashare
```

Verify both hosts with `uname -r`, `nvidia-smi`, Docker/Compose/toolkit
versions, `ibv_devinfo`, fresh-login `ulimit -l`, `swapon --show`, and
`align-host-stack.sh --check`. If Docker config activation fails, restore the
dated `daemon.json` backup, validate it with `dockerd --validate`, restart
Docker once, and check every affected service. If head fails to boot or load
the driver, select `6.17.0-1008-nvidia` in GRUB Advanced Options, restore
services, and preserve journal/NVIDIA evidence before further changes.

Keep head swap-free and leave worker swap untouched. Every TP=2 benchmark must
capture `vmstat 1` or `/proc/vmstat` and fail if `pswpin` or `pswpout` rises on
either rank. Disabling worker swap is a separate, explicitly authorized host
policy decision.

During this execution, `needrestart` attempted to restart
`nvidia-persistenced` after package configuration. The old daemon was already
in uninterruptible `D` state because of the pre-existing GPU reset, so systemd
could not stop it. All package configuration, initramfs generation, and GRUB
generation had completed. After confirming no `dpkg`/`dpkg-deb` process was
active, only the `needrestart` and waiting `systemctl` client processes were
terminated; the APT hook is explicitly best-effort (`|| true`). The planned
reboot cleared the old daemon. This is an incident recovery exception, not a
normal upgrade step.
