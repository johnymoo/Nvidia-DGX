#!/usr/bin/env python3
"""Collect per-bench JSONs in a results dir into summary.json (window evidence)."""
import json
import sys
from pathlib import Path


def load(res: Path, name: str):
    try:
        return json.loads((res / name).read_text())
    except Exception:
        return None


def main() -> int:
    res = Path(sys.argv[1])
    s = {"ts": res.name}
    mode = res / "mode.txt"
    if mode.exists():
        s["fallback_mode"] = "fallback_mode=1" in mode.read_text()
    boot = res / "boot.txt"
    if boot.exists():
        s["boot_secs"] = boot.read_text().strip()
    kv = res / "kv-pool.txt"
    if kv.exists():
        lines = [ln for ln in kv.read_text().splitlines() if ln.strip()]
        s["kv_pool_lines"] = lines[-3:]
    for name, key in (("decode-structured.json", "decode_structured_c1"),
                      ("decode-prose.json", "decode_prose_c1")):
        d = load(res, name)
        if d:
            s[key] = {"tok_s_median": d.get("tok_s_median"),
                      "accept_per_step_median": d.get("accepted_per_step_median"),
                      "accept_ratio_median": d.get("accept_ratio_median"),
                      "coherent": d.get("coherent")}
    for name, key in (("conc-struct-c2.json", "conc_structured_c2"),
                      ("conc-struct-c4.json", "conc_structured_c4"),
                      ("conc-prose-c2.json", "conc_prose_c2")):
        d = load(res, name)
        if d:
            s[key] = d.get("summary")
    d = load(res, "prefill-ladder.json")
    if d:
        s["prefill_ladder"] = {f"{k}k": v.get("prefill_tok_s_best")
                               for k, v in (d.get("summary") or {}).items()}
        s["prefill_aborted"] = d.get("aborted", False)
        s["prefill_mem_min_mb"] = d.get("mem_min_overall_mb")
    v = load(res, "vision.json")
    if v:
        glm = (v.get("treatments") or {}).get("off", {}).get("glm") or {}
        on_ = (v.get("treatments") or {}).get("on", {}).get("glm") or {}
        q = glm.get("quality") or {}
        s["vision_off_quality"] = {"passed": q.get("passed"), "total": q.get("total")}
        menu = glm.get("menu") or {}
        grade = menu.get("grade") or {}
        fallback = glm.get("menu_fallback") or {}
        s["menu_off"] = {"score": grade.get("passed"), "total": grade.get("total"),
                         "elapsed_s": menu.get("elapsed_s"),
                         "fallback_score": (fallback.get("grade") or {}).get("passed"),
                         "fallback_error": fallback.get("error")}
        g_on = on_.get("menu") or {}
        s["menu_on"] = {"score": (g_on.get("grade") or {}).get("passed"),
                        "total": (g_on.get("grade") or {}).get("total"),
                        "elapsed_s": g_on.get("elapsed_s"),
                        "error": g_on.get("error")}
        perf = {}
        for mode_name, treat in (v.get("treatments") or {}).items():
            g = (treat or {}).get("glm", {}).get("performance") or {}
            for c, blob in g.items():
                perf[f"{mode_name}_{c}"] = (blob.get("summary") or {}).get("median_aggregate_tok_s")
        s["vision_perf_aggregate"] = perf
    (res / "summary.json").write_text(json.dumps(s, indent=2, ensure_ascii=False))
    print(json.dumps(s, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
