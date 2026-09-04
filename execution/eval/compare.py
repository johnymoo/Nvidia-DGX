#!/usr/bin/env python3
"""Compare two suite.py run directories and apply the §5.4 adoption rule.

adopt if the targeted primary KPI improves by >= 5% (decode) or >= 10%
(prefill at the targeted bucket) with the three repeats' ranges not
overlapping the baseline's, and no other primary KPI regresses by > 3%.
Any gate failure (needle, tool-call JSON, vision vs baseline, missing
finish_reason, head MemAvailable, warm TTFT@64K) forces REVERT regardless
of the KPI verdict.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import suite

PRIMARY_KPIS = (
    "decode_c1_tok_s",
    "prefill_cold_tok_s@32K", "prefill_cold_tok_s@64K", "prefill_cold_tok_s@128K",
    "ttft_warm@8K", "ttft_warm@64K",
)
LOWER_IS_BETTER = {"ttft_warm@8K", "ttft_warm@64K"}
REGRESSION_THRESHOLD = 0.03
HEAD_MEM_MIN_BYTES = 4 * 1024 ** 3


def load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def host_gate(hosts: list[dict]) -> bool | None:
    values = [r["head_mem_available_bytes"] for r in hosts if r.get("head_mem_available_bytes") is not None]
    return (min(values) >= HEAD_MEM_MIN_BYTES) if values else None


def target_threshold(target: str) -> float:
    if target == "decode_c1_tok_s":
        return 0.05
    if target.startswith("prefill_cold_tok_s@"):
        return 0.10
    raise SystemExit(
        f"--target must be decode_c1_tok_s or prefill_cold_tok_s@{{32K,64K,128K}}, got {target!r}"
    )


def decide(kpis_a: dict, kpis_b: dict, target: str) -> dict:
    """kpis_a = baseline, kpis_b = candidate."""
    threshold = target_threshold(target)
    if target not in kpis_a or target not in kpis_b:
        return {"verdict": "INCONCLUSIVE", "reason": f"missing data for target {target!r} in one of the two runs"}

    a, b = kpis_a[target], kpis_b[target]
    improvement = (b["median"] - a["median"]) / a["median"] if a["median"] else None
    # "ranges not overlapping" + improved direction: candidate's whole range above baseline's.
    non_overlapping = b["min"] > a["max"]
    target_ok = improvement is not None and improvement >= threshold and non_overlapping

    regressions = []
    for name in PRIMARY_KPIS:
        if name == target or name not in kpis_a or name not in kpis_b:
            continue
        bm, cm = kpis_a[name]["median"], kpis_b[name]["median"]
        if not bm:
            continue
        change = (cm - bm) / bm if name in LOWER_IS_BETTER else (bm - cm) / bm
        if change > REGRESSION_THRESHOLD:
            regressions.append({"kpi": name, "change": round(change, 4)})

    return {
        "verdict": "ADOPT" if target_ok and not regressions else "REVERT",
        "target": target,
        "threshold": threshold,
        "improvement": improvement,
        "non_overlapping_ranges": non_overlapping,
        "regressions": regressions,
    }


def gate_verdicts(baseline_results: list[dict], candidate_results: list[dict],
                   candidate_hosts: list[dict]) -> dict[str, object]:
    baseline_gates = suite.compute_gates(baseline_results)
    candidate_gates = suite.compute_gates(candidate_results)
    verdicts: dict[str, object] = {}
    for name in ("needle_64K_exact", "needle_128K_exact", "tool_call_json_6_6",
                 "no_missing_finish_reason", "warm_ttft_64K_le_2s"):
        verdicts[name] = candidate_gates.get(name)

    baseline_vision, candidate_vision = baseline_gates.get("vision_score"), candidate_gates.get("vision_score")
    if baseline_vision is not None and candidate_vision is not None:
        verdicts["vision_score_not_regressed"] = candidate_vision >= baseline_vision - 2
    else:
        verdicts["vision_score_not_regressed"] = None

    verdicts["head_mem_available_ge_4gib"] = host_gate(candidate_hosts)
    return verdicts


def render_compare_md(tag_a: str, tag_b: str, kpis_a: dict, kpis_b: dict,
                       gates: dict, decision: dict) -> str:
    lines = [
        f"# Compare: {tag_a} (baseline) vs {tag_b} (candidate)", "",
        "## KPIs", "",
        "| KPI | baseline median | baseline range | candidate median | candidate range |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name in sorted(set(kpis_a) | set(kpis_b)):
        a, b = kpis_a.get(name), kpis_b.get(name)
        a_med = f"{a['median']:.3f}" if a else "-"
        a_rng = f"[{a['min']:.3f}, {a['max']:.3f}]" if a else "-"
        b_med = f"{b['median']:.3f}" if b else "-"
        b_rng = f"[{b['min']:.3f}, {b['max']:.3f}]" if b else "-"
        lines.append(f"| {name} | {a_med} | {a_rng} | {b_med} | {b_rng} |")

    lines += ["", "## Gates", "", "| gate | result |", "| --- | --- |"]
    for name in sorted(gates):
        lines.append(f"| {name} | {gates[name]} |")

    lines += ["", "## Decision", "", f"- verdict: **{decision['verdict']}**"]
    if "reason" in decision:
        lines.append(f"- reason: {decision['reason']}")
    else:
        lines.append(f"- target: {decision['target']} (threshold {decision['threshold'] * 100:.0f}%)")
        lines.append(f"- improvement: {decision['improvement']}")
        lines.append(f"- non_overlapping_ranges: {decision['non_overlapping_ranges']}")
        lines.append(f"- other-primary-KPI regressions (>3%): {decision['regressions'] or 'none'}")
    if any(v is False for v in gates.values()):
        lines.append("- NOTE: at least one gate failed -> REVERT regardless of the KPI verdict above")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("baseline_dir")
    ap.add_argument("candidate_dir")
    ap.add_argument("--target", required=True,
                     help="primary KPI this treatment targets, e.g. decode_c1_tok_s or prefill_cold_tok_s@64K")
    ap.add_argument("--out", default=None, help="write compare.md here (default: <candidate_dir>/compare.md)")
    args = ap.parse_args()

    baseline_dir, candidate_dir = Path(args.baseline_dir), Path(args.candidate_dir)
    baseline_results = load_jsonl(baseline_dir / "results.jsonl")
    candidate_results = load_jsonl(candidate_dir / "results.jsonl")
    candidate_hosts = load_jsonl(candidate_dir / "hosts.jsonl")

    kpis_a = suite.compute_kpis(baseline_results)
    kpis_b = suite.compute_kpis(candidate_results)
    gates = gate_verdicts(baseline_results, candidate_results, candidate_hosts)
    decision = decide(kpis_a, kpis_b, args.target)
    if any(v is False for v in gates.values()):
        decision["verdict"] = "REVERT"

    report = render_compare_md(baseline_dir.name, candidate_dir.name, kpis_a, kpis_b, gates, decision)
    out_path = Path(args.out) if args.out else candidate_dir / "compare.md"
    out_path.write_text(report)
    print(report)
    return 0 if decision["verdict"] == "ADOPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
