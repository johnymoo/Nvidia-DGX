#!/usr/bin/env bash
# Step driver for the DeepSeek-V4.1-Flash EXL3 validation window (policy
# 2026-09-17: DS stays DOWN through boot retries; restore only after benches).
# Same shape as the GLM-5.3 window (execution/glm53-eval/window-step.sh).
#
#   window-step.sh up        ensure DS stopped -> boot ds41 (retry-friendly:
#                            on boot failure leave everything for the next
#                            attempt) -> run all benchmarks -> STOP and wait.
#   window-step.sh restore   stop ds41 -> restore DS via official script -> verify.
#   window-step.sh status    current results dir, state, last log lines.
set -uo pipefail

EVAL_ROOT="$HOME/dsv41-eval"
REPO="$EVAL_ROOT/DeepSeek-v4.1-Flash-EXL3-2x-DGX-Sparks"
BIN="$EVAL_ROOT/bin"
WORKER_SSH="${WORKER_SSH:-worker@192.0.2.21}"
DS_STOP_SCRIPT="/opt/dspark-vision/stop-deepseek-v4-flash-dspark.sh"
DS_START_SCRIPT="/opt/dspark-vision/start-deepseek-v4-flash-dspark.sh"
DS_BASE="http://127.0.0.1:8890"
DS_MODEL="deepseek-v4-flash-0731"
DS41_PORT="18890"
DS41_BASE="http://127.0.0.1:${DS41_PORT}"
DS41_MODEL="DeepSeek-v4.1-Flash-EXL3"
DS41_THINK_OFF='{"enable_thinking": false}'
CACHE_ROOT="$HOME/.cache/vllm-dsv41-flash-exl3"

mkdir -p "$EVAL_ROOT/results"
log()  { printf '[step %s] %s\n' "$(date +%H:%M:%S)" "$*"; }
mem_mb(){ awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo; }
ds41_health(){ curl -fsS -m 5 "$DS41_BASE/health" >/dev/null 2>&1; }
ds_health(){ curl -fsS -m 5 "$DS_BASE/health" >/dev/null 2>&1; }

latest_res() { ls -td "$EVAL_ROOT"/results/*/ 2>/dev/null | head -1; }

wait_ds_healthy() {
    local deadline=$((SECONDS + ${1:-1500}))
    while [ $SECONDS -lt $deadline ]; do
        ds_health && { log "DS healthy"; return 0; }
        sleep 10
    done
    return 1
}

fix_cache_perms() {
    # Prior docker preps left root-owned vLLM caches before; launchers
    # (the launcher user locally and over ssh) must be able to write their caches.
    if [ -d "$CACHE_ROOT" ] && [ ! -w "$CACHE_ROOT" ]; then
        log "fixing root-owned $CACHE_ROOT via docker chown"
        docker run --rm --entrypoint chown -v "$CACHE_ROOT:/fix" python:3.11-slim -R "$(id -u):$(id -g)" /fix || return 1
    fi
    mkdir -p "$CACHE_ROOT/triton" "$CACHE_ROOT/tilelang" 2>/dev/null || mkdir -p "$CACHE_ROOT" || return 1
    log "head cache dirs OK ($(ls -ld "$CACHE_ROOT" | awk '{print $1, $3}'))"
    if ! ssh -o BatchMode=yes "$WORKER_SSH" "mkdir -p ~/.cache/vllm-dsv41-flash-exl3" 2>/dev/null; then
        log "fixing root-owned worker cache via docker chown"
        ssh -o BatchMode=yes "$WORKER_SSH" \
            "docker run --rm --entrypoint chown -v \$HOME/.cache/vllm-dsv41-flash-exl3:/fix ghcr.io/anemll/dspark-vllm-gx10:0.1.1 -R \$(id -u):\$(id -g) /fix" || return 1
        ssh -o BatchMode=yes "$WORKER_SSH" "mkdir -p ~/.cache/vllm-dsv41-flash-exl3" || return 1
    fi
    log "worker cache dirs OK"
}

do_stop_ds() {
    if ds_health; then
        log "stopping DS (official script: worker then head)"
        if ! bash "$DS_STOP_SCRIPT" >>"$EVAL_ROOT/results/ds-stop.log" 2>&1; then
            log "FATAL: DS stop script failed"; return 1
        fi
        local deadline=$((SECONDS + 240))
        while ds_health; do
            if [ $SECONDS -gt $deadline ]; then log "FATAL: DS still answering after stop"; return 1; fi
            sleep 5
        done
    else
        log "DS already down - reusing window"
    fi
    log "DS stopped; MemAvailable=$(mem_mb)MB"
    return 0
}

do_stop_ds41() {
    ( cd "$REPO" && ./start.sh stop ) >>"$EVAL_ROOT/results/ds41-stop.log" 2>&1 || true
    docker rm -f dsv41-exl3-head >/dev/null 2>&1 || true
    ssh -o BatchMode=yes "$WORKER_SSH" "docker rm -f dsv41-exl3-worker" >/dev/null 2>&1 || true
}

collect_ds41_logs() {
    local res="$1"
    docker logs dsv41-exl3-head >"$res/ds41-head.log" 2>&1 || true
    ssh -o BatchMode=yes "$WORKER_SSH" "docker logs dsv41-exl3-worker" >"$res/ds41-worker.log" 2>&1 || true
    docker ps -a --format '{{.Names}}\t{{.Status}}' >"$res/containers.txt"
    tail -n 40 "$REPO/logs/hang-head-pyspy.txt" 2>/dev/null >"$res/hang-tail.txt" || true
}

run_bench() {
    local res="$1" name="$2"; shift 2
    ds41_health || { log "ds41 unhealthy before $name - aborting benches"; return 1; }
    log "bench: $name"
    if "$@" >"$res/$name.out" 2>&1; then
        log "bench OK: $name"
    else
        log "bench FAILED: $name (rc=$?)"
    fi
    ds41_health || { log "ds41 unhealthy after $name"; return 1; }
    return 0
}

cmd_up() {
    local res="$EVAL_ROOT/results/$(date +%Y%m%dT%H%M%SZ)"
    mkdir -p "$res"
    ln -sfn "$res" "$EVAL_ROOT/latest"
    exec > >(tee -a "$res/window.log") 2>&1
    state() { printf '%s\n' "$1" > "$res/state.txt"; log "STATE=$1"; }

    state "preflight"
    for f in bench_decode_18890.py bench_concurrent.py bench_prefill_ladder.py vision_ds41_runner.py vision_compare.py summarize_ds41.py; do
        [ -f "$BIN/$f" ] || { log "missing $BIN/$f"; exit 1; }
    done
    [ -f "$EVAL_ROOT/assets/week36-menu.png" ] || { log "missing menu image"; exit 1; }
    fix_cache_perms || { log "FATAL: cannot fix cache perms"; exit 1; }

    # SKIP_SYNC=1 skips prepare_engram_src_dir inside start.sh; the head binds
    # ~/.cache/vllm-dsv41-flash-exl3/engram-src, so build the slim src here.
    ENG_SRC="$HOME/.cache/vllm-dsv41-flash-exl3/engram-src"
    if [ ! -f "$ENG_SRC/config.json" ]; then
        log "building slim engram src (SKIP_SYNC bypass)"
        ( cd "$REPO" && python3 scripts/prepare_engram_src.py --src "$REPO/engram-src" --dst "$ENG_SRC" ) \
            || { log "FATAL: prepare_engram_src failed"; exit 1; }
    fi

    state "ds_stopping"
    do_stop_ds || { state "ds_stop_failed"; exit 1; }

    # stale ds41 containers from a crashed run: the worker rank can outlive a
    # dead head and pin ~112 GiB, tripping the boot margin check
    docker rm -f dsv41-exl3-head >/dev/null 2>&1 || true
    ssh -o BatchMode=yes "$WORKER_SSH" "docker rm -f dsv41-exl3-worker" >/dev/null 2>&1 || true

    state "ds41_booting"
    local boot_t0=$(date +%s)
    if ! ( cd "$REPO" && SKIP_PULL=1 SKIP_BUILD=1 SKIP_DOWNLOAD=1 SKIP_SYNC=1 ./start.sh ) >"$res/ds41-start.out" 2>&1; then
        log "ds41 start.sh failed - leaving DS down for diagnosis/retry (policy 2026-09-17)"
        collect_ds41_logs "$res"
        tail -30 "$res/ds41-head.log" 2>/dev/null || tail -30 "$res/ds41-start.out"
        state "boot_failed"
        exit 1
    fi
    local boot_secs=$(( $(date +%s) - boot_t0 ))
    printf 'boot_secs=%s\n' "$boot_secs" > "$res/boot.txt"
    docker logs dsv41-exl3-head 2>&1 | grep -a -iE "KV cache size|GPU KV cache|max concurrency|fp8_ds_mla" | tail -6 > "$res/kv-pool.txt" || true
    curl -s -m 10 "$DS41_BASE/v1/models" > "$res/ds41-models.json" || true
    log "ds41 healthy (boot ${boot_secs}s)"

    state "benching"
    local failed=0
    run_bench "$res" decode_structured_c1 python3 "$BIN/bench_decode_18890.py" --phase structured --structured --runs 5 --max-tokens 400 --skip-coherence --out "$res/decode-structured.json" || failed=1
    if [ "$failed" = "0" ]; then
        run_bench "$res" decode_prose_c1 python3 "$BIN/bench_decode_18890.py" --phase prose --runs 5 --max-tokens 400 --out "$res/decode-prose.json" || failed=1
    fi
    if [ "$failed" = "0" ]; then
        run_bench "$res" concurrent_structured_c2 python3 "$BIN/bench_concurrent.py" --base "$DS41_BASE" --model "$DS41_MODEL" --thinking-kwargs "$DS41_THINK_OFF" --out "$res/conc-struct-c2.json" --prompt structured --concurrency 2 --runs 3 || true
        run_bench "$res" concurrent_structured_c4 python3 "$BIN/bench_concurrent.py" --base "$DS41_BASE" --model "$DS41_MODEL" --thinking-kwargs "$DS41_THINK_OFF" --out "$res/conc-struct-c4.json" --prompt structured --concurrency 4 --runs 3 || true
        run_bench "$res" concurrent_prose_c2 python3 "$BIN/bench_concurrent.py" --base "$DS41_BASE" --model "$DS41_MODEL" --thinking-kwargs "$DS41_THINK_OFF" --out "$res/conc-prose-c2.json" --prompt prose --concurrency 2 --runs 3 || true
        run_bench "$res" concurrent_prose_c4 python3 "$BIN/bench_concurrent.py" --base "$DS41_BASE" --model "$DS41_MODEL" --thinking-kwargs "$DS41_THINK_OFF" --out "$res/conc-prose-c4.json" --prompt prose --concurrency 4 --runs 3 || true
    fi
    if [ "$failed" = "0" ]; then
        run_bench "$res" prefill_ladder python3 "$BIN/bench_prefill_ladder.py" --base "$DS41_BASE" --model "$DS41_MODEL" --thinking-kwargs "$DS41_THINK_OFF" --out "$res/prefill-ladder.json" --rungs 8,16,32,64,128,256 --repeats 2 || failed=1
    fi
    if [ "$failed" = "0" ]; then
        run_bench "$res" vision_suite python3 "$BIN/vision_ds41_runner.py" --vision-compare "$BIN/vision_compare.py" --menu-image "$EVAL_ROOT/assets/week36-menu.png" --base "$DS41_BASE" --model "$DS41_MODEL" --output "$res/vision.json" || failed=1
    fi

    collect_ds41_logs "$res"
    { free -g; echo ---; docker ps --format '{{.Names}}\t{{.Status}}'; printf 'mem_available_mb=%s\n' "$(mem_mb)"; } > "$res/host-after-bench.txt"

    if [ "$failed" = "1" ] && ! ds41_health; then
        state "bench_failed"
        log "ds41 died during benches - DS stays down; diagnose then rerun 'up' or call 'restore'"
        python3 "$BIN/summarize_ds41.py" "$res" || true
        exit 2
    fi

    state "benched"
    python3 "$BIN/summarize_ds41.py" "$res" || true
    if [ -n "${X570_SSH:-}" ]; then
        log "running hermes ds41 leg (best-effort)"
        if ssh -o BatchMode=yes "$X570_SSH" 'HERMES_BIN=$HOME/glm53-hermes/hermes-venv bash ~/glm53-hermes/run-hermes-real-tasks-ds41.sh --treatment ds41' >"$res/hermes-ds41-leg.out" 2>&1; then
            log "hermes ds41 leg OK"
        else
            log "hermes ds41 leg FAILED (recorded; non-blocking)"
        fi
    else
        log "X570_SSH not set - skipping in-window hermes leg (drive externally)"
    fi
    log "BENCHMARKS COMPLETE - ds41 left running; call 'restore' when ready to bring DS back"
}

cmd_restore() {
    local res
    res="$(latest_res)"
    mkdir -p "$res"
    exec > >(tee -a "$res/restore.log") 2>&1
    state() { printf '%s\n' "$1" > "$res/state.txt"; log "STATE=$1"; }
    state "restoring_ds"
    log "stopping ds41"
    do_stop_ds41
    ds41_health && { log "WARN: ds41 API still up"; }
    log "starting DS"
    bash "$DS_START_SCRIPT" >>"$res/ds-restore.log" 2>&1 || log "start script rc=$? - verifying ourselves"
    if wait_ds_healthy 1500; then
        curl -s -m 10 "$DS_BASE/v1/models" > "$res/ds-models-after.json" 2>&1 || true
        local smoke
        smoke="$(curl -s -m 120 "$DS_BASE/v1/chat/completions" -H 'Content-Type: application/json' \
            -d "{\"model\":\"$DS_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"1+1=? Reply with just the number.\"}],\"max_tokens\":16,\"chat_template_kwargs\":{\"thinking\":false}}" || true)"
        printf '%s\n' "$smoke" > "$res/ds-smoke-after.json"
        if printf '%s' "$smoke" | grep -q '"2"'; then
            log "DS restored AND smoke OK (1+1=2)"
        else
            log "WARN: DS healthy but smoke unexpected (recorded)"
        fi
        state "done"
    else
        state "restore_failed"
        log "FATAL: DS did not become healthy - human attention required"
        exit 1
    fi
}

cmd_status() {
    local res
    res="$(latest_res)"
    echo "RES=$res"
    cat "$res/state.txt" 2>/dev/null
    echo "--- window.log tail ---"
    tail -n 12 "$res/window.log" 2>/dev/null
    echo "--- restore.log tail ---"
    tail -n 6 "$res/restore.log" 2>/dev/null
    echo "--- ds41 api ---"
    ds41_health && echo up || echo down
    echo "--- ds api ---"
    ds_health && echo up || echo down
}

case "${1:-status}" in
    up)      cmd_up ;;
    restore) cmd_restore ;;
    status)  cmd_status ;;
    *) echo "usage: $0 {up|restore|status}" >&2; exit 2 ;;
esac
