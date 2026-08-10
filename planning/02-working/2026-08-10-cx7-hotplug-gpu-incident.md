# CX-7 Hot-Plug / GPU Reset Incident - 2026-08-10

## Impact

`gb10` lost usable GPU state while its existing Qwen vLLM service was running.
The service exited after a later request observed the failed GPU. Pdf2md,
TradingAgents, model downloads, and the head-to-worker rsync continued.

## Verified Timeline

Times are Asia/Shanghai from the head journal unless marked UTC.

| Time | Evidence |
| --- | --- |
| `21:43:07` | Both mlx5 devices reported `Cable plugged`. |
| `21:43:50` | `enp1s0f0np0` and `enP2p1s0f0np0` reported Link Up; RDMA ports became ACTIVE. |
| `21:43:54` | GPU logged `Xid 120`, GSP task exception. |
| `21:43:54` | GPU logged `Xid 154`, recovery action changed to GPU Reset Required. |
| `21:47:33` | Qwen vLLM request failed with CUDA `unspecified launch failure`. |
| `21:47:37` | Qwen container exited with code 0 (`13:47:37Z`). |
| after exit | Docker restart attempt failed: `nvml error: gpu requires reset`. |

The four-second interval between CX-7 Link Up and the first GPU GSP failure is
a strong temporal correlation. It does not establish whether the trigger was
the cable operation, a platform power/PCIe interaction, the old
kernel/driver, or an unrelated latent GPU fault.

## Current State

- CX-7 target port: 200 Gb/s, four lanes, full duplex, RDMA ACTIVE;
- link-local ping: 5/5 in both directions, 0% loss;
- selected CX-7 physical error counters: zero;
- GPU: visible to `nvidia-smi`, but metrics show `ERR!` / `N/A`;
- Qwen container: exited, not OOM-killed, restart count 1;
- head model download, model rsync, and finalizer tmux sessions: running.

## Recovery And Follow-Up

1. Do not restart Qwen or launch another GPU workload in the failed state.
2. Preserve journal and container evidence before reboot.
3. Apply the reviewed head alignment to kernel `6.17.0-1014-nvidia` and driver
   `580.142`, then reboot to reset the GPU.
4. Verify `nvidia-smi`, run a GPU container smoke test, and restore existing
   Compose services before distributed inference.
5. Treat CX-7 cable changes as powered-down maintenance while GPU workloads
   are absent.
6. During post-reboot fabric load, watch for new Xid, PCIe, power, mlx5, and
   link-reset events. Any recurrence blocks model acceptance.

## Recovery Result

The head was aligned and rebooted successfully. It returned on kernel
`6.17.0-1014-nvidia` with driver `580.142`; `nvidia-smi` and an isolated GPU
container smoke test passed. The persistent CX-7 connection returned at MTU
9000 with RoCE v2 GID index 3, and jumbo ping passed. The boot journal had no
new Xid or GPU reset. Qwen reloaded and its health and `/v1/models` endpoints
returned successfully; pdf2md and TradingAgents also returned healthy.

The reboot took longer than a normal boot because the old
`nvidia-persistenced` process had been in uninterruptible `D` state. During
shutdown, SSH was temporarily refused while both management and fabric ICMP
still replied. The worker recorded one expected CX-7 link-down event followed
by `ACTIVE/LINK_UP`. No second reboot was sent.
