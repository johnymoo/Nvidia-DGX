# DSpark Vision CUDA "operation not permitted" crash — 2026-09-05

Scope: the `~/dspark-vision` compose deployment (`deepseek-v4-flash-vllm-dspark-1`,
`ghcr.io/anemll/dspark-vllm-gx10:0.1.1`, TP=2 over RoCE) on `gb10` + `gb10-2`,
serving `deepseek-ai/DeepSeek-V4-Flash-Vision-Exp` as API id `deepseek-v4-flash-0731`
on `:8890`. Same deployment the 2026-09-04 cluster audit snapshot describes.
Morning investigation was read-only; the root-cause fix (explicit nvidia
device nodes in compose) was applied 14:05-14:13 UTC - see "Fix applied".

## Incident (times UTC; local = UTC+8)

- Boot under observation: head started 2026-09-03 15:49, healthy since
  (audit snapshot 09-04 ~08:53 local: both ranks `Up 9 hours (healthy)`).
- 09-05 12:52-12:55: 18+ chat requests served 200 OK from one internal client.
- 09-05 12:55:59: one multimodal request returned HTTP 500 and killed the engine.
  Head `Worker_TP0` traceback:
  `get_mm_embeddings -> encoder_runner.execute_mm_encoder -> embed_multimodal
  (patches/vision_exp/apply.py:305 merge_one_image -> :105 encode_image ->
  vision.py:135 F.unfold/im2col)` ending in
  `torch.AcceleratorError: CUDA error: operation not permitted`
  (cudaErrorNotPermitted). Async-report caveat applies (no CUDA_LAUNCH_BLOCKING).
  Uptime at crash: ~45 h.
- 13:05:59-13:14:57: both ranks died in the standard 10-min NCCL collective
  timeout window (rank0 dump 13:05:59, rank1 terminates 13:14:00, executor logs
  `Worker proc VllmWorker-1 died unexpectedly`). Unlike closed upstream issue
  #172, BOTH containers exited, so `unless-stopped` brought both back and there
  was no split-brain: head restarted 13:07:55, worker 13:15:01.
- 13:15-13:20: clean second boot (worker: weights 80.04 GiB / 143.9 s, DSpark
  draft captured, CUDA graphs 0.71 GiB). Head healthcheck flipped healthy;
  end-to-end outage ~26 min (12:55:59 -> ~13:22).

## Verified-healthy state after recovery (13:22-13:30 UTC)

- Head `Health=healthy` streak 0; `/health` 200; live traffic 200 OK,
  ~43 tok/s generation, spec-decode acceptance ~3.3, prefix cache 63%.
- Worker `Health=healthy`; only pre-existing warnings (known spec-decode
  sizing advisory, first-use Triton JIT spike, `torch.compile` no-op notice).
- Smoke: text chat completion `max_tokens=512, temperature=0` -> HTTP 200,
  content exactly `ok` (16-token budgets can return `content: null` when the
  thinking template consumes them - request-shape artifact, not a fault).
- Protected services untouched: `qwen36-8004-proxy` healthy (46 h),
  `tradingagents-ashare` healthy, worker `lexdata-ai` healthy.

## Upstream linkage (repo MiaAI-Lab/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark)

Sanitized evidence (crash stack incl. the `vision.py:135 F.unfold` surfacing
point, ~45 h uptime, recovery timeline, env flags) was posted to #216 on
2026-09-05 as `johnymoo`:
https://github.com/MiaAI-Lab/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark/issues/216#issuecomment-5552186005
The failing image and per-request token stats were NOT recoverable (bodies
not retained by the serving path); that limitation is stated in the comment.

- **Issue #216 (OPEN, no fix)**: identical crash signature
  (`cudaErrorNotPermitted` in `merge_one_image`, EngineCore death, TP=2 down).
  Maintainer repro on 09-05 on the same stack but FRESH boot: 5/5 large-image
  requests passed. Open hypotheses: failing image content, uptime/state
  dependence (their reporter: 46 h uptime, ours: 45 h), or environment delta.
  Drafted but unshipped fixes: (a) `torch.cuda.synchronize()` after
  `encode_image` to surface the true fault origin; (b) request-scoped guard
  rejecting the vision request instead of killing EngineCore. Paired-rank
  restart hardening tracked separately. Blocked pending a reproducer.
- **Issue #172 (closed 09-01)**: placeholder-count mismatch EngineCore kill +
  split-brain recovery (single-rank restart). Not our failure mode, but its
  recovery lesson is why both-ranks-down + joint auto-restart is preferable.
- **PR #204 (merged 09-04)**: vision-exp MoE routing perf refactor touching
  `patches/vision_exp/apply.py` / `image_processor.py`. NOT a #216 fix, but
  our head checkout pins `d828ddd` (merge of #199, 09-02) while the
  maintainer's repro baseline is main-including-#204 - a real patch-version
  delta when comparing against their results.
- Open PR scan (09-05): nothing fixes #216 or adds vision CUDA error handling.

## Root cause (diagnosed 2026-09-05 ~14:00 UTC, read-only; NOT yet fixed)

**Not a vLLM / vision-patch bug. It is the documented NVIDIA Container Toolkit
"container loses GPU access after `systemctl daemon-reload`" problem, surfacing
as `cudaErrorNotPermitted` at the first fresh device-memory mapping.**

Evidence chain (all verified on the hosts):

1. **Crash site rules out an upstream async error.** `vision.py:135 F.unfold`
   is in `Aligner.forward`, i.e. AFTER the whole ViT (dozens of launch-checked
   kernels) and after `F.pad` (also launch-checked) succeeded. The only CUDA
   runtime call between the last good check and the failing one is the
   allocation for the `im2col` output (`resize_` -> caching allocator ->
   driver). The OP's site (`block.clone()` / `.to()` / index_put) is likewise
   an allocation point. Both crashes are "first allocation that needed a NEW
   segment from the driver".
2. **Request metadata is in the EngineCore `dump_input`** (previous session
   missed it): `chatcmpl-961875d1c53f123f-b99b510e`, prompt 98,886 tokens,
   98,304 prefix-cached, one image `n_vit_h=63 x n_vit_w=45` (~1008x720 px,
   357 vision tokens, `PlaceholderRange(offset=98517, length=357)`), scheduled
   chunk 582 tokens, `max_tokens=32768`. Encoder activations are only a few
   MB - not a capacity OOM.
3. **No kernel/driver log at crash time.** `dmesg`/`journalctl -k` has NVRM
   `NV_ERR_NO_MEMORY` bursts at 09-04 03:27 UTC (some other process creating a
   CUDA context) and 09-05 13:18 UTC (the restart's weight load), but NOTHING
   at 12:55:59 UTC. The denial happened above the driver (VFS/cgroup layer).
4. **Docker uses the systemd cgroup driver (cgroup v2) on BOTH hosts**
   (`docker info`: driver=systemd, v2, live-restore=false, Docker 29.2.1,
   nvidia-container-toolkit 1.19.0, runc 1.3.4). The compose file requests
   GPUs via `gpus: all` -> legacy `nvidia-container-runtime-hook`, which
   injects `/dev/nvidia0`, `/dev/nvidiactl`, `/dev/nvidia-uvm`,
   `/dev/nvidia-uvm-tools` and their cgroup rules BEHIND systemd's back.
5. **systemd's own allowlist for the container has no GPU devices.**
   `systemctl show docker-<id>.scope -p DeviceAllow` on both hosts:
   `DevicePolicy=strict`, allow = `/dev/char/231:*` (InfiniBand - present
   because `/dev/infiniband` IS passed via `devices:`), tty/null/random, and
   `char-* m`. Zero entries for majors 195 (nvidia0/ctl), 499 (nvidia-uvm),
   502 (nvidia-caps). Any `daemon-reload` makes systemd re-attach its BPF
   device program from this list -> `open("/dev/nvidia*")` inside the container
   returns EPERM -> CUDA maps it to `cudaErrorNotPermitted` ("operation not
   permitted"). Existing fds keep working, so steady-state text traffic that
   reuses cached allocator segments runs for hours; the first request that
   forces the allocator to map a NEW segment (libcuda re-opens `/dev/nvidia0`
   per new mapping) dies.
6. **The reloads happened, and only on the rank that crashed.** gb10 journal
   (container started 09-03 23:49 local): snapd auto-refresh triggered
   `systemd[1]: Reloading...` at 09-04 21:42:13/21:42:28 local (snapd
   2.76.2->2.76.3) and 5x at 09-05 02:57:51-56 local (snap change #87
   "Auto-refresh snap chromium"). gb10-2 (rank 1) journal: NO reload since its
   container started -> rank 1 never lost device access and died only via the
   NCCL collective timeout, exactly as observed.
7. **Independent confirmation:** NVIDIA forum thread "Spark: cudaErrorNotPermitted
   in comfyui - but only after Docker sits idle for hours" (GB10, driver 580.95,
   Dec 2025) - same error, same platform, reply traces it to daemon-reload; and
   the NVIDIA Container Toolkit troubleshooting page section "Containers losing
   access to GPUs with error: Failed to initialize NVML: Unknown Error" names
   `systemctl daemon-reload` + systemd cgroup driver as the trigger.
8. **Fix mechanism proven non-disruptively (gb10, 13:59 UTC):** a throwaway
   `sleep` container started with the same `--gpus all` PLUS explicit
   `--device /dev/nvidia0 --device /dev/nvidiactl --device /dev/nvidia-uvm
   --device /dev/nvidia-uvm-tools` got `DeviceAllow=/dev/char/195:0, 195:255,
   499:0, 499:1` in its systemd scope and `nvidia-smi -L` worked; container
   removed afterwards. Required `/dev/char/<maj>:<min>` symlinks exist on both
   hosts (udev `71-nvidia.rules`), so the runc caveat in NVIDIA's doc does not
   apply.

Why upstream can't reproduce: a fresh boot has had no daemon-reload. Why
"~45-46 h uptime" in both reports: it is just "long enough for a host-side
reload (snap refresh, apt unit install, manual `systemctl daemon-reload`) to
have happened". Same exposure applies to `lexdata-ai` on gb10-2
(`runtime: nvidia`, no explicit devices) and any other GPU container here.

## Fix applied 2026-09-05 14:05-14:13 UTC (owner go-ahead: "A 立刻执行; C 服务停掉")

- 14:05:44 service idle (0 requests in prior 2 min); `stop-deepseek-v4-flash-dspark.sh`
  removed both ranks. 14:06:08 `start-deepseek-v4-flash-dspark.sh` (log:
  `~/dspark-vision/artifacts/start-20260905-nvidia-devices.log` on gb10) recreated
  both; the script scp'd the edited compose to the worker (md5 identical).
- Head compose diff = option A below (4 device lines + comment). Pre-change copy:
  `~/dspark-vision/artifacts/docker-compose.dspark.yml.pre-nvidia-devices.bak`.
  Committed on both hosts on top of the `d828ddd` pin: gb10 `a0f724b`
  (`--no-verify`: the local privacy-filter hook false-positived on the
  pre-existing upstream comment "Tony/Capicua25x Patch 5", not on the diff),
  gb10-2 `fb1d1dc` (identity `dspark-ops`, worker has no git identity).
- **Verified:** `systemctl show docker-<id>.scope -p DeviceAllow` now lists
  `/dev/char/195:0, 195:255, 499:0, 499:1` (+ `231:0`) on BOTH ranks - the exact
  list systemd re-applies on `daemon-reload`, so GPU access now survives it.
- Both ranks `healthy` at +6 min; recipe warmup 47/47 ok; `/health` 200; text
  smoke -> `ok`; multimodal smoke (`artifacts/mm_smoke.py`, generated PNG via
  `image_url`) 1024x768 -> HTTP 200 6.0 s and 1600x1200 -> HTTP 200 3.3 s
  (357 image tokens each, same token count as the crashing request).
  Outage window ~8 min (14:05:44 -> ~14:13 UTC).
- C: `lexdata-ai` on gb10-2 stopped (`docker stop`; policy `unless-stopped`, so
  it stays down across reboots; `docker start lexdata-ai` to resume; compose
  project at `/opt/lexdata-ai`).
- NOT done: live `daemon-reload` proof on production (owner's call), snap hold
  (not needed for the DeepSeek stack after A; see below), upstream #216 comment.

Residual exposure: any OTHER container started with `gpus: all`/`runtime:
nvidia` and no explicit `devices:` (e.g. `lexdata-ai` if restarted, ad-hoc
benchmark containers) still loses GPU access on a host `daemon-reload`. Fleet
wide cure would be CDI or the cgroupfs driver (dockerd restart, all containers
bounce) - schedule separately if wanted.

## Fix plan as proposed (for reference)

A. **Permanent fix (NVIDIA-documented option 2): explicit device nodes** in
   `~/dspark-vision/docker-compose.dspark.yml` on BOTH hosts (files are
   md5-identical today), keeping `gpus: all` for the library mounts:
   ```yaml
   devices:
     - /dev/infiniband:/dev/infiniband
     - /dev/nvidia0
     - /dev/nvidiactl
     - /dev/nvidia-uvm
     - /dev/nvidia-uvm-tools
   ```
   Then a coordinated recreate via the recipe's own
   `start-deepseek-v4-flash-dspark.sh` (it drives both ranks; ~15-25 min
   outage). Verify with `systemctl show docker-<id>.scope -p DeviceAllow`
   showing 195:*/499:* on both hosts. This is a 4-line diff vs the `d828ddd`
   pin and is the right upstream fix for #216 (PR candidate: Ubuntu/DGX OS
   default to the systemd cgroup driver, so every recipe user is exposed).
   Alternative (option 3): CDI (`nvidia-ctk cdi generate`) - cleaner long-term
   but changes the runtime path; option 1 (cgroupfs driver) needs a dockerd
   restart with live-restore=false, i.e. restarts every container - not
   recommended.
B. **Zero-downtime stopgap until A is scheduled:** `sudo snap refresh --hold`
   on both hosts (reversible with `--unhold`); removes the only observed
   trigger. Note: non-interactive sudo is available on the head but not on the
   worker. Does not cover other reload sources (apt installing units,
   manual daemon-reload).
C. Apply the same `devices:` treatment to `lexdata-ai` (gb10-2) when it is
   next recreated.
D. Post the root cause + the recoverable request stats to upstream #216 (not
   yet written or posted).

## Recommended follow-ups (original, kept for history)

1. ~~Contribute sanitized evidence to #216~~ - done (see Upstream linkage).
   Token stats WERE recoverable from `dump_input` after all (see Root cause
   item 2) - worth adding to the upstream comment.
2. Until fix A is applied, any host-side `daemon-reload` re-arms the bomb; the
   next fresh-mapping request then takes the two-host service down for
   ~25-30 min (10-min NCCL timeout + boot). Auto-recovery works.
3. The drafted upstream synchronize/guard patches would only improve error
   attribution / request-scoping; they do not address this root cause.
4. Standing non-fatal items (documented in the 09-04 audit): recurring
   `NET/IB rocep1s0f0 port error(10)/active(9)` warn pairs on the worker RoCE
   link, spec-decode sizing advisory, JIT warmup spike.
