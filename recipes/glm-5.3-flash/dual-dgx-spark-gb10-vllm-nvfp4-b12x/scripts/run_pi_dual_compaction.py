#!/usr/bin/env python3
"""pi 双 agent 上下文叠加到压缩：真实 agent 客户端的并发长请求场景。

与 bench_agent_context.py（API 级合成阶梯，精确 TTFT）互补：
  - 用 pi（非 codex）驱动 N 个真实 agent 会话并发；
  - 每轮给每个 agent 追加一条 ~2k token 的确定性"工具结果"（@file 注入），
    上下文一路叠加，直到 pi 自动压缩（auto-compaction）；
  - 每轮记录 wall 时间；从 pi 会话 JSONL 解析 input/output/cacheRead tokens；
  - 压缩判定：会话出现 compact* 条目，或 input_tokens 在 ≥80% contextWindow
    后较上轮骤降 >50%。命中后再补跑一轮，度量压缩后首轮的恢复表现。

TTFT 不从 pi 取（pi 不暴露首 token 时间）：精确 TTFT 用 bench_agent_context.py；
本脚本回答的是"真实 agent 走到压缩时会发生什么、恢复多快"。

用法：
  python3 run_pi_dual_compaction.py --label dual-pi --out results/pi-dual-compact
  python3 run_pi_dual_compaction.py --agents 1 --label solo-pi --out results/pi-solo
"""

import argparse
import json
import os
import random
import string
import subprocess
import threading
import time
import uuid

FILLER_HEADER = "tool result #{turn} (bash: tail -n 400 build-and-telemetry.log)\n"


def filler_text(turn: int, n_chars: int, rng: random.Random) -> str:
    """Deterministic, turn-unique, token-dense filler (~2.5 chars/token)."""
    out = [FILLER_HEADER.format(turn=turn)]
    routes = ["/api/v7/items", "/api/v7/cart", "/ingest/batch", "/auth/refresh",
              "/metrics/flush", "/search/idx", "/notify/push", "/billing/usage"]
    words = ["adapter", "backoff", "checksum", "downgrade", "envelope", "flush",
             "gateway", "handshake", "idempotent", "journal", "keepalive",
             "lease", "merge", "normalize", "overflow", "prefetch", "quota",
             "retry", "shard", "throttle", "upstream", "vertex", "warmup"]
    while sum(len(l) + 1 for l in out) < n_chars:
        r = rng.choice(routes)
        out.append(
            f"[{rng.randint(10,29)}:{rng.randint(10,59)}:{rng.randint(10,59)}] "
            f"{r} status={rng.choice([200, 200, 200, 201, 204, 304, 500])} "
            f"latency_ms={rng.uniform(0.8, 950):.1f} bytes={rng.randint(64, 65536)} "
            f"shard={rng.randint(0, 31)} {rng.choice(words)}={rng.choice(words)}_"
            f"{''.join(rng.choices(string.hexdigits.lower(), k=8))}"
        )
    return "\n".join(out)


def last_assistant_usage(session_path):
    """Latest assistant message (usage, timestamp) + any compaction entries."""
    usage = None
    ts = None
    compacted = False
    if not os.path.exists(session_path):
        return None, None, False
    with open(session_path) as f:
        for line in f:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = e.get("type", "")
            if "compact" in t:
                compacted = True
            if t == "message" and e.get("message", {}).get("role") == "assistant":
                usage = e["message"].get("usage")
                ts = e.get("timestamp")
    return usage, ts, compacted


def pi_turn(pi_bin, session_dir, session_id, chunk_path, turn, timeout_s, log):
    """One pi -p turn with @file injection. Returns (wall_s, stdout, returncode)."""
    instruction = (f"Append the attached tool result to the working context. "
                   f"Do not run any tools. Reply with exactly: CHUNK {turn} OK")
    cmd = [pi_bin, "-p", "--mode", "json",
           "--provider", "private-llm", "--model", "GLM-5.3-Flash-EXL3",
           "--session-dir", session_dir, "--session-id", session_id,
           f"@{chunk_path}", instruction]
    t0 = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout_s)
        wall = time.monotonic() - t0
        if proc.returncode != 0:
            log.append(f"turn {turn}: pi rc={proc.returncode} "
                       f"stderr={proc.stderr[-300:]}")
        return wall, proc.stdout, proc.returncode
    except subprocess.TimeoutExpired:
        return time.monotonic() - t0, "", -1


def agent_loop(agent_id, args, out_dir, stop, results):
    label = f"{args.label}-a{agent_id}"
    jsonl_path = os.path.join(out_dir, f"{label}.jsonl")
    sess_dir = os.path.join(args.scratch, f"agent{agent_id}", "sessions")
    os.makedirs(sess_dir, exist_ok=True)
    session_id = str(uuid.uuid4())
    # pi's layout is <session-dir>/<sanitized-cwd>/<ts>_<id>.jsonl; locate by id.
    real = None
    logs = []
    rng = random.Random(f"pi:{args.label}:{agent_id}")
    chunk_path = os.path.join(args.scratch, f"agent{agent_id}", "chunk.txt")
    os.makedirs(os.path.dirname(chunk_path), exist_ok=True)

    rows = []
    compaction_turn = None
    post_compaction_done = False
    prev_input = 0
    t0 = time.monotonic()
    print(f"[{label}] start: window {args.context_window}, "
          f"+~{args.step_tokens} tok/turn", flush=True)

    with open(jsonl_path, "w") as fj:
        turn = 0
        while not stop.is_set():
            turn += 1
            with open(chunk_path, "w") as fc:
                fc.write(filler_text(turn, int(args.step_tokens * 2.5), rng))
            wall, stdout, rc = pi_turn(args.pi_bin, sess_dir, session_id,
                                       chunk_path, turn, args.timeout, logs)
            # locate the session file (pi names it <ts>_<session_id>.jsonl)
            real = None
            for root, _dirs, files in os.walk(sess_dir):
                for fn in files:
                    if session_id in fn:
                        real = os.path.join(root, fn)
            usage, ts, compact_evt = (last_assistant_usage(real)
                                      if real else (None, None, False))
            inp = (usage or {}).get("input")
            outp = (usage or {}).get("output")
            cre = (usage or {}).get("cacheRead")
            row = {
                "turn": turn, "wall_s": round(wall, 2), "rc": rc,
                "input_tokens": inp, "output_tokens": outp,
                "cache_read": cre, "assistant_ts": ts,
                "compaction_event": compact_evt,
                "wall_since_start_s": round(time.monotonic() - t0, 1),
            }
            rows.append(row)
            fj.write(json.dumps(row) + "\n"); fj.flush()
            print(f"[{label}] turn {turn:3d}: input {inp} cached {cre} "
                  f"out {outp} wall {wall:6.1f}s", flush=True)

            dropped = (prev_input and inp and inp < prev_input * 0.5)
            if prev_input >= 0.8 * args.context_window and dropped:
                compact_evt = True
            prev_input = inp or prev_input

            if (compact_evt or dropped) and compaction_turn is None:
                compaction_turn = turn
                print(f"[{label}] COMPACTION detected at turn {turn} "
                      f"(input {inp}, prev {prev_input})", flush=True)
                continue  # one more turn to observe recovery
            if compaction_turn is not None:
                post_compaction_done = True
                print(f"[{label}] post-compaction turn done; stop", flush=True)
                break
            if inp and inp >= 0.97 * args.context_window:
                print(f"[{label}] hit 97% of window without compaction; stop",
                      flush=True)
                break
            if turn >= args.max_turns:
                print(f"[{label}] max turns reached", flush=True)
                break
            if rc != 0 and all(r.get("rc", 0) != 0
                               for r in rows[-3:]):
                print(f"[{label}] 3 consecutive pi failures; stop", flush=True)
                break
            if args.gap > 0:
                stop.wait(args.gap)

    walls = [r["wall_s"] for r in rows if r.get("rc") == 0]
    inputs = [r["input_tokens"] for r in rows if r.get("input_tokens")]
    summary = {
        "label": label, "agent_id": agent_id,
        "session_id": session_id,
        "session_path": real,
        "pi_notes": logs,
        "turns": len(rows),
        "compaction_turn": compaction_turn,
        "compaction_input_tokens": (rows[compaction_turn - 1]
                                    .get("input_tokens")
                                    if compaction_turn else None),
        "post_compaction_turn_recorded": post_compaction_done,
        "max_input_tokens": max(inputs) if inputs else None,
        "wall_min": round((time.monotonic() - t0) / 60, 1),
        "wall_p50_s": sorted(walls)[len(walls) // 2] if walls else None,
        "wall_max_s": max(walls) if walls else None,
        "total_output_tokens": sum(r.get("output_tokens") or 0 for r in rows),
    }
    with open(os.path.join(out_dir, f"{label}-summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    results[agent_id] = (rows, summary)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pi-bin", default=os.path.expanduser("~/.local/bin/pi"))
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--agents", type=int, default=2)
    ap.add_argument("--context-window", type=int, default=300000,
                    help="pi models.json contextWindow for the served model")
    ap.add_argument("--step-tokens", type=int, default=2000)
    ap.add_argument("--max-turns", type=int, default=200)
    ap.add_argument("--timeout", type=float, default=600.0,
                    help="per-turn pi timeout")
    ap.add_argument("--gap", type=float, default=0.0)
    ap.add_argument("--scratch", default=None,
                    help="dir for chunk files + pi sessions "
                         "(default <out>/scratch)")
    args = ap.parse_args()

    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)
    if args.scratch is None:
        args.scratch = os.path.join(out_dir, "scratch")
    os.makedirs(args.scratch, exist_ok=True)

    stop = threading.Event()
    results = [None] * args.agents
    threads = []
    t0 = time.monotonic()
    for i in range(args.agents):
        def run(idx=i):
            agent_loop(idx, args, out_dir, stop, results)
        th = threading.Thread(target=run, daemon=True)
        th.start()
        threads.append(th)
    for th in threads:
        th.join()

    summaries = [r[1] for r in results if r]
    combined = {
        "label": args.label,
        "agents": args.agents,
        "context_window": args.context_window,
        "step_tokens": args.step_tokens,
        "wall_min": round((time.monotonic() - t0) / 60, 1),
        "agent_summaries": summaries,
        "compaction_input_tokens": [s["compaction_input_tokens"]
                                    for s in summaries],
    }
    with open(os.path.join(out_dir, f"{args.label}-summary.json"), "w") as f:
        json.dump(combined, f, indent=2)
    print(json.dumps(combined, indent=2), flush=True)


if __name__ == "__main__":
    main()
