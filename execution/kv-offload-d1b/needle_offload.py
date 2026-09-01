#!/usr/bin/env python3
"""Offload-hit correctness probe for KV-offload Phase A (arm A1 gate).

Subcommands:
  needle  --seed S --n-words N --state DIR   build+send needle prompt, save state
  flood   --tokens T --base-seed S           sequential 72500-word fresh probes until >= T tokens
  requery --seed S --n-words N --state DIR   re-send byte-identical prompt, compare answer

Needle prompt: N random words (seed S), sentence "The secret passphrase is
AURORA-73-KESTREL." inserted after word N*7//17 (=7000 for N=17000), then the
question. temperature 0, thinking off. State file records prompt sha256 and
answer so requery is provably byte-identical.
"""
import argparse
import hashlib
import json
import random
import string
import sys
import time
import urllib.request

API = "http://192.168.88.181:8890/v1/chat/completions"
MODEL = "deepseek-v4-flash-0731"
PASSPHRASE = "AURORA-73-KESTREL"


def rand_words(n_words, seed):
    rng = random.Random(seed)
    return [
        "".join(rng.choices(string.ascii_lowercase, k=rng.randint(3, 9)))
        for _ in range(n_words)
    ]


def needle_prompt(n_words, seed):
    words = rand_words(n_words, seed)
    pos = n_words * 7 // 17
    words.insert(pos, f"The secret passphrase is {PASSPHRASE}.")
    return (
        " ".join(words)
        + "\nQuestion: what is the secret passphrase mentioned in the text?"
        " Answer with just the passphrase."
    )


def request(prompt, max_tokens, timeout=1800):
    body = json.dumps(
        {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0,
            "chat_template_kwargs": {"thinking": False},
        }
    ).encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    dt = time.time() - t0
    usage = data.get("usage") or {}
    return {
        "latency_s": round(dt, 2),
        "prompt_tokens": usage.get("prompt_tokens"),
        "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
        "answer": (data.get("choices") or [{}])[0].get("message", {}).get("content", ""),
    }


def state_path(state_dir, seed, n_words):
    return f"{state_dir}/needle-s{seed}-w{n_words}.json"


def cmd_needle(args):
    prompt = needle_prompt(args.n_words, args.seed)
    digest = hashlib.sha256(prompt.encode()).hexdigest()
    r = request(prompt, max_tokens=32)
    out = {
        "phase": "cold",
        "seed": args.seed,
        "n_words": args.n_words,
        "prompt_sha256": digest,
        "pass_ok": PASSPHRASE in r["answer"],
        **r,
    }
    with open(state_path(args.state, args.seed, args.n_words), "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))
    sys.exit(0 if out["pass_ok"] else 1)


def cmd_requery(args):
    with open(state_path(args.state, args.seed, args.n_words)) as f:
        cold = json.load(f)
    prompt = needle_prompt(args.n_words, args.seed)
    digest = hashlib.sha256(prompt.encode()).hexdigest()
    assert digest == cold["prompt_sha256"], "prompt reconstruction mismatch"
    r = request(prompt, max_tokens=32)
    verdict = {
        "answer_match": r["answer"] == cold["answer"],
        "pass_ok": PASSPHRASE in r["answer"],
        "cache_hit": bool(r["cached_tokens"]),
        "latency_ok": r["latency_s"] <= args.max_latency,
    }
    out = {
        "phase": "requery",
        "seed": args.seed,
        "n_words": args.n_words,
        "prompt_sha256": digest,
        "cold": {k: cold[k] for k in ("latency_s", "cached_tokens", "answer")},
        **r,
        "verdict": verdict,
        "gate_pass": all(verdict.values()),
    }
    print(json.dumps(out, indent=2))
    sys.exit(0 if out["gate_pass"] else 1)


def cmd_flood(args):
    total = 0
    seed = args.base_seed
    rounds = []
    while total < args.tokens:
        prompt = " ".join(rand_words(72500, seed))
        r = request(prompt, max_tokens=1)
        total += r["prompt_tokens"] or 0
        rounds.append({"seed": seed, **r})
        print(json.dumps({"flood_round": len(rounds), "seed": seed, "total_tokens": total, **r}))
        seed += 1
    print(json.dumps({"phase": "flood", "rounds": len(rounds), "total_tokens": total}))


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("needle", "requery"):
        s = sub.add_parser(name)
        s.add_argument("--seed", type=int, required=True)
        s.add_argument("--n-words", type=int, required=True)
        s.add_argument("--state", required=True)
        if name == "requery":
            s.add_argument("--max-latency", type=float, required=True)
    s = sub.add_parser("flood")
    s.add_argument("--tokens", type=int, required=True)
    s.add_argument("--base-seed", type=int, required=True)
    args = p.parse_args()
    {"needle": cmd_needle, "requery": cmd_requery, "flood": cmd_flood}[args.cmd](args)


if __name__ == "__main__":
    main()
