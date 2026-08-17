#!/bin/bash
# 一键部署脚本

set -e

MODEL_PATH="${MODEL_PATH:-~/models/Qwen/Qwen3___5-9B}"
GGUF_PATH="${GGUF_PATH:-~/models/gguf}"
LLAMA_PORT="${LLAMA_PORT:-8081}"

echo "=================================="
echo "Qwen3.5 DGX Spark 部署脚本"
echo "=================================="
echo ""

# 检查依赖
check_dependencies() {
    echo "[1/5] 检查依赖..."
    
    if ! command -v nvcc &> /dev/null; then
        export PATH="/usr/local/cuda-13.0/bin:$PATH"
    fi
    
    if ! command -v nvcc &> /dev/null; then
        echo "错误: CUDA 未找到"
        exit 1
    fi
    
    echo "  ✓ CUDA 可用: $(nvcc --version | grep release)"
}

# 编译 llama.cpp
build_llama() {
    echo ""
    echo "[2/5] 编译 llama.cpp..."
    
    if [ ! -d ~/llama.cpp ]; then
        git clone --depth 1 https://github.com/ggml-org/llama.cpp.git ~/llama.cpp
    fi
    
    cd ~/llama.cpp
    
    if [ ! -f build/bin/llama-server ]; then
        export PATH="/usr/local/cuda-13.0/bin:$PATH"
        export CUDACXX=/usr/local/cuda-13.0/bin/nvcc
        cmake -B build -DGGML_CUDA=ON
        cmake --build build --config Release -j$(nproc)
        echo "  ✓ 编译完成"
    else
        echo "  ✓ 已编译"
    fi
}

# 转换模型
convert_model() {
    echo ""
    echo "[3/5] 转换模型..."
    
    mkdir -p $GGUF_PATH
    
    if [ ! -f $GGUF_PATH/Qwen3.5-9B-Q4_K_M.gguf ]; then
        if [ ! -f $GGUF_PATH/Qwen3.5-9B-f16.gguf ]; then
            echo "  转换为 F16..."
            pip install transformers torch numpy sentencepiece protobuf --break-system-packages -q
            python3 ~/llama.cpp/convert_hf_to_gguf.py \
                $MODEL_PATH \
                --outfile $GGUF_PATH/Qwen3.5-9B-f16.gguf \
                --outtype f16
        fi
        
        echo "  量化为 Q4_K_M..."
        ~/llama.cpp/build/bin/llama-quantize \
            $GGUF_PATH/Qwen3.5-9B-f16.gguf \
            $GGUF_PATH/Qwen3.5-9B-Q4_K_M.gguf \
            Q4_K_M
        
        echo "  ✓ 转换完成"
    else
        echo "  ✓ 模型已存在"
    fi
}

# 启动服务
start_server() {
    echo ""
    echo "[4/5] 启动 llama-server..."
    
    # 停止已有服务
    pkill -f "llama-server" 2>/dev/null || true
    sleep 2
    
    ~/llama.cpp/build/bin/llama-server \
        -m $GGUF_PATH/Qwen3.5-9B-Q4_K_M.gguf \
        -c 8192 \
        --host 0.0.0.0 \
        --port $LLAMA_PORT \
        -ngl 35 \
        --no-mmap \
        > /tmp/llama_server.log 2>&1 &
    
    echo "  等待服务启动..."
    for i in {1..30}; do
        if curl -s http://localhost:$LLAMA_PORT/health > /dev/null 2>&1; then
            echo "  ✓ 服务已启动 (PID: $!)"
            echo "  API: http://localhost:$LLAMA_PORT/v1/chat/completions"
            return 0
        fi
        sleep 1
    done
    
    echo "  ✗ 服务启动失败"
    cat /tmp/llama_server.log
    exit 1
}

# 运行测试
run_benchmark() {
    echo ""
    echo "[5/5] 运行性能测试..."
    
    if [ -f ./benchmark.sh ]; then
        ./benchmark.sh
    else
        echo "  benchmark.sh 不存在，跳过测试"
    fi
}

# 主流程
main() {
    check_dependencies
    build_llama
    convert_model
    start_server
    run_benchmark
    
    echo ""
    echo "=================================="
    echo "部署完成!"
    echo "=================================="
    echo ""
    echo "使用方法:"
    echo "  curl http://localhost:$LLAMA_PORT/v1/chat/completions \\"
    echo "    -H 'Content-Type: application/json' \\"
    echo "    -d '{\"model\": \"Qwen3.5-9B-Q4_K_M\", \"messages\": [{\"role\": \"user\", \"content\": \"你好\"}]}'"
    echo ""
}

main "$@"
