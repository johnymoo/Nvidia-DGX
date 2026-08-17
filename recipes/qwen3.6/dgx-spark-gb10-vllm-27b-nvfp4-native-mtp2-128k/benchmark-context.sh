#!/bin/bash
# Qwen3.6-35B-A3B 上下文长度压力测试脚本
# 测试从 4K 到 250K 的上下文处理能力

set -e

API_URL="${API_URL:-http://localhost:8002/v1/chat/completions}"
MODEL="${MODEL:-Qwen3.6-35B-A3B-UD-Q4_K_S}"

echo "========================================"
echo "Qwen3.6-35B-A3B 上下文压力测试"
echo "========================================"
echo "  API: $API_URL"
echo "  Model: $MODEL"
echo ""

# 生成重复文本作为长上下文 prompt
generate_prompt() {
    local target_tokens="$1"
    local sentence="The quick brown fox jumps over the lazy dog. "
    # 每个句子约 10 tokens，需要重复 target_tokens/10 次
    local repeats=$((target_tokens / 10))
    python3 -c "
sentence = '$sentence'
print(sentence * $repeats)
"
}

# 测试不同上下文长度
test_context() {
    local target_tokens="$1"
    local label="$2"

    echo "--- 测试 $label (目标 ~${target_tokens} tokens) ---"

    # 生成 prompt
    local prompt
    prompt=$(generate_prompt "$target_tokens")

    # 先 tokenize 确认长度
    local token_count
    token_count=$(curl -s "${API_URL//v1\/chat\/completions/\/tokenize}" \
        -H "Content-Type: application/json" \
        -d "{\"content\": \"$prompt\"}" | jq '.tokens | length')
    echo "  实际 prompt tokens: $token_count"

    # 发送请求并测量
    local start end duration ttft gen_speed
    start=$(date +%s.%N)

    local response
    response=$(curl -s "$API_URL" \
        -H "Content-Type: application/json" \
        -d "{
            \"model\": \"$MODEL\",
            \"messages\": [
                {\"role\": \"system\", \"content\": \"你是一个助手，请根据用户提供的文本回答问题。\"},
                {\"role\": \"user\", \"content\": \"$prompt\\n\\n请用一句话总结上文。\"}
            ],
            \"max_tokens\": 50,
            \"temperature\": 0.1,
            \"stream\": false
        }")

    end=$(date +%s.%N)
    duration=$(echo "$end - $start" | bc)

    # 检查结果
    local completion_tokens total_tokens error
    completion_tokens=$(echo "$response" | jq -r '.usage.completion_tokens // 0')
    total_tokens=$(echo "$response" | jq -r '.usage.total_tokens // 0')
    error=$(echo "$response" | jq -r '.error.message // empty')

    if [ -n "$error" ]; then
        echo "  ✗ 错误: $error"
        return 1
    fi

    # TTFT ≈ 总时间（因为生成内容很短）
    ttft=$(printf "%.2f" "$duration")
    gen_speed=$(echo "scale=1; if ($duration > 0) then $completion_tokens / $duration else 0 end" | bc)

    echo "  总 tokens: $total_tokens"
    echo "  生成 tokens: $completion_tokens"
    echo "  总时间: ${ttft}s"
    echo "  生成速度: ${gen_speed} tok/s"
    echo "  ✓ 通过"
    echo ""
}

# 运行测试序列
test_context 4096 "4K"
test_context 16384 "16K"
test_context 32768 "32K"
test_context 65536 "64K"
test_context 100000 "100K"
test_context 120000 "120K"
test_context 250000 "250K"

echo "========================================"
echo "上下文压力测试完成"
echo "========================================"
