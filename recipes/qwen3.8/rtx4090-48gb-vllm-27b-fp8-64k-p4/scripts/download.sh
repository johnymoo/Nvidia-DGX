#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

mkdir -p "$(dirname -- "${MODEL_ROOT}")"
docker image inspect "${MODELSCOPE_IMAGE}" >/dev/null 2>&1 || docker pull "${MODELSCOPE_IMAGE}"
docker run --rm --network host --memory 4g --memory-swap 4g \
  -v "$(dirname -- "${MODEL_ROOT}"):/models" \
  "${MODELSCOPE_IMAGE}" sh -ec \
  "pip install --no-cache-dir modelscope==1.38.1 && modelscope download --model '${MODELSCOPE_MODEL}' --revision '${MODELSCOPE_REVISION}' --local_dir '/models/$(basename -- "${MODEL_ROOT}")' --max-workers 16"
verify_model
echo "Verified ModelScope snapshot: ${MODEL_ROOT}"
