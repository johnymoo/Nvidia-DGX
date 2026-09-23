#!/usr/bin/env bash
# GLM-5.3-Flash-NVFP4 stack — canonical status
echo "=== API ==="; curl -s -m 3 http://127.0.0.1:8890/v1/models | head -c 200; echo
echo "=== containers ==="
docker ps -a --format "{{.Names}}: {{.Status}}" | grep vllm_node || true
ssh -n admin@192.168.192.198 "docker ps -a --format \"{{.Names}}: {{.Status}}\" | grep vllm_node" || true
echo "=== KV line (last boot) ==="
grep -E "KV cache size|Maximum concurrency" /tmp/nvfp4-serve.log 2>/dev/null | tail -1
echo "=== memory ==="
grep MemAvailable /proc/meminfo
ssh -n admin@192.168.192.198 "grep MemAvailable /proc/meminfo"
