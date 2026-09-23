#!/usr/bin/env python3
"""Agent 上下文阶梯 benchmark：模拟 agent 应用的逐步追加式上下文增长。

每个循环迭代：
  1. 向历史追加一条 ~2k token 的"工具结果"消息（前缀保持不变，命中前缀缓存，
     与真实 dsh/pi agent 的上下文增长方式一致）；
  2. 发起一次流式 /v1/chat/completions，记录 TTFT（首个生成 token，含 reasoning）、
     总时长、引擎侧 prompt_tokens / cached_tokens；
  3. 追加 assistant 回复，进入下一步。

--agents N（默认 1）：N 条独立阶梯并发增长（各自的 salt/历史/JSONL），
  模拟两个真实 agent 会话同时变长（双长请求竞争 prefill/KV/decode）。
--sibling-context：静态体量差分对照（增长阶梯 + 固定体量 sibling），保留兼容。

跑到 --target-tokens 或触发护栏（连续 N 步 TTFT 超阈值，确认悬崖已出现）为止。
输出每 agent JSONL 逐步行 + 每 agent 汇总 + 合并汇总，供前后配置对比。

用法：
  python3 bench_agent_context.py --label baseline --out results/agentladder-baseline
  python3 bench_agent_context.py --label dual-upstream --agents 2 \
      --target-tokens 400000 --out results/agentladder-dual
"""

import argparse
import json
import os
import random
import string
import threading
import time

import requests

SYSTEM_PROMPT = (
    "You are a coding agent working inside a large repository. You receive "
    "tool results incrementally and must keep track of all of them. Reply "
    "tersely (a single short sentence) unless asked otherwise."
)

FILLER_HEADER = "tool result #{step} (bash: tail -n 400 build-and-telemetry.log)\n"


def filler_text(step: int, n_chars: int, rng: random.Random) -> str:
    """Deterministic, step-unique, token-dense filler (~2.5 chars/token)."""
    out = [FILLER_HEADER.format(step=step)]
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


def sse_stream(client, url, payload, timeout_s):
    t_send = time.monotonic()
    t_first = None
    t_end = None
    usage = None
    finish = None
    resp = client.post(url, json=payload, stream=True, timeout=timeout_s)
    resp.raise_for_status()
    for raw in resp.iter_lines(decode_unicode=True):
        if not raw or not raw.startswith("data: "):
            continue
        body = raw[6:]
        if body == "[DONE]":
            break
        try:
            ev = json.loads(body)
        except json.JSONDecodeError:
            continue
        if ev.get("usage"):
            usage = ev["usage"]
        for ch in ev.get("choices", []):
            d = ch.get("delta") or {}
            if t_first is None and (d.get("content") or d.get("reasoning_content")):
                t_first = time.monotonic()
            if ch.get("finish_reason"):
                finish = ch["finish_reason"]
        t_end = time.monotonic()
    if t_first is None:
        t_first = t_end
    return t_send, t_first, t_end, usage, finish


def agent_ladder(agent_id, args, url, stop_churn, churn_enabled, churn_errors):
    """One growing ladder. Returns (rows, summary, label)."""
    label = args.label if args.agents == 1 else f"{args.label}-a{agent_id}"
    jsonl_path = os.path.join(args.out, f"{label}.jsonl")
    client = requests.Session()
    rng = random.Random(f"ladder:{args.salt}:a{agent_id}")
    chars_per_token = 2.5  # measured density of the filler mix

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    rows = []
    consecutive_bad = 0
    t0 = time.monotonic()
    print(f"[{label}] start: target {args.target_tokens} tok, "
          f"+{args.step_tokens} tok/step", flush=True)

    with open(jsonl_path, "w") as fj:
        step = 0
        while True:
            step += 1
            messages.append({
                "role": "user",
                "content": filler_text(
                    step,
                    int((args.init_tokens if step == 1
                         else args.step_tokens - 60) * chars_per_token), rng)
                + "\nContinue. Reply with one short sentence only.",
            })
            payload = {
                "model": args.model,
                "messages": messages,
                "max_tokens": args.max_tokens,
                "temperature": 0,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            try:
                t_send, t_first, t_end, usage, finish = sse_stream(
                    client, url, payload, args.timeout)
            except Exception as e:
                row = {"step": step, "error": repr(e)}
                fj.write(json.dumps(row) + "\n"); fj.flush()
                print(f"[{label}] step {step}: ERROR {e!r}", flush=True)
                break
            ttft = t_first - t_send
            total = t_end - t_send
            prompt_tok = (usage or {}).get("prompt_tokens")
            cached_tok = ((usage or {}).get("prompt_tokens_details") or {}).get("cached_tokens")
            gen_tok = (usage or {}).get("completion_tokens")
            row = {
                "step": step, "ttft_s": round(ttft, 3), "total_s": round(total, 3),
                "prompt_tokens": prompt_tok, "cached_tokens": cached_tok,
                "gen_tokens": gen_tok, "finish": finish,
                "wall_since_start_s": round(time.monotonic() - t0, 1),
            }
            rows.append(row)
            fj.write(json.dumps(row) + "\n"); fj.flush()
            print(f"[{label}] step {step:3d}: prompt {prompt_tok} cached {cached_tok} "
                  f"ttft {ttft:7.2f}s total {total:7.2f}s", flush=True)
            if step + 1 >= args.churn_start_step:
                churn_enabled.set()

            reply = "OK." if row["gen_tokens"] else ""
            messages.append({"role": "assistant", "content": reply})

            consecutive_bad = consecutive_bad + 1 if ttft > args.ttft_guard else 0
            if consecutive_bad >= 3:
                print(f"[{label}] cliff confirmed "
                      f"(3 consecutive TTFT > {args.ttft_guard}s); stop", flush=True)
                break
            if prompt_tok and prompt_tok >= args.target_tokens:
                print(f"[{label}] target reached", flush=True)
                break
            if args.gap > 0:
                time.sleep(args.gap)

    ttfts = [r["ttft_s"] for r in rows if "ttft_s" in r]
    prompts = [r["prompt_tokens"] for r in rows if r.get("prompt_tokens")]
    cliffs = [r for r in rows if r.get("ttft_s", 0) > 30]
    summary = {
        "label": label, "agent_id": agent_id, "endpoint": args.endpoint,
        "steps": len(rows),
        "params": {"init_tokens": args.init_tokens, "gap_s": args.gap,
                   "target_tokens": args.target_tokens},
        "max_prompt_tokens": max(prompts) if prompts else None,
        "wall_min": round((time.monotonic() - t0) / 60, 1),
        "total_ttft_s": round(sum(ttfts), 1),
        "ttft_p50_s": sorted(ttfts)[len(ttfts) // 2] if ttfts else None,
        "ttft_max_s": max(ttfts) if ttfts else None,
        "first_cliff_step": cliffs[0]["step"] if cliffs else None,
        "first_cliff_prompt_tokens": cliffs[0].get("prompt_tokens") if cliffs else None,
        "steps_over_30s": len(cliffs),
        "total_prompt_tokens": sum(p for p in prompts if p),
        "total_cached_tokens": sum(r.get("cached_tokens") or 0 for r in rows),
    }
    with open(os.path.join(args.out, f"{label}-summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    return rows, summary, label


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="http://192.168.88.181:8890")
    ap.add_argument("--model", default="GLM-5.3-Flash-EXL3")
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True, help="output dir for jsonl+summary")
    ap.add_argument("--agents", type=int, default=1,
                    help="number of concurrent growing ladders (default 1)")
    ap.add_argument("--target-tokens", type=int, default=190000)
    ap.add_argument("--step-tokens", type=int, default=2000)
    ap.add_argument("--max-tokens", type=int, default=96)
    ap.add_argument("--ttft-guard", type=float, default=150.0,
                    help="early-stop after 3 consecutive TTFTs above this")
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--init-tokens", type=int, default=0,
                    help="size the first user message to jump-start context")
    ap.add_argument("--gap", type=float, default=0.0,
                    help="sleep between steps (simulated tool execution time)")
    ap.add_argument("--churn-every", type=float, default=0.0,
                    help="if >0, a background client sends one unique cold "
                         "12k-token request every N seconds (cache-eviction "
                         "pressure simulating relay co-tenants)")
    ap.add_argument("--churn-start-step", type=int, default=1,
                    help="step number at which churn begins (prefix is built "
                         "cleanly before this)")
    ap.add_argument("--salt", default=str(int(time.time())),
                    help="unique filler salt per run (avoids cross-run "
                         "prefix-cache hits)")
    ap.add_argument("--sibling-context", type=int, default=0,
                    help="if >0, a second agent ladder with its own growing "
                         "context of this initial size runs concurrently "
                         "(simulates another agent session on the endpoint)")
    args = ap.parse_args()
    if args.agents < 1:
        ap.error("--agents must be >= 1")

    os.makedirs(args.out, exist_ok=True)
    url = f"{args.endpoint}/v1/chat/completions"

    stop_churn = threading.Event()
    churn_enabled = threading.Event()
    if args.churn_start_step <= 1:
        churn_enabled.set()
    churn_errors = []

    def churn_loop():
        c = requests.Session()
        c_rng = random.Random(f"churn:{args.salt}")
        i = 0
        while not stop_churn.is_set():
            if not churn_enabled.is_set():
                stop_churn.wait(0.5)
                continue
            i += 1
            try:
                c.post(url, json={
                    "model": args.model,
                    "messages": [{"role": "user", "content":
                                  filler_text(-i, 30000, c_rng)}],
                    "max_tokens": 32, "temperature": 0.7,
                }, timeout=args.timeout)
            except Exception as e:
                churn_errors.append(repr(e))
            stop_churn.wait(args.churn_every)

    if args.churn_every > 0:
        threading.Thread(target=churn_loop, daemon=True).start()

    def sibling_loop():
        c = requests.Session()
        s_rng = random.Random(f"sibling:{args.salt}")
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        i = 0
        while not stop_churn.is_set():
            if not churn_enabled.is_set():
                stop_churn.wait(0.5)
                continue
            i += 1
            budget = args.sibling_context if i == 1 else 2000
            msgs.append({
                "role": "user",
                "content": filler_text(10000 + i, int(budget * 2.5), s_rng)
                           + "\nContinue. Reply with one short sentence only.",
            })
            try:
                r = c.post(url, json={
                    "model": args.model, "messages": msgs,
                    "max_tokens": 32, "temperature": 0,
                }, timeout=args.timeout)
                msgs.append({"role": "assistant", "content": "OK."})
            except Exception as e:
                churn_errors.append(f"sibling:{e!r}")
            stop_churn.wait(args.gap if args.gap > 0 else 30)

    if args.sibling_context > 0:
        threading.Thread(target=sibling_loop, daemon=True).start()

    t0 = time.monotonic()
    results = [None] * args.agents
    threads = []
    for i in range(args.agents):
        def run(idx=i):
            results[idx] = agent_ladder(
                idx, args, url, stop_churn, churn_enabled, churn_errors)
        th = threading.Thread(target=run, daemon=True)
        th.start()
        threads.append(th)
    for th in threads:
        th.join()
    stop_churn.set()

    summaries = [r[1] for r in results if r]
    all_rows = [row for r in results if r for row in r[0]]
    ttfts = [r["ttft_s"] for r in all_rows if "ttft_s" in r]
    cliffs = [r for r in all_rows if r.get("ttft_s", 0) > 30]
    combined = {
        "label": args.label, "endpoint": args.endpoint,
        "agents": args.agents,
        "params": {"init_tokens": args.init_tokens, "gap_s": args.gap,
                   "churn_every_s": args.churn_every,
                   "target_tokens": args.target_tokens,
                   "step_tokens": args.step_tokens,
                   "salt": args.salt},
        "churn_errors": len(churn_errors),
        "agent_summaries": summaries,
        "steps_total": len(all_rows),
        "wall_min": round((time.monotonic() - t0) / 60, 1),
        "ttft_p50_all_s": sorted(ttfts)[len(ttfts) // 2] if ttfts else None,
        "ttft_max_all_s": max(ttfts) if ttfts else None,
        "first_cliff_step": cliffs[0]["step"] if cliffs else None,
        "steps_over_30s": len(cliffs),
        "total_prompt_tokens": sum(s["total_prompt_tokens"] for s in summaries),
        "total_cached_tokens": sum(s["total_cached_tokens"] for s in summaries),
    }
    with open(os.path.join(args.out, f"{args.label}-summary.json"), "w") as f:
        json.dump(combined, f, indent=2)
    print(json.dumps(combined, indent=2), flush=True)


if __name__ == "__main__":
    main()
