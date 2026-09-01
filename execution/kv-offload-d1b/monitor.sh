#!/usr/bin/env bash
# 60s-interval campaign monitor. Usage: monitor.sh <outfile>
# Stop with: touch <outfile>.stop
set -u
OUT="$1"
while [ ! -f "$OUT.stop" ]; do
  {
    echo "--- $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    ssh gb10 'docker ps --format "{{.Names}} {{.Status}}" | grep dspark; free -g | awk "/Mem:/{print \"gb10 avail_g=\" \$7}"; TZ=UTC journalctl -k --since "-2 min" --no-pager 2>/dev/null | grep -Ei "Xid|oom|NV_ERR" | tail -5' 2>&1
    ssh gb10-2 'docker ps --format "{{.Names}} {{.Status}}" | grep dspark; free -g | awk "/Mem:/{print \"gb10-2 avail_g=\" \$7}"; TZ=UTC journalctl -k --since "-2 min" --no-pager 2>/dev/null | grep -Ei "Xid|oom|NV_ERR" | tail -5' 2>&1
    curl -m 5 -fsS http://192.168.88.181:8890/v1/models >/dev/null 2>&1 && echo "api=200" || echo "api=FAIL"
    curl -m 5 -fsS http://192.168.88.181:8890/metrics 2>/dev/null | grep -E "^vllm:(kv_offload|num_requests_(running|waiting)|prefix_cache_(queries|hits)_total)" | head -12
    ssh gb10 'docker logs --since 2m gb10-deepseek-v4-vllm-dspark-1 2>&1 | grep -Ei "CUDA error|OOM|Traceback|kv_load_fail" | tail -5' 2>&1
    ssh gb10-2 'docker logs --since 2m gb10-deepseek-v4-vllm-dspark-1 2>&1 | grep -Ei "CUDA error|OOM|Traceback|kv_load_fail" | tail -5' 2>&1
  } >> "$OUT"
  sleep 60
done
echo "monitor stopped $(date -u +%FT%TZ)" >> "$OUT"
