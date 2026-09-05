# DSpark Vision (2x DGX Spark, TP=2) — GPU device-node hardening

Companion material for the 2026-09-05 `cudaErrorNotPermitted` outage
(`operations/debug-notes/gb10-deployment-issues.md`, entry 2026-09-05;
full timeline in `planning/02-working/2026-09-05-dspark-vision-cuda-not-permitted-incident.md`;
upstream MiaAI-Lab/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark#216).

Status: applied to both ranks on 2026-09-05; cgroup-level evidence verified,
long-uptime / live `daemon-reload` verification still pending (tracked in the
GitHub issue).

## Why

Docker on DGX OS uses the systemd cgroup driver. With `gpus: all` the GPU
device nodes are injected by the nvidia hook behind systemd's back, so the
unit's `DeviceAllow` list has no `/dev/nvidia*`. Any host
`systemctl daemon-reload` (snapd auto-refresh, apt unit installs, manual)
re-applies that list and the container loses the ability to `open()` the GPU
nodes. Long-lived CUDA processes keep working on already-open fds until the
caching allocator has to map a fresh segment, then fail with
`CUDA error: operation not permitted`.

## Files

- `compose-explicit-nvidia-devices.diff` — the exact change applied to
  `docker-compose.dspark.yml` (upstream pin `d828ddd`): list
  `/dev/nvidia0 /dev/nvidiactl /dev/nvidia-uvm /dev/nvidia-uvm-tools` under
  `devices:` while keeping `gpus: all` for the library mounts. The node set is
  what the hook injects for `NVIDIA_DRIVER_CAPABILITIES=compute,utility`.
- `mm_smoke.py` — multimodal smoke test: generates a WxH noise PNG in-process
  and sends one `image_url` chat completion to `127.0.0.1:8890`.
  `python3 mm_smoke.py 1024 768`. Vary the size to force fresh encoder
  allocations.

## Apply

```bash
cd ~/dspark-vision                       # head; the start script scp's the file to the worker
git apply /path/to/compose-explicit-nvidia-devices.diff
./stop-deepseek-v4-flash-dspark.sh
./start-deepseek-v4-flash-dspark.sh      # ~8 min until both ranks healthy
```

## Verify

```bash
CID=$(docker inspect -f '{{.Id}}' deepseek-v4-flash-vllm-dspark-1)
systemctl show docker-$CID.scope -p DevicePolicy -p DeviceAllow | tr ' ' '\n' | grep -E '195:|499:'
# expect /dev/char/195:0 195:255 499:0 499:1 on BOTH hosts
ls -l /dev/char/195:0 /dev/char/499:0    # symlinks must exist (71-nvidia.rules)
python3 mm_smoke.py 1024 768 && python3 mm_smoke.py 1600 1200
```

Pending proof (owner decision, pokes production): `sudo systemctl daemon-reload`
on the head, then `mm_smoke.py` with a new image size — must return 200.
