#!/usr/bin/env python3
"""Daily production KPI report from scrape.sh's metrics/<date>.jsonl (§5.6).

Turns counter deltas across a day's 60s scrapes into: requests/day by prompt
bucket, TTFT/ITL tail counts (>10s, >30s), decode tok/s (derived from
accepted-tokens-per-step and the median inter-token-latency bucket),
acceptance, prefix-hit ratio, kv_cache_usage_perc max, preemptions,
request_success by reason, and boot events (a monotonic counter going
backwards between consecutive scrapes).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import metrics


def load_scrapes(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def detect_boot_events(snapshots: list[tuple[str, metrics.Snapshot]]) -> list[dict]:
    events = []
    prev_ts, prev_snap = None, None
    for ts, snap in snapshots:
        if prev_snap is not None:
            prev_gen = metrics.sum_metric(prev_snap, "vllm:generation_tokens_total")
            cur_gen = metrics.sum_metric(snap, "vllm:generation_tokens_total")
            if cur_gen < prev_gen:
                events.append({
                    "ts": ts, "prev_ts": prev_ts, "metric": "generation_tokens_total",
                    "prev": prev_gen, "cur": cur_gen,
                })
        prev_ts, prev_snap = ts, snap
    return events


def bucket_tail_counts(bucket_cumulative: dict[str, float]) -> dict[str, object]:
    """bucket_cumulative: le -> count of observations <= le (cumulative,
    summed over the day). Tail counts use the smallest le >= threshold as
    the cutoff, so they are bucket-boundary approximations, not exact."""
    if not bucket_cumulative:
        return {"total": 0.0, "gt_10s": None, "gt_30s": None}
    les = sorted((le for le in bucket_cumulative if le != "+Inf"), key=float)
    total = bucket_cumulative.get("+Inf", max(bucket_cumulative.values()))

    def count_le(threshold: float) -> float | None:
        for le in les:
            if float(le) >= threshold:
                return bucket_cumulative[le]
        return bucket_cumulative.get("+Inf")

    c10, c30 = count_le(10.0), count_le(30.0)
    return {
        "total": total,
        "gt_10s": (total - c10) if c10 is not None else None,
        "gt_30s": (total - c30) if c30 is not None else None,
    }


def _histogram_median(bucket_cumulative: dict[str, float]) -> float | None:
    """Approximate median (the `le` of the first bucket whose cumulative
    count reaches half the day's total observations)."""
    if not bucket_cumulative:
        return None
    total = bucket_cumulative.get("+Inf")
    if not total:
        return None
    half = total / 2
    for le in sorted((le for le in bucket_cumulative if le != "+Inf"), key=float):
        if bucket_cumulative[le] >= half:
            return float(le)
    return None


def daily_report(rows: list[dict]) -> dict:
    ok_rows = [r for r in rows if r.get("ok") and r.get("text")]
    snapshots = [(r["ts"], metrics.snapshot(r["text"])) for r in ok_rows]
    boot_events = detect_boot_events(snapshots)
    scrape_failures = len(rows) - len(ok_rows)

    if len(snapshots) < 2:
        return {
            "scrapes": len(rows), "ok_scrapes": len(ok_rows), "scrape_failures": scrape_failures,
            "boot_events": boot_events, "error": "fewer than 2 usable scrapes; cannot compute deltas",
        }

    def interval_sum(name: str) -> float:
        # Boot events reset counters; a whole-day first-vs-last delta would
        # under-count across a restart, so sum per-interval deltas and treat
        # a post-restart decrease as "new activity == the post-restart value".
        total = 0.0
        for (_, before), (_, after) in zip(snapshots, snapshots[1:]):
            b, a = metrics.sum_metric(before, name), metrics.sum_metric(after, name)
            total += (a - b) if a >= b else a
        return total

    ttft_bucket_total: dict[str, float] = {}
    itl_bucket_total: dict[str, float] = {}
    prompt_bucket_total: dict[str, float] = {}
    for (_, before), (_, after) in zip(snapshots, snapshots[1:]):
        for name, acc in (
            ("vllm:time_to_first_token_seconds", ttft_bucket_total),
            ("vllm:inter_token_latency_seconds", itl_bucket_total),
            ("vllm:request_prompt_tokens", prompt_bucket_total),
        ):
            for le, v in metrics.bucket_deltas(before, after, name).items():
                if v >= 0:
                    acc[le] = acc.get(le, 0.0) + v

    generation_tokens = interval_sum("vllm:generation_tokens_total")
    prompt_tokens = interval_sum("vllm:prompt_tokens_total")
    accepted = interval_sum("vllm:spec_decode_num_accepted_tokens_total")
    draft = interval_sum("vllm:spec_decode_num_draft_tokens_total")
    drafts = interval_sum("vllm:spec_decode_num_drafts_total")
    hits = interval_sum("vllm:prefix_cache_hits_total")
    queries = interval_sum("vllm:prefix_cache_queries_total")
    preemptions = interval_sum("vllm:num_preemptions_total")

    avg_accepted_per_step = (accepted / drafts) if drafts else None
    median_itl_s = _histogram_median(itl_bucket_total)
    decode_tok_s = (avg_accepted_per_step / median_itl_s) if avg_accepted_per_step and median_itl_s else None

    kv_usage_values = [metrics.sum_metric(snap, "vllm:kv_cache_usage_perc") for _, snap in snapshots]
    first_snap, last_snap = snapshots[0][1], snapshots[-1][1]
    success_first = metrics.by_label(first_snap, "vllm:request_success_total", "finished_reason")
    success_last = metrics.by_label(last_snap, "vllm:request_success_total", "finished_reason")
    success_delta = {k: success_last.get(k, 0.0) - success_first.get(k, 0.0) for k in success_last}

    return {
        "scrapes": len(rows), "ok_scrapes": len(ok_rows), "scrape_failures": scrape_failures,
        "boot_events": boot_events,
        "start_ts": snapshots[0][0], "end_ts": snapshots[-1][0],
        "requests_by_prompt_bucket": prompt_bucket_total,
        "ttft_tail": bucket_tail_counts(ttft_bucket_total),
        "itl_tail": bucket_tail_counts(itl_bucket_total),
        "generation_tokens": generation_tokens,
        "prompt_tokens": prompt_tokens,
        "acceptance": (accepted / draft) if draft else None,
        "avg_accepted_per_step": avg_accepted_per_step,
        "decode_tok_s": decode_tok_s,
        "prefix_hit_ratio": (hits / queries) if queries else None,
        "kv_cache_usage_perc_max": max(kv_usage_values) if kv_usage_values else None,
        "preemptions": preemptions,
        "request_success_by_reason": success_delta,
    }


def render_report_md(date: str, report: dict) -> str:
    lines = [
        f"# Daily production report: {date}", "",
        f"- scrapes: {report.get('scrapes')} (ok: {report.get('ok_scrapes')}, "
        f"failed: {report.get('scrape_failures')})",
        f"- boot_events: {len(report.get('boot_events') or [])}",
    ]
    if "error" in report:
        lines.append(f"- error: {report['error']}")
        return "\n".join(lines) + "\n"
    lines += [
        f"- generation_tokens: {report['generation_tokens']:.0f}",
        f"- prompt_tokens: {report['prompt_tokens']:.0f}",
        f"- decode_tok_s: {report.get('decode_tok_s')}",
        f"- acceptance: {report.get('acceptance')}",
        f"- avg_accepted_per_step: {report.get('avg_accepted_per_step')}",
        f"- prefix_hit_ratio: {report.get('prefix_hit_ratio')}",
        f"- kv_cache_usage_perc_max: {report.get('kv_cache_usage_perc_max')}",
        f"- preemptions: {report.get('preemptions')}",
        f"- request_success_by_reason: {report.get('request_success_by_reason')}",
        f"- ttft_tail: {report.get('ttft_tail')}",
        f"- itl_tail: {report.get('itl_tail')}",
        f"- requests_by_prompt_bucket: {report.get('requests_by_prompt_bucket')}",
    ]
    if report.get("boot_events"):
        lines += ["", "## Boot events"]
        lines += [f"- {ev}" for ev in report["boot_events"]]
    return "\n".join(lines) + "\n"


def default_scrape_dir() -> Path:
    env = os.environ.get("SCRAPE_OUT_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "tmp" / "eval" / "scrape"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default=None, help="UTC date YYYY-MM-DD; default: today")
    ap.add_argument("--scrape-dir", default=None,
                     help="directory of <date>.jsonl scrape files (default: $SCRAPE_OUT_DIR or tmp/eval/scrape)")
    ap.add_argument("--out", default=None, help="write the JSON report here; default: stdout")
    ap.add_argument("--md-out", default=None, help="also write a markdown report here")
    args = ap.parse_args()

    date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    scrape_dir = Path(args.scrape_dir) if args.scrape_dir else default_scrape_dir()
    path = scrape_dir / f"{date}.jsonl"
    if not path.is_file():
        print(f"no scrape file for {date}: {path}", file=sys.stderr)
        return 2

    report = daily_report(load_scrapes(path))
    report["date"] = date
    out_text = json.dumps(report, indent=2)

    if args.out:
        Path(args.out).write_text(out_text + "\n")
    else:
        print(out_text)
    if args.md_out:
        Path(args.md_out).write_text(render_report_md(date, report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
