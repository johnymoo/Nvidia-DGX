#!/usr/bin/env bash
# Read-only symptom watch over vLLM container logs (design §5.2/§5.7). The
# symptom-gated correctness workarounds (DSPARK_ENABLE_ISSUE141_SPARSE_MLA_CHUNK,
# DSPARK_ENABLE_ASSISTANT_FINAL_HOTFIX, ISSUE136_XGRAMMAR, ...; see
# planning/02-working/2026-09-04-dspark-upstream-feature-survey.md) stay off
# until their symptom is actually observed here.
#
# Grep-detectable symptoms:
#   dsml_markup       -- DSML/CJK markup leaking into generated text
#                        (Issue #21/#26/#36/#52)
#   nccl_cuda_oom     -- NCCL/CUDA errors, OOM kills, tracebacks
#   jit_in_inference  -- torch.compile / CUDA graph capture logged after
#                        startup (should only happen once, at boot)
#
# NOT grep-detectable from logs alone: the sparse-MLA stall (Issue #141) is
# silent -- a frozen batch or truncated stream with no error line at all --
# and "grammar tokens after termination" needs finish_reason accounting, not
# a log pattern. Those are covered by suite.py's `no_missing_finish_reason`
# gate and metrics.py's request_success/finished_reason tracking instead.
set -euo pipefail

CONTAINER="${EVAL_CONTAINER:-}"
if [ -z "$CONTAINER" ]; then
  echo "loghealth: EVAL_CONTAINER is not set (see eval.env.example)" >&2
  exit 2
fi
SINCE="${LOGHEALTH_SINCE:-30m}"
SSH_ALIAS="${1:-}"
DOCKER_BIN="${DOCKER_BIN:-docker}"

run_logs() {
  if [ -n "$SSH_ALIAS" ]; then
    ssh "$SSH_ALIAS" "$DOCKER_BIN logs --since $SINCE $CONTAINER" 2>&1
  else
    "$DOCKER_BIN" logs --since "$SINCE" "$CONTAINER" 2>&1
  fi
}

count() {
  printf '%s\n' "$logs" | grep -cE "$1" || true
}

logs="$(run_logs)" || { echo "loghealth: could not read logs for $CONTAINER" >&2; exit 2; }

dsml_markup=$(count 'DSML')
nccl_cuda_oom=$(count 'NCCL error|CUDA error|CUDA out of memory|out of memory|OOM|Traceback \(most recent call last\)')
jit_in_inference=$(count 'torch\.compile|Capturing CUDA graph|Recompiling')

echo "container=$CONTAINER since=$SINCE"
echo "dsml_markup=$dsml_markup"
echo "nccl_cuda_oom=$nccl_cuda_oom"
echo "jit_in_inference=$jit_in_inference"

total=$((dsml_markup + nccl_cuda_oom + jit_in_inference))
if [ "$total" -gt 0 ]; then
  echo "loghealth: symptom(s) observed ($total match(es)); review before enabling any symptom-gated flag" >&2
  exit 1
fi
echo "loghealth: clean"
