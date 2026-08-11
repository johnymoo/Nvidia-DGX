#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PILOT_SCRIPT="$SCRIPT_DIR/../run-claude-code-flash-pilot.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# shellcheck source=../run-claude-code-flash-pilot.sh
source "$PILOT_SCRIPT"

ACTIVE_REMOTE_SERVICE=1
CURRENT_ARTIFACT="$TMP"
REMOTE_ALIAS="fake-head"
REMOTE_ROOT="/fake/root"

ssh() {
  printf '{"state":"stopped","qwen_restore":"passed"}\n'
}

rollback_active_service

test -s "$TMP/rollback-receipt.json"
jq -e '.state == "stopped" and .qwen_restore == "passed"' \
  "$TMP/rollback-receipt.json" >/dev/null
test ! -s "$TMP/rollback.stderr.log"

printf '{"status":"passed","tests":1}\n'
