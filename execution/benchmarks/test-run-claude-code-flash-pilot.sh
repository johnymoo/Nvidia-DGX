#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PILOT_SCRIPT="$SCRIPT_DIR/../run-claude-code-flash-pilot.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# shellcheck source=../run-claude-code-flash-pilot.sh
source "$PILOT_SCRIPT"

CURRENT_ARTIFACT="$TMP"
remote_service() {
  printf '%s\n' "$*" >>"$TMP/actions.log"
  printf '{"state":"stopped","qwen_health":"healthy"}\n'
}

CURRENT_PHASE="pre-transition"
if (false; recover_on_exit); then
  echo "pre-transition recovery unexpectedly succeeded" >&2
  exit 1
fi
grep -Fxq -- '--stop --restore-qwen' "$TMP/actions.log"
test -s "$TMP/rollback-receipt.json"
test -d "$TMP/.recovery-lock"
rmdir "$TMP/.recovery-lock"

: >"$TMP/actions.log"
CURRENT_PHASE="post-transition"
if (false; recover_on_exit); then
  echo "post-transition recovery unexpectedly succeeded" >&2
  exit 1
fi
grep -Fxq -- '--status' "$TMP/actions.log"
if grep -Fxq -- '--transition-qwen' "$TMP/actions.log"; then
  echo "healthy Qwen recovery unexpectedly transitioned" >&2
  exit 1
fi
test -s "$TMP/qwen-recovery-receipt.json"
test -d "$TMP/.recovery-lock"
rmdir "$TMP/.recovery-lock"

: >"$TMP/actions.log"
remote_service() {
  printf '%s\n' "$*" >>"$TMP/actions.log"
  if [ "$*" = "--status" ]; then
    printf '{"state":"stopped","qwen_health":"unhealthy"}\n'
  else
    printf '{"state":"qwen-running","qwen":{"restored":true}}\n'
  fi
}
CURRENT_PHASE="post-transition"
if (false; recover_on_exit); then
  echo "unhealthy post-transition recovery unexpectedly succeeded" >&2
  exit 1
fi
grep -Fxq -- '--status' "$TMP/actions.log"
grep -Fxq -- '--transition-qwen' "$TMP/actions.log"
test -s "$TMP/qwen-recovery-receipt.json"

printf '{"status":"passed","tests":3}\n'
