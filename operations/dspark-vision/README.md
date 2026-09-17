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
- `mm_smoke_multi.py` — N-image smoke for the `--limit-mm-per-prompt` cap:
  `python3 mm_smoke_multi.py 10` sends 10 user turns with one image each
  (agent-session shape; the cap counts images across the whole prompt),
  `--single-turn` puts them all in one message. Exit 1 with the error body
  on 400, so `mm_smoke_multi.py 17` doubles as a probe of the effective cap.

## Image-count cap (same day, separate issue)

`LIMIT_MM_PER_PROMPT` defaults to 8 images per prompt; multi-turn agent
sessions that re-send screenshot history hit
`At most 8 image(s) may be provided in one prompt` after the 9th image.
Raised to 16 on 2026-09-05 (then the hard cap in `patches/vision_exp/processor.py`)
and to **32** on 2026-09-06 after syncing upstream main `957890a`, whose PR #231
drops the hardcoded 16 and makes `--limit-mm-per-prompt` the only cap. Set it in
`.env.dspark` on the head — **use the `image=N` form**; the JSON form loses its
quotes in the env file and fails `vllm serve` argparse (upstream fixed its
`.env.dspark.example` in the same PR). Profiling batch is unchanged (encoder
budget 8192 // 384 = 21 items for any N >= 4), so the KV budget is not affected;
32 is where we stopped because larger values only grow request size / TTFT and
gateway-side pruning of old images is the real fix (shiliai/LLM-Portal#98).
When syncing upstream, merge on **both** checkouts: the start script pushes
compose / env / `patches/vision_exp/` to the worker but not the other hotfix
files the compose bind-mounts. Details: debug-notes entries "2026-09-05 -
DSpark Vision 多轮对话累计图片超限 400" and its 2026-09-06 follow-up.

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
