#!/bin/bash
# Qwen3.6-35B-A3B llama.cpp 部署脚本 (DGX Spark / GB10)
# 支持 128K 和 256K 上下文配置
# 使用本地编译的 llama.cpp (版本 9789c4e, 支持 CUDA sm_121 和 qwen35moe 架构)

set -e

MODEL_PATH="${MODEL_PATH:-/home/chriswang/models/qwen36-q4ks/Qwen3.6-35B-A3B-UD-Q4_K_S.gguf}"
LLAMA_BIN="${LLAMA_BIN:-~/project/llama.cpp/build/bin/llama-server}"
PORT="${PORT:-8002}"
CONTEXT="${CONTEXT:-128000}"   # 支持 128000 或 256000

echo "=================================="
echo "Qwen3.6-35B-A3B llama.cpp 部署"
echo "=================================="
echo "  上下文: ${CONTEXT} tokens"
echo "  端口: ${PORT}"
echo ""

# 检查模型文件
if [ ! -f "$MODEL_PATH" ]; then
    echo "错误: 模型文件不存在: $MODEL_PATH"
    echo "请下载 GGUF 模型:"
    echo "  modelscope download --model unsloth/Qwen3.6-35B-A3B-GGUF --local_dir ~/models/qwen36-q4ks"
    exit 1
fi

# 检查 llama-server
if [ ! -f "$LLAMA_BIN" ]; then
    echo "错误: llama-server 未找到: $LLAMA_BIN"
    echo "请先编译 llama.cpp:"
    echo "  cd ~/project/llama.cpp"
    echo "  cmake -B build -DGGML_CUDA=ON"
    echo "  cmake --build build --config Release -j\$(nproc)"
    exit 1
fi

echo "[1/2] 停止已有服务..."
pkill -f "llama-server.*Qwen3.6" 2>/dev/null || true
sleep 2

echo "[2/2] 启动 llama-server (上下文 ${CONTEXT})..."

# 注意：
# - -fa on 必须带 on，否则贪婪消费下一个参数
# --reasoning off 关闭默认思考模式，避免 API 返回空 content
# -ngl 99 将所有层卸载到 GPU
# --jinja 启用 Jinja 模板支持

nohup "$LLAMA_BIN" \
  -m "$MODEL_PATH" \
  --host 0.0.0.0 \
  --port "$PORT" \
  -ngl 99 \
  -fa on \
  -c "$CONTEXT" \
  --jinja \
  --reasoning off \
  > "/tmp/llama36-${CONTEXT}.log" 2>&1 &

PID=$!
echo "  PID: $PID"
echo "  等待服务启动..."

for i in {1..30}; do
    if curl -s "http://localhost:$PORT/health" > /dev/null 2>&1; then
        echo "✓ 服务已启动"
        echo "  API: http://localhost:$PORT/v1/chat/completions"
        echo "  日志: /tmp/llama36-${CONTEXT}.log"
        echo ""
        echo "内存占用预估 (@ ${CONTEXT} 上下文):"
        if [ "$CONTEXT" -ge 256000 ]; then
            echo "  模型权重 (Q4_K_S): ~19.4 GB"
            echo "  KV cache (10 全注意力层): ~5.0 GB"
            echo "  DeltaNet 循环状态 (30 层): ~0.25 GB"
            echo "  计算缓冲区: ~0.8 GB"
            echo "  总计 GPU: ~26 GB"
        else
            echo "  模型权重 (Q4_K_S): ~19.4 GB"
            echo "  KV cache (10 全注意力层): ~2.5 GB"
            echo "  DeltaNet 循环状态 (30 层): ~0.25 GB"
            echo "  计算缓冲区: ~0.8 GB"
            echo "  总计 GPU: ~23 GB"
        fi
        exit 0
    fi
    sleep 1
done

echo "✗ 服务启动失败，查看日志:"
tail -50 "/tmp/llama36-${CONTEXT}.log"
exit 1
