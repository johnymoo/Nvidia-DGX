#!/usr/bin/env bash
set -euo pipefail

ROOT="${H3_ROOT:-/home/admin/minimax-h3}"
BENCH_ROOT="${H3_BENCH_ROOT:-/home/admin/minimax-h3-benchmark}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$BENCH_ROOT/artifacts"

receipt="$($ROOT/venv/bin/python "$SCRIPT_DIR/benchmark.py" run \
  --root "$ROOT" --output "$BENCH_ROOT/artifacts" \
  --workflow "$ROOT/workflows/h3-dense-baseline.json" \
  --cases "$SCRIPT_DIR/cases.json")"

"$ROOT/venv/bin/python" "$SCRIPT_DIR/benchmark.py" render \
  --input "$receipt" --site "$BENCH_ROOT/site"
printf 'benchmark=%s\nsite=%s\n' "$receipt" "$BENCH_ROOT/site"
