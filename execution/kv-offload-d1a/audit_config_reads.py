#!/usr/bin/env python3
"""D1a config-read audit: every <x>_config.<attr> read in the overlay must
exist on the fork's config classes (image ground truth), else boot crash.

Boot 4 lesson: attribute reads on VllmConfig receivers were outside the
previous spec/tensor/group audits. This closes the class.
"""
import re
import sys
from pathlib import Path

OVERLAY = Path("tmp/kv-offload-d1a/overlay/vllm")
REFS = {
    "vllm_config": Path("tmp/kv-offload-d1a/fork-vllmconfig-ref.py"),
    "scheduler_config": Path("tmp/kv-offload-d1a/fork-config-scheduler.py"),
    "parallel_config": Path("tmp/kv-offload-d1a/fork-config-parallel.py"),
    "cache_config": Path("tmp/kv-offload-d1a/fork-config-cache.py"),
    "model_config": Path("tmp/kv-offload-d1a/fork-config-model.py"),
    "speculative_config": Path("tmp/kv-offload-d1a/fork-config-speculative.py"),
}
CLASS_NAME = {
    "vllm_config": "VllmConfig",
    "scheduler_config": "SchedulerConfig",
    "parallel_config": "ParallelConfig",
    "cache_config": "CacheConfig",
    "model_config": "ModelConfig",
    "speculative_config": "SpeculativeConfig",
}


def surface(path, cls):
    """Attribute names defined on `class cls` (fields, properties, methods)."""
    names, in_cls, indent = set(), False, None
    for line in path.read_text().splitlines():
        m = re.match(r"^(\s*)class\s+" + cls + r"\b", line)
        if m:
            in_cls, indent = True, len(m.group(1))
            continue
        if in_cls:
            if line.strip() and not line.startswith(" " * (indent + 1)):
                if line.startswith(" " * indent) and re.match(r"^\s*(class|def)\b|^@|^#", line) is None and not line.startswith(" " * (indent + 1)):
                    in_cls = False  # dedented past the class body
                elif not line.startswith(" " * (indent + 1)) and not line.strip().startswith(("#", "@", '"""', "'''")):
                    in_cls = False
            f = re.match(r"^\s{4,}(\w+)\s*[:=]", line)
            d = re.match(r"^\s+def\s+(\w+)", line)
            s = re.match(r"^\s+self\.(\w+)\s*=[^=]", line)
            if f:
                names.add(f.group(1))
            if d:
                names.add(d.group(1))
            if s:
                names.add(s.group(1))
    return names


def main():
    surfaces = {}
    for var, path in REFS.items():
        surfaces[var] = surface(path, CLASS_NAME[var])
        if not surfaces[var]:
            print(f"WARN: empty surface for {var} ({path.name})", file=sys.stderr)
    read_re = re.compile(r"\b(" + "|".join(REFS) + r")\.(\w+)")
    # depth-2 chains: vllm_config.<sub>.<attr> and local <sub>.<attr>.<x>
    # (boot 5 miss: vllm_config.cache_config.kv_cache_layout — tip-only
    # sub-config field read through a chained access)
    subs = "|".join(k for k in REFS if k != "vllm_config")
    chain_re = re.compile(
        r"\b(?:vllm_config\.(" + subs + r")|(?<!\w)(" + subs + r"))\.(\w+)"
    )
    hits, missing = {}, []
    for py in sorted(OVERLAY.rglob("*.py")):
        rel = str(py.relative_to(OVERLAY))
        text = py.read_text()
        for m in read_re.finditer(text):
            var, attr = m.group(1), m.group(2)
            lineno = text[: m.start()].count("\n") + 1
            hits.setdefault((var, attr), []).append(f"{rel}:{lineno}")
            if attr not in surfaces[var]:
                missing.append((var, attr, rel, lineno))
        for m in chain_re.finditer(text):
            sub = m.group(1) or m.group(2)
            attr = m.group(3)
            lineno = text[: m.start()].count("\n") + 1
            key = (sub, attr)
            if key in hits:
                continue
            # skip <sub>.<attr> where attr is itself a call/module ref noise
            hits.setdefault(key, []).append(f"{rel}:{lineno} (chain)")
            if attr not in surfaces[sub]:
                missing.append((sub, attr, rel, lineno))
    print(f"overlay files scanned: {len(list(OVERLAY.rglob('*.py')))}; distinct reads: {len(hits)}")
    if missing:
        print("MISSING ON FORK CONFIG:")
        for var, attr, rel, lineno in sorted(set(missing)):
            print(f"  {var}.{attr}  <- {rel}:{lineno}")
        sys.exit(1)
    print("ALL CONFIG READS PRESENT ON FORK — PASS")


if __name__ == "__main__":
    main()
