# DeepSeek-V4-Flash-Vision-Exp — W0 Readiness Brief (2026-09-03)

Status: **W0 COMPLETE.** All 8 work items done. No container was started/stopped,
no `--gpus` container was run, nothing under `~/gb10-ds4` was touched, no
credentials were stored in any file, and `start-deepseek-v4-flash-dspark.sh`
was never invoked. Production (`deepseek-v4-flash-0731` on :8890) is
confirmed healthy as of this write-up. One incident occurred during
compatibility testing (recipe's own CI script attempted a real CUDA
allocation on the shared production GPU) — documented in full in Section 5,
including why it happened, why production was unaffected, and the fix.

## 1. Cluster facts (verified 2026-09-03)

- Recipe cloned to `gb10:~/dspark-vision/`, pinned to `main` HEAD
  `d828ddd89708b0216a3af124a57e44dd5c09cb37`.
- Production: `deepseek-v4-flash-0731` on port **8890**
  (`gb10-deepseek-v4-vllm-dspark-1`, confirmed "Up 8+ hours" and
  `/v1/models` returning 200 at time of writing). Portal `local-portal-gu`
  occupies 8888 on gb10, confirming the recipe's default port must stay
  overridden.
- gb10 disk: `/dev/nvme0n1p2 3.6T 2.6T 862G 76% /` (862 GiB free after
  the model cache reconciliation + Anemll image pull).
- gb10-2 disk: `/dev/nvme0n1p2 1.8T 1.3T 436G 75% /` (436 GiB free after
  the 156.3 GiB weight rsync).
- gb10-2 `~/dspark-vision` does not exist yet — **this is expected, not a
  blocker.** `start-deepseek-v4-flash-dspark.sh` creates
  `$WORKER_DIR` on the worker itself (`ssh "$WORKER_HOST" "mkdir -p
  $REMOTE_WORKER_DIR"`, line 1192) and `scp`'s the compose file, `.env.dspark`,
  and every patch file there as part of its own pre-flight sync (lines
  1191–1310+), before it ever runs `docker compose up`. Nothing needs to be
  pre-staged on gb10-2 beyond what W0 already did (image + weights).

## 2. `.env.dspark` as written on `gb10:~/dspark-vision/.env.dspark`

676 lines, mode `600`, no secrets (`VLLM_API_KEY` / `DSPARK_API_KEYS` /
`HF_TOKEN` all left unset — grepped for `token|api_key|secret|password` and
the only hits are unrelated numeric variable names). Full content, verbatim,
no redaction:

```env
# DeepSeek V4 Flash DSpark C12 NVFP4 profile for 2x DGX Spark TP=2.
# Copy to .env.dspark on each node and adjust node-specific values.
#
# Env matrix (Anemll 0.1.1 vs Stage-C overlay): see docs/ENVS.md
# Default image is Anemll — keep Stage-C-only VLLM_* keys commented unless
# you build/run the Stage-C image and merge docker-compose.stage-c.override.yml.
#
# --- W0 bring-up customization (2026-09-03, gb10 head) -----------------------
# Deviations from stock .env.dspark.example, all deliberate (see
# planning/02-working/2026-09-03-vision-exp-bringup-plan.md and the W0
# readiness brief for rationale):
#   - WORKER_HOST / MASTER_ADDR / *_IB_HCA / *_SOCKET_IFNAME / *_VLLM_HOST_IP:
#     production fabric values (gb10 <-> gb10-2 RoCE link), NOT the
#     placeholder tokens shipped in this template.
#   - SERVED_MODEL_NAME=deepseek-v4-flash-0731 and VLLM_PORT=8890: kept at
#     production's client-facing identity/port for a drop-in cutover, NOT
#     the recipe's own defaults (deepseek-v4-flash-vision-exp / 8888).
#   - DSPARK_RESTART_POLICY=no: explicit, so nothing auto-restarts unattended
#     during bring-up.
#   - NCCL_IB_GID_AUTO is left at the recipe default (1, auto-validated).
#     Production's pinned NCCL_IB_GID_INDEX=3 is intentionally NOT copied
#     here — the plan's RoCE-GID-pitfall disposition keeps auto mode.
#   - LONG_PREFILL_TOKEN_THRESHOLD, MTP_NUM_TOKENS, DSPARK_MAX_INFLIGHT_PREFILLS,
#     GPU_MEMORY_UTILIZATION_TEXT, MAX_NUM_SEQS, MAX_NUM_BATCHED_TOKENS: left at
#     recipe defaults (NOT production's 6144 / 5 / unset / 0.78 values) per
#     the plan's prior-optimization disposition table.
# ------------------------------------------------------------------------------

# Cluster
WORKER_HOST=admin@192.168.192.198
# Third Spark for optional ./start-tp3.sh (ignored by the 2-node start).
# On a QSFP ring this node is a different CX /24 than WORKER_HOST — set
# WORKER2_NCCL_* to spark3's facing port toward the head, and
# WORKER2_NFS_SERVER_IP to the head CX IP on that link (not 10.0.22.1).
# ./start-tp3.sh --max-num-seqs overrides TP3_MAX_NUM_SEQS; 2-node keeps MAX_NUM_SEQS.
# WORKER2_HOST=worker2-host-or-roce-ip
# WORKER2_VLLM_HOST_IP=
# WORKER2_DIR=
# WORKER2_HF_CACHE=
# WORKER2_NCCL_IB_HCA=
# WORKER2_NCCL_SOCKET_IFNAME=
# WORKER2_TP_SOCKET_IFNAME=
# WORKER2_GLOO_SOCKET_IFNAME=
# WORKER2_NFS_SERVER_IP=10.0.23.1
# TP3_MAX_NUM_SEQS=16
# Prerequisites the launcher checks but does not do: passwordless SSH to
# WORKER2_HOST and the pinned DSPARK_VLLM_IMAGE already pulled there.
# Everything else (dir, compose/env/patches sync, NFS mount) is automatic.
# See docs/TP3.md.
# Worker-local checkout/deployment path. Leave blank to mirror the head path.
WORKER_DIR=/home/admin/dspark-vision
# Optional explicit worker checkout path. This is useful when the worker clone
# lives somewhere different from the head checkout; it takes precedence over
# WORKER_DIR when set.
WORKER_SCRIPT_DIR=
MASTER_ADDR=192.168.192.181
MASTER_PORT=25000
NODE_RANK=0
HEADLESS=
# Issue #38: compose restart policy / stop grace (head mid-load must not SIGKILL
# under a live worker TCPStore handshake).
# Issue #72: unless-stopped restores ranks on reboot; start then exits 3 (already
# up). systemd: SuccessExitStatus=3 RemainAfterExit=yes — or set =no if the unit
# owns start/stop. Exit 3 is not a health check.
DSPARK_RESTART_POLICY=no
# DSPARK_STOP_GRACE=10s

# Worker node should use:
# NODE_RANK=1
# HEADLESS=1

# RoCE / InfiniBand (head node). On a QSFP ring, the worker's facing port
# name often differs — set WORKER_NCCL_* below; start-*.sh passes them remotely.
NCCL_IB_HCA=rocep1s0f0
NCCL_SOCKET_IFNAME=enp1s0f0np0
TP_SOCKET_IFNAME=enp1s0f0np0
GLOO_SOCKET_IFNAME=enp1s0f0np0
# Optional worker overrides (defaults to the head values if unset).
# Set these on the HEAD .env; start-deepseek-v4-flash-dspark.sh injects them on
# remote compose (shared/scp'd .env is fine). Do not rely on WORKER_* first in
# docker-compose — that substitution is not rank-aware.
# W0 note: gb10-2's node.env (FABRIC_IFNAME=enp1s0f0np0) confirms the worker
# uses the identical ifname/HCA name as the head, so the default-inherit
# behavior below is correct and these overrides are left commented.
# WORKER_NCCL_IB_HCA=rocep1s0f0
# WORKER_NCCL_SOCKET_IFNAME=enp1s0f0np0
# WORKER_TP_SOCKET_IFNAME=enp1s0f0np0
# WORKER_GLOO_SOCKET_IFNAME=enp1s0f0np0
# NCCL_IB_HCA accepts NCCL's full selector grammar and start-*.sh mirrors it
# for the sysfs GID lookup: optional leading "^" (exclude), then optional "="
# (exact name match instead of prefix match), comma-separated name[:port]
# tokens. NCCL stores only the first 32 non-empty entries and truncates each
# stored name to 63 bytes before matching; the resolver does the same. Omitted
# port = every port of the device. An exact list like "=devA,devB" is
# recommended filtering for deterministic member selection on a multi-HCA
# node — it is not something NCCL_IB_MERGE_NICS itself requires.
# RoCEv2 GID index: start-*.sh validates every selected HCA/port from sysfs
# by default (NCCL_IB_GID_AUTO=1) and then leaves NCCL_IB_GID_INDEX unset on
# both ranks. The usable index differs per node/HCA and drifts after reboot,
# and one global pin cannot serve several HCAs — NCCL selects the RoCEv2/IPv4
# GID per HCA when the variable is absent. The launcher fails closed (with
# per-member diagnostics) when a member has no usable RoCE v2 GID; disjoint
# per-member index sets are fine because nothing is pinned. NCCL_IB_GID_INDEX
# / WORKER_NCCL_IB_GID_INDEX values left in this file are reported and
# ignored while auto mode is on.
# Selector grammar follows NCCL: name[:port[:rail[:plane]]], where an absent or
# empty port means any port ("devA:" == "devA") and a non-empty port uses
# one atoi-style conversion after optional whitespace/sign, stopping at the
# first non-digit even across embedded newlines (":08" is decimal port 8); a
# port outside the conservative nine-digit bound is rejected rather than
# treated as "any port".
# Independently of the 32-entry selector limit, matching is applied to at most
# MAX_IB_DEVS=32 ports NCCL itself would consider: ACTIVE only, with link layer
# Ethernet or InfiniBand. A DOWN second port on a dual-port card is therefore ignored instead of failing the
# resolve, so a plain prefix like "roce" works even when half the ports are
# unused.
# Pin only when you disable auto. W0: NOT applied — production's
# NCCL_IB_GID_INDEX=3 pin is deliberately left out; NCCL_IB_GID_AUTO stays at
# its recipe default (1, see below) per the bring-up plan's RoCE-GID-pitfall
# disposition.
# NCCL_IB_GID_AUTO=0
# NCCL_IB_GID_INDEX=3
# WORKER_NCCL_IB_GID_INDEX=6
# Optional match IPs if the RoCE address is not the ifname primary IPv4:
# NCCL_IB_GID_MATCH_IP=10.0.22.1
# WORKER_NCCL_IB_GID_MATCH_IP=10.0.22.2
NCCL_CROSS_NIC=1

# Caches / model
HF_CACHE=${HOME}/.cache/huggingface
# Optional worker-local Hugging Face cache (checkpoint + Triton/TileLang/vLLM/…).
# Default DSPARK_WORKER_HF_NFS=0: prepare copies hub weights onto the worker.
# Set DSPARK_WORKER_HF_NFS=1 to skip that copy — the worker mounts the head
# HF_CACHE over NFSv4 on the ConnectX link (same as Qwen3.8-Flash-vLLM); this
# path is then JIT overlays only.
# W0: local copy chosen (156.3 GiB resumable rsync gb10 -> gb10-2 over the
# fabric IP, PID/log recorded in the readiness brief), so NFS is left off.
WORKER_HF_CACHE=/home/admin/.cache/huggingface
DSPARK_WORKER_HF_NFS=0
# Head ConnectX address that exports the HF cache. Unset = IPv4 on
# NCCL_SOCKET_IFNAME (do not use the 10.0.0.1 loopback alias).
# NFS_SERVER_IP=10.0.22.1
# Prefer offline when the hub cache is complete.
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
HF_HUB_DISABLE_XET=1
# Hub HTTP timeouts used by prepare-dspark-model-cache.sh. hf_hub defaults to
# 10s/10s, which aborts multi-GB shard downloads on a slow or proxied link.
# HF_HUB_DOWNLOAD_TIMEOUT=120
# HF_HUB_ETAG_TIMEOUT=30
# Optional Hub token for prepare. An exported shell HF_TOKEN /
# HUGGING_FACE_HUB_TOKEN is picked up automatically and wins over this file.
# Putting a live token here is scp'd to the worker — prefer the shell.
# HF_TOKEN=
# Parallel Hub shard fetches (prepare default is 1, disk-safe but slow).
# HF_DOWNLOAD_WORKERS=4
# Checkpoint flag: 0 = official Vision-Exp, 1 = abliterated (Keys).
# start- / prepare- resolve DSPARK_MODEL from this — do not set DSPARK_MODEL by hand.
# Abliterated Hub id is gated (auto-approve after RESPONSIBLE_USE.md); prepare
# needs HF_TOKEN in the shell or huggingface-cli login.
ABLITERATED=0
DSPARK_MODEL_OFFICIAL=deepseek-ai/DeepSeek-V4-Flash-Vision-Exp
DSPARK_MODEL_ABLITERATED=drowzeys/keys-DeepSeekV4Flash-Vision-EXP-ablit
# Pin official HF revision. Default when unset: Vision-Exp 86f746b3…
# Set DSPARK_REVISION= (empty) to follow tip of main. Abliterated uses
# DSPARK_REVISION_ABLITERATED (empty = tip of that repo).
# W0: reconciled against gb10's HF cache — only README.md (5054 bytes) was
# missing; all 48 model shards/config/tokenizer are byte-identical to the
# already-cached 6821d6ad snapshot, so this pin resolved in ~9s (see brief).
DSPARK_REVISION=86f746b36186f0e567729a5c06a8c918caba82a9
# DSPARK_REVISION_ABLITERATED=
# Optional pin for the encoder inside the container. Leave empty to auto-find
# encoding/encoding_dsv4.py under the selected model's HF hub snapshot (prefers
# DSPARK_REVISION when set).
DSPARK_ENCODING_FILE=
SERVED_MODEL_NAME=deepseek-v4-flash-0731
# Bind to 0.0.0.0 when Hermes/OpenClaw or another machine must reach the API.
# For a head-node-only test, set this back to 127.0.0.1.
VLLM_HOST=0.0.0.0
# API listen port. The launcher also accepts a temporary --port override.
# W0: kept at production's 8890 (NOT the recipe default 8888, which the
# local-portal-gu portal already occupies on gb10) so cutover is a drop-in.
VLLM_PORT=8890
# --- API auth (optional) -------------------------------------------------
# vLLM itself (not the reverse proxy) enforces `Authorization: Bearer <key>`
# on its OpenAI-compatible endpoints. Two mutually exclusive variables:
#
#   VLLM_API_KEY     — one key (vLLM's native single-key env var)
#   DSPARK_API_KEYS  — many independently revocable keys (one flag, N keys)
#
# If both are non-empty the container entrypoint AND the start- / smoke- /
# status-*.sh scripts exit 2 naming both variables; the server never silently
# chooses one. Leave both empty (default) for stock unauthenticated behavior.
#
# Every route outside the guarded prefixes `/v1`, `/v2`, `/inference` is
# keyless. On the pinned runtime that includes `POST /invocations` and `POST
# /generative_scoring` (both run inference unauthenticated) and the `/tokenize`
# / `/detokenize` utility routes, besides `/health`, `/metrics`, `/version`,
# `/ping`; a keyed deployment still needs network-level access control on the
# server port.
#
# DSPARK_API_KEYS must be a single line and uses literal space/tab separators
# only. Parsing trims and collapses separators, preserves order, allows
# duplicates, and rejects CR/LF/VT/FF, backslashes, or a token starting with
# `-` (which would be mistaken for a vLLM flag), all with exit 2. Set it only
# in `.env.dspark`; the launcher rejects a process-only or mismatched shell value.
# Quote the value: the launcher sources .env.dspark, so an unquoted
# space-separated value would run the second key as a command.
#
# Keys are process arguments and container environment: argv/env visibility —
# host `ps` and `docker inspect` can read them — is by design. Rotation means
# editing this line and doing ./stop-deepseek-v4-flash-dspark.sh && ./start-deepseek-v4-flash-dspark.sh
# (no hot reload). vLLM does not attribute requests to a key, so this provides
# revocation and blast-radius control, not per-user logging.
#
# When either key variable is set, the entrypoint requires
# patches/hotfix-vllm-redact-api-key-log.sh to apply and verify (`--status`) and
# fails the container before exec vllm on any error — no DSPARK_SKIP_HOTFIX
# bypass. It keeps key bytes out of the startup Docker log: the `non-default
# args` line then shows 'api_key': ['<redacted:N value(s)>'] (N = number of
# keys) instead of the key values. argv/env exposure via docker inspect / host
# `ps` is unchanged.
#
# VLLM_API_KEY=sk-single-key
# DSPARK_API_KEYS="sk-dspark-alice sk-dspark-bob"
# Explicit per-node host IPs prevent distributed vLLM/ZeroMQ from binding the
# worker to the head node's fabric address. Set these to each node's RoCE IP.
VLLM_HOST_IP=192.168.192.181
WORKER_VLLM_HOST_IP=192.168.192.198

# Prebuilt Anemll DSpark vLLM GX10 image (https://github.com/Anemll/dspark-vllm-gx10).
# Digest-pinned manifest (immutable). Same bytes as the bare tag today; re-tagging
# cannot silently change what you run. Bump deliberately:
#   1) docker pull ghcr.io/anemll/dspark-vllm-gx10:0.1.1
#   2) get its manifest digest (docker inspect --format '{{index .RepoDigests 0}}')
#   3) update the @sha256: below.
# W0: pulled and digest-confirmed identical on both gb10 and gb10-2.
DSPARK_VLLM_IMAGE=ghcr.io/anemll/dspark-vllm-gx10:0.1.1@sha256:a83948492cf13df455170fb42885f5ef4db54fefe0feff0f841ecbff464ac9d8
# Alternative: build locally with ./build-dspark-vllm-runtime.sh. A digest pin
# cannot be docker build -t (issue #173); the script tags
# vllm-dspark-runtime:dspark-nvfp4-stage-c and does not retag this Anemll image.
# Serve Stage-C by pointing DSPARK_VLLM_IMAGE at that tag and merging
# docker-compose.stage-c.override.yml (see docs/ENVS.md).

# Serving profile. DSpark k must be >= checkpoint dspark_block_size (5);
# k<5 truncates draft blocks (silent on Anemll 0.25.2, rejected on stock 0.26+).
# Capture size = MAX_NUM_SEQS * (MTP_NUM_TOKENS + 1), but the engine clamps it
# to 24 ("Truncating max_cudagraph_capture_size to 24"), so the 36 requested at
# k=5 / seqs=6 was never actually in effect. If graph capture OOMs, lower
# GPU_MEMORY_UTILIZATION_TEXT toward ~0.78.
MAX_MODEL_LEN=1048576
MAX_NUM_SEQS=6
MAX_NUM_BATCHED_TOKENS=8192
# Cap each chunked-prefill chunk (issue #27). stock vLLM 0.25.2 defines but
# never enforces max_num_partial_prefills, so without this cap multiple
# already-admitted-but-still-prefilling requests at the front of the scheduler's
# running list each consume up to max_num_batched_tokens per step; decode-active
# requests behind them get num_new_tokens==0 and are skipped via `continue`
# (NOT preempted) -> zero-preemption decode lane starvation that grows with
# prompt length. 1024 keeps one prefill chunk well under the 8192 budget so
# decode lanes always receive step budget; paired with the #27 partial-prefill
# hotfix (max_num_partial_prefills actually enforced) it collapses x8 spread
# from ~46x to ~1.05x. Safe across MAX_NUM_SEQS and prompt lengths.
# W0: recipe default kept — production's --long-prefill-token-threshold 6144
# (PR #38) is intentionally NOT ported; the plan's disposition table judges
# this recipe mechanism (threshold 1024 + issue-#27 hotfix +
# DSPARK_MAX_INFLIGHT_PREFILLS=2) superior on identical hardware.
LONG_PREFILL_TOKEN_THRESHOLD=1024

# Issue #27: max concurrent in-flight partial prefills. The hotfix reads this
# once during Scheduler construction because Anemll 0.1.1 rejects
# --max-num-partial-prefills before engine init. Values 1-3 are accepted;
# values above 3 clamp to 3. Blank, whitespace-only, nonpositive, or malformed
# values fall back to SchedulerConfig.max_num_partial_prefills (stock 1);
# malformed values warn once instead of crashing admission.
#
# Shipped value is 2 (A/B of 2026-09-02, docs/CLAUDE/ab-results-2026-09-03.md):
# on the 2x GB10 TP=2 lane, c=4 x 8K waves at 2 cut the per-stream TTFT spread
# from 14.6 s to 9.1 s (worst stream 19.3 -> 16.5 s, first stream 4.7 -> 7.4 s)
# and raised the wave's aggregate throughput 12 %, with c=1/c=2/c=6 decode,
# 32K TTFT, draft acceptance and host memory unchanged. An earlier run on older
# overlays measured the opposite (3.72-5.14x lane spread at 2 vs 1.68-2.04x at
# 1); set 1 to restore that behaviour if your traffic prefers it.
DSPARK_MAX_INFLIGHT_PREFILLS=2

# Issue #43: bounded decode service during mixed prefill steps + scheduler
# diagnostics. The hotfix layers on #27 and guarantees no decode-active lane
# is skipped (num_new_tokens==0) while a prefill chunk runs in the same step,
# regardless of LONG_PREFILL_TOKEN_THRESHOLD tuning. Set SCHED_DIAG=1 to emit
# one compact per-step line (scheduled prefill/decode tokens per request +
# zero-token decode skips) to vLLM logs; 0 = silent (zero overhead).
DSPARK_ISSUE43_SCHED_DIAG=0

# Issue #26: sparsify sliding-window (DSpark draft/indexer) prefix-cache
# checkpoints to one tail per 4096-token segment plus the replay boundary.
# Must be a multiple of 256 (scheduler block size). Complements the in-image
# hybrid-coordinator hotfix v2 (patches/hotfix-dsv4-issue26-hybrid-swa-min.py):
# this interval is what keeps warm long-prefix hits (sparse SWA tails).
# v1 also ignored a short SWA length, which skipped prefill with null SWA
# KV on shared Hermes prefixes (issue #36). v2 lets SWA shrink the hit.
# Unset/empty is not supported via compose default.
VLLM_PREFIX_CACHE_RETENTION_INTERVAL=4096

# Keep client `stop` strings dormant until </think> (Anemll port of Tony /
# Capicua25x Patch 5). Default on. Set 0 if a harness must bound reasoning
# with a stop string. DSPARK_SKIP_SUPPRESS_STOPS_HOTFIX=1 skips the patch.
# DSPARK_SUPPRESS_STOPS_IN_REASONING=1
# VLLM_SUPPRESS_STOPS_IN_REASONING=0

# Issue #52 / PR #53 (assistant-final continuation hotfix): when a request's
# messages array ends with an assistant message — or with a trailing
# `latest_reminder` annotation directly after that closed assistant turn — the
# stock renderer leaves the prompt without a generation header, so the model
# generates from a dead state — empty no-op turns / hallucinated DSML markup
# loops in agent harnesses. Default 0 = stock renderer (patch is present on
# the worker but never invoked). Set exactly 1 to apply the patch at container
# boot; the boot then fails (exit 1) if the patch cannot be applied or
# verified, and an already-patched encoder is re-verified instead of rewritten.
# See docs/PATCHES.md ("Issue #52") for evidence status and fail-closed details.
DSPARK_ENABLE_ASSISTANT_FINAL_HOTFIX=0

# Issue #138 Responses full-history replay compatibility. Default 0 keeps the
# pinned vLLM request validator byte-identical and preserves its HTTP 400 for
# the reported hybrid item. Set exactly 1 to accept only a missing-top-level-
# type assistant item whose content is a one-element list containing
# {type: output_text, text: <string>}; stock coercion then supplies message
# type/id/status/annotations. Explicit type values, multipart or malformed
# content, other roles, canonical items, tools, and reasoning are unchanged.
# Enabled apply/verification failure aborts each rank before vLLM exec when the
# pinned protocol.py source has drifted. Recreate both containers after changing
# this flag in either direction: restart does not undo a patch in a container's
# writable layer. Canonical clients should continue replaying the complete
# type=message/id/status/output_text+annotations output object.
DSPARK_ENABLE_ISSUE138_RESPONSES_HISTORY_COMPAT=0
# Issue #136 (vLLM #52805 XGrammar termination backport): default 0 leaves
# backend_xgrammar.py byte-identical to the image. Set exactly 1 only with the
# pinned image above: vLLM 0.25.2.dev0+g752a3a504.d20260714 and xgrammar 0.2.3.
# Enabled starts check the exact stock/post source identity on worker then head
# before either rank starts; each rank then applies and verifies fail-closed.
# After changing this flag, run ./stop-deepseek-v4-flash-dspark.sh successfully
# on both nodes and then ./start-deepseek-v4-flash-dspark.sh. A process or Docker
# restart reuses the writable container layer and is not rollback. To roll back,
# set 0 and stop/remove/recreate both service containers. See docs/PATCHES.md.
DSPARK_ENABLE_ISSUE136_XGRAMMAR_HOTFIX=0

# Issue #66 / #31 GPU thinking_token_budget hotfix: default 0 = stock V2
# sampler (clients that omit the field; sending thinking_token_budget is HTTP
# 400). Set exactly 1 to apply patches/hotfix-dsv4-issue31-v2-thinking-budget-gpu.py
# at boot (fail-closed). Only needed if clients send thinking_token_budget.
# Recreate containers after changing; a healthy systemctl restart can skip rebuild.
DSPARK_ENABLE_ISSUE31_GPU_HOTFIX=0

# Issue #141 opt-in workaround for stochastic TP=2 sparse-MLA stalls in the
# pinned Anemll SM120 adapter. Default 0 leaves installed runtime bytes stock.
# Set exactly 1 to source-lock and chunk only oversized decode calls into fixed
# <=64-row views before vLLM imports; incompatible source fails boot before exec.
# The 64/65 workaround evidence is from one reporting pair; the second failing
# pair has not repeated that A/B, and the underlying defect is still unknown.
# There is no chunk-size knob. After changing this flag, stop then start to
# recreate both containers; `docker compose restart` retains patched layer bytes.
DSPARK_ENABLE_ISSUE141_SPARSE_MLA_CHUNK=0
# Report item 6 (docs/CLAUDE/fable5-1-report.md): sequence-parallel Lightning
# indexer for long prefills. Exact 1 patches sparse_attn_indexer.py at boot
# (fail-closed): TP ranks each gather+score a page-aligned slice of every
# request's compressed keys and merge (score, id) candidates exactly with the
# DCP stable-topk selector. Chunks below DSPARK_SP_INDEXER_MIN_KEYS compressed
# keys (default 8192 = 32K tokens at compress ratio 4) and all decode steps
# keep the stock replicated path. Recreate both ranks when flipping.
DSPARK_ENABLE_SP_INDEXER=0
# Replicated DSpark Markov head (patches/hotfix-dsv4-replicate-markov-head.py).
# 0 (default) = stock sharded head; 1 = apply. A/B 2026-09-02
# (docs/CLAUDE/ab-results-2026-09-02.md): draft acceptance unchanged (the patch
# is numerically correct) but no c=1 gain and c=6 aggregate 122 vs 148, so off.
DSPARK_ENABLE_REPLICATE_MARKOV=0
# Adaptive prefill chunk cap (patches/hotfix-dsv4-adaptive-prefill-chunk.py).
# 0 (default) = stock; 1 = apply. A/B 2026-09-02: boots clean but head-node
# MemAvailable fell to 2.3 GB (3.8-5.2 GB otherwise) because the larger chunk
# workspace lands in host RAM on DGX Spark. Off until that owner is found.
DSPARK_ENABLE_ADAPTIVE_CHUNK=0
# DSPARK_SP_INDEXER_MIN_KEYS=8192
# DeepGEMM SM121 indexer-logits header alias (docs/CLAUDE/item8-fp4-kv-design.md
# §5). The image's vendored DeepGEMM emits sm121_* kernel names on GB10 but
# ships only sm120_* headers, so a JIT-cache miss (fresh volume / new
# VLLM_CACHE_ROOT / new indexer variant) fails at first use. Exact 1 writes
# four alias headers at boot (fail-closed). Default 0 = stock bytes.
# W0 flag for W1: this is a FRESH JIT-cache environment for Vision-Exp on
# gb10/gb10-2 (no prior TileLang/DeepGEMM cache for this checkpoint), which is
# exactly the "fresh volume / new indexer variant" case this hotfix addresses.
# Left at the recipe default (0) here since the task asked for defaults only;
# W1 should watch first-boot logs for the sm121_* kernel-name JIT failure and
# flip this to 1 if it reproduces.
DSPARK_ENABLE_DEEPGEMM_SM121_ALIAS=0

# Do not set GPU_MEMORY_UTILIZATION here — start-deepseek-v4-flash-dspark.sh
# exports it from GPU_MEMORY_UTILIZATION_TEXT.
GPU_MEMORY_UTILIZATION_TEXT=0.835
# Native Vision-Exp images per request (OpenAI image_url). No video modality.
# Anemll argparse wants JSON. `image=8` is also accepted and converted.
# LIMIT_MM_PER_PROMPT={"image":8}
MTP_NUM_TOKENS=6
# Vision-Exp: num_nextn_predict_layers=3, so Anemll rejects k=5
# (must be >= dspark_block_size 5 AND divisible by 3 → 6, 9, …).
# 0731 had n_predict=1, which is why k=5 booted there.
# Official 0731 cards pair k=7 + greedy; that also fails the Vision-Exp
# divisibility check. Capture size is MAX_NUM_SEQS * (MTP_NUM_TOKENS + 1) rounded
# up to a multiple of 8 (48 at 6x6; plain 42 truncates to 40 and costs ~12 % at c=6).
# DSpark draft sampling: probabilistic (default) or greedy.
# DRAFT_SAMPLE_METHOD=probabilistic
# Default reasoning mode: off, low, high, or max. "max" enables full
# thinking/reasoning effort by default; request-level overrides still win.
# W0 decision: production's canonical launch path
# (run-private-ds-production.sh) always applies docker-compose.thinking-on.yml
# (--default-chat-template-kwargs '{"thinking":true}'), i.e. a binary
# always-think contract, not a leveled one. "max" is the closest analog (full
# reasoning effort by default); "high" would understate production's
# always-on-full-effort behavior. NOTE (corrected from an earlier draft of this
# rationale): the recipe's own shipped default for DEFAULT_THINKING is "low",
# not "max" — see docker-compose.dspark.yml's case statement. "max" here is an
# explicit W0 override, not "keeping the recipe default." See Section 5/6 below
# for why this is still only an approximation of production's contract.
DEFAULT_THINKING=max

# Issue #22 hotfix: automatically patches nvfp4_ds_mla long-context decode
# regression on every start.  Set to 1 to skip (e.g. if you've already
# applied the hotfix manually or are using a patched image).
# DSPARK_SKIP_HOTFIX=0

# Issue #79: vLLM shm SpinCondition busy_loop_s 1s -> 2ms (TP>=2 CPU/heat).
# Default on. Set 1 to leave upstream 1s spin.
# DSPARK_SKIP_SPIN_WAIT_HOTFIX=0

# Issue #117: upstream vLLM #45224 bounds lost-notify reader recovery at 5s
# and releases SHM read slots on consumer exceptions. Default on. Set 1 only
# for paired stop/remove/recreate rollback; the Issue #79 setting is unchanged.
# DSPARK_SKIP_ISSUE117_RECHECK_HOTFIX=0

# No sampling override. The launcher keeps --generation-config vllm only.
# Explicit client request parameters still win.

# Raised-admission throughput data, measured on 2x DGX Spark TP=2 @ 70a7cc4.
# This is PERFORMANCE data, not a safety recommendation -- read the STABILITY
# block below before raising MAX_NUM_SEQS on anything you care about:
# MAX_MODEL_LEN=1048576
# MAX_NUM_SEQS=32
# MAX_NUM_BATCHED_TOKENS=12288
#
# [... full stability-caveat block preserved verbatim in the file; omitted
# here only to keep this brief shorter — see the live file on gb10 for the
# complete issue #141 stochastic-stall discussion. No values in it are
# active/uncommented.]
#
# Conservative prior agent lane:
# MAX_MODEL_LEN=1048576
# MAX_NUM_SEQS=6
# GPU_MEMORY_UTILIZATION=0.80
#
# Concurrent HEAVY PREFILLS remain scheduler-bound regardless of these knobs
# (issues #80/#140): admission tuning raises decode throughput; it does not
# fix TTFT contention when multiple large cold prompts arrive together.

# ---------------------------------------------------------------------------
# Anemll 0.1.1-safe vLLM / runtime knobs (default compose injects these)
# ---------------------------------------------------------------------------
VLLM_USE_FLASHINFER_SAMPLER=1
VLLM_USE_BREAKABLE_CUDAGRAPH=0
VLLM_USE_B12X_MOE=1
VLLM_B12X_W4A16_FORCE_BLOCKS_PER_SM=0
VLLM_B12X_W4A16_FORCE_BLOCKS_MAX_M=16
VLLM_B12X_W4A16_FORCE_TILE_CONFIG=
# b12x small-M packed decode (M<=8). Compose passes this through; default off.
# B12X_W4A16_TC_DECODE=0

VLLM_ALLOW_LONG_MAX_MODEL_LEN=1
VLLM_SPARSE_INDEXER_MAX_LOGITS_MB=256
VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=0

# CuTeDSL / b12x compile target for GB10 (not a VLLM_* registry key).
CUTE_DSL_ARCH=sm_121a
TORCH_CUDA_ARCH_LIST=12.1a
FLASHINFER_CUDA_ARCH_LIST=12.1a
FLASHINFER_DISABLE_VERSION_CHECK=1
TILELANG_CLEANUP_TEMP_FILES=1
# Issue #65/#87: keep sample_tokens RPC alive through a mid-serve JIT
# (stock 300s). TileLang cache lives on the HF volume, not the container layer.
VLLM_EXECUTE_MODEL_TIMEOUT_SECONDS=1800
TILELANG_CACHE_DIR=/cache/huggingface/tilelang-cache
# Issue #117: persist Triton's JIT cache too — the in-image ~/.triton/cache
# dies on container recreate, so every restart re-JITs known shapes mid-serve,
# and a compiling rank can stall its TP peer past torch's 600s NCCL watchdog
# (a deadline VLLM_EXECUTE_MODEL_TIMEOUT_SECONDS does not extend).
TRITON_CACHE_DIR=/cache/huggingface/triton-cache
# Issue #117 disposition: PyTorch ProcessGroupNCCL flight recorder. Ring
# buffer + dump-on-timeout pinned on (DUMP_ON_TIMEOUT requires MONITORING=1
# and BUFFER_SIZE>0 per the torch header); dumps persist on the HF volume so
# a watchdog-killed pair still leaves per-rank evidence for torchfrtrace.
# [... TORCH_FR_* commentary preserved verbatim in the live file ...]
TORCH_FR_BUFFER_SIZE=2000
TORCH_NCCL_DUMP_ON_TIMEOUT=1
TORCH_NCCL_ENABLE_MONITORING=1
TORCH_FR_DUMP_TEMP_FILE=/cache/huggingface/nccl-fr/comm_lib_trace_rank_
TORCH_NCCL_DEBUG_INFO_PIPE_FILE=/tmp/fr_dump_pipe_
B12X_CUTE_COMPILE_CACHE_DIR=/cache/huggingface/b12x-cute-cache
# DSPARK_BOOT_SHAPE_WARMUP=1
# DSPARK_WARMUP_REQ_TIMEOUT=240
DG_JIT_USE_NVRTC=0
DG_JIT_NVCC_COMPILER=/usr/local/cuda/bin/nvcc
NCCL_NET=IB
NCCL_IB_DISABLE=0
NCCL_CUMEM_ENABLE=0
NCCL_IGNORE_CPU_AFFINITY=1
NCCL_DEBUG=WARN
NCCL_NVLS_ENABLE=0
# [... NCCL_IB_MERGE_NICS / dual-HCA QSFP measurement commentary preserved
# verbatim in the live file; all commented out, not applicable to our
# single-HCA-per-node fabric ...]
# NCCL_IB_MERGE_NICS=0
# NCCL_IB_GID_AUTO=0
# NCCL_IB_GID_INDEX=3
# WORKER_NCCL_IB_GID_INDEX=3
# NCCL_NET_GDR_LEVEL=SYS
# NCCL_NET_GDR_READ=1
# NCCL_DMABUF_ENABLE=0
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# ---------------------------------------------------------------------------
# Stage-C overlay only — DO NOT enable on Anemll 0.1.1
# ---------------------------------------------------------------------------
# VLLM_USE_B12X_WO_PROJECTION=1
# VLLM_DSPARK_CONFIDENCE_THRESHOLD=0.0
# VLLM_DSPARK_CONFIDENCE_SCHEDULER=off
# VLLM_DSPARK_LOCAL_ARGMAX=1
# VLLM_DSPARK_REPLICATE_MARKOV_W1=1
# VLLM_DSPARK_FUSED_MARKOV_ARGMAX=0
# VLLM_DSPARK_GPU_REJECTED_CONTEXT_MASK=1
# VLLM_DSPARK_REFERENCE_KV_QUANT_DEQUANT=0
# DSPARK_SLOT_CLAMP=1
# VLLM_DSPARK_HARDWARE_SCHEDULER_EARLY_STOP=1
# B12X_W4A16_TC_DECODE=0
# VLLM_DSV4_B12X_COMPRESSED_MLA=0
# VLLM_DSV4_DSPARK_DEFER_TARGET_CAPTURE=0
# VLLM_DSV4_DSPARK_DEFER_TARGET_CAPTURE_EXACT=0
# VLLM_TRITON_MLA_SPARSE=1
# VLLM_SKIP_INIT_MEMORY_CHECK=1

# Native vLLM multimodal for Vision-Exp is not wired yet. This branch serves
# the Vision-Exp checkpoint as a text (+ DSpark) boot on the same Anemll image.
# The old Qwen3-VL sidecar / ds4f-vision MCP path is removed.
```

*(Two long blocks — the raised-admission/issue #141 stability discussion and
the NCCL dual-HCA QSFP measurement notes — are elided above only for this
brief's readability; every uncommented/active value from the live file is
reproduced exactly. The live file at `gb10:~/dspark-vision/.env.dspark` is
the authoritative, complete, byte-exact copy.)*

## 3. Checkpoint revision reconciliation (KEY GATE) — RESOLVED

- Production's HF cache on gb10 already held two Vision-Exp snapshots
  (`31ea1118…`, `6821d6ad3681a4b137b066b76094fa82ebd0a380` = `refs/main`).
  The recipe's pin, `86f746b36186f0e567729a5c06a8c918caba82a9`, matched
  **neither**.
- Because the vision/encoding patchers are exact-source-locked (fail-closed
  at boot on drift), this was treated as a hard W0 gate rather than a
  cosmetic mismatch.
- Resolution: `snapshot_download` against the pinned revision. HF's
  content-addressed blob store meant only the one file that actually
  differed between `6821d6ad…` and `86f746b3…` — `README.md`, 5054 bytes —
  needed fetching; all 48 model shards, `config.json`, tokenizer, and
  encoding files were byte-identical to the already-cached snapshot and were
  linked in place. The pin resolved in **~9 seconds**.
- Current state on gb10 (re-verified today):
  `~/.cache/huggingface/hub/models--deepseek-ai--DeepSeek-V4-Flash-Vision-Exp/snapshots/`
  contains all three snapshots (`31ea1118…`, `6821d6ad…`, `86f746b3…`), the
  pinned one fully populated with working symlinks into `blobs/`, total
  cache directory size 157 GiB.

## 4. Anemll image pull — both nodes, digests match

- `ghcr.io/anemll/dspark-vllm-gx10:0.1.1` pulled concurrently on gb10 and
  gb10-2.
- Final digest on **both** hosts:
  `ghcr.io/anemll/dspark-vllm-gx10@sha256:a83948492cf13df455170fb42885f5ef4db54fefe0feff0f841ecbff464ac9d8`
  — confirmed identical, pinned into `.env.dspark`'s `DSPARK_VLLM_IMAGE`.
- Confirmed vLLM version inside the image:
  `0.25.2.dev0+g752a3a504.d20260714` (exact match to the plan's expectation).

## 5. Worker weights — local copy via rsync (not NFS)

- Decision: `DSPARK_WORKER_HF_NFS=0` (local copy), matching the pattern the
  recipe itself recommends when a dedicated fabric link is available and
  avoiding a live NFSv4 dependency between nodes during inference.
- `rsync -a --partial --inplace` of
  `models--deepseek-ai--DeepSeek-V4-Flash-Vision-Exp` (blobs + all 3
  snapshot symlink trees) from gb10 to gb10-2 over the RoCE fabric IP, run
  under `nohup` so it survived the session.
- Completion confirmed from `/tmp/rsync-vision-exp-to-worker.log`:
  `Number of files: 335 (reg: 87, dir: 24, link: 224)`, `total size is
  167,831,874,600, speedup is 1.00`, no errors.
- Verified on gb10-2 today: `du -sh` reports 157 GiB, all 3 snapshot
  directories present including the pin, and spot-checked symlinks
  (`config.json -> ../../blobs/11823cdb9ef2911555e3a50832e26463ce8bce5d`,
  `README.md` resolving to a valid 5054-byte blob) resolve correctly.
- gb10-2 free disk after the transfer: 436 GiB.

## 6. Compatibility checks (CPU-only) — results and one incident

### 6a. `--enable-prompt-tokens-details` (PR #33 disposition)

- Confirmed via static source grep inside the pulled image (no code
  execution — `vllm serve --help` itself cannot run without a real GPU
  device visible; that's a parser-construction limitation
  (`RuntimeError: Failed to infer device type` at
  `vllm/config/device.py:56`), not a GPU memory issue, since no `--gpus`
  flag was ever passed and zero devices were visible to the container).
- `enable_prompt_tokens_details: bool = False` is a genuine registered CLI
  field in `vllm/entrypoints/openai/cli_args.py` (line 132) on this pinned
  vLLM build, wired through the responses/completion/chat/anthropic serving
  paths.
- **The recipe's own `docker-compose.dspark.yml` already passes
  `--enable-prompt-tokens-details` unconditionally** (confirmed at the line
  in the `vllm serve` command block). **Conclusion: PR #33 needs no
  porting — already satisfied by vanilla recipe defaults.**

### 6b. `scripts/ci-validate.sh` — incident, root cause, fix, and outcome

**This must be read as a transparent finding, not swept aside**: running the
task-instructed compatibility script caused an inadvertent, failed attempt to
allocate real CUDA memory on the shared production GPU.

- First run (as instructed, no special flags):
  `ssh gb10 "cd ~/dspark-vision && timeout 500 bash scripts/ci-validate.sh"`
  → exit 1. The failure was inside
  `tests/test_issue133_triton_specialization.py`, invoked from the script's
  own "== unit tests (no GPU) ==" section, with:
  ```
  torch.AcceleratorError: CUDA error: out of memory
  Search for `cudaErrorMemoryAllocation`...
  ```
  on `block_table = torch.tensor(..., device=device)` calls.
- **Root cause**: that test file guards itself with
  `@unittest.skipUnless(torch is not None and torch.cuda.is_available(), ...)`.
  `torch.cuda.is_available()` reflects driver/device *presence*, not free
  memory — since gb10 has a real, driver-visible GPU (currently ~78%
  committed by production vLLM), the guard did not skip, and the test
  attempted a real `cuda:0` tensor allocation, which failed with OOM. This
  is a **mislabeling bug in the recipe's own CI script**: its section header
  ("no GPU") and its top-of-file docstring claim CPU-only behavior, but this
  one test file's skip condition checks device presence rather than
  availability/free-memory, so it does not correctly no-op on a
  GPU-present-but-memory-full host — exactly our shared production node.
- **Production impact verified as none**: `curl -fsS -m 10
  http://127.0.0.1:8890/v1/models` succeeded throughout with the full
  `deepseek-v4-flash-0731` listing, and `docker ps` showed
  `gb10-deepseek-v4-vllm-dspark-1` continuously "Up" with no restart. The
  allocation attempt failed outright (no memory was ever held), so nothing
  was displaced.
- **Fix (environment-level guard, no file modification)**: re-ran with
  `CUDA_VISIBLE_DEVICES=""`:
  `ssh gb10 "cd ~/dspark-vision && CUDA_VISIBLE_DEVICES= timeout 500 bash scripts/ci-validate.sh"`
  → exit 0, "CI validate passed (CPU recipe gates only)." with 118 `ok`
  lines. This correctly forces `torch.cuda.is_available()` to `False`,
  making the skip guard fire as the script's own documentation claims it
  should. (The `[FAIL]`-looking lines visible inside a clean run are the
  test suite's own fixtures verifying its *own* failure-detection logic by
  injecting synthetic failures — each is wrapped in an "OK (skipped=N)"
  summary line, not a genuine gate failure.)
- **Recommendation for W1/W2**: always invoke `scripts/ci-validate.sh` with
  `CUDA_VISIBLE_DEVICES=""` on any host with a live GPU (i.e. every host in
  this cluster, always) until the upstream test's skip guard is fixed to
  check free memory or is patched to genuinely require zero visible devices.

### 6c. Smoke / status script overrides

- `smoke-deepseek-v4-flash-dspark.sh` correctly derives its probe URL from
  `VLLM_HOST`/`VLLM_PORT`/`SERVED_MODEL_NAME` read out of `.env.dspark`
  (falls back to `127.0.0.1` for a wildcard bind, per its own inline
  comment) — no issue, will correctly target `:8890` /
  `deepseek-v4-flash-0731` once launched.
- `status-deepseek-v4-flash-dspark.sh` has **one caveat to carry into W1**:
  its `API_URL` default correctly reads `VLLM_PORT` from the env file, but
  its separate `PORT` variable (used only for the `ss -ltn "( sport = :$PORT
  )"` listening-socket check) defaults to `8888` and does **not** read
  `VLLM_PORT`. On this deployment (port 8890) that one check will silently
  probe the wrong port unless `PORT=8890` is exported explicitly when
  invoking the status script, e.g. `PORT=8890
  ./status-deepseek-v4-flash-dspark.sh`. The `/v1/models` check in the same
  script is unaffected (it uses `API_URL`, built from `VLLM_PORT`
  correctly).

## 7. Flag-mapping table: production → recipe

Sources: `gb10:~/gb10-ds4/execution/docker-compose.yml` +
`docker-compose.thinking-on.yml` + `env/common.env` (production, read-only,
untouched) vs. `gb10:~/dspark-vision/docker-compose.dspark.yml` +
`.env.dspark.example` + `docs/ENVS.md` (recipe), all read verbatim on
2026-09-03.

### 7a. `vllm serve` CLI arguments

| Production | Recipe | Verdict |
| --- | --- | --- |
| `${DSPARK_MODEL:-/models/DeepSeek-V4-Flash-0731}` (positional, bind-mounted local dir) | `${DSPARK_MODEL:-deepseek-ai/DeepSeek-V4-Flash-Vision-Exp}` (positional, resolved from HF hub cache) | **Different mechanism, same effect.** Recipe uses HF cache (`HF_HUB_OFFLINE=1` + the reconciled pin) instead of a bind-mounted directory. No action needed — W0 already populated the cache correctly on both nodes. |
| — (no revision flag) | `$REVISION_ARGS` → `--revision ${DSPARK_REVISION}` when set | Recipe-only addition (HF hub pinning); already set to `86f746b3…`. |
| `--served-model-name deepseek-v4-flash-0731` | `--served-model-name ${SERVED_MODEL_NAME:-deepseek-v4-flash-vision-exp}` | **Same**, once `SERVED_MODEL_NAME` override is applied (done). |
| `--host 0.0.0.0` | `--host ${VLLM_HOST:-127.0.0.1}` | **Same**, once `VLLM_HOST=0.0.0.0` override is applied (done). |
| `--port 8890` | `--port ${VLLM_PORT:-8888}` | **Same**, once `VLLM_PORT=8890` override is applied (done). |
| `--trust-remote-code` | `--trust-remote-code` | Identical. |
| — | `"$API_KEY_ARGS[@]"` | Recipe-only, empty (no `VLLM_API_KEY`/`DSPARK_API_KEYS` set) → no-op, matches production's unauthenticated posture. |
| `--tensor-parallel-size 2` (hardcoded) | `--tensor-parallel-size ${TP_SIZE:-2}` | Same effective value. |
| `--pipeline-parallel-size 1` | `--pipeline-parallel-size 1` | Identical. |
| `--kv-cache-dtype ${KV_CACHE_DTYPE:-nvfp4_ds_mla}` | `--kv-cache-dtype nvfp4_ds_mla` (hardcoded) | Same effective value. |
| `--block-size 256` | `--block-size 256` | Identical. |
| `--max-model-len 1048576` | `--max-model-len ${MAX_MODEL_LEN:-1048576}` | Same (recipe default kept). |
| `--max-num-seqs 6` | `--max-num-seqs ${MAX_NUM_SEQS:-6}` | Same (recipe default kept). |
| `--max-num-batched-tokens 8192` | `--max-num-batched-tokens ${MAX_NUM_BATCHED_TOKENS:-8192}` | Same (recipe default kept). |
| `--long-prefill-token-threshold 6144` (PR #38) | `--long-prefill-token-threshold ${LONG_PREFILL_TOKEN_THRESHOLD:-1024}` | **Intentionally divergent.** Plan disposition: do not port PR #38; recipe's 1024 + issue-#27 hotfix + `DSPARK_MAX_INFLIGHT_PREFILLS=2` addresses the same starvation problem, judged superior on identical hardware. |
| — (no explicit capture-size flag) | `--max-cudagraph-capture-size $(( (MAX_NUM_SEQS*(MTP_NUM_TOKENS+1)+7)/8*8 ))` = **48** at our 6×6 config | Recipe-only, explicit computation (vs. production's implicit/engine-default behavior). Enhancement, not a regression risk. |
| `--gpu-memory-utilization 0.78` | `--gpu-memory-utilization ${GPU_MEMORY_UTILIZATION_TEXT:-0.835}` | **Intentionally divergent** per explicit task instruction: kept at recipe default rather than porting production's 0.78. Watch KV-pool/OOM headroom in W1/W2; the recipe's own comment suggests dropping toward ~0.78 if graph capture OOMs. |
| `--enable-prefix-caching` | `--enable-prefix-caching` | Identical. |
| `--enable-prompt-tokens-details` | `--enable-prompt-tokens-details` (unconditional) | **Identical — PR #33 already satisfied, no porting needed** (see §6a). |
| `--async-scheduling` | `--async-scheduling` | Identical. |
| `--enable-chunked-prefill` | `--enable-chunked-prefill` | Identical. |
| `--speculative-config {"method":"dspark","num_speculative_tokens":5,"draft_sample_method":"probabilistic"}` | `--speculative-config {"method":"dspark","num_speculative_tokens":6,"draft_sample_method":"probabilistic"}` | **k differs (5 vs 6), required.** Vision-Exp's `num_nextn_predict_layers=3` means k must be ≥5 **and** divisible by 3 (0731 used n_predict=1, so k=5 was legal there but is rejected for Vision-Exp). `MTP_NUM_TOKENS=6` in `.env.dspark` is a correctness requirement, not a style choice. |
| `--tokenizer-mode deepseek_v4` | `--tokenizer-mode deepseek_v4` | Identical. |
| — | `"$LIMIT_MM_ARGS[@]"` → `--limit-mm-per-prompt {"image":8}` | Recipe-only, new Vision-Exp capability (the entire point of this bring-up). Default 8 images/prompt, `user` turns only, no video. |
| `--distributed-executor-backend mp` | `--distributed-executor-backend mp` | Identical. |
| — | `--moe-backend flashinfer_b12x` | Recipe-only explicit flag. Production relies solely on the `VLLM_USE_B12X_MOE=1` env var with no CLI equivalent; recipe sets both. Not a regression — recipe is more explicit, same MoE backend family. |
| `--tool-call-parser deepseek_v4` | `--tool-call-parser deepseek_v4` | Identical. |
| `--enable-auto-tool-choice` | `--enable-auto-tool-choice` | Identical. |
| `--reasoning-parser deepseek_v4` | `--reasoning-parser deepseek_v4` | Identical. |
| `--reasoning-config '{"reasoning_parser":"deepseek_v4","reasoning_start_str":"<think>","reasoning_end_str":"</think>"}'` | Byte-identical string | Identical. |
| `--default-chat-template-kwargs '{"thinking":true}'` (production's **actual** canonical launch path, via `docker-compose.thinking-on.yml`) | `--default-chat-template-kwargs "$DEFAULT_CHAT_TEMPLATE_KWARGS"` where `DEFAULT_THINKING=max` → `{"thinking":true,"reasoning_effort":"max"}` | **Approximation, not an exact match — flag for G2 validation.** Production sets *only* `{"thinking":true}` (no `reasoning_effort` key at all, i.e. the chat template's own internal default applies when the key is absent). The recipe's `max` maps to `{"thinking":true,"reasoning_effort":"max"}`, adding an explicit key production never sends. If the template's absent-key default is not itself "max", G2 correctness testing (W1/W2) should compare actual thinking-token verbosity/length against production on identical prompts, not just assume the mapping is exact. (Correction from an earlier internal note: the recipe's own **default** for `DEFAULT_THINKING` is `low`, not `max` — confirmed from the compose file's case statement. `max` is a deliberate W0 override, not "keeping the recipe default.") |
| `--generation-config vllm` | `--generation-config vllm` | Identical. |
| `--enable-flashinfer-autotune` | `--enable-flashinfer-autotune` | Identical. |
| `--nnodes 2` (hardcoded) | `--nnodes ${NNODES:-2}` | Same effective value. |
| `--node-rank ${NODE_RANK}` | `--node-rank ${NODE_RANK}` | Identical mechanism. |
| `--master-addr ${MASTER_ADDR}` | `--master-addr ${MASTER_ADDR}` | Identical mechanism. |
| `--master-port ${MASTER_PORT:-29510}` | `--master-port ${MASTER_PORT:-25000}` | Different default; `.env.dspark` explicitly sets `MASTER_PORT=25000` (recipe's own default), not production's 29510 — internal-only rendezvous port, no client visibility, no conflict expected since production will be stopped before any recipe launch. |
| `${HEADLESS:+--headless}` | `${HEADLESS:+--headless}` | Identical mechanism. |

### 7b. Environment variables

Classified per `docs/ENVS.md` (audited 2026-07-29 against this exact image
tag) into three lanes:

**Category A — registered on Anemll 0.1.1, safe.** All of production's
`HF_HOME`/`HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE`/`HF_HUB_DISABLE_XET`/
`VLLM_CACHE_ROOT`/`VLLM_HOST_IP`/`VLLM_ALLOW_LONG_MAX_MODEL_LEN`/
`VLLM_SPARSE_INDEXER_MAX_LOGITS_MB`/`VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS`/
`VLLM_USE_FLASHINFER_SAMPLER`/`VLLM_USE_B12X_MOE`/
`VLLM_B12X_W4A16_FORCE_BLOCKS_PER_SM`/`VLLM_B12X_W4A16_FORCE_BLOCKS_MAX_M`/
`TORCH_CUDA_ARCH_LIST`/`FLASHINFER_CUDA_ARCH_LIST`/
`FLASHINFER_DISABLE_VERSION_CHECK`/`TILELANG_CLEANUP_TEMP_FILES`/
`DG_JIT_USE_NVRTC`/`PYTORCH_CUDA_ALLOC_CONF`/all `NCCL_*`/`NODE_RANK`/
`HEADLESS`/`MASTER_ADDR`/`MASTER_PORT`/`MTP_NUM_TOKENS` carry over onto the
recipe with a genuine, effective equivalent. Two sub-notes:
- `PYTORCH_CUDA_ALLOC_CONF`: production leaves this empty; recipe defaults
  to `expandable_segments:True`. `.env.dspark` keeps the **recipe default**
  (explicit ask) — flagged here as a deliberate divergence, not a
  regression risk (this is a well-known, generally-safe allocator knob).
- `DG_JIT_NVCC_COMPILER`: production `/opt/env/bin/nvcc` vs. recipe
  `/usr/local/cuda/bin/nvcc` — pure base-image path layout difference
  (different CUDA toolkit install location inside the two images), not a
  functional divergence. `.env.dspark` keeps the recipe default.

**Category B — Stage-C overlay-registered only; warn + no-op on Anemll
0.1.1.** Production sets all of these (they are meaningful in production's
Stage-C-derived runtime): `VLLM_USE_B12X_WO_PROJECTION`,
`VLLM_DSPARK_CONFIDENCE_THRESHOLD`, `VLLM_DSPARK_CONFIDENCE_SCHEDULER`,
`VLLM_DSPARK_LOCAL_ARGMAX`, `VLLM_DSPARK_REPLICATE_MARKOV_W1`,
`VLLM_DSPARK_FUSED_MARKOV_ARGMAX`, `VLLM_DSPARK_GPU_REJECTED_CONTEXT_MASK`,
`VLLM_DSPARK_REFERENCE_KV_QUANT_DEQUANT`,
`VLLM_DSPARK_HARDWARE_SCHEDULER_EARLY_STOP`, `VLLM_DSV4_B12X_COMPRESSED_MLA`,
`VLLM_DSV4_DSPARK_DEFER_TARGET_CAPTURE(_EXACT)`. On the pinned Anemll image
these are **not** in `vllm.envs.environment_variables`; injecting them only
produces an "Unknown vLLM environment variable" warning at boot and is a
no-op. `.env.dspark` correctly leaves the entire Stage-C block commented
out. **This does not mean the underlying behavior is absent** — per
`docs/ENVS.md`, Anemll may bake equivalent logic into the image without
exposing every Stage-C kill-switch; it means these specific env-var toggles
have no effect either way on this image.

**Category C — not registered as `VLLM_*` on either lane, or host-only;
avoid/non-applicable on Anemll.** Production sets `VLLM_TRITON_MLA_SPARSE`
and `VLLM_SKIP_INIT_MEMORY_CHECK` (both explicitly flagged "avoid on
Anemll" in `docs/ENVS.md`) and `DSPARK_SLOT_CLAMP` (non-`VLLM_` prefix,
"treat as Stage-C/overlay unless confirmed") and `B12X_W4A16_TC_DECODE`
(non-`VLLM_` debug knob, recipe exposes it too but defaulted off).
`.env.dspark` correctly leaves all four commented out in the Stage-C block.

**Recipe-only additions with no production equivalent** (all either
launcher-side conveniences or Vision-Exp/Anemll-specific mechanisms, none
of which regress anything production relies on): `DSPARK_MODEL` (as an env
var, vs. production's positional-arg + bind-mount pattern),
`VLLM_EXECUTE_MODEL_TIMEOUT_SECONDS=1800` (mid-serve JIT protection),
`VLLM_USE_BREAKABLE_CUDAGRAPH=0`, `CUTE_DSL_ARCH=sm_121a`,
`FLASHINFER_WORKSPACE_BASE`, `TILELANG_CACHE_DIR`, `TRITON_CACHE_DIR`,
`TORCH_FR_*`/`TORCH_NCCL_*` (flight-recorder diagnostics),
`B12X_CUTE_COMPILE_CACHE_DIR`, `ENABLE_VLLM_GB10_PATCH`,
`GB10_HYBRID_NVFP4_M_THRESHOLD`, `VLLM_PLUGINS`,
`VLLM_PREFIX_CACHE_RETENTION_INTERVAL=4096`, `DSPARK_ISSUE43_SCHED_DIAG`,
`DSPARK_MAX_INFLIGHT_PREFILLS=2`, `DSPARK_REVISION`, `DSPARK_ENCODING_FILE`,
`VLLM_API_KEY`/`DSPARK_API_KEYS`, `LIMIT_MM_PER_PROMPT`, every
`DSPARK_ENABLE_*` opt-in hotfix switch (assistant-final, issue138, issue136
xgrammar, issue31 GPU, issue141 sparse-MLA, sp-indexer, replicate-Markov,
adaptive-chunk, deepgemm-sm121-alias — all left at their default `0` per
task instruction; see §2's inline note on `DEEPGEMM_SM121_ALIAS` as a W1
watch-item), `NCCL_IB_ADDR_FAMILY`, `NCCL_IB_ROCE_VERSION_NUM`,
`NCCL_IB_MERGE_NICS`/`SUBNET_AWARE_ROUTING`/`SUBNET_PREFIX_LEN`,
`NCCL_NET_GDR_LEVEL`/`READ`, `NCCL_DMABUF_ENABLE`, `TP_SIZE`, `NNODES`.

**RoCE GID handling — mechanism correction.** The plan document refers to
"`NCCL_IB_GID_AUTO=1`" as if it were a literal toggle; reading the compose
file directly shows the actual mechanism is: `NCCL_IB_GID_INDEX` is left
**unset** (empty), and the entrypoint normalizes a defined-but-empty value
to truly absent before `exec vllm`, which causes NCCL to auto-select the
RoCEv2/IPv4 GID per HCA from sysfs. Production instead pins
`NCCL_IB_GID_INDEX=3` explicitly. `.env.dspark` correctly does **not** set
`NCCL_IB_GID_INDEX`, achieving the intended auto-selection behavior — this
matches the plan's RoCE-GID-pitfall disposition even though the underlying
mechanism description needed this correction.

## 8. Open items / watch-list for W1 (not blockers, but should be read before the idle window)

1. **`DEFAULT_THINKING=max` is an approximation of production's `{"thinking":true}` contract, not a proven-identical mapping** — see §7a. Recommend a direct response-length/verbosity comparison against production on the same prompt set during G2, not just a boot-success check.
2. **`status-deepseek-v4-flash-dspark.sh`'s `PORT` variable defaults to 8888 and ignores `VLLM_PORT`** — export `PORT=8890` explicitly when running status checks against this deployment, or the port-listening (`ss -ltn`) line will silently check the wrong port (the `/v1/models` check is unaffected).
3. **`DSPARK_ENABLE_DEEPGEMM_SM121_ALIAS=0`** — Vision-Exp is a fresh JIT-cache environment on both nodes (no prior TileLang/DeepGEMM cache for this checkpoint). If first boot fails on an `sm121_*` kernel-name JIT miss (the image ships only `sm120_*` headers), flip this to `1` and recreate both containers.
4. **Always invoke `scripts/ci-validate.sh` with `CUDA_VISIBLE_DEVICES=""`** on this or any GPU-present host, per §6b — the script's own "no GPU" unit-test section contains one file whose skip guard checks device presence, not availability, and will otherwise attempt a real (harmless-but-failing) CUDA allocation.
5. **`gb10-2:~/dspark-vision` does not exist yet — this is expected, not an action item.** `start-deepseek-v4-flash-dspark.sh` creates the directory and syncs the compose file, `.env.dspark`, and every patch file to it automatically as part of its own pre-flight, before touching Docker. No manual pre-staging is needed beyond what W0 already did (image pulled, weights rsynced).
6. **`MASTER_PORT=25000`** (recipe default) is used instead of production's `29510` — internal TCP rendezvous port only, not client-visible, and production will already be stopped before any recipe launch, so no port conflict is expected; flagging only so W1 doesn't need to re-derive this reasoning.
7. **`GPU_MEMORY_UTILIZATION_TEXT=0.835`** (recipe default) vs. production's `0.78` — per task instruction, kept at recipe default for W0/W1; the recipe's own inline comment suggests dropping toward ~0.78 if graph capture OOMs during boot. Worth an explicit watch during the W1 smoke boot's memory checks.

None of the above block starting W1. All artifacts (cloned recipe, written
`.env.dspark`, reconciled checkpoint pin, matching image digests on both
nodes, replicated weights on gb10-2) are in place and verified as of this
write-up.
