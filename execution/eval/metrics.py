#!/usr/bin/env python3
"""Generic Prometheus text-format parser plus vLLM-specific derived stats.

Metric names are verified against `fixtures/metrics-20260904.txt`, a live
snapshot from this vLLM 0.25.2 build (see that file for the authoritative
`# HELP`/`# TYPE` list). The parser itself does not hardcode any metric name;
name-specific logic lives only in `delta()` and its helpers.
"""
from __future__ import annotations

import re
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path

_SAMPLE_RE = re.compile(r'^([A-Za-z_:][A-Za-z0-9_:]*)(\{([^}]*)\})?\s+(\S+)\s*$')
_LABEL_RE = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')


@dataclass
class Sample:
    name: str
    labels: dict[str, str]
    value: float


Snapshot = dict  # name -> list[Sample]


def parse(text: str) -> list[Sample]:
    samples = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _SAMPLE_RE.match(line)
        if not m:
            continue
        labels = dict(_LABEL_RE.findall(m.group(3) or ""))
        try:
            value = float(m.group(4))
        except ValueError:
            continue
        samples.append(Sample(m.group(1), labels, value))
    return samples


def fetch(url: str, timeout: int = 10) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def snapshot(text: str) -> Snapshot:
    grouped: Snapshot = {}
    for sample in parse(text):
        grouped.setdefault(sample.name, []).append(sample)
    return grouped


def load(path: str | Path) -> Snapshot:
    return snapshot(Path(path).read_text(encoding="utf-8"))


def sum_metric(snap: Snapshot, name: str, label_filter: dict[str, str] | None = None) -> float:
    total = 0.0
    for sample in snap.get(name, []):
        if label_filter and any(sample.labels.get(k) != v for k, v in label_filter.items()):
            continue
        total += sample.value
    return total


def by_label(snap: Snapshot, name: str, label_key: str) -> dict[str, float]:
    """Sum a metric's samples grouped by one label value (e.g. `position`,
    `finished_reason`), collapsing the `engine` label."""
    out: dict[str, float] = {}
    for sample in snap.get(name, []):
        key = sample.labels.get(label_key, "")
        out[key] = out.get(key, 0.0) + sample.value
    return out


def num_requests_running(snap: Snapshot) -> float:
    return sum_metric(snap, "vllm:num_requests_running")


def bucket_deltas(before: Snapshot, after: Snapshot, name: str) -> dict[str, float]:
    """Cumulative `*_bucket{le=...}` deltas, summed across engines. Values
    are still cumulative (count of observations <= le); take successive
    differences over sorted `le` to get per-bin counts."""
    b0 = by_label(before, f"{name}_bucket", "le")
    b1 = by_label(after, f"{name}_bucket", "le")
    return {le: b1.get(le, 0.0) - b0.get(le, 0.0) for le in b1}


def delta(before: Snapshot, after: Snapshot) -> dict:
    def d(name: str) -> float:
        return sum_metric(after, name) - sum_metric(before, name)

    accepted = d("vllm:spec_decode_num_accepted_tokens_total")
    draft = d("vllm:spec_decode_num_draft_tokens_total")
    drafts = d("vllm:spec_decode_num_drafts_total")
    pos_before = by_label(before, "vllm:spec_decode_num_accepted_tokens_per_pos_total", "position")
    pos_after = by_label(after, "vllm:spec_decode_num_accepted_tokens_per_pos_total", "position")
    per_position = {
        pos: pos_after.get(pos, 0.0) - pos_before.get(pos, 0.0)
        for pos in sorted(pos_after, key=lambda x: int(x) if x.isdigit() else 0)
    }
    hits = d("vllm:prefix_cache_hits_total")
    queries = d("vllm:prefix_cache_queries_total")
    success_after = by_label(after, "vllm:request_success_total", "finished_reason")
    success_before = by_label(before, "vllm:request_success_total", "finished_reason")
    success_delta = {r: success_after.get(r, 0.0) - success_before.get(r, 0.0) for r in success_after}
    return {
        "generation_tokens_delta": d("vllm:generation_tokens_total"),
        "prompt_tokens_delta": d("vllm:prompt_tokens_total"),
        "accepted_tokens_delta": accepted,
        "draft_tokens_delta": draft,
        "drafts_delta": drafts,
        "acceptance": (accepted / draft) if draft else None,
        "accepted_per_position_delta": per_position,
        "prefix_cache_hits_delta": hits,
        "prefix_cache_queries_delta": queries,
        "prefix_hit_ratio": (hits / queries) if queries else None,
        "preemptions_delta": d("vllm:num_preemptions_total"),
        "request_success_delta": success_delta,
        "kv_cache_usage_perc_last": sum_metric(after, "vllm:kv_cache_usage_perc"),
        "ttft_bucket_delta": bucket_deltas(before, after, "vllm:time_to_first_token_seconds"),
        "itl_bucket_delta": bucket_deltas(before, after, "vllm:inter_token_latency_seconds"),
        "request_prompt_tokens_bucket_delta": bucket_deltas(before, after, "vllm:request_prompt_tokens"),
    }


def host_mem_available_bytes(ssh_alias: str, timeout: int = 10) -> int | None:
    """`ssh <alias> free -b` -> MemAvailable (last column of the `Mem:` row).
    Returns None on any failure (missing alias, timeout, parse error) so
    callers can record a gap in hosts.jsonl rather than crash the suite."""
    try:
        out = subprocess.run(
            ["ssh", ssh_alias, "free", "-b"],
            capture_output=True, text=True, timeout=timeout, check=True,
        ).stdout
    except Exception:
        return None
    for line in out.splitlines():
        if line.startswith("Mem:"):
            fields = line.split()
            try:
                return int(fields[-1])
            except (ValueError, IndexError):
                return None
    return None
