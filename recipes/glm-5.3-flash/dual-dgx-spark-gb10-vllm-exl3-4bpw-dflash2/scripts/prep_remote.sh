#!/usr/bin/env bash
# Runs on the head node as the deploying user. Idempotent prep for the GLM-5.3 window.
# Subcommands: verify | pull-images | sync-weights | stamp-check | all
# Deliberately memory-light: docker pulls + rsync only. The exllamav3/E3 compile
# runs inside the window after DS is stopped (host has ~5G MemAvailable now; nvcc
# could OOM the production rank).
set -euo pipefail

EVAL_ROOT="$HOME/glm53-eval"
REPO="$EVAL_ROOT/GLM-5.3-Flash-EXL3-2x-DGX-Sparks"
WORKER_SSH="${WORKER_SSH:-worker@192.0.2.21}"
HF_HUB="$HOME/.cache/huggingface/hub"
GLM_DIR="$HF_HUB/models--Mia-AiLab--GLM-5.3-Flash-EXL3-TR3-4bpw"
DF_DIR="$HF_HUB/models--incoai--GLM-5.3-Flash-DFlash2"
DF_REV="dc77ff1c99eeb2df044ee3d4f0094eb033fee410"
STATUS="$EVAL_ROOT/prep-status"
BASE_IMG="vllm/vllm-openai:glm53-flash-arm64-cu130@sha256:905c02933be6021301db2dc284e24e3727467aa3a0f63b41d609885778a07bce"
FALLBACK_IMG="ghcr.io/miaai-lab/glm-5.3-flash-2x-dgx-sparks:exl3"

log() { printf '[prep %s] %s\n' "$(date +%H:%M:%S)" "$*"; }

verify() {
    local fail=0
    [ -d "$REPO" ] && log "repo present" || { log "FAIL repo missing at $REPO"; fail=1; }
    [ -f "$REPO/.env" ] && log ".env present" || { log "FAIL .env missing"; fail=1; }

    local rev snap shards
    rev="$(cat "$GLM_DIR/refs/main" 2>/dev/null || true)"
    if [ -n "$rev" ]; then
        snap="$GLM_DIR/snapshots/$rev"
        shards="$(find -L "$snap" -maxdepth 1 -name '*.safetensors' 2>/dev/null | wc -l | tr -d ' ')"
        if [ -f "$snap/config.json" ] && [ "$shards" -ge 120 ]; then
            log "GLM weights OK: snapshot $rev, $shards shards + config.json"
        else
            log "FAIL GLM weights incomplete: rev=$rev shards=$shards config=$([ -f "$snap/config.json" ] && echo y || echo n)"
            fail=1
        fi
    else
        log "FAIL GLM refs/main empty"; fail=1
    fi

    if [ -f "$DF_DIR/snapshots/$DF_REV/model.safetensors" ]; then
        log "DFlash2 OK: $DF_REV"
    else
        log "FAIL DFlash2 snapshot $DF_REV missing"; fail=1
    fi

    local g
    g="$(cat /sys/class/infiniband/rocep1s0f0/ports/1/gids/3 2>/dev/null || true)"
    [[ "$g" == *c0a8:c0b5* ]] && log "head GID3 = $g (fabric IP)" || { log "FAIL head GID3=$g"; fail=1; }
    g="$(ssh -o BatchMode=yes "$WORKER_SSH" "cat /sys/class/infiniband/rocep1s0f0/ports/1/gids/3" 2>/dev/null || true)"
    [[ "$g" == *c0a8:c0c6* ]] && log "worker GID3 = $g (fabric IP)" || { log "FAIL worker GID3=$g"; fail=1; }

    if ss -tln 2>/dev/null | grep -q ":18888 "; then log "FAIL port 18888 busy"; fail=1; else log "port 18888 free"; fi
    if ss -tln 2>/dev/null | grep -q ":29521 "; then log "FAIL port 29521 busy"; fail=1; else log "port 29521 free"; fi

    ssh -o BatchMode=yes "$WORKER_SSH" "mkdir -p ~/.cache/huggingface/hub" \
        && log "worker hub dir writable" || { log "FAIL worker hub mkdir"; fail=1; }

    local dh dw
    dh="$(df -Pk "$HOME" | awk 'NR==2{print $4}')"
    dw="$(ssh -o BatchMode=yes "$WORKER_SSH" "df -Pk \$HOME" | awk 'NR==2{print $4}')"
    log "disk free: head $((dh/1024/1024))G worker $((dw/1024/1024))G"

    if [ "$fail" = "1" ]; then log "VERIFY FAILED"; exit 1; fi
    log "VERIFY OK"
    printf 'verified %s\n' "$(date -Is)" > "$STATUS/verify.ok"
}

pull_images() {
    log "pulling fallback GHCR image (also stages base layers)..."
    docker pull "$FALLBACK_IMG" >>"$STATUS/pull.log" 2>&1 || log "WARN fallback pull failed (non-fatal; only needed if local build fails)"
    log "pulling build base image..."
    docker pull "$BASE_IMG" >>"$STATUS/pull.log" 2>&1 || { log "FAIL base image pull"; exit 1; }
    log "images pulled"
    printf 'pulled %s\n' "$(date -Is)" > "$STATUS/pull.ok"
}

sync_weights() {
    local rev marker
    mkdir -p "$STATUS"
    rev="$(cat "$GLM_DIR/refs/main")"
    marker=".glm53-exl3-synced"

    log "rsync GLM weights ($rev) to worker over CX7..."
    ssh -o BatchMode=yes "$WORKER_SSH" "mkdir -p .cache/huggingface/hub/models--Mia-AiLab--GLM-5.3-Flash-EXL3-TR3-4bpw"
    # shellcheck disable=SC2086
    if rsync -a --partial --info=progress2 -e "ssh -o BatchMode=yes" \
        "$GLM_DIR/" \
        "$WORKER_SSH:.cache/huggingface/hub/models--Mia-AiLab--GLM-5.3-Flash-EXL3-TR3-4bpw/" \
        >>"$STATUS/rsync.log" 2>&1; then
        ssh -o BatchMode=yes "$WORKER_SSH" "printf '%s' '$rev' > .cache/huggingface/hub/models--Mia-AiLab--GLM-5.3-Flash-EXL3-TR3-4bpw/$marker"
        log "GLM weights synced + marker written"
    else
        log "FAIL GLM rsync (see $STATUS/rsync.log)"; exit 1
    fi

    log "rsync DFlash2..."
    ssh -o BatchMode=yes "$WORKER_SSH" "mkdir -p .cache/huggingface/hub/models--incoai--GLM-5.3-Flash-DFlash2"
    if rsync -a --partial --info=progress2 -e "ssh -o BatchMode=yes" \
        "$DF_DIR/" \
        "$WORKER_SSH:.cache/huggingface/hub/models--incoai--GLM-5.3-Flash-DFlash2/" \
        >>"$STATUS/rsync.log" 2>&1; then
        ssh -o BatchMode=yes "$WORKER_SSH" "printf '%s' '$DF_REV' > .cache/huggingface/hub/models--incoai--GLM-5.3-Flash-DFlash2/$marker"
        log "DFlash2 synced + marker written"
    else
        log "FAIL DFlash2 rsync"; exit 1
    fi
    printf 'synced %s\n' "$(date -Is)" > "$STATUS/sync.ok"
}

stamp_check() {
    # Sourcing the sed-stripped lib keeps SCRIPT_DIR = repo (lib lives inside it).
    local lib="$REPO/.glm53-lib.sh"
    [ -f "$lib" ] || sed '$d' "$REPO/start.sh" > "$lib"
    IMAGE="glm53-flash-sm121:local" bash -c "\
        source '$lib' >/dev/null 2>&1 || true
        want=\$(overlay_recipe_hash)
        have=\$(image_recipe_stamp)
        echo \"stamp_have=\$have\"
        echo \"stamp_want=\$want\"
        [ -n \"\$have\" ] && [ \"\$have\" = \"\$want\" ] && echo STAMP_MATCH || echo STAMP_DRIFT"
}

case "${1:-all}" in
    verify)       verify ;;
    pull-images)  mkdir -p "$STATUS"; pull_images ;;
    sync-weights) mkdir -p "$STATUS"; sync_weights ;;
    stamp-check)  stamp_check ;;
    all)
        mkdir -p "$STATUS"
        verify
        nohup bash "$0" pull-images  >"$STATUS/pull.out" 2>&1 &
        nohup bash "$0" sync-weights >"$STATUS/sync.out" 2>&1 &
        log "background jobs started: pull-images + sync-weights (poll $STATUS/*.ok)"
        ;;
    *) echo "usage: $0 {verify|pull-images|sync-weights|stamp-check|all}" >&2; exit 2 ;;
esac
