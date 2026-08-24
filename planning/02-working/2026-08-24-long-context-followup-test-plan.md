# Long-Context Follow-up Test Plan: Options 1 -> 3 -> 4 (2026-08-24)

Executor: autonomous agent (Sonnet). Decision-maker: the lead session reviews
the report and decides adoption. The executor NEVER adopts a change: every
test arm is measured, then the fleet is restored to the production baseline.

Goal: produce decision-grade evidence for three follow-ups documented in
`planning/03-core/03-operations-runbook.md` ("Long-context follow-up
options"):

1. `GPU_MEMORY_UTILIZATION` 0.78 -> 0.80 (KV pool +~330K tokens; risk:
   upstream issue #8 - boots clean, dies when DSpark buffers allocate under
   first real traffic).
3. `VLLM_USE_B12X_SPARSE_INDEXER=1` A/B (tiled SM120-family indexer
   extend/topk path; candidate for the ~25% prefill decay from 64K to 254K).
4. Kernel-level prefill characterization via nsys (evidence to decide whether
   deep-kernel work is worth it; NOT a kernel change).

Option 2 (NVMe KV offload) is intentionally out of scope.

## 0. Hard constraints (violating any of these = stop and report)

- Operate the DeepSeek service ONLY through
  `ssh gb10 'cd /home/chriswang/gb10-ds4 && execution/run-private-ds-production.sh --check|--start|--status|--stop'`.
  Never run per-rank `docker compose up/down/stop` for the DeepSeek service
  while `/home/chriswang/gb10-ds4/artifacts/service/active.json` exists.
- Do not touch: the `:8004` X570 proxy, pdf2md, trading, lexdata, the SSH
  relay unit, or any non-DeepSeek container.
- Never store or request a password. Never push to git. Do not modify files
  in the local workspace repo (only remote host files + local `tmp/` evidence).
- `--max-model-len 1048576` is frozen. Never change it or `MAX_NUM_SEQS`,
  `MAX_NUM_BATCHED_TOKENS=8192`, `LONG_PREFILL_TOKEN_THRESHOLD=6144`,
  `MTP_NUM_TOKENS=5`, `KV_CACHE_DTYPE=nvfp4_ds_mla`.
- Every remote file you edit gets a timestamped backup first:
  `cp FILE FILE.bak-$(date -u +%Y%m%dT%H%M)`. Record every backup path.
- Total wall budget: 6 hours from first restart. If exceeded, skip remaining
  tests and jump to Section 7 (Final restore). Section 7 runs UNCONDITIONALLY,
  including after any failure.
- If the service cannot be brought back healthy after 2 start attempts at any
  point, restore all backups, attempt one final baseline start, then STOP all
  work and report the exact state (do not loop on mutations).

## 1. Fixed facts (verified 2026-08-24, do not re-derive)

- Hosts: head `gb10` (user chriswang, deploy root `/home/chriswang/gb10-ds4`),
  worker `gb10-2` (user admin, deploy root `/home/admin/gb10-ds4`). Both
  reachable by ssh from this workstation. Container name on both:
  `gb10-deepseek-v4-vllm-dspark-1`.
- API: `http://192.168.88.181:8890/v1`, model `deepseek-v4-flash-0731`.
  Metrics: `http://192.168.88.181:8890/metrics`
  (`vllm:num_requests_running`, `vllm:num_requests_waiting`).
- Env files (edit IN SYNC on both hosts):
  head `/home/chriswang/gb10-ds4/execution/env/common.env`,
  worker `/home/admin/gb10-ds4/execution/env/common.env`.
- Compose files (edit IN SYNC on both hosts unless stated head-only):
  `execution/docker-compose.yml` (base; `environment:` map merges with the
  override) and `execution/docker-compose.thinking-on.yml` (production
  override that REPLACES the whole `command:`).
- Contract: head `execution/run-vllm-acceptance.sh` `assert_rendered_config`
  asserts the rendered command of BOTH ranks, including
  `--gpu-memory-utilization 0.78` (around line 230). The check runs from the
  head copy only; the worker copy is not executed for this. Assertions use
  substring `contains(...)`, so wrapping the command with a profiler
  launcher does NOT break them, but changing gmu DOES.
- Restart discipline: after `--stop`, unified memory must settle before
  `--start`. Failed run `20260814T050959Z` showed an immediate restart left
  7.07 GiB KV < the required 7.3 GiB floor. Wait >= 3 minutes after stop AND
  confirm `free -g` "available" on both hosts is within ~10 GB of the
  pre-test stopped baseline; if a start fails on the KV floor, wait 5 more
  minutes and retry once.
- Before any `--stop`: poll `/metrics` until `vllm:num_requests_running` is 0
  (up to 10 minutes), then proceed regardless (window is authorized).
- Boot takes ~13-16 min. After `--start` returns, verify:
  `curl -fsS http://192.168.88.181:8890/v1/models` and read the new run ID
  from `/home/chriswang/gb10-ds4/artifacts/service/active.json`.
- KV pool line: `ssh gb10 'docker logs gb10-deepseek-v4-vllm-dspark-1 2>&1 | grep -iE "kv cache (size|memory)"'`
  (same on gb10-2). Record GiB and tokens for every boot.
- Probe tool: `tmp/prefill-probe/probe.py <n_words> <seed>` (run locally).
  Sends one uncached prompt, max_tokens=1, thinking off; prints JSON with
  `latency_s`, `prompt_tokens`, `cached_tokens`, `tok_per_s`.
  ~3.5 tokens/word. Never reuse a seed for a "cold" measurement.
- Prior baseline (same config, 2026-08-23/24): cold prefill ~1939 tok/s @14K
  -> ~1573 tok/s @254K (~1400 @480K); solo 64K cold ~36 s; decode ~62 tok/s;
  small request during a 130K cold prefill ~11 s; boot KV pool 8.81 GiB /
  1,221,928 tokens.
- B12X gates verified in the deployed source: SM121 passes
  `is_device_capability_family(120)`; the fp4 indexer cache is impossible on
  GB10 (SM100-only assert), so the deployed indexer cache is already the
  FP8/C4 one that B12X requires. Expected boot outcome: clean.
  Related knob left at default: `VLLM_B12X_NSA_EXTEND_TOPK_SUPERTILE_K=32768`.
- The fork has NO torch-profiler support (`VLLM_TORCH_PROFILER_DIR` absent
  from `vllm/envs.py`; no `/start_profile` endpoint). Host gb10 has Nsight
  Systems 2025.3.2 at `/opt/nvidia/nsight-systems/2025.3.2` (sbsa target
  binary `target-linux-sbsa-armv8/nsys`; `/usr/local/bin/nsys` on host PATH).
- Shell hygiene: avoid deep nested quoting over ssh. Prefer
  `ssh HOST 'bash -s' < local_script.sh`, or scp a script over. Avoid bare
  `===` echoes in zsh.

## 2. Evidence layout

Create `tmp/followup-tests/<UTC>/` locally (UTC = start timestamp,
`date -u +%Y%m%dT%H%M%SZ`), with subdirs `t0-baseline/`, `t1-gmu080/`,
`t3-b12x/`, `t4-nsys/`, `restore/`. Every probe JSON line, soak log, docker
log excerpt, nsys stats CSV, and edited-file backup path list goes there.
Write the final `report.md` at the top level of that directory.

## 3. Test 0 - fresh baseline on the running production config (no restart)

Purpose: same-session comparison arms for tests 1/3/4. Current production run
is `20260823T164410Z` (gmu 0.78, B12X off, threshold 6144).

1. Record `--status` output, active.json, `/v1/models`, and both ranks' KV
   pool log lines.
2. Depth sweep (sequential, fresh seeds, record each JSON):
   n_words = 4600 (~16K), 18300 (~64K), 37000 (~130K), 72500 (~254K), plus a
   repeat at 18300 with another seed for variance. During the 18300 run,
   capture `nvidia-smi dmon -s pucm` at 1 Hz on BOTH hosts into files
   (start it before, stop after).
3. Decode rate: one request, small prompt, `max_tokens=500`, temperature 0,
   thinking off; record completion_tokens / wall seconds. Run it twice.
4. HOL check: launch n_words=37000 cold prefill in the background; 5 s later
   send a small request ("Reply with the single word: ready", max_tokens 8);
   record the small request's wall latency.
5. Correctness set (temperature 0, thinking off; save full responses):
   - C1 "What is the capital of Australia? Answer with one word." (max 16)
   - C2 "Compute 17*23. Answer with just the number." (max 16)
   - C3 "Write a Python one-liner that reverses a string s." (max 64)
   - C4 "List the first 6 prime numbers, comma separated." (max 32)
   - C5 needle: build locally with python: 17000 random words (seed 90001),
     insert the sentence "The secret passphrase is AURORA-73-KESTREL." after
     word 7000, append "Question: what is the secret passphrase mentioned in
     the text? Answer with just the passphrase." (max 32). ~60K tokens.
     Expected answer contains "AURORA-73-KESTREL".
   Keep the exact C5 prompt bytes (same seed/construction) for reuse in
   Test 3 so the comparison is apples-to-apples (it will be cache-warm on
   re-runs within an arm; that is fine - correctness, not speed).

Note: the 72500-word probe evicts real user cache; run it exactly once here
and once in Test 3 arm B.

## 4. Test 1 - GPU_MEMORY_UTILIZATION 0.80 (boot + KV pool + soak stability)

Apply:
1. Both hosts: backup then edit `execution/env/common.env`:
   `GPU_MEMORY_UTILIZATION=0.78` -> `0.80` (add the line if absent; the
   compose default is 0.78 so the env line must exist and be 0.80).
2. Head only: backup then edit `execution/run-vllm-acceptance.sh`:
   `s/--gpu-memory-utilization 0.78/--gpu-memory-utilization 0.80/`.
3. Drain (metrics poll), `--stop`, settle wait, `--start`.
   - If start fails on the KV floor: wait 5 min, retry once. If it fails
     again or on the contract: revert steps 1-2, baseline `--start`, mark
     Test 1 FAILED(boot), continue to Test 3.
4. Record boot KV pool (GiB + tokens) from both ranks. Expectation: pool
   grows from ~1.22M toward ~1.5M+ tokens. If the pool did NOT grow
   materially (< +150K tokens), note it - that alone weakens option 1.

Soak (>= 40 min total, this is the core of Test 1 - issue #8 died under
first real traffic, so begin immediately after boot):
5. Phase A (first-allocation risk, ~5 min): one small request; then
   n_words=18300 cold (fresh seed); then n_words=37000 cold (fresh seed).
   After each: both containers still up, API 200.
6. Phase B (>= 35 min): loop with a local driver script:
   - every ~6 min: one cold prefill alternating 18300 / 37000 words (fresh
     seeds), run in background so overlap occurs;
   - every 30 s: one small request (max_tokens 8), record latency;
   - every ~6 min: one decode request (max_tokens 300);
   - keep <= 3 requests in flight.
   Monitor every 60 s into a log: `docker ps` state on both hosts, `curl -m 5
   /v1/models` status, `free -g` available, and
   `journalctl -k --since '-2 min' | grep -Ei 'Xid|oom|out of memory'` on
   both hosts; plus `docker logs --since 2m` filtered for
   `CUDA|OOM|Error|Traceback` on both ranks.
7. PASS = zero engine deaths, zero API outages, zero Xid/OOM, small-request
   latency profile comparable to Test 0, cold prefill tok/s within ~10% of
   Test 0. FAIL = any engine death/OOM (capture full logs BEFORE recovery).
8. Wrap-up (regardless of outcome): revert BOTH hosts' env to
   `GPU_MEMORY_UTILIZATION=0.78` and restore the head contract file from its
   backup. Do NOT restart yet - the next restart belongs to Test 3.
   (Exception: if Test 1 FAILED with a dead service, restore backups first,
   then apply Test 3's edits, and use the recovery start as Test 3's start.)

## 5. Test 3 - B12X sparse indexer A/B (prefill depth curve + correctness)

Arm A = Test 0 numbers. Arm B:
1. Both hosts: backup then edit `execution/docker-compose.yml`: in the
   `environment:` map, directly after the `VLLM_SPARSE_INDEXER_MAX_LOGITS_MB`
   line, insert:
   `      VLLM_USE_B12X_SPARSE_INDEXER: "${VLLM_USE_B12X_SPARSE_INDEXER:-0}"`
   (the thinking-on override merges environment maps; no command change; the
   contract is unaffected).
2. Both hosts: append to `execution/env/common.env`:
   `VLLM_USE_B12X_SPARSE_INDEXER=1`.
3. Confirm gmu was reverted to 0.78 and the contract backup restored (Test 1
   step 8). Drain, `--stop`, settle, `--start`.
   - If boot fails with a RuntimeError mentioning B12X/indexer: capture the
     exact traceback, remove the env line (keep the compose passthrough,
     default 0), restart baseline, mark Test 3 FAILED(boot), go to Test 4.
4. Verify the path is active: `docker exec` grep the engine logs for
   b12x/indexer init lines on both ranks; record boot KV pool (expect ~1.22M;
   a materially smaller pool is itself a finding).
5. Arm B depth sweep: identical methodology to Test 0 step 2 (fresh seeds!),
   n_words 4600 / 18300 / 37000 / 72500 + one 18300 repeat, with dmon capture
   during one 18300 run.
6. Arm B decode rate (Test 0 step 3) and HOL check (step 4).
7. Arm B correctness: run C1-C5 byte-identical to Test 0. C2 and C5 must
   match exactly ("391"; contains "AURORA-73-KESTREL"); C1/C3/C4 must be
   semantically equal to arm A. Any correctness regression = the whole
   option is DEAD regardless of speed; say so explicitly in the report.
8. Wrap-up: remove `VLLM_USE_B12X_SPARSE_INDEXER=1` from both env files
   (leave the compose passthrough line, default 0). Do NOT restart yet -
   the next restart belongs to Test 4.

## 6. Test 4 - kernel-level prefill characterization (nsys, head rank only)

Primary path (time-box: 90 min from the Test 4 restart; on overrun, fall
back and restore):
1. Head only: backup then edit `execution/docker-compose.yml` volumes: add
   `      - /opt/nvidia/nsight-systems/2025.3.2:/host-nsys:ro`.
2. Head only: backup then edit `execution/docker-compose.thinking-on.yml`:
   replace `exec /opt/env/bin/vllm serve` with
   `exec /host-nsys/target-linux-sbsa-armv8/nsys launch --session-new=dsprof -- /opt/env/bin/vllm serve`
   (consult `/host-nsys/target-linux-sbsa-armv8/nsys launch --help` if the
   flag set differs; the goal: injection enabled, NO capture until
   `nsys start`). All contract-asserted substrings remain present. Worker
   files stay untouched.
3. Drain, `--stop`, settle, `--start`. If boot fails or hangs past the
   readiness timeout: restore both head compose backups, baseline `--start`,
   mark Test 4 BLOCKED(injection), run the fallback (step 8) on baseline.
4. Capture window 1 (shallow): inside the head container
   (`docker exec gb10-deepseek-v4-vllm-dspark-1 ...`):
   `nsys start --session=dsprof -o /cache/huggingface/nsys-16k`; run local
   probe n_words=4600 (fresh seed); `nsys stop --session=dsprof`.
5. Capture window 2 (deep): `nsys start --session=dsprof -o
   /cache/huggingface/nsys-130k`; probe n_words=37000 (fresh seed);
   `nsys stop --session=dsprof`. If the session refuses a second start,
   capture both probes in one window and note it.
6. Optional if time allows - capture window 3 (decode): start, one request
   with max_tokens=400, stop, `-o /cache/huggingface/nsys-decode`.
7. Analysis on the gb10 HOST (nsys on PATH): locate the `.nsys-rep` files
   under the head CACHE_ROOT (read `execution/env/node.env` on gb10 for the
   path), then for each:
   `nsys stats --report cuda_gpu_kern_sum --format csv -o <out> <rep>`
   (also `cuda_gpu_sum` if available). scp the CSVs into `t4-nsys/`.
   Deliverable table per capture: top 20 kernels by total GPU time with %,
   plus total capture wall time vs sum of kernel time (exposes idle/comm
   gaps). Highlight: share of grouped/MoE GEMM kernels, indexer/topk/logits
   kernels, attention kernels, NCCL kernels, and how the mix shifts 16K->130K.
8. Fallback evidence (only if the primary path is blocked): fit the Test 0 +
   Test 3 depth sweeps to `time(n) = a*n + b*n^2` (report a, b, and R^2, and
   the implied flat-vs-quadratic split at 130K/254K/465K), attach the dmon
   SM%/power traces, and state explicitly that kernel-level attribution
   requires framework instrumentation this fork lacks.
9. Wrap-up: restore the two head compose backups (removing wrapper + mount).

## 7. Final restore and verification (UNCONDITIONAL)

1. Restore/verify on both hosts against the pre-test backups: env
   `common.env` (gmu 0.78, NO B12X line), `docker-compose.yml`,
   `docker-compose.thinking-on.yml`, head `run-vllm-acceptance.sh`. The final
   host state must be byte-identical to pre-test (diff each file against its
   backup and record the diffs - all must be empty).
2. Drain, `--stop`, settle, `--start`. Verify: `--status`, `/v1/models`,
   run ID recorded, KV pool line matches ~8.8 GiB / ~1.22M tokens, one smoke
   chat request answers, one small probe (n_words 800) succeeds, `:8004`
   proxy still healthy (`curl -fsS http://192.168.88.181:8004/v1/models`),
   lexdata/trading/pdf2md containers untouched.
3. If the final start fails twice: restore backups again, capture full logs,
   STOP, and put the exact state at the top of the report.

## 8. Report format (write to report.md; also return a summary)

- Executive table: per test PASS/FAIL/BLOCKED + the one number that matters.
- Test 0 vs Test 3 depth table: tok/s at 16K/64K/130K/254K per arm + delta %.
- Test 1: KV pool before/after (GiB + tokens), soak duration, event log
  summary (deaths/Xid/OOM/API errors = counts), small-request latency
  distribution during soak.
- Test 3: correctness matrix C1-C5 (arm A answer, arm B answer, verdict).
- Test 4: top-kernel tables per capture, or the fallback fit.
- Timeline of every stop/start with run IDs; all backup paths; any deviation
  from this plan; final-state verification diffs (must be empty).
- Raw file inventory under `tmp/followup-tests/<UTC>/`.
