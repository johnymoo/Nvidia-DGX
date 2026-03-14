#!/bin/bash
# Nemotron-3-Super-120B Deployment Script for DGX Spark (GB10)
# Usage: ./deploy.sh [--context 16k|200k] [--port 8090]

set -e

# Configuration
MODEL_DIR="${MODEL_DIR:-$HOME/models/nemotron-super-modelscope}"
MODEL_FILE="NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-00001-of-00003.gguf"
LLAMA_CPP_DIR="${LLAMA_CPP_DIR:-$HOME/llama.cpp}"
CONTEXT="${1:-200k}"
PORT="${2:-8090}"
HOST="${3:-0.0.0.0}"

# Parse context
case "$CONTEXT" in
    16k|16K)
        CONTEXT_SIZE=16384
        ;;
    200k|200K)
        CONTEXT_SIZE=200000
        ;;
    *)
        echo "Usage: $0 [--context 16k|200k] [--port PORT]"
        echo "Invalid context: $CONTEXT. Use 16k or 200k."
        exit 1
        ;;
esac

echo "========================================"
echo "Nemotron-3-Super-120B Deployment"
echo "========================================"
echo "Context: ${CONTEXT_SIZE} tokens"
echo "Port: ${PORT}"
echo "Model: ${MODEL_DIR}/UD-Q4_K_XL/${MODEL_FILE}"
echo "========================================"

# Check if model exists
if [ ! -f "${MODEL_DIR}/UD-Q4_K_XL/${MODEL_FILE}" ]; then
    echo "Error: Model not found at ${MODEL_DIR}/UD-Q4_K_XL/${MODEL_FILE}"
    echo ""
    echo "Please download the model first:"
    echo "  # From ModelScope (recommended for China)"
    echo "  pip install modelscope"
    echo "  python3 -c \"from modelscope import snapshot_download; snapshot_download('ggml-org/nemotron-3-super-120b-GGUF', local_dir='${MODEL_DIR}')\""
    echo ""
    echo "  # Or from Hugging Face"
    echo "  git lfs install && git clone https://huggingface.co/ggml-org/nemotron-3-super-120b-GGUF ${MODEL_DIR}"
    exit 1
fi

# Check if llama.cpp is built
if [ ! -f "${LLAMA_CPP_DIR}/build/bin/llama-server" ]; then
    echo "Error: llama-server not found at ${LLAMA_CPP_DIR}/build/bin/llama-server"
    echo ""
    echo "Please build llama.cpp first:"
    echo "  git clone https://github.com/ggml-org/llama.cpp ${LLAMA_CPP_DIR}"
    echo "  cd ${LLAMA_CPP_DIR}"
    echo "  cmake -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=121"
    echo "  cmake --build build --config Release -j\$(nproc)"
    exit 1
fi

# Kill existing process if any
EXISTING_PID=$(pgrep -f "llama-server.*${PORT}" 2>/dev/null || true)
if [ -n "$EXISTING_PID" ]; then
    echo "Stopping existing llama-server (PID: $EXISTING_PID)..."
    kill "$EXISTING_PID" 2>/dev/null || true
    sleep 2
fi

# Start the server
echo ""
echo "Starting llama-server..."
echo ""

cd "${MODEL_DIR}/UD-Q4_K_XL"

nohup "${LLAMA_CPP_DIR}/build/bin/llama-server" \
    -m "${MODEL_FILE}" \
    -ngl 99 \
    -c "${CONTEXT_SIZE}" \
    --host "${HOST}" \
    --port "${PORT}" \
    -fa on \
    > /tmp/llama-server.log 2>&1 &

SERVER_PID=$!
echo "Server PID: ${SERVER_PID}"
echo "Log file: /tmp/llama-server.log"

# Wait for server to start
echo ""
echo "Waiting for server to start..."
MAX_WAIT=60
WAIT_COUNT=0

while [ $WAIT_COUNT -lt $MAX_WAIT ]; do
    if curl -s "http://localhost:${PORT}/v1/models" > /dev/null 2>&1; then
        echo ""
        echo "✅ Server is ready!"
        echo ""
        echo "API Endpoints:"
        echo "  Models:  GET http://localhost:${PORT}/v1/models"
        echo "  Chat:    POST http://localhost:${PORT}/v1/chat/completions"
        echo ""
        echo "Test command:"
        echo "  curl http://localhost:${PORT}/v1/models | jq"
        echo ""
        echo "To stop the server:"
        echo "  kill ${SERVER_PID}"
        exit 0
    fi
    sleep 1
    WAIT_COUNT=$((WAIT_COUNT + 1))
    printf "."
done

echo ""
echo "❌ Server failed to start within ${MAX_WAIT} seconds"
echo "Check log file: /tmp/llama-server.log"
exit 1