#!/bin/bash
# Qwen3.5 llama.cpp 推理速度测试脚本

API_URL="http://localhost:8081/v1/chat/completions"
MODEL="Qwen3.5-9B-Q4_K_M"

echo "========================================"
echo "Qwen3.5 llama.cpp 推理速度测试"
echo "========================================"
echo ""

# 测试 1: 100 tokens
echo "测试 1: 生成 100 tokens"
START_TIME=$(date +%s.%N)
RESPONSE=$(curl -s $API_URL \
  -H "Content-Type: application/json" \
  -d '{
    "model": "'"$MODEL"'",
    "messages": [{"role": "user", "content": "用50字介绍北京"}],
    "max_tokens": 100,
    "temperature": 0.7
  }')
END_TIME=$(date +%s.%N)

COMPLETION_TOKENS=$(echo $RESPONSE | jq -r '.usage.completion_tokens')
TIME=$(echo "$END_TIME - $START_TIME" | bc)
SPEED=$(echo "scale=1; $COMPLETION_TOKENS / $TIME" | bc)

echo "  输出: $COMPLETION_TOKENS tokens"
echo "  时间: $(printf "%.2f" $TIME)s"
echo "  速度: $SPEED tok/s"
echo ""

# 测试 2: 500 tokens
echo "测试 2: 生成 500 tokens"
START_TIME=$(date +%s.%N)
RESPONSE=$(curl -s $API_URL \
  -H "Content-Type: application/json" \
  -d '{
    "model": "'"$MODEL"'",
    "messages": [{"role": "user", "content": "写一篇500字的关于人工智能发展历史的文章"}],
    "max_tokens": 500,
    "temperature": 0.7
  }')
END_TIME=$(date +%s.%N)

COMPLETION_TOKENS=$(echo $RESPONSE | jq -r '.usage.completion_tokens')
TIME=$(echo "$END_TIME - $START_TIME" | bc)
SPEED=$(echo "scale=1; $COMPLETION_TOKENS / $TIME" | bc)

echo "  输出: $COMPLETION_TOKENS tokens"
echo "  时间: $(printf "%.2f" $TIME)s"
echo "  速度: $SPEED tok/s"
echo ""

# 测试 3: 1000 tokens
echo "测试 3: 生成 1000 tokens"
START_TIME=$(date +%s.%N)
RESPONSE=$(curl -s $API_URL \
  -H "Content-Type: application/json" \
  -d '{
    "model": "'"$MODEL"'",
    "messages": [{"role": "user", "content": "写一篇2000字的关于人工智能从图灵测试到GPT的发展历史详细文章"}],
    "max_tokens": 1000,
    "temperature": 0.7
  }')
END_TIME=$(date +%s.%N)

COMPLETION_TOKENS=$(echo $RESPONSE | jq -r '.usage.completion_tokens')
TIME=$(echo "$END_TIME - $START_TIME" | bc)
SPEED=$(echo "scale=1; $COMPLETION_TOKENS / $TIME" | bc)

echo "  输出: $COMPLETION_TOKENS tokens"
echo "  时间: $(printf "%.2f" $TIME)s"
echo "  速度: $SPEED tok/s"
echo ""

echo "========================================"
echo "测试完成"
echo "========================================"
