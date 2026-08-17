#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=execution/minimax-h3/runtime-lib.sh
source "$SCRIPT_DIR/runtime-lib.sh"

root=""
port="${H3_PORT:-8188}"

while (( $# )); do
  case "$1" in
    --root) root="$2"; shift 2 ;;
    --port) port="$2"; shift 2 ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; exit 1 ;;
  esac
done

[[ -n "$root" ]] || { printf '%s\n' '--root is required' >&2; exit 1; }

process="$(h3_process_observation "$root" "$port")"
protected="$(h3_protected_status "${H3_PROTECTED_BASELINE:-}")"
http_code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:$port/" || true)"
jq -n --argjson process "$process" --argjson protected "$protected" \
  --arg http_code "$http_code" \
  '$process + {http_code: $http_code, protected: $protected}'
