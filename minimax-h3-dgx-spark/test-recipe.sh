#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY="$ROOT/execution/minimax-h3"
BENCH="$ROOT/execution/minimax-h3-benchmark"

bash -n "$DEPLOY"/*.sh "$BENCH"/*.sh
python3 -m py_compile "$DEPLOY"/*.py "$BENCH"/*.py "$ROOT/sanitize-results.py"

summary="$(bash -c 'source "$1/lib.sh"; h3_validate_manifest "$1/weights-manifest.tsv"' _ "$DEPLOY")"
[[ "$summary" == $'11\t176195310067' ]]

disabled="$(bash -c 'source "$1/runtime-lib.sh"; h3_protected_status' _ "$DEPLOY")"
jq -e '.enabled == false and .matches == true' <<<"$disabled" >/dev/null

jq -e '
  .schema_version == 1 and
  (.profiles | length) == 1 and
  .profiles[0].id == "trained-max-15s" and
  .profiles[0].frames == 362 and
  (.cases | length) == 9
' "$BENCH/cases.json" >/dev/null

jq -e '
  .status == "passed" and
  (.provenance.raw_receipt_sha256 | length) == 64 and
  .subject.weight_files == 11 and
  .subject.weight_bytes == 176195310067 and
  .profile.frames == 362 and
  .summary.successful == 9 and
  .summary.reproducibility.decoded_frames_equal == true and
  (.cases | length) == 9
' "$ROOT/benchmark-results.json" >/dev/null

grep -q 'expected_installer_sha="83405c98203d8f7d7f5e57be58a2810665b06d3f6e9ea9f174a058a6bedec37a"' \
  "$DEPLOY/install-upstream-recipe.sh"
grep -q "if 'pkill -f' in text or '/tmp/keys-heretic-tmp' in text" \
  "$DEPLOY/install-upstream-recipe.sh"
grep -q 'cleanup_unreceipted' "$DEPLOY/start-comfyui.sh"
python3 "$ROOT/test-start-cleanup.py"

fixture="$ROOT/benchmark-results.json"
python3 - "$ROOT/sanitize-results.py" "$fixture" <<'PY'
import importlib.util
import json
import sys

spec = importlib.util.spec_from_file_location("sanitize_results", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
published = json.load(open(sys.argv[2]))
assert published["provenance"]["raw_receipt_sha256"] == \
    "8974fa3d6f8c2b024c1e2721c61d66b2add498db8b07d66ce056f86fe83a85da"
assert all("source_path" not in case for case in published["cases"])
assert all(len(case["video_sha256"]) == 64 for case in published["cases"])
PY

"$BENCH/test-benchmark.sh" >/dev/null
python3 - "$BENCH/benchmark.py" <<'PY'
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("benchmark", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
value = module.public_runtime({
    "pid": 1, "start_ticks": 2, "boot_id": "boot",
    "started_at": "time", "http_code": "200", "listener": "listener",
    "protected": {"enabled": False, "matches": True, "observed": {}},
})
assert value["protected"] == {
    "enabled": False, "matches": True, "container_id": None,
    "health": None, "restart_count": None,
}
PY
printf 'passed\n'
