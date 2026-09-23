#!/usr/bin/env bash
# Hermes real-task benchmark, GLM/DS variant of
# execution/benchmarks/run-hermes-real-tasks-ab.sh (qwen/ds original).
# Runs ON x570 (hermes host since 2026-09-06) — all model endpoints are LAN.
#
#   run-hermes-real-tasks.sh [--treatment glm|ds|glm-ds]   (default glm-ds)
#
# Each leg freezes the 3 collected cron-task prompts, clones an isolated hermes
# profile, configures the provider explicitly, runs the agent loop per task,
# records agent usage + server-side vLLM metric deltas (prefill/decode TPS).
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-/home/chriswang/.hermes}"
HERMES_BIN="${HERMES_BIN:-$HERMES_HOME/hermes-agent/hermes}"
SOURCE_PROFILE="${SOURCE_PROFILE:-family-kitchen-helper}"
BENCH_PROFILE="${BENCH_PROFILE:-benchmark-real-tasks}"
ARTIFACT_BASE="${ARTIFACT_BASE:-$HERMES_HOME/benchmarks/real-tasks-glm}"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
ROOT="$ARTIFACT_BASE/$RUN_ID"
JOBS_FILE="$HERMES_HOME/cron/jobs.json"

GB10_LAN="192.168.88.181"
GLM_PROVIDER="local-vllm-glm53"
GLM_MODEL="GLM-5.3-Flash-EXL3"
GLM_METRICS_URL="http://${GB10_LAN}:8890/metrics"
DS_PROVIDER="local-vllm-private-ds"
DS_MODEL="deepseek-v4-flash-0731"
DS_METRICS_URL="http://${GB10_LAN}:8890/metrics"

TREATMENT="glm-ds"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --treatment) TREATMENT="$2"; shift 2 ;;
        *) echo "unknown arg $1" >&2; exit 2 ;;
    esac
done
case "$TREATMENT" in glm|ds|glm-ds) ;; *) echo "bad --treatment" >&2; exit 2 ;; esac

PROFILE_CREATED=0
log() { printf '[%s] %s\n' "$(date -Is)" "$*"; }

cleanup() {
    if (( PROFILE_CREATED )); then
        log "Removing isolated profile $BENCH_PROFILE"
        "$HERMES_BIN" profile delete "$BENCH_PROFILE" -y >/dev/null 2>&1 || true
        PROFILE_CREATED=0
    fi
}
trap cleanup EXIT INT TERM

require_commands() {
    local cmd
    for cmd in awk curl jq sha256sum stat; do
        command -v "$cmd" >/dev/null || { printf 'Missing: %s\n' "$cmd" >&2; exit 2; }
    done
    [[ -x "$HERMES_BIN" ]] || { printf 'hermes not found: %s\n' "$HERMES_BIN" >&2; exit 2; }
}

metric_value() {
    awk -v metric="$2" '
        $1 ~ ("^" metric "(\\{|$)") { total += $2 }
        END { printf "%.9f", total + 0 }
    ' "$1"
}

number_delta() { awk -v a="$1" -v b="$2" 'BEGIN{printf "%.9f", a-b}'; }
safe_rate() { awk -v n="$1" -v d="$2" 'BEGIN{if(d>0)printf "%.6f",n/d; else printf "0"}'; }

wait_for_idle() {
    local url="$1" deadline=$((SECONDS + 120)) running
    while (( SECONDS < deadline )); do
        running="$(curl -fsS "$url" 2>/dev/null | awk -v m='vllm:num_requests_running' '$1 ~ ("^" m "(\\{|$)"){t+=$2} END{printf "%.9f",t+0}')"
        [[ "$running" == "0.000000000" ]] && return 0
        sleep 2
    done
    log "WARNING: server not idle within 120s - proceeding"
}

# vLLM-side delta for both GLM and DS (same metric family).
write_metric_delta() {
    local before="$1" after="$2" output="$3"
    local prompt_total prompt_cached prompt_uncached gen prefill_s decode_s reqs
    prompt_total="$(number_delta "$(metric_value "$after" 'vllm:prompt_tokens_total')" "$(metric_value "$before" 'vllm:prompt_tokens_total')")"
    prompt_cached="$(number_delta "$(metric_value "$after" 'vllm:prompt_tokens_cached_total')" "$(metric_value "$before" 'vllm:prompt_tokens_cached_total')")"
    prompt_uncached="$(number_delta "$prompt_total" "$prompt_cached")"
    gen="$(number_delta "$(metric_value "$after" 'vllm:generation_tokens_total')" "$(metric_value "$before" 'vllm:generation_tokens_total')")"
    prefill_s="$(number_delta "$(metric_value "$after" 'vllm:request_prefill_time_seconds_sum')" "$(metric_value "$before" 'vllm:request_prefill_time_seconds_sum')")"
    decode_s="$(number_delta "$(metric_value "$after" 'vllm:request_decode_time_seconds_sum')" "$(metric_value "$before" 'vllm:request_decode_time_seconds_sum')")"
    reqs="$(number_delta "$(metric_value "$after" 'vllm:request_success_total')" "$(metric_value "$before" 'vllm:request_success_total')")"
    jq -n --argjson p "$prompt_total" --argjson pc "$prompt_cached" --argjson pu "$prompt_uncached" \
        --argjson g "$gen" --argjson ps "$prefill_s" --argjson ds "$decode_s" --argjson r "$reqs" \
        '{prompt_tokens:$p, prompt_cached_tokens:$pc, prompt_uncached_tokens:$pu,
          generation_tokens:$g, prefill_seconds:$ps, decode_seconds:$ds,
          prompt_tps_uncached:(if $ps>0 then $pu/$ps else 0 end),
          decode_tps:(if $ds>0 then $g/$ds else 0 end),
          completed_requests:$r}' > "$output"
}

run_case() {
    local task_id="$1" task_slug="$2" treatment="$3"
    local provider model metrics_url
    if [[ "$treatment" == "glm" ]]; then
        provider="$GLM_PROVIDER"; model="$GLM_MODEL"; metrics_url="$GLM_METRICS_URL"
    else
        provider="$DS_PROVIDER"; model="$DS_MODEL"; metrics_url="$DS_METRICS_URL"
    fi
    local case_dir prompt started_at finished_at start_ns end_ns elapsed_ms
    local monitor_pid exit_code output_sha output_bytes max_running max_waiting

    case_dir="$ROOT/runs/$task_slug/$treatment"
    mkdir -p "$case_dir"
    prompt="$(jq -r --arg id "$task_id" '.jobs[] | select(.id == $id) | .prompt' "$JOBS_FILE")"

    log "Starting $task_slug on $treatment ($model)"
    wait_for_idle "$metrics_url"
    curl -fsS "$metrics_url" > "$case_dir/metrics.before"
    ( while :; do
        curl -fsS "$metrics_url" 2>/dev/null | awk -v m='vllm:num_requests_running' '$1 ~ ("^" m "(\\{|$)"){r+=$2} END{print r+0}' \
            >> "$case_dir/running.samples" 2>/dev/null || true
        sleep 2
      done ) &
    monitor_pid=$!

    started_at="$(date -Is)"
    start_ns="$(date +%s%N)"
    set +e
    "$HERMES_BIN" -p "$BENCH_PROFILE" \
        --provider "$provider" \
        -m "$model" \
        --reasoning low \
        --usage-file "$case_dir/usage.json" \
        -z "$prompt" \
        > "$case_dir/output.txt" \
        2> "$case_dir/stderr.log"
    exit_code=$?
    set -e
    end_ns="$(date +%s%N)"
    finished_at="$(date -Is)"

    kill "$monitor_pid" 2>/dev/null || true
    wait "$monitor_pid" 2>/dev/null || true
    curl -fsS "$metrics_url" > "$case_dir/metrics.after"

    elapsed_ms=$(( (end_ns - start_ns) / 1000000 ))
    [[ -f "$case_dir/usage.json" ]] || printf '{}\n' > "$case_dir/usage.json"
    write_metric_delta "$case_dir/metrics.before" "$case_dir/metrics.after" "$case_dir/server-metrics.json"

    output_sha="$(sha256sum "$case_dir/output.txt" | awk '{print $1}')"
    output_bytes="$(stat -c %s "$case_dir/output.txt")"
    max_running="$(sort -n "$case_dir/running.samples" 2>/dev/null | tail -1)"
    max_running="${max_running:-0}"

    jq -n --arg task_id "$task_id" --arg task "$task_slug" --arg treatment "$treatment" \
        --arg provider "$provider" --arg model "$model" \
        --arg started_at "$started_at" --arg finished_at "$finished_at" \
        --arg output_sha256 "$output_sha" --argjson exit_code "$exit_code" \
        --argjson elapsed_ms "$elapsed_ms" --argjson output_bytes "$output_bytes" \
        --argjson max_running "$max_running" \
        --slurpfile usage "$case_dir/usage.json" \
        --slurpfile server "$case_dir/server-metrics.json" \
        '{task_id:$task_id, task:$task, treatment:$treatment, provider:$provider, model:$model,
          started_at:$started_at, finished_at:$finished_at,
          success:($exit_code == 0 and (($usage[0].failed // false) | not)),
          exit_code:$exit_code, elapsed_ms:$elapsed_ms,
          output_sha256:$output_sha256, output_bytes:$output_bytes,
          max_server_requests_running:$max_running,
          usage:$usage[0], server:$server[0]}' > "$case_dir/run.json"

    log "Finished $task_slug on $treatment: exit=$exit_code elapsed_ms=$elapsed_ms"
}

write_summary() {
    find "$ROOT/runs" -name run.json -type f -print0 | sort -z | xargs -0 jq -s '
      sort_by(.task, .treatment) as $runs
      | { schema_version: 1, run_id: $ENV.RUN_ID, generated_at: (now | todateiso8601),
          treatments: (
            $runs | group_by(.treatment) | map({key: .[0].treatment, value: {
                model: .[0].model,
                successful_tasks: (map(select(.success)) | length),
                task_count: length,
                elapsed_ms: (map(.elapsed_ms) | add),
                agent_api_calls: (map(.usage.api_calls // 0) | add),
                input_tokens: (map(.usage.input_tokens // 0) | add),
                cache_read_tokens: (map(.usage.cache_read_tokens // 0) | add),
                output_tokens: (map(.usage.output_tokens // 0) | add),
                server_prompt_tokens: (map(.server.prompt_tokens // 0) | add),
                server_prompt_cached_tokens: (map(.server.prompt_cached_tokens // 0) | add),
                server_prompt_uncached_tokens: (map(.server.prompt_uncached_tokens // 0) | add),
                server_generation_tokens: (map(.server.generation_tokens // 0) | add),
                server_prefill_seconds: (map(.server.prefill_seconds // 0) | add),
                server_decode_seconds: (map(.server.decode_seconds // 0) | add),
                server_decode_tps: ((map(.server.generation_tokens // 0) | add) / (map(.server.decode_seconds // 0) | add)),
                server_prompt_tps_uncached: ((map(.server.prompt_uncached_tokens // 0) | add) / (map(.server.prefill_seconds // 0) | add)),
                server_prompt_cache_hit_ratio: ((map(.server.prompt_cached_tokens // 0) | add) / (map(.server.prompt_tokens // 0) | add))
            }}) | from_entries
          ),
          runs: $runs }' > "$ROOT/summary.json"

    jq -r '"# Hermes real-task benchmark (glm/ds)\n\n"
        + "Run: `" + .run_id + "`\n\n"
        + "| Task | Treatment | Success | Wall (s) | API calls | Input | Cache read | Output | Decode TPS | Max running |\n"
        + "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n"
        + ([.runs[]
            | "| " + .task + " | " + .treatment + " | " + (.success|tostring)
              + " | " + ((.elapsed_ms/1000)|tostring)
              + " | " + ((.usage.api_calls // 0)|tostring)
              + " | " + ((.usage.input_tokens // 0)|tostring)
              + " | " + ((.usage.cache_read_tokens // 0)|tostring)
              + " | " + ((.usage.output_tokens // 0)|tostring)
              + " | " + ((.server.decode_tps // 0)|tostring)
              + " | " + (.max_server_requests_running|tostring) + " |"] | join("\n"))' "$ROOT/summary.json" > "$ROOT/report.md"
    cat "$ROOT/report.md"
}

main() {
    require_commands
    [[ -d "$HERMES_HOME/profiles/$BENCH_PROFILE" ]] && { echo "profile exists; refusing" >&2; exit 3; }
    mkdir -p "$ROOT/runs"
    export RUN_ID

    jq '[.jobs[] | select(.id == "fee9289d05f6" or .id == "5571a79908f2" or .id == "1479ec2587fb")] | sort_by(.id)' \
        "$JOBS_FILE" > "$ROOT/jobs.frozen.json"
    sha256sum "$JOBS_FILE" > "$ROOT/original-jobs.sha256.before"
    sha256sum "$HERMES_HOME/profiles/$SOURCE_PROFILE/config.yaml" > "$ROOT/original-config.sha256.before"
    curl -fsS "http://${GB10_LAN}:8890/v1/models" > "$ROOT/ds-model.before.json" || true
    curl -fsS "http://${GB10_LAN}:8890/v1/models" > "$ROOT/glm-model.before.json" || true

    log "Creating isolated profile $BENCH_PROFILE"
    "$HERMES_BIN" profile create "$BENCH_PROFILE" \
        --clone-from "$SOURCE_PROFILE" \
        --no-alias \
        --description 'Temporary isolated profile for real-task GLM/DeepSeek benchmark' \
        > "$ROOT/profile-create.log"
    PROFILE_CREATED=1

    "$HERMES_BIN" -p "$BENCH_PROFILE" config set --force providers.local-vllm-glm53 \
        '{"name":"local-vllm-glm53","base_url":"http://'"${GB10_LAN}"':8890/v1","api_key":"no-key-required","default_model":"GLM-5.3-Flash-EXL3","extra_body":{"chat_template_kwargs":{"enable_thinking":true},"reasoning_effort":"low"}}' \
        >> "$ROOT/profile-config.log"
    "$HERMES_BIN" -p "$BENCH_PROFILE" config set --force providers.local-vllm-private-ds \
        '{"name":"local-vllm-private-ds","base_url":"http://'"${GB10_LAN}"':8890/v1","api_key":"not-needed","default_model":"deepseek-v4-flash-0731","extra_body":{"chat_template_kwargs":{"enable_thinking":true},"reasoning_effort":"low"}}' \
        >> "$ROOT/profile-config.log"

    local ids=(fee9289d05f6 5571a79908f2 1479ec2587fb)
    local slugs=(codex-quota-reset daily-stock-price-monitor hermes-version-check)
    local i t
    if [[ "$TREATMENT" == "glm-ds" ]]; then
        for i in 0 1 2; do
            run_case "${ids[$i]}" "${slugs[$i]}" glm
            run_case "${ids[$i]}" "${slugs[$i]}" ds
        done
    else
        t="$TREATMENT"
        for i in 0 1 2; do
            run_case "${ids[$i]}" "${slugs[$i]}" "$t"
        done
    fi

    write_summary
    cleanup
    trap - EXIT INT TERM

    sha256sum "$JOBS_FILE" > "$ROOT/original-jobs.sha256.after"
    cmp "$ROOT/original-jobs.sha256.before" "$ROOT/original-jobs.sha256.after"
    test ! -d "$HERMES_HOME/profiles/$BENCH_PROFILE"
    printf 'ARTIFACT_ROOT=%s\n' "$ROOT"
    jq . "$ROOT/summary.json"
}

main "$@"
