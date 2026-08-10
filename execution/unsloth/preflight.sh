#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  echo "Usage: $0 COMMON_ENV NODE_ENV [target|dspark]" >&2
  exit 1
fi

MODE="${3:-target}"
case "$MODE" in
  target|dspark) ;;
  *)
    echo "Mode must be target or dspark, got: $MODE" >&2
    exit 1
    ;;
esac

for env_file in "$1" "$2"; do
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
done

failures=0
fail() { echo "FAIL: $*" >&2; failures=$((failures + 1)); }
pass() { echo "PASS: $*"; }

if docker info >/dev/null 2>&1; then
  pass "Docker daemon is accessible"
else
  fail "Docker daemon is not accessible"
fi

if docker image inspect "$UNSLOTH_LLAMA_IMAGE" >/dev/null 2>&1; then
  pass "Unsloth llama.cpp image exists"
else
  fail "Unsloth llama.cpp image is missing"
fi

if [ "$(cat "/sys/class/net/$FABRIC_IFNAME/carrier" 2>/dev/null || echo 0)" = "1" ]; then
  pass "fabric carrier is present"
else
  fail "fabric carrier is absent"
fi

if ip -4 -o address show dev "$FABRIC_IFNAME" 2>/dev/null | grep -q " $FABRIC_IP/"; then
  pass "fabric address $FABRIC_IP is configured"
else
  fail "fabric address $FABRIC_IP is not configured"
fi

if rdma link show 2>/dev/null | grep -q "$RDMA_HCA/1 state ACTIVE"; then
  pass "RDMA device $RDMA_HCA is active"
else
  fail "RDMA device $RDMA_HCA is not active"
fi

if ping -c 1 -W 2 "$PEER_FABRIC_IP" >/dev/null 2>&1; then
  pass "fabric peer is reachable"
else
  fail "fabric peer is not reachable"
fi

if ss -ltn | grep -q ":$RPC_PORT[[:space:]]"; then
  fail "RPC port $RPC_PORT is already in use"
else
  pass "RPC port $RPC_PORT is available"
fi

if [ "$ROLE" = "head" ]; then
  target="${GGUF_MODEL_ROOT}${GGUF_TARGET_MODEL#/models}"
  target_prefix="${target%-00001-of-00005.gguf}"
  target_ready=1
  if [ "$target_prefix" = "$target" ]; then
    target_ready=0
  else
    target_shards=(
      "00001 5257408"
      "00002 48935523072"
      "00003 48980787136"
      "00004 49999168416"
      "00005 7174505088"
    )
    for record in "${target_shards[@]}"; do
      read -r shard expected_size <<<"$record"
      shard_path="${target_prefix}-${shard}-of-00005.gguf"
      if [ ! -f "$shard_path" ] \
        || [ "$(stat -c %s "$shard_path" 2>/dev/null || echo 0)" != "$expected_size" ]; then
        target_ready=0
      fi
    done
  fi
  if [ "$target_ready" = "1" ]; then
    pass "all five target GGUF shards have the expected sizes"
  else
    fail "target GGUF shard set is incomplete or has unexpected sizes"
  fi
  if [ "$MODE" = "dspark" ]; then
    draft="${GGUF_MODEL_ROOT}${GGUF_DRAFT_MODEL#/models}"
    if [ -f "$draft" ] && [ "$(stat -c %s "$draft")" = "10896057440" ]; then
      pass "DSpark sidecar has the expected size"
    else
      fail "DSpark sidecar is missing or has an unexpected size"
    fi
  fi
  if ss -ltn | grep -q ":${LLAMA_PORT:-8891}[[:space:]]"; then
    fail "API port ${LLAMA_PORT:-8891} is already in use"
  else
    pass "API port ${LLAMA_PORT:-8891} is available"
  fi
fi

if [ "$failures" -ne 0 ]; then
  echo "Unsloth preflight failed with $failures issue(s)." >&2
  exit 1
fi

echo "Unsloth preflight passed for $ROLE."
