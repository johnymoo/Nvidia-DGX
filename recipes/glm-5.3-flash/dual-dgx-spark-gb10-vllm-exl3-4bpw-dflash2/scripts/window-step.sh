#!/usr/bin/env bash
# Step driver for the GLM-5.3 validation window (policy 2026-09-10: DS stays
# DOWN through repeated GLM boot attempts; restore only after benches finish).
#
#   window-step.sh up        ensure DS stopped -> boot GLM (retry-friendly:
#                            on boot failure leave everything for the next
#                            attempt) -> run all benchmarks -> STOP and wait.
#   window-step.sh restore   stop GLM -> restore DS via official script -> verify.
#   window-step.sh status    current results dir, state, last log lines.
set -uo pipefail

EVAL_ROOT="$HOME/glm53-eval"
REPO="$EVAL_ROOT/GLM-5.3-Flash-EXL3-2x-DGX-Sparks"
BIN="$EVAL_ROOT/bin"
WORKER_SSH="${WORKER_SSH:-worker@192.0.2.21}"
DS_STOP_SCRIPT="${DS_STOP_SCRIPT:-/opt/dspark-vision/stop-deepseek-v4-flash-dspark.sh}"
DS_START_SCRIPT="${DS_START_SCRIPT:-/opt/dspark-vision/start-deepseek-v4-flash-dspark.sh}"
DS_BASE="http://127.0.0.1:8890"
DS_MODEL="deepseek-v4-flash-0731"
GLM_PORT="18888"
GLM_BASE="http://127.0.0.1:${GLM_PORT}"
CACHE_ROOT="$HOME/.cache/vllm-glm53-flash"

mkdir -p "$EVAL_ROOT/results"
log()  { printf '[step %s] %s\n' "$(date +%H:%M:%S)" "$*"; }
mem_mb(){ awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo; }
glm_health(){ curl -fsS -m 5 "$GLM_BASE/health" >/dev/null 2>&1; }
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
    # Aug-30 experiment left root-owned ~/.cache/vllm-glm53-flash on BOTH hosts;
    # launchers (local user and the worker user over ssh) must create triton/ + tilelang/
    # inside it. Docker chown, no sudo.
    if [ -d "$CACHE_ROOT" ] && [ ! -w "$CACHE_ROOT" ]; then
        log "fixing root-owned $CACHE_ROOT via docker chown"
        docker run --rm --entrypoint chown -v "$CACHE_ROOT:/fix" python:3.11-slim -R "$(id -u):$(id -g)" /fix || return 1
    fi
    mkdir -p "$CACHE_ROOT/triton" "$CACHE_ROOT/tilelang" || return 1
    log "head cache dirs OK ($(ls -ld "$CACHE_ROOT" | awk '{print $1, $3}'))"
    if ! ssh -o BatchMode=yes "$WORKER_SSH" "mkdir -p ~/.cache/vllm-glm53-flash/triton ~/.cache/vllm-glm53-flash/tilelang" 2>/dev/null; then
        log "fixing root-owned worker cache via docker chown"
        ssh -o BatchMode=yes "$WORKER_SSH" \
            "docker run --rm --entrypoint chown -v \$HOME/.cache/vllm-glm53-flash:/fix ghcr.io/anemll/dspark-vllm-gx10:0.1.1 -R \$(id -u):\$(id -g) /fix" || return 1
        ssh -o BatchMode=yes "$WORKER_SSH" "mkdir -p ~/.cache/vllm-glm53-flash/triton ~/.cache/vllm-glm53-flash/tilelang" || return 1
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

do_stop_glm() {
    ( cd "$REPO" && ./start.sh stop ) >>"$EVAL_ROOT/results/glm-stop.log" 2>&1 || true
    docker rm -f glm53-exl3-head >/dev/null 2>&1 || true
    ssh -o BatchMode=yes "$WORKER_SSH" "docker rm -f glm53-exl3-worker" >/dev/null 2>&1 || true
}

collect_glm_logs() {
    local res="$1"
    docker logs glm53-exl3-head >"$res/glm-head.log" 2>&1 || true
    ssh -o BatchMode=yes "$WORKER_SSH" "docker logs glm53-exl3-worker" >"$res/glm-worker.log" 2>&1 || true
    docker ps -a --format '{{.Names}}\t{{.Status}}' >"$res/containers.txt"
    tail -n 40 "$REPO/logs/build-sm121.log" 2>/dev/null | tr '\r' '\n' >"$res/build-tail.txt" || true
}

run_bench() {
    local res="$1" name="$2"; shift 2
    glm_health || { log "GLM unhealthy before $name - aborting benches"; return 1; }
    log "bench: $name"
    if "$@" >"$res/$name.out" 2>&1; then
        log "bench OK: $name"
    else
        log "bench FAILED: $name (rc=$?)"
    fi
    glm_health || { log "GLM unhealthy after $name"; return 1; }
    return 0
}

cmd_up() {
    local res="$EVAL_ROOT/results/$(date +%Y%m%dT%H%M%SZ)"
    mkdir -p "$res"
    ln -sfn "$res" "$EVAL_ROOT/latest"
    exec > >(tee -a "$res/window.log") 2>&1
    state() { printf '%s\n' "$1" > "$res/state.txt"; log "STATE=$1"; }

    state "preflight"
    for f in bench_decode_18888.py bench_concurrent.py bench_prefill_ladder.py vision_glm_runner.py vision_compare.py; do
        [ -f "$BIN/$f" ] || { log "missing $BIN/$f"; exit 1; }
    done
    [ -f "$EVAL_ROOT/assets/week36-menu.png" ] || { log "missing menu image"; exit 1; }
    fix_cache_perms || { log "FATAL: cannot fix cache perms"; exit 1; }

    state "ds_stopping"
    do_stop_ds || { state "ds_stop_failed"; exit 1; }

    state "glm_booting"
    local boot_t0=$(date +%s)
    if ! ( cd "$REPO" && SKIP_PULL=1 SKIP_DOWNLOAD=1 SKIP_SYNC=1 ./start.sh ) >"$res/glm-start.out" 2>&1; then
        log "GLM start.sh failed - leaving DS down for diagnosis/retry (policy 2026-09-10)"
        collect_glm_logs "$res"
        tail -30 "$res/glm-head.log" 2>/dev/null || tail -30 "$res/glm-start.out"
        state "boot_failed"
        exit 1
    fi
    local boot_secs=$(( $(date +%s) - boot_t0 ))
    printf 'boot_secs=%s\n' "$boot_secs" > "$res/boot.txt"
    docker logs glm53-exl3-head 2>&1 | grep -a -iE "KV cache size|GPU KV cache|Maximum concurrency|max concurrency" | tail -6 > "$res/kv-pool.txt" || true
    curl -s -m 10 "$GLM_BASE/v1/models" > "$res/glm-models.json" || true
    log "GLM healthy (boot ${boot_secs}s)"

    if [ "${SKIP_SYNTH:-0}" = "1" ]; then
        log "SKIP_SYNTH=1 - jumping straight to hermes tasks"
        state "benching"
        local failed=0
        if [ -n "${X570_SSH:-}" ]; then
            run_bench "$res" hermes_tasks_glm ssh -o BatchMode=yes "$X570_SSH" 'HERMES_BIN=$HOME/glm53-hermes/hermes-venv bash ~/glm53-hermes/run-hermes-real-tasks.sh --treatment glm' || failed=1
        else
            log "X570_SSH not set - skipping in-window glm leg (drive externally)"
        fi
        collect_glm_logs "$res"
        if [ "$failed" = "1" ] && ! glm_health; then
            state "bench_failed"; python3 "$BIN/summarize.py" "$res" || true; exit 2
        fi
        state "benched"
        log "hermes GLM leg done; call 'restore' when ready to bring DS back"
        return 0
    fi

    state "benching"
    local failed=0
    run_bench "$res" decode_structured_c1 python3 "$BIN/bench_decode_18888.py" --phase structured --structured --runs 5 --max-tokens 400 --skip-coherence --out "$res/decode-structured.json" || failed=1
    if [ "$failed" = "0" ]; then
        run_bench "$res" decode_prose_c1 python3 "$BIN/bench_decode_18888.py" --phase prose --runs 5 --max-tokens 400 --out "$res/decode-prose.json" || failed=1
    fi
    if [ "$failed" = "0" ]; then
        run_bench "$res" concurrent_structured_c2 python3 "$BIN/bench_concurrent.py" --out "$res/conc-struct-c2.json" --prompt structured --concurrency 2 --runs 3 || true
        run_bench "$res" concurrent_structured_c4 python3 "$BIN/bench_concurrent.py" --out "$res/conc-struct-c4.json" --prompt structured --concurrency 4 --runs 3 || true
        run_bench "$res" concurrent_prose_c2 python3 "$BIN/bench_concurrent.py" --out "$res/conc-prose-c2.json" --prompt prose --concurrency 2 --runs 3 || true
    fi
    if [ "$failed" = "0" ]; then
        run_bench "$res" prefill_ladder python3 "$BIN/bench_prefill_ladder.py" --out "$res/prefill-ladder.json" --rungs 8,16,32,64,128,256 --repeats 2 || failed=1
    fi
    if [ "$failed" = "0" ]; then
        run_bench "$res" vision_suite python3 "$BIN/vision_glm_runner.py" --vision-compare "$BIN/vision_compare.py" --menu-image "$EVAL_ROOT/assets/week36-menu.png" --output "$res/vision.json" || failed=1
    fi

    collect_glm_logs "$res"
    { free -g; echo ---; docker ps --format '{{.Names}}\t{{.Status}}'; printf 'mem_available_mb=%s\n' "$(mem_mb)"; } > "$res/host-after-bench.txt"

    if [ "$failed" = "1" ] && ! glm_health; then
        state "bench_failed"
        log "GLM died during benches - DS stays down; diagnose then rerun 'up' or call 'restore'"
        python3 "$BIN/summarize.py" "$res" || true
        exit 2
    fi

    state "benched"
    python3 "$BIN/summarize.py" "$res" || true
    log "BENCHMARKS COMPLETE - GLM left running; call 'restore' when ready to bring DS back"
}

cmd_restore() {
    local res
    res="$(latest_res)"
    mkdir -p "$res"
    exec > >(tee -a "$res/restore.log") 2>&1
    state() { printf '%s\n' "$1" > "$res/state.txt"; log "STATE=$1"; }
    state "restoring_ds"
    log "stopping GLM"
    do_stop_glm
    glm_health && { log "WARN: GLM API still up"; }
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
        if [ -n "${X570_SSH:-}" ] && [ "${RUN_DS_LEG:-1}" = "1" ]; then
            log "running hermes DS comparison leg (best-effort, against production DS)"
            if ssh -o BatchMode=yes "$X570_SSH" 'HERMES_BIN=$HOME/glm53-hermes/hermes-venv bash ~/glm53-hermes/run-hermes-real-tasks.sh --treatment ds' >"$res/hermes-ds-leg.out" 2>&1; then
                log "hermes DS leg OK"
            else
                log "hermes DS leg FAILED (recorded in hermes-ds-leg.out; non-blocking)"
            fi
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
    echo "--- glm api ---"
    glm_health && echo up || echo down
    echo "--- ds api ---"
    ds_health && echo up || echo down
}

case "${1:-status}" in
    up)      cmd_up ;;
    restore) cmd_restore ;;
    status)  cmd_status ;;
    *) echo "usage: $0 {up|restore|status}" >&2; exit 2 ;;
esac
