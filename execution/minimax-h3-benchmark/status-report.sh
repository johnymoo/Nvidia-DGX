#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/report-lib.sh"
ROOT="${H3_BENCH_ROOT:-/home/admin/minimax-h3-benchmark}"
PORT="${H3_REPORT_PORT:-8890}"
report_observe "$ROOT" "$PORT"
