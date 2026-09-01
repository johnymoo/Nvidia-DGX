#!/usr/bin/env python3
"""D0 diagnostic arm edits: A1 connector config + kv-events publisher + PYTHONHASHSEED=0.

Run ON a host via: ssh HOST "python3 - <subcmd> <deploy_root> <bak_tag>" < edit_files.py
Subcommands: d0 | rollback | verify
Every edit: verify precondition -> cp FILE FILE.bak-<tag> (first edit only) -> apply
-> verify postcondition. Prints one JSON object; nonzero exit on any failure.
Idempotent: already-applied edits report {"status": "already"} and make no backup.

D0 config = A1 (OffloadingConnector @ 8 GiB) PLUS:
  --kv-events-config (zmq publisher, tcp://127.0.0.1:19555, topic kv)
  PYTHONHASHSEED="0" (Dynamo-documented hygiene; removes one variable)
Live hosts are in the ADOPTED A0 state (compose has the PYTORCH_CUDA_ALLOC_CONF
passthrough line; common.env has PYTORCH_CUDA_ALLOC_CONF=) — these anchors are
asserted, not assumed.
"""
import json
import shutil
import sys

ANCHOR = "        --enable-chunked-prefill\n"
KV_LINE = (
    "        --kv-transfer-config '"
    '{"kv_connector":"OffloadingConnector","kv_role":"kv_both",'
    '"kv_connector_extra_config":{"cpu_bytes_to_use":${KV_OFFLOAD_CPU_BYTES:-8589934592}}}'
    "'\n"
)
KVEV_LINE = (
    "        --kv-events-config '"
    '{"enable_kv_cache_events":true,"publisher":"zmq",'
    '"endpoint":"tcp://127.0.0.1:19555","topic":"kv"}'
    "'\n"
)
KV_BLOCK = KV_LINE + KVEV_LINE
ENV_ANCHOR = '      PYTORCH_CUDA_ALLOC_CONF: "${PYTORCH_CUDA_ALLOC_CONF:-}"\n'
PYHASH_LINE = '      PYTHONHASHSEED: "0"\n'
ENV_KV_BYTES = "KV_OFFLOAD_CPU_BYTES=8589934592\n"
FILES = ("docker-compose.yml", "docker-compose.thinking-on.yml", "env/common.env")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def backup(path, tag):
    dst = f"{path}.bak-{tag}"
    if not __import__("os").path.exists(dst):
        shutil.copy2(path, dst)
    return dst


def insert_after(path, anchor, insertion, tag, results):
    text = read(path)
    if insertion in text:
        results.append({"file": path, "status": "already"})
        return
    if text.count(anchor) != 1:
        raise SystemExit(json.dumps({"error": f"anchor count {text.count(anchor)} != 1 in {path}"}))
    bak = backup(path, tag)
    write(path, text.replace(anchor, anchor + insertion))
    assert insertion in read(path)
    results.append({"file": path, "status": "edited", "backup": bak})


def append_line(path, line, tag, results):
    text = read(path)
    if line in text:
        results.append({"file": path, "status": "already"})
        return
    key = line.split("=")[0] + "="
    if any(ln.startswith(key) for ln in text.splitlines()):
        raise SystemExit(json.dumps({"error": f"conflicting {key} line already in {path}"}))
    bak = backup(path, tag)
    write(path, text + ("" if text.endswith("\n") else "\n") + line)
    results.append({"file": path, "status": "edited", "backup": bak})


def main():
    cmd, root, tag = sys.argv[1], sys.argv[2].rstrip("/"), sys.argv[3]
    ex = f"{root}/execution"
    compose = f"{ex}/docker-compose.yml"
    thinking = f"{ex}/docker-compose.thinking-on.yml"
    env = f"{ex}/env/common.env"
    results = []
    if cmd == "d0":
        insert_after(compose, ANCHOR, KV_BLOCK, tag, results)
        insert_after(thinking, ANCHOR, KV_BLOCK, tag, results)
        insert_after(compose, ENV_ANCHOR, PYHASH_LINE, tag, results)
        append_line(env, ENV_KV_BYTES, tag, results)
    elif cmd == "rollback":
        for name in FILES:
            path = f"{ex}/{name}"
            bak = f"{path}.bak-{tag}"
            try:
                shutil.copy2(bak, path)
                results.append({"file": path, "status": "restored", "from": bak})
            except FileNotFoundError:
                results.append({"file": path, "status": "no-backup", "from": bak})
        text_c, text_t, text_e = read(compose), read(thinking), read(env)
        leftovers = {
            "compose_kv": KV_LINE in text_c or KVEV_LINE in text_c,
            "compose_pyhash": PYHASH_LINE in text_c,
            "thinking_kv": KV_LINE in text_t or KVEV_LINE in text_t,
            "env_kv_bytes": ENV_KV_BYTES in text_e,
        }
        results.append({"leftovers_after_rollback": leftovers})
        if any(leftovers.values()):
            raise SystemExit(json.dumps({"cmd": cmd, "results": results, "error": "leftover D0 hunks"}))
    elif cmd == "verify":
        text_c, text_t, text_e = read(compose), read(thinking), read(env)
        results.append(
            {
                "file": compose,
                "present": {
                    "kv-transfer": KV_LINE.strip() in text_c,
                    "kv-events": KVEV_LINE.strip() in text_c,
                    "pyhashseed": PYHASH_LINE.strip() in text_c,
                    "a0-passthrough": ENV_ANCHOR.strip() in text_c,
                },
            }
        )
        results.append({"file": thinking, "present": {"kv-transfer": KV_LINE.strip() in text_t, "kv-events": KVEV_LINE.strip() in text_t}})
        results.append({"file": env, "present": {"kv_bytes": ENV_KV_BYTES.strip() in text_e}})
    else:
        raise SystemExit(json.dumps({"error": f"unknown subcommand {cmd}"}))
    print(json.dumps({"cmd": cmd, "root": root, "results": results}, indent=2))


if __name__ == "__main__":
    main()
