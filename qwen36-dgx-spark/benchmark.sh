#!/bin/bash
# Qwen3.6-35B-A3B 推理速度与质量测试脚本
# 支持 vLLM 和 llama.cpp 两种后端

set -e

API_URL="${API_URL:-http://localhost:8002/v1/chat/completions}"
MODEL="${MODEL:-Qwen3.6-35B-A3B-UD-Q4_K_S}"

echo "========================================"
echo "Qwen3.6-35B-A3B 推理测试"
echo "========================================"
echo "  API: $API_URL"
echo "  Model: $MODEL"
echo ""

# 辅助函数：发送请求并测量时间
benchmark_chat() {
    local prompt="$1"
    local max_tokens="$2"
    local label="$3"
    local temp="${4:-0.7}"

    echo "测试: $label (max_tokens=$max_tokens)"
    local start end duration tokens speed
    start=$(date +%s.%N)

    local response
    response=$(curl -s "$API_URL" \
        -H "Content-Type: application/json" \
        -d "{
            \"model\": \"$MODEL\",
            \"messages\": [{\"role\": \"user\", \"content\": \"$prompt\"}],
            \"max_tokens\": $max_tokens,
            \"temperature\": $temp
        }")

    end=$(date +%s.%N)
    duration=$(echo "$end - $start" | bc)
    tokens=$(echo "$response" | jq -r '.usage.completion_tokens // 0')
    speed=$(echo "scale=1; if ($duration > 0) then $tokens / $duration else 0 end" | bc)

    echo "  输出: ${tokens} tokens"
    echo "  时间: $(printf "%.2f" "$duration")s"
    echo "  速度: ${speed} tok/s"
    echo ""
}

# 1. Token 速度测试
echo "--- 1. Token 速度测试 ---"
benchmark_chat "用50字介绍北京" 100 "短文本 (100 tokens)"
benchmark_chat "写一篇500字的关于人工智能发展历史的文章" 500 "中文本 (500 tokens)"
benchmark_chat "写一篇2000字的关于人工智能从图灵测试到GPT的发展历史详细文章" 1000 "长文本 (1000 tokens)"

# 2. 推理准确性测试 (经典问题)
echo "--- 2. 推理准确性测试 ---"

ask_question() {
    local question="$1"
    local expected="$2"
    local label="$3"

    echo "问题: $label"
    local response
    response=$(curl -s "$API_URL" \
        -H "Content-Type: application/json" \
        -d "{
            \"model\": \"$MODEL\",
            \"messages\": [{\"role\": \"user\", \"content\": \"$question\"}],
            \"max_tokens\": 256,
            \"temperature\": 0.1
        }")

    local content
    content=$(echo "$response" | jq -r '.choices[0].message.content // empty')
    echo "  回答: ${content:0:100}..."

    if echo "$content" | grep -qi "$expected"; then
        echo "  ✓ 通过"
    else
        echo "  ✗ 未通过 (期望包含: $expected)"
    fi
    echo ""
}

ask_question "一个农民有17只羊，除了9只以外都死了，还剩几只？" "9" "羊的谜题"
ask_question "如果5台机器5分钟生产5个零件，那么100台机器生产100个零件需要多少分钟？" "5" "机器与零件"
ask_question "Sally有3个兄弟。每个兄弟有1个姐妹。Sally有几个姐妹？" "1" "Sally的姐妹"
ask_question "球拍和球一共11美元，球拍比球贵10美元，球多少钱？" "0.05" "球拍与球"
ask_question "三个盒子分别标为苹果、橙子、苹果和橙子，但所有标签都贴错了。你只能从一个盒子里拿出一个水果查看，如何正确重贴标签？" "苹果和橙子" "错标签盒子"
ask_question "最长递增子序列(LIS)的时间复杂度是什么？" "O(N log N)" "LIS复杂度"

# 3. API 功能测试
echo "--- 3. API 功能测试 ---"

# 关闭思考模式测试
ask_no_think() {
    echo "测试: /no_think 指令"
    local response
    response=$(curl -s "$API_URL" \
        -H "Content-Type: application/json" \
        -d "{
            \"model\": \"$MODEL\",
            \"messages\": [{\"role\": \"user\", \"content\": \"/no_think 1+1=?\"}],
            \"max_tokens\": 50,
            \"temperature\": 0.1
        }")
    local content
    content=$(echo "$response" | jq -r '.choices[0].message.content // empty')
    echo "  回答: $content"
    echo ""
}
ask_no_think

# 代码模式测试
ask_code() {
    echo "测试: 代码生成"
    local response
    response=$(curl -s "$API_URL" \
        -H "Content-Type: application/json" \
        -d "{
            \"model\": \"$MODEL\",
            \"messages\": [{\"role\": \"user\", \"content\": \"写一个Python函数，计算斐波那契数列的第n项\"}],
            \"max_tokens\": 512,
            \"temperature\": 0.6
        }")
    local tokens
    tokens=$(echo "$response" | jq -r '.usage.completion_tokens // 0')
    echo "  生成: ${tokens} tokens"
    echo ""
}
ask_code

echo "========================================"
echo "测试完成"
echo "========================================"
