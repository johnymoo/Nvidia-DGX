# Qwen3.6-35B-A3B-FP8 on DGX Spark (GB10) - 部署与性能基准

## 概述

本文档记录 Qwen3.6-35B-A3B-FP8 在 NVIDIA DGX Spark (GB10) 上的 vLLM 部署配置和性能基准测试结果。

**关键特性**:
- FP8 量化（权重 + KV Cache）
- Tool Calling 支持（qwen3_coder parser）
- Reasoning/Thinking 模式控制
- Prefix Caching 加速重复 prompt

---

## 硬件环境

- **设备**: NVIDIA DGX Spark (GB10)
- **GPU**: NVIDIA GB10 (Blackwell, sm_121)
- **内存**: 128GB 统一内存
- **CUDA**: 13.0
- **Docker**: 用户已在 docker 组（无需 sudo）

---

## 模型信息

| 属性 | 值 |
|------|-----|
| **模型** | Qwen/Qwen3.6-35B-A3B-FP8 |
| **架构** | MoE (35B total, 3B active) |
| **量化** | FP8 (block size 128) |
| **大小** | ~35 GB |
| **上下文** | 262,144 tokens (可扩展到 1M+) |
| **精度** | 接近 BF16 原始模型 |

---

## 部署配置

### Docker Compose

```yaml
services:
  vllm-qwen36-fp8:
    image: vllm/vllm-openai:cu130-nightly
    container_name: vllm-qwen36-fp8
    restart: unless-stopped
    ports:
      - "8004:8000"
    volumes:
      - /home/chriswang/models/Qwen3.6-35B-A3B-FP8:/models:ro
      - /home/chriswang/.cache/huggingface:/root/.cache/huggingface
    environment:
      - HF_HOME=/root/.cache/huggingface
      - CUDA_VISIBLE_DEVICES=0
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    ipc: host
    shm_size: 64gb
    command: >
      /models
      --served-model-name qwen3.6-35b-fp8
      --port 8000
      --host 0.0.0.0
      --max-model-len 262144
      --gpu-memory-utilization 0.80
      --quantization fp8
      --dtype bfloat16
      --kv-cache-dtype fp8
      --reasoning-parser qwen3
      --enable-auto-tool-choice
      --tool-call-parser qwen3_coder
      --enable-prefix-caching
      --trust-remote-code
```

### 关键参数说明

| 参数 | 值 | 说明 |
|------|-----|------|
| `--gpu-memory-utilization` | 0.80 | GPU 内存使用率，留 20% 余量 |
| `--quantization fp8` | FP8 权重量化 | 减少模型内存占用 |
| `--kv-cache-dtype fp8` | FP8 KV Cache | 进一步减少内存 |
| `--reasoning-parser qwen3` | Qwen3 推理解析器 | 提取 thinking 内容 |
| `--tool-call-parser qwen3_coder` | Tool calling 解析器 | 支持函数调用 |
| `--enable-prefix-caching` | 启用前缀缓存 | 加速重复 prompt |

---

## 性能基准测试

### 测试环境

- **日期**: 2026-04-22
- **vLLM 版本**: v0.16.1rc1 (cu130-nightly)
- **测试脚本**: `benchmark_vllm_qwen36.py`
- **测试次数**: 每种配置 3 次运行取平均

### 测试结果摘要

| 测试场景 | 配置 | 平均速度 | 稳定性 (±) | 输出长度 |
|---------|------|---------|-----------|---------|
| Short prompt | default | **69.4 tok/s** | ±0.1 | ~163 tokens |
| Short prompt | greedy (T=0) | **70.6 tok/s** | ±0.1 | ~144 tokens |
| Medium prompt | default | **70.3 tok/s** | ±0.0 | 512 tokens |
| Medium prompt | greedy | **71.7 tok/s** | ±0.1 | 512 tokens |
| Long reasoning | default | **69.8 tok/s** | ±0.1 | 512 tokens |
| Long reasoning | greedy | **71.3 tok/s** | ±0.1 | 512 tokens |
| Code generation | default | **70.0 tok/s** | ±0.1 | 512 tokens |
| Code generation | greedy | **71.3 tok/s** | ±0.0 | 512 tokens |
| Reasoning ON | default | **70.1 tok/s** | ±0.1 | ~1652 tokens |
| Reasoning OFF | default | **70.0 tok/s** | ±0.0 | ~1639 tokens |

### 关键发现

1. **速度非常稳定**: 所有测试都在 69-72 tok/s 范围内，标准差 < 0.3
2. **Greedy 模式稍快**: T=0 时比 T=0.7 快约 1-2 tok/s
3. **Reasoning 模式影响**: 
   - ON: 输出更长（更多 thinking 内容），总时间增加
   - OFF: 输出更直接，速度稳定
4. **Tool calling 稳定性**: 本次测试未触发 JSON 解析错误

### 详细结果文件

完整结果: [`benchmark_results_20260422_133739.json`](./benchmark_results_20260422_133739.json)

---

## 与社区基准对比

| 配置 | 单流速度 | 来源 |
|------|---------|------|
| **本部署 (FP8)** | **~70 tok/s** | 实测 |
| Qwen3.5-FP8 @ vLLM | ~38 tok/s | llama.cpp discussion |
| Qwen3.6-BF16 @ spark-vllm-docker | ~50 tok/s | Reddit |
| AEON-7 NVFP4+DFlash | 83-127 tok/s | 推测解码 (heretic 模型) |

**结论**: 本部署在 FP8 配置下已达到非常优秀的性能，超过社区 BF16 报告。

---

## 已知问题

### 1. Tool Calling JSON 解析错误

**症状**:
```
json.decoder.JSONDecodeError: Unterminated string starting at: line 1 column 61
```

**位置**: `vllm/entrypoints/chat_utils.py:1516`

**影响**: 某些 tool calling 请求会失败

**状态**: vLLM v0.16.1 已知问题，v0.19+ 已修复 (PR #35347)

** workaround**:
- 升级到 vLLM v0.19+
- 或使用 `--tool-call-parser qwen35_coder`（如果可用）

### 2. MoE 配置警告

**症状**:
```
WARNING: Using default MoE config. Performance might be sub-optimal!
```

**影响**: 可能有 5-10% 性能损失

**状态**: vLLM 尚未为 GB10+FP8 提供最优 MoE kernel 配置

---

## 优化建议

### 短期（无需停机）

1. **调整采样参数**
   - Greedy (T=0) 可获得最高速度（71+ tok/s）
   - 生产环境建议 T=0.7, top_p=0.95

2. **启用 Prefix Caching**
   - 已启用，命中率 83.4%
   - 对重复 prompt 加速明显

### 中期（需要重启）

3. **升级 vLLM 到 v0.19+**
   - 修复 tool calling JSON 解析问题
   - V1 Engine 性能提升
   - 更好的 Qwen3.6 支持

4. **尝试 MARLIN FP8 Backend**
   ```bash
   -e VLLM_TEST_FORCE_FP8_MARLIN=1
   ```
   - 社区报告 SM121 上比 TRITON 快 10-20%

5. **启用 MTP 推测解码**
   ```bash
   --speculative-config '{"method":"qwen3_next_mtp","num_speculative_tokens":2}'
   ```
   - 可能提升 20-40% 单流速度

### 长期（考虑替换模型）

6. **NVFP4 量化**
   - 模型更小 (~22GB vs ~35GB)
   - 更多内存给 KV cache
   - 需要 AEON-7 定制镜像或等待官方支持

---

## 快速开始

### 启动服务

```bash
cd ~/docker/vllm-qwen36-fp8
docker compose up -d
```

### 测试 API

```bash
# 查看模型信息
curl http://localhost:8004/v1/models

# 简单对话
curl http://localhost:8004/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.6-35b-fp8",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 512
  }'

# 禁用 reasoning
curl http://localhost:8004/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.6-35b-fp8",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 512,
    "extra_body": {"chat_template_kwargs": {"enable_thinking": false}}
  }'
```

### 运行 Benchmark

```bash
python3 benchmark_vllm_qwen36.py
```

---

## 文件清单

| 文件 | 说明 |
|------|------|
| `README.md` | 本文件 |
| `docker-compose.yml` | 部署配置 |
| `benchmark_vllm_qwen36.py` | 性能测试脚本 |
| `benchmark_results_20260422_133739.json` | 基准测试结果 |
| `CONFIG.md` | 系统配置参考 |

---

## 参考资源

- [Qwen3.6 官方文档](https://qwen.ai/blog?id=qwen3.6-35b-a3b)
- [Qwen3.6-FP8 HuggingFace](https://huggingface.co/Qwen/Qwen3.6-35B-A3B-FP8)
- [vLLM Qwen Recipes](https://docs.vllm.ai/projects/recipes/en/latest/Qwen/Qwen3.5.html)
- [NVIDIA DGX Spark 论坛](https://forums.developer.nvidia.com/c/dgx-spark/)
- [AEON-7 NVFP4+DFlash 方案](https://github.com/AEON-7/Qwen3.6-NVFP4-DFlash)

---

## 更新记录

| 日期 | 变更 |
|------|------|
| 2026-04-17 | 初始部署 |
| 2026-04-22 | 添加性能基准测试 |

---

*本项目的贡献规则遵循仓库根目录 [README.md](../README.md) 中的「仓库贡献规则」章节。*
