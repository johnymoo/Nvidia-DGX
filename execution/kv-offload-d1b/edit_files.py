#!/usr/bin/env python3
"""D1b gate-boot edits: image swap to d1a-kvoffload + A1 connector config.

Run ON a host via: ssh HOST "python3 - <subcmd> <deploy_root> <bak_tag>" < edit_files.py
Subcommands: host | head | rollback-host | rollback-head | verify
  host        compose KV line (both compose files) + common.env image swap + KV bytes
  head        acceptance EXPECTED_IMAGE/FINGERPRINT + image assert + connector jq lines,
              service fingerprint in service_load_active
Every edit: precondition -> cp FILE FILE.bak-<tag> (once per file) -> apply -> verify.
Idempotent; nonzero exit on any failure.
"""
import json
import os
import shutil
import sys

OLD_IMAGE = "gb10-ds4-vllm:f277b3d-nvfp4"
NEW_IMAGE = "gb10-ds4-vllm:d1a-kvoffload"
OLD_FP = "36adbf92fe8cdd5c57609b2c5ccfa8e2fc32a340c9ee3d727be538143dda74db"
NEW_FP = "b845f104b33e1927473b9d3d7a7eb4e4f05a41c327efc26ee85a367e33a53326"

ANCHOR = "        --enable-chunked-prefill\n"
KV_LINE = (
    "        --kv-transfer-config '"
    '{"kv_connector":"OffloadingConnector","kv_role":"kv_both",'
    '"kv_connector_extra_config":{"cpu_bytes_to_use":${KV_OFFLOAD_CPU_BYTES:-8589934592}}}'
    "'\n"
)
ENV_IMG_OLD = f"DSPARK_VLLM_IMAGE={OLD_IMAGE}\n"
ENV_IMG_NEW = f"DSPARK_VLLM_IMAGE={NEW_IMAGE}\n"
ENV_KV_BYTES = "KV_OFFLOAD_CPU_BYTES=8589934592\n"

JQ_ANCHOR = '      and ($c | contains("--kv-cache-dtype nvfp4_ds_mla"))\n'
JQ_LINES = (
    '      and ($c | contains("--kv-transfer-config"))\n'
    '      and ($c | contains("OffloadingConnector"))\n'
)
ACC_IMG_OLD = f'readonly EXPECTED_IMAGE="{OLD_IMAGE}"\n'
ACC_IMG_NEW = f'readonly EXPECTED_IMAGE="{NEW_IMAGE}"\n'
ACC_FP_OLD = f'readonly EXPECTED_FINGERPRINT="{OLD_FP}"\n'
ACC_FP_NEW = f'readonly EXPECTED_FINGERPRINT="{NEW_FP}"\n'
ACC_RENDER_OLD = f'    | $s.image == "{OLD_IMAGE}"\n'
ACC_RENDER_NEW = f'    | $s.image == "{NEW_IMAGE}"\n'
SVC_FP_OLD = f'    .release.fingerprint == "{OLD_FP}" and\n'
SVC_FP_NEW = f'    .release.fingerprint == "{NEW_FP}" and\n'

HOST_FILES = ("docker-compose.yml", "docker-compose.thinking-on.yml", "env/common.env")
HEAD_FILES = ("run-vllm-acceptance.sh", "run-vllm-service.sh")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def backup(path, tag):
    dst = f"{path}.bak-{tag}"
    if not os.path.exists(dst):
        shutil.copy2(path, dst)
    return dst


def replace_once(path, old, new, tag, results):
    text = read(path)
    if new in text and old not in text:
        results.append({"file": path, "status": "already"})
        return
    if text.count(old) != 1:
        raise SystemExit(json.dumps({"error": f"precondition failed: {old[:60]!r} count={text.count(old)} in {path}"}))
    bak = backup(path, tag)
    write(path, text.replace(old, new, 1))
    assert new in read(path)
    results.append({"file": path, "status": "edited", "backup": bak})


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
    acc = f"{ex}/run-vllm-acceptance.sh"
    svc = f"{ex}/run-vllm-service.sh"
    results = []
    if cmd == "host":
        insert_after(compose, ANCHOR, KV_LINE, tag, results)
        insert_after(thinking, ANCHOR, KV_LINE, tag, results)
        replace_once(env, ENV_IMG_OLD, ENV_IMG_NEW, tag, results)
        append_line(env, ENV_KV_BYTES, tag, results)
    elif cmd == "head":
        replace_once(acc, ACC_IMG_OLD, ACC_IMG_NEW, tag, results)
        replace_once(acc, ACC_FP_OLD, ACC_FP_NEW, tag, results)
        replace_once(acc, ACC_RENDER_OLD, ACC_RENDER_NEW, tag, results)
        insert_after(acc, JQ_ANCHOR, JQ_LINES, tag, results)
        replace_once(svc, SVC_FP_OLD, SVC_FP_NEW, tag, results)
    elif cmd in ("rollback-host", "rollback-head"):
        files = HOST_FILES if cmd == "rollback-host" else HEAD_FILES
        for name in files:
            path = f"{ex}/{name}"
            bak = f"{path}.bak-{tag}"
            try:
                shutil.copy2(bak, path)
                results.append({"file": path, "status": "restored", "from": bak})
            except FileNotFoundError:
                results.append({"file": path, "status": "no-backup"})
        text_c, text_t, text_e = read(compose), read(thinking), read(env)
        text_a, text_s = read(acc), read(svc)
        if cmd == "rollback-host":
            leftovers = {
                "compose_kv": KV_LINE in text_c,
                "thinking_kv": KV_LINE in text_t,
                "env_image_new": ENV_IMG_NEW in text_e,
                "env_kv_bytes": ENV_KV_BYTES in text_e,
            }
        else:
            leftovers = {
                "acc_image_new": ACC_IMG_NEW in text_a,
                "acc_fp_new": ACC_FP_NEW in text_a,
                "acc_render_new": ACC_RENDER_NEW in text_a,
                "acc_jq": JQ_LINES in text_a,
                "svc_fp_new": SVC_FP_NEW in text_s,
            }
        results.append({"leftovers_after_rollback": leftovers})
        if any(leftovers.values()):
            raise SystemExit(json.dumps({"cmd": cmd, "results": results, "error": "leftover D1b hunks"}))
    elif cmd == "verify":
        text_c, text_t, text_e = read(compose), read(thinking), read(env)
        text_a, text_s = read(acc), read(svc)
        print(json.dumps({
            "compose": {"kv": KV_LINE.strip() in text_c},
            "thinking": {"kv": KV_LINE.strip() in text_t},
            "env": {"image": ENV_IMG_NEW.strip() in text_e, "kv_bytes": ENV_KV_BYTES.strip() in text_e, "old_image_gone": ENV_IMG_OLD not in text_e},
            "acceptance": {"image": ACC_IMG_NEW.strip() in text_a, "fp": ACC_FP_NEW.strip() in text_a, "render": ACC_RENDER_NEW.strip() in text_a, "jq_kv": JQ_LINES.splitlines()[0].strip() in text_a},
            "service": {"fp": SVC_FP_NEW.strip() in text_s},
        }, indent=2))
        return
    else:
        raise SystemExit(json.dumps({"error": f"unknown subcommand {cmd}"}))
    print(json.dumps({"cmd": cmd, "root": root, "results": results}, indent=2))


if __name__ == "__main__":
    main()
