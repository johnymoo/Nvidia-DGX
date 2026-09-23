#!/usr/bin/env bash
# GLM-5.3-Flash-NVFP4 stack — canonical stop (head first, then worker)
set -uo pipefail
pkill -f "run-recipe.py recipes/glm-5.3-flash.yaml" 2>/dev/null && echo "launcher killed" || echo "no launcher"
sleep 1
docker stop vllm_node && echo "head vllm_node stopped"
ssh -n admin@192.168.192.198 "docker stop vllm_node" && echo "worker vllm_node stopped"
free -g | head -2
