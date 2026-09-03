#!/usr/bin/env bash
# Phase B (NVMe tier) deployment edits — apply | rollback | verify
#
# Usage:  apply-phase-b-edits.sh <TAG> <apply|rollback|verify> <head|worker>
#
# Prereqs on BOTH hosts before apply:
#   ~/phase-b-nvme/vllm_nvme_tier/*.py            (the package)
#   ~/phase-b-nvme/overlay/vllm/distributed/kv_transfer/kv_connector/v1/offloading/{common,scheduler,worker}.py
#   <service-root>/kv-offload-tier/               (empty dir; per-rank subdirs are created by the spec)
#
# Edits (with .bak-<TAG> backups of every touched file):
#   docker-compose.yml             KV line + 5 volumes + PYTHONHASHSEED/PYTHONPATH
#   docker-compose.thinking-on.yml KV line only (command override fragment)
#   env/common.env                 KV_OFFLOAD_NVME_BYTES=137438953472
#   run-vllm-acceptance.sh         jq conjuncts (HEAD only)
#
# Apply is idempotent (no-op when the KV line is already present).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # .../gb10-ds4/execution
cd "$SCRIPT_DIR"
SERVICE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"                 # .../gb10-ds4
TAG="$1"; MODE="$2"; ROLE="${3:-head}"
PKG_DIR="$HOME/phase-b-nvme"
TIER_DIR="$SERVICE_ROOT/kv-offload-tier"
OVERLAY_REL="overlay/vllm/distributed/kv_transfer/kv_connector/v1/offloading"
IMG_OFFLOAD_DIR="/opt/env/lib/python3.12/site-packages/vllm/distributed/kv_transfer/kv_connector/v1/offloading"

ALL_FILES=("$SCRIPT_DIR/docker-compose.yml" \
           "$SCRIPT_DIR/docker-compose.thinking-on.yml" \
           "$SCRIPT_DIR/env/common.env")

backup() { cp -p "$1" "$1.bak-$TAG"; }
restore() {
  if [ -f "$1.bak-$TAG" ]; then cp -p "$1.bak-$TAG" "$1"; echo "restored $1";
  else echo "no backup for $1"; fi
}

apply_edits() {
  PKG_DIR="$PKG_DIR" TIER_DIR="$TIER_DIR" \
  OVERLAY_REL="$OVERLAY_REL" IMG_OFFLOAD_DIR="$IMG_OFFLOAD_DIR" \
  ROLE="$ROLE" python3 <<'PYEOF'
import os, sys

kv_line = (
    "        --kv-transfer-config "
    '\'{"kv_connector":"OffloadingConnector","kv_role":"kv_both",'
    '"kv_load_failure_policy":"recompute","kv_connector_extra_config":'
    '{"spec_name":"NVMeTieredOffloadingSpec","spec_module_path":"vllm_nvme_tier.spec",'
    '"nvme_bytes_to_use":${KV_OFFLOAD_NVME_BYTES:-343597383680},'
    '"nvme_root_dir":"/kv-tier/offload","staging_ring_bytes":3221225472}}\''
)
pkg = os.environ["PKG_DIR"]
tier = os.environ["TIER_DIR"]
orel = os.environ["OVERLAY_REL"]
imgd = os.environ["IMG_OFFLOAD_DIR"]
role = os.environ["ROLE"]
exec_dir = os.getcwd()

volume_lines = [f"      - {pkg}:/opt/kv-tier:ro"] + [
    f"      - {pkg}/{orel}/{f}:{imgd}/{f}:ro"
    for f in ("common.py", "scheduler.py", "worker.py")
] + [f"      - {tier}:/kv-tier"]

def insert_after(lines, anchor, additions):
    for i, ln in enumerate(lines):
        if anchor in ln:
            return lines[:i + 1] + additions + lines[i + 1:]
    raise SystemExit(f"anchor not found: {anchor[:60]!r}")

def edit_compose(path, is_main):
    with open(path) as f:
        lines = f.readlines()
    if any("--kv-transfer-config" in ln for ln in lines):
        print(f"skip (already applied): {path}")
        return
    lines = insert_after(lines, "--reasoning-config", [kv_line + "\n"])
    if is_main:
        lines = insert_after(lines, "CACHE_ROOT:?set CACHE_ROOT",
                             [l + "\n" for l in volume_lines])
        lines = insert_after(
            lines, "MTP_NUM_TOKENS:",
            ['      PYTHONHASHSEED: "0"\n', "      PYTHONPATH: /opt/kv-tier\n"])
    with open(path, "w") as f:
        f.writelines(lines)
    print(f"edited {path}")

edit_compose(os.path.join(exec_dir, "docker-compose.yml"), True)
edit_compose(os.path.join(exec_dir, "docker-compose.thinking-on.yml"), False)

envp = os.path.join(exec_dir, "env", "common.env")
with open(envp) as f:
    src = f.read()
if "KV_OFFLOAD_NVME_BYTES=" not in src:
    if src and not src.endswith("\n"):
        src += "\n"
    src += "KV_OFFLOAD_NVME_BYTES=343597383680\n"
    with open(envp, "w") as f:
        f.write(src)
    print(f"appended KV_OFFLOAD_NVME_BYTES to {envp}")

if role == "head":
    acc = os.path.join(exec_dir, "run-vllm-acceptance.sh")
    with open(acc) as f:
        src = f.read()
    if '--kv-transfer-config' not in src:
        anchor = None
        for cand in ('      and ($c | contains("{\\"thinking\\":" + $thinking + "}"))\n',):
            if cand in src:
                anchor = cand
                break
        assert anchor, "acceptance anchor not found"
        add = ('      and ($c | contains("--kv-transfer-config"))\n'
               '      and ($c | contains("OffloadingConnector"))\n'
               '      and ($c | contains("NVMeTieredOffloadingSpec"))\n'
               '      and ($c | contains("recompute"))\n')
        src = src.replace(anchor, anchor + add, 1)
        with open(acc, "w") as f:
            f.write(src)
        print(f"edited {acc}")
PYEOF
  mkdir -p "$TIER_DIR"
}

case "$MODE" in
  apply)
    for f in "${ALL_FILES[@]}"; do backup "$f"; done
    [ "$ROLE" = head ] && backup "$SCRIPT_DIR/run-vllm-acceptance.sh"
    apply_edits
    echo "APPLIED tag=$TAG role=$ROLE"
    ;;
  rollback)
    for f in "${ALL_FILES[@]}"; do restore "$f"; done
    [ "$ROLE" = head ] && restore "$SCRIPT_DIR/run-vllm-acceptance.sh"
    echo "ROLLED BACK tag=$TAG"
    ;;
  verify)
    # Render the FULL production chain exactly as run-vllm-acceptance.sh does.
    render=$(docker compose \
      --env-file "$SCRIPT_DIR/env/common.env" --env-file "$SCRIPT_DIR/env/node.env" \
      -f "$SCRIPT_DIR/docker-compose.yml" \
      -f "$SCRIPT_DIR/docker-compose.f277b3d-timeout.yml" \
      -f "$SCRIPT_DIR/docker-compose.thinking-on.yml" \
      config 2>&1) || { echo "RENDER FAILED"; echo "$render"; exit 1; }
    for pat in "--kv-transfer-config" "OffloadingConnector" "NVMeTieredOffloadingSpec" "PYTHONHASHSEED" "PYTHONPATH: /opt/kv-tier" "target: /opt/kv-tier" "/kv-tier/offload" "target: /kv-tier"; do
      n=$(echo "$render" | grep -c -- "$pat" || true)
      echo "  [$n] $pat"
    done
    [ -d "$PKG_DIR/vllm_nvme_tier" ] && echo "pkg dir OK" || echo "PKG DIR MISSING"
    [ -d "$TIER_DIR" ] && echo "tier dir OK" || echo "TIER DIR MISSING"
    for f in common.py scheduler.py worker.py; do
      [ -f "$PKG_DIR/$OVERLAY_REL/$f" ] || echo "OVERLAY MISSING: $f"
    done
    ;;
  *) echo "usage: $0 <TAG> <apply|rollback|verify> <head|worker>"; exit 2;;
esac
