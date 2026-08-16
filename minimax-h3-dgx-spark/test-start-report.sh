#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if output="$(H3_REPORT_PYTHON='h3-report-python-does-not-exist' \
  "$SCRIPT_DIR/execution/minimax-h3-benchmark/start-report.sh" 2>&1)"; then
  printf '%s\n' 'expected unresolved H3_REPORT_PYTHON to fail' >&2
  exit 1
fi
[[ "$output" == *'H3_REPORT_PYTHON must resolve to an executable: h3-report-python-does-not-exist'* ]]
