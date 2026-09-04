#!/usr/bin/env bash
# 60s /metrics scraper for production KPI telemetry (design §5.6). Appends one
# JSON line per scrape to <out-dir>/<UTC-date>.jsonl; rotation is automatic
# since the filename is date-based. daily_report.py is the reader.
#
# No hostname/IP/port is hardcoded here: SCRAPE_METRICS_URL is required.
set -euo pipefail

SCRAPE_METRICS_URL="${SCRAPE_METRICS_URL:?set SCRAPE_METRICS_URL, e.g. http://127.0.0.1:<port>/metrics}"
SCRAPE_OUT_DIR="${SCRAPE_OUT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/tmp/eval/scrape}"
SCRAPE_INTERVAL_S="${SCRAPE_INTERVAL_S:-60}"
CURL_BIN="${CURL_BIN:-curl}"
JQ_BIN="${JQ_BIN:-jq}"

mkdir -p "$SCRAPE_OUT_DIR"

scrape_once() {
  local ts out text
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  out="${SCRAPE_OUT_DIR}/$(date -u +%Y-%m-%d).jsonl"
  if text="$("$CURL_BIN" -fsS --max-time 10 "$SCRAPE_METRICS_URL")"; then
    "$JQ_BIN" -nc --arg ts "$ts" --arg text "$text" '{ts: $ts, ok: true, text: $text}' >> "$out"
  else
    "$JQ_BIN" -nc --arg ts "$ts" '{ts: $ts, ok: false, text: null}' >> "$out"
  fi
}

case "${1:-loop}" in
  once)
    scrape_once
    ;;
  loop)
    while true; do
      scrape_once
      sleep "$SCRAPE_INTERVAL_S"
    done
    ;;
  *)
    echo "Usage: $0 [once|loop]" >&2
    exit 64
    ;;
esac
