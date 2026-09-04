#!/usr/bin/env python3
"""A/B eval suite: runs the S/M/L/N/C/T/V blocks (see planning/02-working/
2026-09-04-gb10-cluster-optimization-and-eval-design.md §5.3) against an
OpenAI-compatible vLLM service and writes tmp/eval/<UTC>-<tag>/.

Blocks:
  S short chat        8 fixed prompts, temp 0 and 0.6, 3 repeats -> decode_c1_tok_s
  M medium (8K)       2 fresh bodies, 3 repeats each (1 cold + 2 warm) -> ttft_warm@8K
  L cold prefill      32K/64K/128K, 3 fresh seeds + 1 warm repeat -> prefill_cold_tok_s
  N needle            64K/128K with a buried marker -> exact-quote correctness gate
  C concurrency       c=2/c=4 of block-S prompts + one mixed decode+prefill overlap probe
  T tool calls        6 prompts against a 3-function tool schema, tool_choice=auto
  V vision            the menu image, existing vision_compare grader
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import config
import metrics
import probes
import workload

DEFAULT_BLOCKS = "S,M,L,N,C,T,V"
SEED_BASE_DEFAULT = 90000
PREFILL_SIZES = (32000, 64000, 128000)
NEEDLE_SIZES = (64000, 128000)
NEEDLE_MAX_TOKENS = 256


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")


def git_head(repo_root: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root,
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
    except Exception:
        return None


def scaled(args: argparse.Namespace, n: int) -> int:
    """--scale shrinks prompt-body token counts for fast offline tests; a
    50-token floor keeps bodies non-degenerate."""
    return max(50, round(n * args.scale))


class SeedAllocator:
    def __init__(self, base: int):
        self._next = base
        self.used: list[int] = []

    def next(self) -> int:
        s = self._next
        self._next += 1
        self.used.append(s)
        return s


class Ctx:
    def __init__(self, cfg: config.Config, args: argparse.Namespace, seed_alloc: SeedAllocator):
        self.cfg = cfg
        self.args = args
        self.seed_alloc = seed_alloc
        self.results: list[dict] = []
        self.plan: list[dict] = []

    def plan_or_run(self, *, block: str, name: str, seed: int | None, repeat: int,
                     temperature: float | None, max_tokens: int, est_tokens: int) -> bool:
        self.plan.append({
            "block": block, "name": name, "seed": seed, "repeat": repeat,
            "temperature": temperature, "max_tokens": max_tokens, "est_prompt_tokens": est_tokens,
        })
        return not self.args.dry_run

    def sample(self, *, block: str, name: str, seed: int | None, repeat: int,
               temperature: float | None, request_fn, own_concurrency: int = 1, gate_fn=None,
               probe_factory=None) -> dict:
        """Every probe reads num_requests_running before and after the call; a
        nonzero value (or, for block C, a value above the round's own
        concurrency before the call) marks the sample contaminated and
        triggers one re-run, keeping both records (per §5.3's contamination
        rule). Cold probes pass `probe_factory(seed) -> (request_fn, gate_fn)`
        so the re-run gets a fresh seed — an identical body would hit the
        prefix cache and measure a warm prefill as cold. Returns the last
        record appended."""
        threshold = own_concurrency if block == "C" else 0
        running_before = probes.fetch_num_requests_running(self.cfg.metrics_url)
        result = request_fn()
        running_after = probes.fetch_num_requests_running(self.cfg.metrics_url)
        contaminated = running_before > threshold or running_after > 0
        gate_fields = gate_fn(result) if gate_fn else {}
        rec = _make_record(block, name, seed, repeat, temperature, result, contaminated,
                           running_before=running_before, running_after=running_after, **gate_fields)
        self.results.append(rec)
        if contaminated:
            seed2 = seed
            if probe_factory is not None:
                seed2 = self.seed_alloc.next()
                request_fn, gate_fn = probe_factory(seed2)
            running_before2 = probes.fetch_num_requests_running(self.cfg.metrics_url)
            result2 = request_fn()
            running_after2 = probes.fetch_num_requests_running(self.cfg.metrics_url)
            gate_fields2 = gate_fn(result2) if gate_fn else {}
            rec = _make_record(block, name, seed2, repeat, temperature, result2, False,
                               running_before=running_before2, running_after=running_after2,
                               rerun_of_contaminated=True, **gate_fields2)
            self.results.append(rec)
        return rec


def _make_record(block: str, name: str, seed: int | None, repeat: int, temperature: float | None,
                  result: dict, contaminated: bool, **gate_fields) -> dict:
    usage = result.get("usage") or {}
    rec = {
        "block": block, "name": name, "seed": seed, "repeat": repeat, "temperature": temperature,
        "prompt_tokens": usage.get("prompt_tokens"),
        "cached_tokens": result.get("cached_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "ttft_s": result.get("ttft_s"),
        "gen_tok_s": result.get("gen_tok_s"),
        "itl_p95_s": result.get("itl_p95_s"),
        "finish_reason": result.get("finish_reason"),
        "contaminated": contaminated,
        "error": result.get("error"),
    }
    rec.update(gate_fields)
    return rec


# --- Block S: short chat -----------------------------------------------------
def run_block_s(ctx: Ctx) -> None:
    repeats = ctx.args.repeats or 3
    for temperature in (0.0, 0.6):
        for idx, prompt in enumerate(workload.SHORT_CHAT_PROMPTS):
            name = f"s{idx}"
            est = workload.estimate_tokens_natural(prompt)
            for repeat in range(1, repeats + 1):
                if ctx.plan_or_run(block="S", name=name, seed=None, repeat=repeat, temperature=temperature,
                                    max_tokens=400, est_tokens=est):
                    ctx.sample(
                        block="S", name=name, seed=None, repeat=repeat, temperature=temperature,
                        request_fn=lambda prompt=prompt, temperature=temperature: probes.stream_request(
                            ctx.cfg.base_url, ctx.cfg.model, [{"role": "user", "content": prompt}],
                            max_tokens=400, temperature=temperature, thinking=ctx.args.thinking,
                        ),
                    )


# --- Block M: medium (8K) -----------------------------------------------------
def run_block_m(ctx: Ctx) -> None:
    repeats = ctx.args.repeats or 3
    n_tokens = scaled(ctx.args, 8000)
    for body_idx in range(2):
        seed = ctx.seed_alloc.next()
        body = workload.build_random_body(n_tokens, seed) + workload.SUMMARY_QUESTION
        name = f"m8k-{body_idx}"
        for repeat in range(1, repeats + 1):
            if ctx.plan_or_run(block="M", name=name, seed=seed, repeat=repeat, temperature=0.0,
                                max_tokens=256, est_tokens=n_tokens):
                warm = repeat > 1

                def gate(result: dict, warm: bool = warm) -> dict:
                    prompt_tokens = (result.get("usage") or {}).get("prompt_tokens")
                    cached = result.get("cached_tokens") or 0
                    ratio = (cached / prompt_tokens) if prompt_tokens else None
                    return {"warm": warm, "cached_ratio": ratio}

                ctx.sample(
                    block="M", name=name, seed=seed, repeat=repeat, temperature=0.0,
                    request_fn=lambda body=body: probes.stream_request(
                        ctx.cfg.base_url, ctx.cfg.model, [{"role": "user", "content": body}],
                        max_tokens=256, temperature=0.0, thinking=ctx.args.thinking,
                    ),
                    gate_fn=gate,
                )


# --- Block L: cold/warm prefill ----------------------------------------------
def run_block_l(ctx: Ctx) -> None:
    repeats = ctx.args.repeats or 3
    for n_tokens_base in PREFILL_SIZES:
        n_tokens = scaled(ctx.args, n_tokens_base)
        label = f"{n_tokens_base // 1000}K"
        name = f"prefill_{label}"
        bodies: dict[int, str] = {}

        def cold_probe(seed: int):
            body = bodies.setdefault(seed, workload.build_random_body(n_tokens, seed) + workload.ONE_WORD_QUESTION)

            def request_fn() -> dict:
                return probes.stream_request(
                    ctx.cfg.base_url, ctx.cfg.model, [{"role": "user", "content": body}],
                    max_tokens=8, temperature=0.0, timeout=1800, thinking=ctx.args.thinking,
                )

            return request_fn, (lambda result: {"warm": False})

        last_seed = last_body = None
        for repeat in range(1, repeats + 1):
            seed = ctx.seed_alloc.next()
            request_fn, gate_fn = cold_probe(seed)
            last_seed, last_body = seed, bodies[seed]
            if ctx.plan_or_run(block="L", name=name, seed=seed, repeat=repeat, temperature=0.0,
                                max_tokens=8, est_tokens=n_tokens):
                rec = ctx.sample(
                    block="L", name=name, seed=seed, repeat=repeat, temperature=0.0,
                    request_fn=request_fn, gate_fn=gate_fn, probe_factory=cold_probe,
                )
                last_seed, last_body = rec["seed"], bodies[rec["seed"]]

        warm_repeat = repeats + 1
        if ctx.plan_or_run(block="L", name=name, seed=last_seed, repeat=warm_repeat, temperature=0.0,
                            max_tokens=8, est_tokens=n_tokens):
            def gate(result: dict) -> dict:
                prompt_tokens = (result.get("usage") or {}).get("prompt_tokens")
                cached = result.get("cached_tokens") or 0
                ratio = (cached / prompt_tokens) if prompt_tokens else None
                return {"warm": True, "cached_ratio": ratio}

            ctx.sample(
                block="L", name=name, seed=last_seed, repeat=warm_repeat, temperature=0.0,
                request_fn=lambda: probes.stream_request(
                    ctx.cfg.base_url, ctx.cfg.model, [{"role": "user", "content": last_body}],
                    max_tokens=8, temperature=0.0, timeout=1800, thinking=ctx.args.thinking,
                ),
                gate_fn=gate,
            )


# --- Block N: needle ----------------------------------------------------------
def run_block_n(ctx: Ctx) -> None:
    repeats = ctx.args.repeats or 2
    for n_tokens_base in NEEDLE_SIZES:
        n_tokens = scaled(ctx.args, n_tokens_base)
        label = f"{n_tokens_base // 1000}K"
        name = f"needle_{label}"
        def needle_probe(seed: int):
            marker = workload.make_marker(seed)
            body = workload.build_needle_body(n_tokens, seed, marker) + workload.NEEDLE_QUESTION

            def request_fn() -> dict:
                # thinking stays at the production default, so the answer may
                # sit in reasoning_text; NEEDLE_MAX_TOKENS leaves room for it.
                return probes.stream_request(
                    ctx.cfg.base_url, ctx.cfg.model, [{"role": "user", "content": body}],
                    max_tokens=NEEDLE_MAX_TOKENS, temperature=0.0, timeout=1800, thinking=ctx.args.thinking,
                )

            def gate_fn(result: dict) -> dict:
                in_text = probes.needle_pass(marker, result.get("text") or "")
                in_reasoning = probes.needle_pass(marker, result.get("reasoning_text") or "")
                return {"needle_pass": in_text or in_reasoning, "needle_in_text": in_text, "marker": marker}

            return request_fn, gate_fn

        for repeat in range(1, repeats + 1):
            seed = ctx.seed_alloc.next()
            if ctx.plan_or_run(block="N", name=name, seed=seed, repeat=repeat, temperature=0.0,
                                max_tokens=NEEDLE_MAX_TOKENS, est_tokens=n_tokens):
                request_fn, gate_fn = needle_probe(seed)
                ctx.sample(
                    block="N", name=name, seed=seed, repeat=repeat, temperature=0.0,
                    request_fn=request_fn, gate_fn=gate_fn, probe_factory=needle_probe,
                )


# --- Block C: concurrency + mixed decode/prefill overlap ----------------------
def run_block_c(ctx: Ctx) -> None:
    repeats = ctx.args.repeats or 2
    for c in (2, 4):
        for round_idx in range(1, repeats + 1):
            _run_concurrent_round(ctx, c, round_idx)
    _run_mixed_probe(ctx)


def _execute_round(ctx: Ctx, c: int, prompts: list[str], round_idx: int, contaminated: bool) -> dict:
    before_snap = metrics.snapshot(metrics.fetch(ctx.cfg.metrics_url))
    stream_results: list[dict | None] = [None] * c

    def worker(i: int) -> None:
        stream_results[i] = probes.stream_request(
            ctx.cfg.base_url, ctx.cfg.model, [{"role": "user", "content": prompts[i]}],
            max_tokens=400, temperature=0.0, thinking=ctx.args.thinking,
        )

    t0 = time.time()
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(c)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.time() - t0
    after_snap = metrics.snapshot(metrics.fetch(ctx.cfg.metrics_url))
    d = metrics.delta(before_snap, after_snap)
    aggregate_tok_s = d["generation_tokens_delta"] / wall if wall > 0 else None
    per_stream = [r.get("gen_tok_s") for r in stream_results if r and r.get("gen_tok_s")]
    ratio = (max(per_stream) / min(per_stream)) if len(per_stream) >= 2 and min(per_stream) > 0 else None
    errors = [r.get("error") for r in stream_results if r and r.get("error")]
    ttfts = [r.get("ttft_s") for r in stream_results if r and r.get("ttft_s") is not None]
    itls = [r.get("itl_p95_s") for r in stream_results if r and r.get("itl_p95_s") is not None]
    prompt_tokens_sum = sum((r.get("usage") or {}).get("prompt_tokens") or 0 for r in stream_results if r)
    completion_tokens_sum = sum((r.get("usage") or {}).get("completion_tokens") or 0 for r in stream_results if r)
    finish_reasons = sorted({r.get("finish_reason") for r in stream_results if r})
    return {
        "block": "C", "name": f"c{c}", "seed": None, "repeat": round_idx, "temperature": 0.0,
        "prompt_tokens": prompt_tokens_sum or None,
        "cached_tokens": None,
        "completion_tokens": completion_tokens_sum or None,
        "ttft_s": statistics.median(ttfts) if ttfts else None,
        "gen_tok_s": aggregate_tok_s,
        "itl_p95_s": statistics.median(itls) if itls else None,
        "finish_reason": finish_reasons[0] if len(finish_reasons) == 1 else finish_reasons,
        "contaminated": contaminated,
        "per_stream_tok_s": per_stream,
        "max_min_ratio": ratio,
        "error": "; ".join(e for e in errors if e) or None,
    }


def _run_concurrent_round(ctx: Ctx, c: int, round_idx: int) -> None:
    prompts = [workload.SHORT_CHAT_PROMPTS[i % len(workload.SHORT_CHAT_PROMPTS)] for i in range(c)]
    est = sum(workload.estimate_tokens_natural(p) for p in prompts)
    if not ctx.plan_or_run(block="C", name=f"c{c}", seed=None, repeat=round_idx, temperature=0.0,
                            max_tokens=400, est_tokens=est):
        return
    running_before = probes.fetch_num_requests_running(ctx.cfg.metrics_url)
    rec = _execute_round(ctx, c, prompts, round_idx, running_before > c)
    ctx.results.append(rec)
    if rec["contaminated"]:
        running_before2 = probes.fetch_num_requests_running(ctx.cfg.metrics_url)
        rec2 = _execute_round(ctx, c, prompts, round_idx, running_before2 > c)
        ctx.results.append(rec2)


def _run_mixed_probe(ctx: Ctx) -> None:
    """One c=1 decode stream (block-S prompt, max_tokens 600); 2s later a
    fresh cold 64K prefill starts. Records the decode stream's inter-token
    latency during the overlap window. Not re-run on contamination (unlike
    the other blocks) since re-running would just repeat the same overlap
    measurement; the contaminated flag is still recorded."""
    decode_prompt = workload.SHORT_CHAT_PROMPTS[0]
    n_tokens = scaled(ctx.args, 64000)
    est = workload.estimate_tokens_natural(decode_prompt) + n_tokens
    if not ctx.plan_or_run(block="C", name="mixed", seed=None, repeat=1, temperature=0.0,
                            max_tokens=600, est_tokens=est):
        return
    seed = ctx.seed_alloc.next()
    prefill_body = workload.build_random_body(n_tokens, seed) + workload.ONE_WORD_QUESTION

    running_before = probes.fetch_num_requests_running(ctx.cfg.metrics_url)
    decode_result: dict = {}
    prefill_result: dict = {}
    prefill_window: dict = {}

    def decode_worker() -> None:
        decode_result.update(probes.stream_request(
            ctx.cfg.base_url, ctx.cfg.model, [{"role": "user", "content": decode_prompt}],
            max_tokens=600, temperature=0.0, thinking=ctx.args.thinking,
        ))

    def prefill_worker() -> None:
        prefill_window["start"] = time.time()
        prefill_result.update(probes.stream_request(
            ctx.cfg.base_url, ctx.cfg.model, [{"role": "user", "content": prefill_body}],
            max_tokens=8, temperature=0.0, timeout=1800, thinking=ctx.args.thinking,
        ))
        prefill_window["end"] = time.time()

    decode_thread = threading.Thread(target=decode_worker)
    decode_thread.start()
    time.sleep(2.0)
    prefill_thread = threading.Thread(target=prefill_worker)
    prefill_thread.start()
    decode_thread.join()
    prefill_thread.join()

    token_ts = decode_result.get("token_ts") or []
    start, end = prefill_window.get("start"), prefill_window.get("end")
    overlap_itls = []
    if start is not None and end is not None:
        for a, b in zip(token_ts, token_ts[1:]):
            if start <= b <= end:
                overlap_itls.append(b - a)
    if len(overlap_itls) >= 2:
        itl_p95 = statistics.quantiles(overlap_itls, n=100)[94]
    elif overlap_itls:
        itl_p95 = overlap_itls[0]
    else:
        itl_p95 = decode_result.get("itl_p95_s")
    itl_max = max(overlap_itls) if overlap_itls else decode_result.get("itl_max_s")

    ctx.results.append({
        "block": "C", "name": "mixed", "seed": seed, "repeat": 1, "temperature": 0.0,
        "prompt_tokens": (decode_result.get("usage") or {}).get("prompt_tokens"),
        "cached_tokens": decode_result.get("cached_tokens"),
        "completion_tokens": (decode_result.get("usage") or {}).get("completion_tokens"),
        "ttft_s": decode_result.get("ttft_s"),
        "gen_tok_s": decode_result.get("gen_tok_s"),
        "itl_p95_s": round(itl_p95, 4) if itl_p95 is not None else None,
        "itl_max_s": round(itl_max, 4) if itl_max is not None else None,
        "finish_reason": decode_result.get("finish_reason"),
        "contaminated": running_before > 2,
        "prefill_prompt_tokens": (prefill_result.get("usage") or {}).get("prompt_tokens"),
        "prefill_ttft_s": prefill_result.get("ttft_s"),
        "error": decode_result.get("error") or prefill_result.get("error"),
    })


# --- Block T: tool calls -------------------------------------------------------
def run_block_t(ctx: Ctx) -> None:
    repeats = ctx.args.repeats or 1
    for idx, prompt in enumerate(workload.TOOL_PROMPTS):
        name = f"tool{idx}"
        est = workload.estimate_tokens_natural(prompt)
        for repeat in range(1, repeats + 1):
            if ctx.plan_or_run(block="T", name=name, seed=None, repeat=repeat, temperature=0.0,
                                max_tokens=300, est_tokens=est):
                def gate(result: dict) -> dict:
                    tool_calls = result.get("tool_calls") or []
                    valid, call_name = False, None
                    if tool_calls:
                        call_name = tool_calls[0]["function"]["name"]
                        try:
                            json.loads(tool_calls[0]["function"]["arguments"])
                            valid = True
                        except (json.JSONDecodeError, TypeError):
                            valid = False
                    return {"tool_call_valid": valid, "tool_call_name": call_name}

                ctx.sample(
                    block="T", name=name, seed=None, repeat=repeat, temperature=0.0,
                    request_fn=lambda prompt=prompt: probes.stream_request(
                        ctx.cfg.base_url, ctx.cfg.model, [{"role": "user", "content": prompt}],
                        max_tokens=300, temperature=0.0, thinking=ctx.args.thinking,
                        tools=list(workload.TOOLS), tool_choice="auto",
                    ),
                    gate_fn=gate,
                )


# --- Block V: vision (menu image) ---------------------------------------------
def run_block_v(ctx: Ctx) -> None:
    vc = workload.vision_compare()
    if vc is None:
        # The menu probe definition and 47-field grader live in
        # execution/benchmarks/vision_compare.py, which is not committed with
        # this package (customer-derived); without them record an explicit
        # skip so a clean checkout still runs the other six blocks.
        if ctx.plan_or_run(block="V", name="menu", seed=None, repeat=1, temperature=0.0,
                           max_tokens=0, est_tokens=0):
            ctx.results.append(_make_record(
                block="V", name="menu", seed=None, repeat=1, temperature=0.0,
                result={"error": "skipped: execution/benchmarks/vision_compare.py not found"},
                contaminated=False, skipped=True))
        return
    image_path = Path(ctx.args.menu_image_override) if ctx.args.menu_image_override else config.menu_image_path()
    image_bytes = workload.load_menu_image(image_path)
    max_tokens = 4096 if ctx.args.thinking == "off" else 16384
    if not ctx.plan_or_run(block="V", name="menu", seed=None, repeat=1, temperature=0.0,
                            max_tokens=max_tokens, est_tokens=2000):
        return

    def gate(result: dict) -> dict:
        text = result.get("text") or ""
        try:
            parsed = vc.parse_json_object(text)
            grade = vc.grade_menu(parsed)
            return {"vision_score": grade["passed"], "vision_total": grade["total"]}
        except Exception as exc:
            return {"vision_score": 0, "vision_total": 47, "vision_parse_error": str(exc)}

    messages = [{"role": "user", "content": [vc.image_part(image_bytes), {"type": "text", "text": vc.MENU_PROMPT}]}]
    ctx.sample(
        block="V", name="menu", seed=None, repeat=1, temperature=0.0,
        request_fn=lambda: probes.stream_request(
            ctx.cfg.base_url, ctx.cfg.model, messages, max_tokens=max_tokens, temperature=0.0,
            thinking=ctx.args.thinking, response_format=vc.menu_response_format(), timeout=1800,
        ),
        gate_fn=gate,
    )


BLOCK_RUNNERS = {
    "S": run_block_s, "M": run_block_m, "L": run_block_l, "N": run_block_n,
    "C": run_block_c, "T": run_block_t, "V": run_block_v,
}


# --- KPIs, gates, report -------------------------------------------------------
def compute_kpis(all_results: list[dict]) -> dict[str, dict]:
    kpis: dict[str, dict] = {}
    results = [r for r in all_results if not r.get("contaminated")]

    def add(name: str, values: list) -> None:
        vals = [v for v in values if v is not None]
        if vals:
            kpis[name] = {"median": statistics.median(vals), "min": min(vals), "max": max(vals), "n": len(vals)}

    add("decode_c1_tok_s", [
        r["gen_tok_s"] for r in results
        if r["block"] == "S" and r["temperature"] == 0.0 and not r.get("error")
    ])

    for label in ("32K", "64K", "128K"):
        name = f"prefill_{label}"
        cold = [r for r in results if r["block"] == "L" and r["name"] == name and not r.get("warm") and not r.get("error")]
        add(f"prefill_cold_tok_s@{label}", [
            r["prompt_tokens"] / r["ttft_s"] for r in cold if r.get("prompt_tokens") and r.get("ttft_s")
        ])
        if label == "64K":
            warm = [r for r in results if r["block"] == "L" and r["name"] == name and r.get("warm") and not r.get("error")]
            add("ttft_warm@64K", [r["ttft_s"] for r in warm])

    add("ttft_warm@8K", [
        r["ttft_s"] for r in results if r["block"] == "M" and r.get("warm") and not r.get("error")
    ])

    for c in (2, 4):
        add(f"aggregate_tok_s_c{c}", [
            r["gen_tok_s"] for r in results if r["block"] == "C" and r["name"] == f"c{c}"
        ])

    return kpis


def compute_gates(results: list[dict]) -> dict[str, object]:
    gates: dict[str, object] = {}
    for label in ("64K", "128K"):
        needle = [r for r in results if r["block"] == "N" and r["name"] == f"needle_{label}"]
        gates[f"needle_{label}_exact"] = all(r.get("needle_pass") for r in needle) if needle else None

    tool = [r for r in results if r["block"] == "T"]
    gates["tool_call_json_6_6"] = (sum(1 for r in tool if r.get("tool_call_valid")) == 6) if tool else None

    vision = [r for r in results if r["block"] == "V"]
    gates["vision_score"] = vision[0].get("vision_score") if vision else None

    excluded_names = {"c2", "c4"}
    gates["no_missing_finish_reason"] = all(
        r.get("finish_reason") not in (None, "")
        for r in results if r["name"] not in excluded_names and not r.get("skipped")
    ) if results else None

    warm_64k = [r for r in results if r["block"] == "L" and r["name"] == "prefill_64K" and r.get("warm")]
    if warm_64k and warm_64k[0].get("ttft_s") is not None:
        gates["warm_ttft_64K_le_2s"] = warm_64k[0]["ttft_s"] <= 2.0

    return gates


def render_report_md(tag: str, results: list[dict], metrics_before_text: str, metrics_after_text: str) -> str:
    kpis = compute_kpis(results)
    gates = compute_gates(results)
    d = metrics.delta(metrics.snapshot(metrics_before_text), metrics.snapshot(metrics_after_text)) if metrics_before_text else {}

    lines = [f"# Eval report: {tag}", "", "## KPIs", "", "| KPI | median | min | max | n |", "| --- | --- | --- | --- | --- |"]
    for name in sorted(kpis):
        stat = kpis[name]
        lines.append(f"| {name} | {stat['median']:.3f} | {stat['min']:.3f} | {stat['max']:.3f} | {stat['n']} |")

    lines += ["", "## Gates", "", "| gate | result |", "| --- | --- |"]
    for name in sorted(gates):
        lines.append(f"| {name} | {gates[name]} |")

    contamination_count = sum(1 for r in results if r.get("contaminated"))
    lines += [
        "", "## /metrics delta", "",
        f"- contamination_count: {contamination_count}",
        f"- acceptance: {d.get('acceptance')}",
        f"- accepted_per_position_delta: {d.get('accepted_per_position_delta')}",
        f"- prefix_hit_ratio: {d.get('prefix_hit_ratio')}",
        f"- preemptions_delta: {d.get('preemptions_delta')}",
        f"- request_success_delta: {d.get('request_success_delta')}",
        f"- kv_cache_usage_perc_last: {d.get('kv_cache_usage_perc_last')}",
        "",
    ]
    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--blocks", default=DEFAULT_BLOCKS)
    ap.add_argument("--repeats", type=int, default=None, help="override every block's repeat count")
    ap.add_argument("--seed-base", type=int, default=SEED_BASE_DEFAULT)
    ap.add_argument("--thinking", choices=["off", "low", "high"], default=None,
                     help="default omits chat_template_kwargs entirely (production default thinking=true, reasoning_effort=low)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan (block/name/seed/repeat/est tokens); no network")
    ap.add_argument("--force", action="store_true", help="bypass the idle-window guard (recorded in manifest.json)")
    ap.add_argument("--no-hosts", action="store_true", help="skip ssh MemAvailable sampling")
    ap.add_argument("--scale", type=float, default=1.0, help="shrink body token counts for fast offline tests")
    ap.add_argument("--out-dir", default="tmp/eval")
    ap.add_argument("--menu-image", dest="menu_image_override", default=None,
                     help="override EVAL_MENU_IMAGE for this run")
    ap.add_argument("--idle-poll-gap", type=float, default=60.0, help="seconds between the two idle-window polls")
    return ap


def main() -> int:
    args = build_arg_parser().parse_args()
    cfg = config.load_config()
    blocks = [b.strip().upper() for b in args.blocks.split(",") if b.strip()]
    unknown = [b for b in blocks if b not in BLOCK_RUNNERS]
    if unknown:
        print(f"unknown block(s): {unknown}; choose from {sorted(BLOCK_RUNNERS)}", file=sys.stderr)
        return 2

    seed_alloc = SeedAllocator(args.seed_base)
    ctx = Ctx(cfg, args, seed_alloc)

    idle_note = None
    if not args.dry_run:
        ok, reason = probes.idle_window_ok(cfg.metrics_url, poll_gap_s=args.idle_poll_gap)
        if not ok:
            if not args.force:
                print(f"idle-window guard failed: {reason} (use --force to override)", file=sys.stderr)
                return 2
            idle_note = f"FORCED past idle-window guard: {reason}"
            print(f"WARNING: {idle_note}", file=sys.stderr)

    started_at = datetime.now(timezone.utc).isoformat()
    metrics_before_text = "" if args.dry_run else metrics.fetch(cfg.metrics_url)

    hosts_samples: list[dict] = []
    stop_hosts = threading.Event()
    hosts_thread = None
    if not args.dry_run and not args.no_hosts and (cfg.head_ssh or cfg.worker_ssh):
        def sample_hosts() -> None:
            while True:
                row = {"ts": datetime.now(timezone.utc).isoformat()}
                if cfg.head_ssh:
                    row["head_mem_available_bytes"] = metrics.host_mem_available_bytes(cfg.head_ssh)
                if cfg.worker_ssh:
                    row["worker_mem_available_bytes"] = metrics.host_mem_available_bytes(cfg.worker_ssh)
                hosts_samples.append(row)
                if stop_hosts.wait(30):
                    return

        hosts_thread = threading.Thread(target=sample_hosts, daemon=True)
        hosts_thread.start()

    for block in blocks:
        BLOCK_RUNNERS[block](ctx)

    if hosts_thread:
        stop_hosts.set()
        hosts_thread.join(timeout=5)

    metrics_after_text = "" if args.dry_run else metrics.fetch(cfg.metrics_url)
    finished_at = datetime.now(timezone.utc).isoformat()

    if args.dry_run:
        print(json.dumps({
            "tag": args.tag, "blocks": blocks, "plan": ctx.plan,
            "total_requests": len(ctx.plan),
            "total_est_prompt_tokens": sum(p["est_prompt_tokens"] for p in ctx.plan),
            "seeds": seed_alloc.used,
            "base_url": config.redact_host(cfg.base_url),
        }, indent=2))
        return 0

    run_dir = Path(args.out_dir) / f"{utc_stamp()}-{args.tag}"
    run_dir.mkdir(parents=True, exist_ok=True)
    contamination_count = sum(1 for r in ctx.results if r.get("contaminated"))
    manifest = {
        "tag": args.tag,
        "args": vars(args),
        "seeds": seed_alloc.used,
        "base_url": config.redact_host(cfg.base_url),
        "model": cfg.model,
        "started_at": started_at,
        "finished_at": finished_at,
        "git_head": git_head(Path(__file__).resolve().parents[2]),
        "contamination_count": contamination_count,
        "idle_window_forced_note": idle_note,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (run_dir / "metrics_before.txt").write_text(metrics_before_text)
    (run_dir / "metrics_after.txt").write_text(metrics_after_text)
    with (run_dir / "results.jsonl").open("w", encoding="utf-8") as f:
        for rec in ctx.results:
            f.write(json.dumps(rec) + "\n")
    with (run_dir / "hosts.jsonl").open("w", encoding="utf-8") as f:
        for row in hosts_samples:
            f.write(json.dumps(row) + "\n")
    (run_dir / "report.md").write_text(render_report_md(args.tag, ctx.results, metrics_before_text, metrics_after_text))

    print(f"run dir: {run_dir}")
    print(f"contamination_count={contamination_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
