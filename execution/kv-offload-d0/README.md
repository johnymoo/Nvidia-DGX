# D0 diagnostic arm — runbook (prepared 2026-09-01, NOT yet executed)

Purpose: pin the block-hash-mismatch faulting mechanism (C1 / C2 / C3-family /
Patch-3 decode-side) with ONE 30-minute connector boot + KV-event capture,
per `planning/02-working/2026-09-01-kv-offload-hash-mismatch-rootcause.md` §7
and Rev 2 R2.4. Zero code changes; env/compose lines only; every file backed
up and restored byte-identical.

Status: **awaiting user window approval.** Do not execute without it.
Current service state (precondition): baseline + adopted A0 hunks, healthy.

Package (all validated 2026-09-01 morning):

| File | Role | Validation |
| --- | --- | --- |
| `edit_files.py` | d0 / rollback / verify host edits | applied+rolled-back against real local mirrors; byte-identical restore, no leftovers, YAML-valid edits, idempotent |
| `kv_events_subscriber.py` | in-container ZMQ subscriber → raw JSONL | py_compile (needs container pyzmq; run via docker exec) |
| `d0_probes.py` | A / A' / B battery (TTFT via SSE), meta JSONL | py_compile |
| `analyze_d0.py` | discriminator readout + decision matrix | self-test (`selftest/`) reproduces C1/C2/C3 labels and Patch-3 split correctly |
| `selftest/` | synthetic events + meta + summary.json | regression reference for the labels |

## Sequence (total wall ≈ 50-55 min: 2 boots + 15 min probes)

All commands from the lead workstation. `GB10=/home/chriswang/gb10-ds4`,
`GB102=/home/admin/gb10-ds4`, `CID=gb10-deepseek-v4-vllm-dspark-1`,
evidence dir `tmp/kv-offload-d0/evidence/`.

1. **Pre-flight (2 min)** — service healthy, no active long sessions:
   `ssh gb10 'cd $GB10 && execution/run-private-ds-production.sh --status'`
   + quick portal listen check. Record `TAG=$(date -u +%Y%m%dT%H%M)`Z.

2. **Edits (both hosts, 3 min)**:
   ```
   ssh gb10   "python3 - d0   $GB10  $TAG"  < tmp/kv-offload-d0/edit_files.py
   ssh gb10-2 "python3 - d0   $GB102 $TAG"  < tmp/kv-offload-d0/edit_files.py
   ssh gb10   "python3 - verify $GB10  $TAG" < tmp/kv-offload-d0/edit_files.py   # all true
   ssh gb10-2 "python3 - verify $GB102 $TAG" < tmp/kv-offload-d0/edit_files.py
   ```
   Edits = A1 config (OffloadingConnector @ 8 GiB, both compose files) +
   `--kv-events-config '{"enable_kv_cache_events":true,"publisher":"zmq","endpoint":"tcp://127.0.0.1:19555","topic":"kv"}'`
   + `PYTHONHASHSEED: "0"` (compose env) + `KV_OFFLOAD_CPU_BYTES=8589934592` (common.env).
   Acceptance script deliberately NOT edited (contains-style asserts unaffected; fewer files to roll back).

3. **Restart into D0 config (~18 min)**: `--stop --restore-qwen` → settle ≥180 s →
   `--start` (boot 13-16 min). Boot gates: connector init + CPUOffloadingSpec in
   journal (TZ=UTC), kv-events/zmq publisher init mention, KV pool ≥ 7.3 GiB/rank,
   `free -g` gb10 ≥ 4 Gi.

4. **Subscriber up (1 min)**:
   ```
   scp tmp/kv-offload-d0/kv_events_subscriber.py gb10:/tmp/
   ssh gb10 "docker cp /tmp/kv_events_subscriber.py $CID:/tmp/ && \
             docker exec -d $CID python3 /tmp/kv_events_subscriber.py --out /tmp/kv_events_d0.jsonl && \
             sleep 3 && docker exec $CID wc -l /tmp/kv_events_d0.jsonl"
   ```
   (Engine binds 127.0.0.1:19555 in the host netns; in-container subscriber avoids
   host pyzmq deps and any extra exposed port.)

5. **Probes (≈10 min)**: `python3 tmp/kv-offload-d0/d0_probes.py --meta tmp/kv-offload-d0/evidence/meta.jsonl`
   — A (3K, prefill-only) → A' byte-identical → B (20K, ≥3 chunks, max_tokens 200).
   Watch: A' `cached_tokens` (reproduces A1's zero-hit?), canary A==A' answers.

6. **Capture + analyze (3 min)**:
   ```
   ssh gb10 "docker exec $CID touch /tmp/kv_sub_stop && sleep 1 && \
             docker cp $CID:/tmp/kv_events_d0.jsonl /tmp/." && \
   scp gb10:/tmp/kv_events_d0.jsonl tmp/kv-offload-d0/evidence/
   python3 tmp/kv-offload-d0/analyze_d0.py \
     --events tmp/kv-offload-d0/evidence/kv_events_d0.jsonl \
     --meta tmp/kv-offload-d0/evidence/meta.jsonl \
     --out tmp/kv-offload-d0/evidence/summary.json
   ```
   Read the census BEFORE the numbers (event schema at snapshot 7e33081cee7b
   unverified in-container; if `source` never appears, treat "unlabeled"=GPU and
   identify the connector stream by its per-medium behavior/absence of block_ids).

7. **Rollback + restore boot (~18 min)**: same `d0`→`rollback` subcommand both
   hosts (restores pre-D0 = baseline+A0 state, byte-identical asserted) →
   `--stop --restore-qwen` → settle → `--start` → post-restore lite check:
   identical-prompt-twice cached_tokens>0 (the §8 standing probe), one small
   perf request, `:8004` proxy 200, protected containers healthy.

## Readout → next action (from analyze_d0.py decision matrix)

| Observation | Mechanism | Fix vehicle |
| --- | --- | --- |
| fresh hash values per pass (C1-like), any phase | hash-input instability | vendored subtree @ f5e441de10bd; if concentrated post-TTFT ALSO adopt upstream #46066/#48245 semantics (fork shim on Patch 3) |
| stable hashes re-stored (C2-like) | snapshot bookkeeping bugs | vendored subtree @ f5e441de10bd (fixes wholesale) |
| A' misses + GPU hash sets identical | C3-family / fork boundary code (protected-prompt-blocks territory) | fork-side fix in boundary files + targeted upstream cherry-picks |
| healthy everywhere + A' still misses | lookup-time fault, stores clean | new lookup-side instrumentation (D0b) |
| healthy everywhere + A' hits | not reproduced this boot | diff boot flags vs A1 before concluding |
| A' answer ≠ A answer | CORRUPTION | instant kill: stop, rollback immediately regardless of step |

## Notes

- The subscriber file inside the container and `/tmp/kv_sub_stop` vanish with
  the container on rollback restart — no container-state cleanup needed.
- `PYTHONHASHSEED=0` stays OFF after rollback (it was D0-only); if D0's readout
  is C2/C1-fixed-upstream, consider adding it permanently in the Phase B image
  (root-cause doc §8, Dynamo practice) — decide then, not now.
- Probes reuse the campaign's rand-words generator (same distribution as
  A1's needle probes) but carry no needle; correctness canary = A/A' equality.
