#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$ROOT/.." && pwd)"
RUNNER="$ROOT/run_benchmark.py"
REPORTER="$ROOT/render_report.py"
ARTIFACT_BASE="${BENCHMARK_ARTIFACT_ROOT:-$ROOT/artifacts/runs}"
CACHE="${CLAUDE_PILOT_CACHE:-$ROOT/artifacts/cache}"
TOOLCHAIN="${CODING_AGENT_TOOLCHAIN:-}"

usage() {
  echo "Usage: $0 {test|fake|preflight|run|resume ARTIFACT|report ARTIFACT|serve ARTIFACT}" >&2
}

require_runtime() {
  [ -n "$TOOLCHAIN" ] || { echo "CODING_AGENT_TOOLCHAIN is required" >&2; return 1; }
  [ -x "$TOOLCHAIN/bin/claude" ] || { echo "Claude route shim is missing: $TOOLCHAIN/bin/claude" >&2; return 1; }
  : "${CLAUDE_DS_BASE_URL:?CLAUDE_DS_BASE_URL is required}"
  : "${PRIVATE_DS_BASE_URL:?PRIVATE_DS_BASE_URL is required}"
  : "${QWEN_LOCAL_BASE_URL:?QWEN_LOCAL_BASE_URL is required}"
  command -v claude >/dev/null || { echo "Claude Code is required" >&2; return 1; }
  command -v codex >/dev/null || { echo "Codex CLI is required for GPT judging" >&2; return 1; }
}

run_hook() {
  local command="${!1:-}"
  [ -z "$command" ] || bash -lc "$command"
}

runner() {
  python3 "$RUNNER" --cache "$CACHE" --toolchain "$TOOLCHAIN" "$@"
}

render_report() {
  local artifact="$1"
  python3 "$REPORTER" --project-root "$PROJECT_ROOT" --artifact-root "$artifact" \
    --output "$artifact/review/public/index.html"
}

run_tests() {
  python3 -m py_compile "$RUNNER" "$REPORTER" "$ROOT/merge_manifest.py" "$ROOT/rerun_thinking.py"
  python3 "$ROOT/test_benchmark.py"
  python3 "$ROOT/test_rerun_thinking.py"
  python3 -m unittest discover -s "$ROOT/r3/writing/tests" -v
}

run_preflight() {
  local artifact="$1"
  require_runtime
  mkdir -p "$artifact"
  run_tests
  runner --preflight --artifact-root "$artifact"
}

run_all() {
  local artifact="$1"
  run_preflight "$artifact"
  trap 'run_hook BENCHMARK_FINALIZE_CMD' EXIT
  run_hook BENCHMARK_PREPARE_DEEPSEEK_CMD
  runner --phase deepseek --artifact-root "$artifact"
  run_hook BENCHMARK_PREPARE_QWEN_CMD
  runner --phase qwen --artifact-root "$artifact"
  runner --package --artifact-root "$artifact"
  render_report "$artifact"
  run_hook BENCHMARK_FINALIZE_CMD
  trap - EXIT
  printf '{"status":"completed","artifact":"%s","summary":"%s","details":"%s"}\n' \
    "$artifact" "$artifact/review/public/index.html" "$artifact/review/public/details.html"
}

resume_all() {
  local artifact="$1"
  require_runtime
  [ -f "$artifact/benchmark-state.json" ] || { echo "benchmark state is missing: $artifact" >&2; return 1; }
  trap 'run_hook BENCHMARK_FINALIZE_CMD' EXIT
  run_hook BENCHMARK_PREPARE_DEEPSEEK_CMD
  runner --phase deepseek --artifact-root "$artifact"
  run_hook BENCHMARK_PREPARE_QWEN_CMD
  runner --phase qwen --artifact-root "$artifact"
  runner --package --artifact-root "$artifact"
  render_report "$artifact"
  run_hook BENCHMARK_FINALIZE_CMD
  trap - EXIT
}

case "${1:-}" in
  test)
    [ "$#" -eq 1 ] || { usage; exit 64; }
    run_tests
    ;;
  fake)
    [ "$#" -le 2 ] || { usage; exit 64; }
    artifact="${2:-$(mktemp -d "${TMPDIR:-/tmp}/claude-benchmark-fake.XXXXXX")}"
    python3 "$RUNNER" --fake-run --artifact-root "$artifact"
    render_report "$artifact"
    printf '%s\n' "$artifact/review/public/index.html"
    ;;
  preflight)
    [ "$#" -le 2 ] || { usage; exit 64; }
    artifact="${2:-$ARTIFACT_BASE/preflight-$(date -u +%Y%m%dT%H%M%SZ)}"
    run_preflight "$artifact"
    ;;
  run)
    [ "$#" -le 2 ] || { usage; exit 64; }
    artifact="${2:-$ARTIFACT_BASE/$(date -u +%Y%m%dT%H%M%SZ)}"
    run_all "$(mkdir -p "$artifact" && cd "$artifact" && pwd)"
    ;;
  resume)
    [ "$#" -eq 2 ] || { usage; exit 64; }
    resume_all "$(cd "$2" && pwd)"
    ;;
  report)
    [ "$#" -eq 2 ] || { usage; exit 64; }
    render_report "$(cd "$2" && pwd)"
    ;;
  serve)
    [ "$#" -eq 2 ] || { usage; exit 64; }
    artifact="$(cd "$2" && pwd)"
    python3 "$RUNNER" --serve-review --artifact-root "$artifact" --review-root "$artifact/review"
    ;;
  *)
    usage
    exit 64
    ;;
esac
