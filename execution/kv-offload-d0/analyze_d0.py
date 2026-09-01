#!/usr/bin/env python3
"""D0 readout: discriminate the block-hash-mismatch mechanisms.

Implements the readout of
planning/02-working/2026-09-01-kv-offload-hash-mismatch-rootcause.md §7.4 and
Rev 2 R2.4:

  C1  hash-input instability (fresh hash VALUES per scheduler pass)
  C2  stale-snapshot bookkeeping (stable hashes, re-offered/re-stored anyway)
  C3-family / fork boundary code (GPU-side entry destruction; A/A' readout)
  Patch-3 discriminator: instability concentrated at MTP decode boundaries
      (probe B post-TTFT) vs chunked-prefill passes (probe B pre-TTFT, A/A')

Inputs:
  --events  subscriber JSONL (raw messages; batch wrappers flattened here)
  --meta    d0_probes.py JSONL (probe windows, ttft, cached_tokens)

Schema-tolerant by design: exact KV-event field names at snapshot
7e33081cee7b were not verified in-container, so the first section is a shape
census — read it before trusting the numbers. Exit code is always 0 unless
inputs are unparseable; this is a measurement tool, not a gate.
"""
import argparse
import json
import sys
from collections import Counter, defaultdict

BLOCK = 256


def load_events(path):
    events = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                print(f"warn: line {lineno} not JSON, skipped", file=sys.stderr)
                continue
            ts = msg.get("recv_ts")
            stack = [msg.get("payload")]
            while stack:
                item = stack.pop(0)
                if item is None:
                    continue
                if isinstance(item, list):
                    stack = item + stack
                    continue
                if not isinstance(item, dict):
                    continue
                inner = item.get("events")
                if isinstance(inner, list):
                    stack = inner + stack
                    continue
                item = dict(item)
                item["recv_ts"] = ts
                item["_line"] = lineno
                events.append(item)
    return events


def norm_type(e):
    t = e.get("type") or e.get("event") or ""
    return str(t).lower().replace("-", "_")


def source_of(e):
    return str(e.get("device") or e.get("medium") or "unlabeled")


def hashes_of(e):
    h = e.get("block_hashes") or e.get("hashes") or []
    return [str(x) for x in h]


def group_of(e):
    return e.get("kv_cache_group_id", e.get("group_id", "?"))


def load_meta(path):
    probes = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            probes[r["probe"]] = r
    return probes


def window(events, start, end):
    return [e for e in events if start is not None and e["recv_ts"] is not None and start <= e["recv_ts"] <= end + 5.0]


def series_stats(store_events):
    """store_events: chronological list of store events for one
    (request, group, source). Returns metrics + per-event sizes."""
    instances = 0
    seen = set()
    repeats = 0
    overlap_ratios = []
    sizes = []
    for e in store_events:
        hs = hashes_of(e)
        sizes.append(len(hs))
        prev_union = set(seen)
        cur = [h for h in hs if h in prev_union]
        if hs:
            overlap_ratios.append(len(cur) / len(hs))
        for h in hs:
            instances += 1
            if h in seen:
                repeats += 1
            seen.add(h)
    unique = len(seen)
    return {
        "n_store_events": len(store_events),
        "block_store_instances": instances,
        "unique_hashes": unique,
        "repeat_instances": repeats,
        "repeat_ratio": round(repeats / instances, 3) if instances else 0.0,
        "mean_consecutive_overlap": round(sum(overlap_ratios) / len(overlap_ratios), 3) if overlap_ratios else 0.0,
        "store_event_sizes": sizes[:24],
        "triangular": len(sizes) >= 3 and all(sizes[i] > sizes[i - 1] for i in range(1, min(len(sizes), 6))),
    }


def verdict_for(stats, expected_blocks):
    """Map one series' numbers onto the candidate labels."""
    amp = stats["block_store_instances"] / expected_blocks if expected_blocks else float("nan")
    out = {"amplification_vs_expected": round(amp, 2) if amp == amp else None}
    if stats["n_store_events"] == 0:
        out["label"] = "no-stores"
    elif stats["mean_consecutive_overlap"] >= 0.3 and stats["repeat_ratio"] >= 0.2:
        out["label"] = "C2-like: STABLE hashes re-stored (bookkeeping)"
    elif amp >= 1.6 and stats["mean_consecutive_overlap"] <= 0.05 and stats["repeat_ratio"] <= 0.05:
        out["label"] = "C1-like: FRESH hash values per pass (hash-input instability)"
    elif stats["repeat_ratio"] > 0.05 or stats["mean_consecutive_overlap"] > 0.05:
        out["label"] = "MIXED: partial repeat + partial fresh (oscillating keys?)"
    else:
        out["label"] = "healthy/incremental"
    if stats["triangular"]:
        out["note"] = "store-event sizes strictly growing = full-prefix re-store (triangular) signature"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--out", help="optional JSON summary out")
    a = ap.parse_args()

    events = load_events(a.events)
    probes = load_meta(a.meta)
    summary = {}

    print(f"== census: {len(events)} events ==")
    census = Counter((norm_type(e), source_of(e)) for e in events)
    for (t, s), n in sorted(census.items()):
        print(f"  {t or '<no type>':24s} source={s:10s} n={n}")
    shapes = {}
    for e in events:
        shapes.setdefault(tuple(sorted(e.keys())), e)
    print("  shape samples:")
    for keys, e in list(shapes.items())[:6]:
        print(f"    {json.dumps({k: e[k] for k in keys if k not in ('block_hashes',)})[:400]}")
    summary["census"] = {f"{t}|{s}": n for (t, s), n in census.items()}

    stored = [e for e in events if norm_type(e) == "block_stored"]
    removed = [e for e in events if norm_type(e) == "block_removed"]

    # Group series by (request, group, source), chronologically.
    series = defaultdict(list)
    for e in sorted(stored, key=lambda e: e["recv_ts"] or 0):
        series[(e.get("request_id", "?"), group_of(e), source_of(e))].append(e)

    print(f"\n== per-(request, group, source) store series: {len(series)} ==")
    series_rows = []
    for key in sorted(series, key=lambda k: (k[0], str(k[1]), k[2])):
        evs = series[key]
        stats = series_stats(evs)
        # Map to probe window for expected-size context (use the window the
        # FIRST event falls in). Windows carry +5s slack, so with back-to-back
        # probes keep the LAST match — the chronologically closest probe.
        owning = "?"
        expected = None
        for pname, r in probes.items():
            if r["start_epoch"] <= (evs[0]["recv_ts"] or 0) <= r["end_epoch"] + 5.0:
                owning = pname
                expected = max(1, (r.get("prompt_tokens") or 0) // BLOCK)
        v = verdict_for(stats, expected)
        print(
            f"  req={key[0][:18]:18s} grp={str(key[1]):3s} src={key[2]:9s} probe={owning:3s} "
            f"events={stats['n_store_events']:3d} inst={stats['block_store_instances']:5d} "
            f"uniq={stats['unique_hashes']:5d} rep%={stats['repeat_ratio']*100:5.1f} "
            f"ovl={stats['mean_consecutive_overlap']:5.2f} sizes={stats['store_event_sizes'][:10]}"
        )
        print(f"      -> {v['label']}" + (f" ({v.get('note')})" if v.get("note") else "") + f" amp={v['amplification_vs_expected']}")
        series_rows.append({"key": list(map(str, key)), "probe": owning, **stats, **v})
    summary["series"] = series_rows

    print("\n== A vs A' (GPU prefix-cache readout) ==")
    a_row = {}
    if "A" in probes and "A2" in probes:
        rA, rA2 = probes["A"], probes["A2"]
        cached2 = rA2.get("cached_tokens")
        print(f"  A2 cached_tokens = {cached2} (prompt {rA2.get('prompt_tokens')})")
        a_row["A2_cached_tokens"] = cached2
        if cached2:
            print("  -> GPU hit path WORKS in this boot; GPU-side fault not reproduced (connector behavior may differ from A1).")
            a_row["gpu_readout"] = "hit-ok"
        else:
            gpu_hashes = {}
            for pname, r in (("A", rA), ("A2", rA2)):
                hs = set()
                for e in window(stored, r["start_epoch"], r["end_epoch"]):
                    if source_of(e) in ("gpu", "unlabeled"):
                        hs.update(hashes_of(e))
                gpu_hashes[pname] = hs
            inter = len(gpu_hashes["A"] & gpu_hashes["A2"])
            denom = max(1, len(gpu_hashes["A"]))
            ratio = round(inter / denom, 3)
            print(f"  GPU-stored hash sets: |A|={len(gpu_hashes['A'])} |A2|={len(gpu_hashes['A2'])} overlap={inter} ({ratio:.0%})")
            if not gpu_hashes["A2"]:
                print("  -> A2 stored nothing and hit nothing: inconclusive from stores alone (lookup-time keys unseen).")
                a_row["gpu_readout"] = "inconclusive-no-restores"
            elif ratio >= 0.9:
                print("  -> C3-family / fork boundary code: hashes STABLE across requests, table entries destroyed.")
                a_row["gpu_readout"] = "C3-like-stable-hashes-entries-destroyed"
            else:
                print("  -> C1-family: hash values DIVERGE across requests at creation.")
                a_row["gpu_readout"] = "C1-like-cross-request-divergence"
    summary["A_vs_A2"] = a_row

    print("\n== probe B: prefill passes vs MTP-decode phase (Patch-3 discriminator) ==")
    b_row = {}
    if "B" in probes and probes["B"].get("ttft_s"):
        r = probes["B"]
        split = r["start_epoch"] + r["ttft_s"]
        phases = {"prefill": [], "decode": []}
        for e in window(stored, r["start_epoch"], r["end_epoch"]):
            phases["prefill" if e["recv_ts"] <= split else "decode"].append(e)
        for phase, evs in phases.items():
            inst = sum(len(hashes_of(e)) for e in evs)
            uniq = len(set().union(*[set(hashes_of(e)) for e in evs])) if evs else 0
            expected = max(1, (r.get("prompt_tokens") or 0) // BLOCK)
            print(f"  {phase:7s}: store events={len(evs):3d} instances={inst:5d} unique={uniq:5d} (expected≈{expected} for the whole prompt)")
            b_row[phase] = {"events": len(evs), "instances": inst, "unique": uniq}
        if b_row.get("decode", {}).get("instances", 0) > b_row.get("prefill", {}).get("instances", 0):
            print("  -> instability CONCENTRATED post-TTFT: MTP/decode boundary => Patch 3 / placeholder handling (fork shim vehicle).")
            b_row["discriminator"] = "patch3-decode-side"
        elif b_row.get("prefill", {}).get("instances", 0) > 2 * (r.get("prompt_tokens") or 1) // BLOCK:
            print("  -> amplification present WITHIN chunked-prefill passes => stale-snapshot C2 / connector-scheduler vehicle (vendored subtree).")
            b_row["discriminator"] = "prefill-pass-instability"
        else:
            print("  -> no clear prefill/decode asymmetry; rely on per-series labels above.")
            b_row["discriminator"] = "asymmetric-none"
    else:
        print("  (probe B meta missing or no ttft)")
    summary["probe_B"] = b_row

    print("\n== BlockRemoved census (eviction-pressure-free window; any removals are signal) ==")
    rem = Counter((source_of(e), group_of(e)) for e in removed)
    print("  " + (json.dumps({f"{s}|{g}": n for (s, g), n in rem.items()}) if rem else "none"))
    summary["block_removed"] = {f"{s}|{g}": n for (s, g), n in rem.items()}

    print(
        "\n== decision matrix (root-cause doc §8 / R2.4-R2.5) ==\n"
        "  C1-like (fresh hashes/pass, any phase)  or C3-like GPU readout => vendored subtree @ f5e441de10bd is the vehicle;\n"
        "      if C1 concentrates post-TTFT (patch3-decode-side) ALSO adopt upstream #46066/#48245 semantics in a fork shim.\n"
        "  C2-like (stable hashes re-stored)       => vendored subtree @ f5e441de10bd (bookkeeping fixes wholesale).\n"
        "  healthy everywhere + A2 miss persists   => fault is at lookup time, not store time; re-read with lookup-side instrumentation.\n"
        "  healthy everywhere + A2 hit             => not reproduced this boot; compare boot flags vs A1 before concluding."
    )

    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        print(f"\nsummary written: {a.out}")


if __name__ == "__main__":
    main()
