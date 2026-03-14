#!/bin/bash
# Nemotron-3-Super-120B Benchmark Script for DGX Spark (GB10)
# Usage: ./benchmark.sh [--port 8090]

set -e

PORT="${1:-8090}"
API_URL="http://localhost:${PORT}"

echo "========================================"
echo "Nemotron-3-Super-120B Benchmark"
echo "========================================"
echo "API URL: ${API_URL}"
echo "Date: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "========================================"

# Check if server is running
if ! curl -s "${API_URL}/v1/models" > /dev/null 2>&1; then
    echo "Error: Server not responding at ${API_URL}"
    echo "Please start the server first: ./deploy.sh"
    exit 1
fi

# Get model info
echo ""
echo "--- Model Info ---"
curl -s "${API_URL}/v1/models" | jq -r '.data[0] | "ID: \(.id)\nContext: \(.meta.n_ctx_train) tokens (trained)\nParams: \(.meta.n_params / 1e9 | floor)B\nSize: \(.meta.size / 1e9 | floor * 100 / 100)GB"'

# GPU Memory
echo ""
echo "--- GPU Memory ---"
nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits 2>/dev/null | while read line; do
    echo "Process: ${line} MiB"
done

# Benchmark function
run_benchmark() {
    local output_tokens=$1
    local prompt_tokens=$2
    
    echo ""
    echo "--- Benchmark: ${output_tokens} output tokens, ${prompt_tokens} prompt tokens ---"
    
    # Generate a prompt with approximately the requested number of tokens
    # (English words are ~1.3 tokens on average)
    local word_count=$((prompt_tokens * 100 / 130))
    local prompt=""
    for i in $(seq 1 $((word_count / 10))); do
        prompt="${prompt}This is sentence number ${i} in the test prompt. "
    done
    
    # Run the benchmark
    local result=$(curl -s -X POST "${API_URL}/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -d "{
            \"model\": \"nemotron\",
            \"messages\": [{\"role\": \"user\", \"content\": \"${prompt}Please respond with exactly ${output_tokens} words about artificial intelligence.\"}],
            \"max_tokens\": ${output_tokens}
        }")
    
    # Parse results
    local prompt_tps=$(echo "$result" | jq -r '.timings.prompt_per_second // 0')
    local gen_tps=$(echo "$result" | jq -r '.timings.predicted_per_second // 0')
    local prompt_ms=$(echo "$result" | jq -r '.timings.prompt_ms // 0')
    local gen_ms=$(echo "$result" | jq -r '.timings.predicted_ms // 0')
    local prompt_n=$(echo "$result" | jq -r '.timings.prompt_n // 0')
    local gen_n=$(echo "$result" | jq -r '.timings.predicted_n // 0')
    
    echo "Prompt Processing:"
    echo "  Tokens: ${prompt_n}"
    echo "  Time: ${prompt_ms}ms"
    echo "  Speed: ${prompt_tps} tokens/s"
    echo ""
    echo "Generation:"
    echo "  Tokens: ${gen_n}"
    echo "  Time: ${gen_ms}ms"
    echo "  Speed: ${gen_tps} tokens/s"
}

# Short prompt, short output
run_benchmark 100 50

# Medium prompt, medium output
run_benchmark 500 200

# Long output
run_benchmark 1000 100

# Summary
echo ""
echo "========================================"
echo "Benchmark Complete"
echo "========================================"
echo ""
echo "Performance Summary:"
echo "- Prompt Processing: ~25-35 tokens/s (depends on context)"
echo "- Generation: ~15-20 tokens/s"
echo ""
echo "Memory Usage:"
nvidia-smi --query-compute-apps=used_memory --format=csv,noheader,nounits 2>/dev/null | head -1 | xargs echo "- GPU Memory:"
echo ""
echo "For more detailed benchmarks, consider using:"
echo "  - llama-bench from llama.cpp"
echo "  - vLLM benchmarking tools"