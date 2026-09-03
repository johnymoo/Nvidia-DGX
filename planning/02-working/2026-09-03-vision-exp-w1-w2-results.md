# Vision-Exp W1/W2 Results (2026-09-03, window opened 00:53Z)

Stack: MiaAI-Lab recipe @ d828ddd, Anemll image 0.1.1 (digest-pinned),
checkpoint pin 86f746b3, `.env.dspark` per W0 brief (port 8890, name
`deepseek-v4-flash-0731`, recipe defaults, `DEFAULT_THINKING=max`).

## Window timeline

- 00:53:42Z production stopped (canonical `--stop --restore-qwen`; receipt
  `state: stopped`, run 20260902T163014Z; qwen `was_running=false` → not
  restored, no GPU co-tenant). Both nodes released ~100 GiB.
- 00:53–01:02Z vision stack first boot: weights 101 s, engine init 201 s,
  graph capture 23 s / 1.85 GiB, **API ready 01:02:24Z (~9 min)**. No
  sm121 JIT failure (watch item #3 did not fire).
- Clients transparently reattached (same port+name); the stack has served
  live portal traffic from minute one with zero failed requests observed.
- W2 ran 01:08–01:40Z. W3 soak started 01:41:27Z.

## G1 boot — PASS

- `deepseek-v4-flash-0731` on :8890; head MemAvailable 5.5 GiB (floor 4);
  protected services untouched (qwen36-8004-proxy, tradingagents-ashare,
  compassionate_burnell, lexdata-ai all Up); worker container healthy.
- KV pool: **11.87 GiB / 1,763,205 tokens** at util 0.835 (recipe's
  reference box: 17.04 GiB / 2.33 M — our co-resident host services shrink
  the profiled pool on unified memory; still > 1 M ctx, no action).
- Boot warnings all known-benign (thinking_token_budget unsupported on V2
  runner = issue #31 default-off; symm-mem capability notice; torch.compile
  unsupported notice).

## G2 correctness — PASS

- temp-0 text needle exact; bat-and-ball 0.05 correct.
- Vision: solid-red → "Red" (227 prompt tok); chart PNG → correctly
  identified as decode-benchmark table including its title.
- Image on `system` role → clean HTTP 400 with documented message
  (fail-closed recipe behavior confirmed).
- Tool calls: deepseek_v4 parser emits proper `tool_calls`,
  `finish_reason:"tool_calls"` (get_weather/Tokyo probe).
- Thinking: enabled by default; reasoning text present.
  **API drift note: this vLLM (0.25.2.dev) returns reasoning in
  `message.reasoning`, NOT `message.reasoning_content`** (old stack key).
  Clients parsing `reasoning_content` lose the reasoning display but keep
  `content`. Portal owners should be told.

## G3 performance — PASS (workload-matched)

Measured with production's own `bench_full.py` suite against the vision
stack (4 warmups first), plus recipe `benchmark-0731.py`, with a 5 s
concurrency sampler attributing live-traffic contention.

| Metric | Vision-Exp (thinking=max) | Gate | Baseline (thinking-on prod) | Verdict |
| --- | --- | --- | --- | --- |
| single-stream mean (5-task suite) | **56.1 tok/s** | ≥50 | 55.4 | PASS (+1.3 %) |
| single-stream peak | 69.1 (mult12/json60) | — | 66.1 | +4.5 % |
| story (creative) | 30.6 | — | 31.7 (Aug fork) | −3 % |
| c=6 aggregate, engine steady-state | **132.9–139.1 tok/s** | ≥125 | recipe ref ≈139 | PASS |
| c=6 `bench_full` wave (400-tok bursts) | 99.8 | — | no thinking-on baseline exists | n/a |
| 64K cold prefill | 1610.9 tok/s (TTFT 40.8 s @65,653 tok) | ≥1482 (−15 % of 1744) | 1744–1772 | PASS (−7.6 %) |
| 25K prefill | 1589.7 | — | 1753 (Aug) | −9.3 % |
| 78K prefill | 2291.2 | — | 2575 (Aug) | −11 % |
| 8K×4 wave TTFT spread | 10.1 s (median TTFT 14.4 s) | — | recipe A/B: 9.1 s w/ inflight=2 | matches recipe claim |
| TTFT short prompt | 0.37–0.48 s | sane | — | PASS |

Contract-difference context (recorded, not gating): the 2026-08-11
baseline (85 tok/s count300, c=6 229) was **thinking-off on the retired
Stage-C-tuned f277b3d fork**. Same thinking-off conditions on the vision
stack today: count300 58.1 (−32 %), c=6 187.1 (−18 %). Root cause is
checkpoint generation, not the serving stack: Vision-Exp's MTP head is
n_predict=3 / k=6 with per-position acceptance falling to ~0.05 by pos 6
(draft acceptance 22–50 % depending on content), vs 0731's n_predict=1 /
k=5. Production's *current* thinking-on contract is what clients actually
get, and there the two stacks are at parity.

- Spec decode: mean acceptance length 2.3–4.0; MTP_NUM_TOKENS=6 is the
  legal minimum (≥5 and divisible by 3). No recipe knob regressions found;
  defaults kept throughout (no tuning was needed to clear the gates).

## Measurement-hygiene notes

- Live portal traffic shares the MAX_NUM_SEQS=6 slots with any benchmark;
  bench-visible numbers exclude client tokens. Engine `loggers.py` lines
  are the truthful aggregate; the c=1 42.3 / c=6 101 readings from
  `benchmark-0731.py` are deflated by (a) wave ramp/drain and (b) client
  co-tenancy, and (c) the numbered-words workload's lower draft acceptance.
- `bench_full.py` currently defaults to :8890 — it benchmarked the vision
  stack directly; tag string "official-0731-patch4" in its output is a
  hardcoded label, ignore it.

## G4 soak — PASS (01:41:27Z–02:26Z, 45 min)

Load: 3 text lanes (rotating structured/creative/code prompts), vision
request every 90 s (alternating red smoke image / chart PNG), ~12K-token
prefill every 5 min, plus live portal client traffic on top.

- **410/410 requests OK, 0 failures, 179,009 completion tokens.**
- Head MemAvailable 4.62 GiB at end (floor 4), worker 7.36 GiB.
- Worker engine log: 0 error lines. Kernel journal: 0 NVRM/XID/OOM.
- Head engine log: exactly one "Exception in ASGI application" — it is the
  logged form of *our own* G2 system-role-image rejection probe (the
  `ValueError: Images are supported in user messages only…` path; client
  correctly received HTTP 400 before the soak started). No real errors.
- Live-traffic spec decode seen as high as acceptance length 5.07 / 67.9 %
  draft acceptance — acceptance is content-dependent; W2's 22–50 % readings
  were workload artifacts, not a stack defect.

## Cutover — DONE 2026-09-03 ~02:30Z (pre-authorized)

`deepseek-v4-flash-0731` on :8890 is now served by the Vision-Exp recipe
stack as the gb10-cluster default inference model. Actions taken:

- `docker update --restart unless-stopped deepseek-v4-flash-vllm-dspark-1`
  on both nodes (reboot restores the service; recipe start script exits 3
  when already up — treat as already-up, not failure).
- `.env.dspark` `DSPARK_RESTART_POLICY=unless-stopped` for future recreates.
- Old production containers verified `restart=no, state=exited` on both
  nodes — cannot resurrect and fight for port 8890 / memory.
- Post-cutover status: recipe status script all green, digest-pinned Anemll
  image identical on both nodes, `/v1/models` serving with
  `root: deepseek-ai/DeepSeek-V4-Flash-Vision-Exp`, max_model_len 1048576.

Rollback (G5, verified paths): old production untouched at `~/gb10-ds4`
(compose + .bak files byte-exact). Instant path:
`cd ~/dspark-vision && ./stop-deepseek-v4-flash-dspark.sh` then
`~/gb10-ds4/execution/run-private-ds-production.sh --start`.

## Follow-ups

1. Tell portal owners: reasoning now arrives in `message.reasoning`
   (was `reasoning_content`); `content`/tool-calls unchanged.
2. Old-stack idle-window runbook is superseded: `run-private-ds-production.sh
   --start` must NOT be run while the vision stack holds :8890 (rollback
   path stops vision first).
3. Next campaign: re-port the issue-#45 NVMe KV tier onto the Anemll stack.
4. Optional tuning backlog (not needed for gates): KV pool is 11.87 GiB vs
   recipe reference 17.04 (host co-residents); `GPU_MEMORY_UTILIZATION_TEXT`
   could be probed upward only with a dedicated window and OOM watch.
