#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: $0 COMMON_ENV NODE_ENV" >&2
  exit 1
fi

for env_file in "$1" "$2"; do
  if [ ! -f "$env_file" ]; then
    echo "Missing env file: $env_file" >&2
    exit 1
  fi
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
done

failures=0
fail() {
  echo "FAIL: $*" >&2
  failures=$((failures + 1))
}
pass() {
  echo "PASS: $*"
}

for command in docker ip jq nvidia-ctk nvidia-smi ping rdma show_gids ss swapon; do
  if command -v "$command" >/dev/null 2>&1; then
    pass "required command $command is available"
  else
    fail "required command $command is missing"
  fi
done

required=(
  ROLE NODE_RANK MODEL_ROOT CACHE_ROOT FABRIC_IFNAME FABRIC_CIDR
  VLLM_HOST_IP MASTER_ADDR PEER_FABRIC_IP DSPARK_VLLM_IMAGE DSPARK_MODEL
  NCCL_IB_HCA NCCL_SOCKET_IFNAME
)
for name in "${required[@]}"; do
  if [ -z "${!name:-}" ]; then
    fail "missing $name"
  fi
done

if [ "$(uname -m)" = "aarch64" ]; then
  pass "architecture is aarch64"
else
  fail "architecture is $(uname -m), expected aarch64"
fi

if [ "$(uname -r)" = "6.17.0-1014-nvidia" ]; then
  pass "kernel is the aligned 6.17.0-1014-nvidia build"
else
  fail "kernel is $(uname -r), expected 6.17.0-1014-nvidia"
fi

gpu_name="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || true)"
driver_version="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 || true)"
if grep -q 'GB10' <<<"$gpu_name"; then
  pass "NVIDIA GB10 detected"
else
  fail "NVIDIA GB10 not detected"
fi
if [ "$driver_version" = "580.142" ]; then
  pass "NVIDIA driver is aligned at 580.142"
else
  fail "NVIDIA driver is ${driver_version:-unavailable}, expected 580.142"
fi

if docker info >/dev/null 2>&1; then
  pass "Docker daemon is accessible"
else
  fail "Docker daemon is not accessible by $(id -un)"
fi

if docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q 'nvidia'; then
  pass "NVIDIA container runtime is configured"
else
  fail "NVIDIA container runtime is not configured"
fi

docker_version="$(docker version --format '{{.Server.Version}}' 2>/dev/null || true)"
compose_version="$(docker compose version 2>/dev/null | sed 's/^Docker Compose version //' || true)"
toolkit_version="$(nvidia-ctk --version 2>/dev/null | sed -n 's/^NVIDIA Container Toolkit CLI version //p' | head -1)"
if [ "$docker_version" = "29.2.1" ] && [ "$compose_version" = "v5.0.2" ]; then
  pass "Docker 29.2.1 and Compose v5.0.2 are aligned"
else
  fail "Docker/Compose are $docker_version/$compose_version, expected 29.2.1/v5.0.2"
fi
if [ "$toolkit_version" = "1.19.0" ]; then
  pass "NVIDIA Container Toolkit is aligned at 1.19.0"
else
  fail "NVIDIA Container Toolkit is ${toolkit_version:-unavailable}, expected 1.19.0"
fi
if [ "$(ulimit -l)" = "unlimited" ]; then
  pass "memlock is unlimited"
else
  fail "memlock is $(ulimit -l), expected unlimited in a fresh SSH session"
fi
if swapon --show --noheadings | grep -q .; then
  fail "active swap is not allowed for TP=2 inference"
else
  pass "no swap is active"
fi

model_dir="$MODEL_ROOT/$(basename "$DSPARK_MODEL")"
if [ -s "$model_dir/config.json" ] && [ -s "$model_dir/model.safetensors.index.json" ]; then
  pass "model metadata exists at $model_dir"
else
  fail "model metadata is incomplete at $model_dir"
fi

if command -v jq >/dev/null 2>&1 && [ -s "$model_dir/config.json" ]; then
  if jq -e '.quantization_config.quant_method == "fp8" and .expert_dtype == "fp4"' \
    "$model_dir/config.json" >/dev/null; then
    pass "checkpoint is the expected mixed FP8/FP4 build"
  else
    fail "checkpoint quantization metadata does not match FP8/FP4"
  fi
fi

if [ -s "$model_dir/model.safetensors.index.json" ]; then
  missing=0
  while IFS= read -r shard; do
    [ -s "$model_dir/$shard" ] || missing=$((missing + 1))
  done < <(jq -r '.weight_map | to_entries[].value' \
    "$model_dir/model.safetensors.index.json" | sort -u)
  if [ "$missing" -eq 0 ]; then
    pass "all indexed model shards are present"
  else
    fail "$missing indexed model shards are missing"
  fi
fi

if [ -d "/sys/class/net/$FABRIC_IFNAME" ]; then
  pass "fabric interface $FABRIC_IFNAME exists"
  if [ "$(cat "/sys/class/net/$FABRIC_IFNAME/carrier" 2>/dev/null || echo 0)" = "1" ]; then
    pass "fabric interface has carrier"
  else
    fail "fabric interface has no carrier"
  fi
  if [ "$(cat "/sys/class/net/$FABRIC_IFNAME/mtu" 2>/dev/null || echo 0)" = "9000" ]; then
    pass "fabric MTU is 9000"
  else
    fail "fabric MTU is not 9000"
  fi
else
  fail "fabric interface $FABRIC_IFNAME does not exist"
fi

if ip -4 -o address show dev "$FABRIC_IFNAME" 2>/dev/null | grep -q " ${VLLM_HOST_IP}/"; then
  pass "fabric address $VLLM_HOST_IP is configured"
else
  fail "fabric address $VLLM_HOST_IP is not configured"
fi

if rdma link show 2>/dev/null | grep -q "$NCCL_IB_HCA/1 state ACTIVE"; then
  pass "RDMA device $NCCL_IB_HCA is active"
else
  fail "RDMA device $NCCL_IB_HCA is not active"
fi

gid_line="$(show_gids 2>/dev/null | awk -v hca="$NCCL_IB_HCA" -v idx="${NCCL_IB_GID_INDEX:-3}" \
  '$1 == hca && $3 == idx { print; exit }' || true)"
if awk -v ip="$VLLM_HOST_IP" -v iface="$FABRIC_IFNAME" \
  '$5 == ip && $6 == "v2" && $7 == iface { found=1 } END { exit !found }' <<<"$gid_line"; then
  pass "GID index ${NCCL_IB_GID_INDEX:-3} maps $VLLM_HOST_IP to RoCE v2"
else
  fail "GID index ${NCCL_IB_GID_INDEX:-3} is not the expected RoCE v2 fabric GID"
fi

if ping -c 1 -W 2 "$PEER_FABRIC_IP" >/dev/null 2>&1; then
  pass "fabric peer $PEER_FABRIC_IP is reachable"
else
  fail "fabric peer $PEER_FABRIC_IP is not reachable"
fi
if ping -M do -s 8972 -c 3 -W 2 "$PEER_FABRIC_IP" >/dev/null 2>&1; then
  pass "8972-byte jumbo ping reaches $PEER_FABRIC_IP"
else
  fail "8972-byte jumbo ping to $PEER_FABRIC_IP failed"
fi

if docker image inspect "$DSPARK_VLLM_IMAGE" >/dev/null 2>&1; then
  pass "runtime image $DSPARK_VLLM_IMAGE exists"
else
  fail "runtime image $DSPARK_VLLM_IMAGE is missing"
fi

if [ "$ROLE" = "head" ] && ss -ltn | grep -q ":${VLLM_PORT:-8890}[[:space:]]"; then
  fail "API port ${VLLM_PORT:-8890} is already in use"
else
  pass "API port ${VLLM_PORT:-8890} is available"
fi

if ss -ltn | grep -q ":${MASTER_PORT:-29510}[[:space:]]"; then
  fail "rendezvous port ${MASTER_PORT:-29510} is already in use"
else
  pass "rendezvous port ${MASTER_PORT:-29510} is available"
fi

if [ "$failures" -ne 0 ]; then
  echo "Preflight failed with $failures issue(s)." >&2
  exit 1
fi

echo "Preflight passed for $ROLE."
