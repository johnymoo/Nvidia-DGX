#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
ENV_FILE=${QWEN38_ENV:-${PROJECT_DIR}/config/qwen38.env}

[[ -f "${ENV_FILE}" ]] || {
  echo "Missing ${ENV_FILE}; copy config/qwen38.env.example first" >&2
  exit 2
}
# shellcheck source=/dev/null
source "${ENV_FILE}"

required=(MODEL_ROOT MODELSCOPE_MODEL MODELSCOPE_REVISION MODELSCOPE_IMAGE VLLM_IMAGE CONTAINER_NAME MODEL_ALIAS PUBLISH_HOST PORT MAX_MODEL_LEN GPU_MEMORY_UTILIZATION HOST_MEMORY_LIMIT VLLM_CACHE_ROOT CONFIG_SHA256 INDEX_SHA256 CHAT_TEMPLATE_SHA256 GENERATION_CONFIG_SHA256 TOKENIZER_CONFIG_SHA256)
for name in "${required[@]}"; do
  [[ -n "${!name:-}" ]] || { echo "Missing configuration: ${name}" >&2; exit 2; }
done

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose --env-file "${ENV_FILE}" -f "${PROJECT_DIR}/compose.yaml" "$@"
  else
    docker-compose --env-file "${ENV_FILE}" -f "${PROJECT_DIR}/compose.yaml" "$@"
  fi
}

verify_model() {
  local root=${MODEL_ROOT}
  [[ -f "${root}/config.json" && -f "${root}/model.safetensors.index.json" ]]
  echo "${CONFIG_SHA256}  ${root}/config.json" | sha256sum --check --status
  echo "${INDEX_SHA256}  ${root}/model.safetensors.index.json" | sha256sum --check --status
  echo "${CHAT_TEMPLATE_SHA256}  ${root}/chat_template.jinja" | sha256sum --check --status
  echo "${GENERATION_CONFIG_SHA256}  ${root}/generation_config.json" | sha256sum --check --status
  echo "${TOKENIZER_CONFIG_SHA256}  ${root}/tokenizer_config.json" | sha256sum --check --status
  python3 - "${root}" <<'PY'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
config = json.loads((root / "config.json").read_text())
index = json.loads((root / "model.safetensors.index.json").read_text())
assert config["architectures"] == ["Qwen3_5ForConditionalGeneration"]
assert config["quantization_config"]["quant_method"] == "fp8"
files = set(index["weight_map"].values())
assert len(files) == 66
missing = sorted(name for name in files if not (root / name).is_file())
assert not missing, missing
assert not list(root.glob("*.incomplete"))
PY
}

verify_gpu() {
  local row name total
  row=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits)
  [[ $(printf '%s\n' "${row}" | awk 'NF {n++} END {print n+0}') -eq 1 ]]
  IFS=, read -r name total <<<"${row}"
  [[ ${name// /} == NVIDIAGeForceRTX4090 && ${total// /} -ge 48000 ]] || {
    echo "This profile requires one RTX 4090 with at least 48,000 MiB VRAM" >&2
    return 1
  }
}

