#!/usr/bin/env bash
# Local-only entry for the DeepSeek-V4.1-Flash EXL3 dual-GB10 recipe.
# The repository does not contain a lifecycle controller for this profile:
# deployment/benchmark runs go through scripts/window-step.sh on the target
# kit (see README.md). Unknown operations exit non-zero.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "${1:-help}" in
  validate)
    bash -n "$SCRIPT_DIR/scripts/window-step.sh"
    bash -n "$SCRIPT_DIR/scripts/run-hermes-real-tasks-ds41.sh"
    python3 -m py_compile \
      "$SCRIPT_DIR/scripts/bench_decode_18890.py" \
      "$SCRIPT_DIR/scripts/bench_prefill_ladder.py" \
      "$SCRIPT_DIR/scripts/bench_concurrent.py" \
      "$SCRIPT_DIR/scripts/summarize_ds41.py"
    python3 -c "import json; json.load(open('$SCRIPT_DIR/benchmark-results-20260917.json'))"
    echo "local static checks passed"
    ;;
  help|--help|-h)
    sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    echo
    echo "Usage: ./run.sh validate"
    echo "Lifecycle operations (prepare/start/stop) live in scripts/window-step.sh"
    echo "and must be run on the target kit; see README.md."
    ;;
  *)
    echo "unsupported operation: $1 (this recipe ships no lifecycle controller)" >&2
    exit 2
    ;;
esac
