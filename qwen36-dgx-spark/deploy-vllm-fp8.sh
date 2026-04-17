#!/bin/bash
# Qwen3.6-35B-A3B-FP8 vLLM 部署脚本 (DGX Spark / GB10)
# 使用官方 FP8 量化模型 + vLLM nightly 镜像

set -e

MODEL_PATH="${MODEL_PATH:-/home/chriswang/models/Qwen3.6-35B-A3B-FP8}"
PORT="${PORT:-8004}"
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.80}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-262144}"

echo "=================================="
echo "Qwen3.6-35B-A3B-FP8 vLLM 部署"
echo "=================================="
echo ""

# 检查模型文件
if [ ! -d "$MODEL_PATH" ]; then
    echo "错误: 模型目录不存在: $MODEL_PATH"
    echo "请先从 HuggingFace 或 ModelScope 下载模型:"
    echo "  modelscope download --model Qwen/Qwen3.6-35B-A3B-FP8 --local_dir ~/models/Qwen3.6-35B-A3B-FP8"
    exit 1
fi

echo "[1/3] 检查 Docker 环境..."
if ! command -v docker &> /dev/null; then
    echo "错误: Docker 未安装"
    exit 1
fi

echo "[2/3] 拉取 vLLM nightly 镜像..."
docker pull vllm/vllm-openai:cu130-nightly

echo "[3/3] 启动 vLLM 服务..."
docker run -d \
  --name vllm-qwen36-fp8 \
  --restart unless-stopped \
  --gpus all \
  --ipc host \
  --shm-size 64gb \
  -p "$PORT:8000" \
  -v "$MODEL_PATH:/models:ro" \
  -e HF_HOME=/tmp \
  -e CUDA_VISIBLE_DEVICES=0 \
  vllm/vllm-openai:cu130-nightly \
  /models \
  --served-model-name qwen3.6-35b-fp8 \
  --port 8000 \
  --host 0.0.0.0 \
  --max-model-len "$MAX_MODEL_LEN" \
  --gpu-memory-utilization "$GPU_MEM_UTIL" \
  --quantization fp8 \
  --dtype bfloat16 \
  --kv-cache-dtype fp8 \
  --reasoning-parser qwen3 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --enable-prefix-caching \
  --trust-remote-code

echo ""
echo "等待服务启动（首次启动需要 ~10-15 分钟捕获 CUDA graphs）..."
for i in {1..120}; do
    if curl -s "http://localhost:$PORT/health" > /dev/null 2>&1; then
        echo "✓ 服务已启动"
        echo "  API: http://localhost:$PORT/v1/chat/completions"
        echo "  Model: qwen3.6-35b-fp8"
        exit 0
    fi
    sleep 5
done

echo "✗ 服务启动超时，查看日志:"
docker logs vllm-qwen36-fp8 --tail 50
exit 1
