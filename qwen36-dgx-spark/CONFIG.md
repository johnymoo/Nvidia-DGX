# DGX Spark (GB10) Qwen3.6 系统配置

## 硬件配置

| 组件 | 规格 |
|------|------|
| **设备** | NVIDIA DGX Spark (Project DIGITS) |
| **GPU** | NVIDIA GB10 (Blackwell架构, SM121) |
| **GPU 显存** | 128GB 统一内存 (VRAM + 系统内存共享) |
| **内存带宽** | 273 GB/s (LPDDR5X) |
| **存储** | 3.7TB NVMe SSD |
| **CPU** | 20核 ARM64 (Neoverse V2) |
| **CUDA** | 12.1 |
| **NVIDIA 驱动** | 580.126.09 |

## 模型信息

| 模型 | 路径 | 大小 | 格式 | 说明 |
|------|------|------|------|------|
| Qwen3.6-35B-A3B-FP8 | `~/models/Qwen3.6-35B-A3B-FP8` | ~35 GB | Safetensors | 官方 FP8 量化 |
| Qwen3.6-35B-A3B-Q4_K_S | `~/models/qwen36-q4ks/Qwen3.6-35B-A3B-UD-Q4_K_S.gguf` | ~19.4 GB | GGUF | Unsloth 量化 |

### 模型架构特点

- **总参数量**: 35B (MoE 架构)
- **激活参数量**: 3B
- **注意力机制**: 混合架构
  - 30 层 DeltaNet 线性注意力 (固定大小循环状态)
  - 10 层标准全注意力 (需要 KV cache)
- **最大上下文**: 262,144 tokens (原生)
- **支持特性**: Tool use, Reasoning, Code generation

## 已部署服务

| 服务 | 端口 | 框架 | 格式 | 上下文 | 说明 |
|------|------|------|------|--------|------|
| llama.cpp (Qwen3.6) | 8002 | llama.cpp | Q4_K_S GGUF | 128K/256K | 单用户高性能 |
| vLLM (Qwen3.6-FP8) | 8004 | vLLM | FP8 | 262K | 多用户并发 |

## 性能基准

### llama.cpp (Q4_K_S)

| 测试 | 输出长度 | 速度 |
|------|---------|------|
| 短文本 | 40 tokens | ~42 tok/s |
| 中文本 | ~785 tokens | ~59 tok/s |
| 长文本 | ~1700 tokens | ~59 tok/s |

**上下文压力测试 (Prefill)**:

| 上下文长度 | Prefill 速度 | 生成速度 |
|-----------|-------------|---------|
| 4K | ~5,200 t/s | ~59 t/s |
| 16K | ~4,800 t/s | ~59 t/s |
| 32K | ~4,200 t/s | ~59 t/s |
| 64K | ~3,600 t/s | ~55 t/s |
| 100K | ~3,000 t/s | ~50 t/s |
| 120K | ~2,600 t/s | ~45 t/s |
| 250K | ~1,300 t/s | ~22 t/s |

**内存占用**:

| 上下文 | 模型权重 | KV cache | DeltaNet 状态 | 计算缓冲 | 总计 |
|--------|---------|----------|--------------|---------|------|
| 128K | ~19.4 GB | ~2.5 GB | ~0.25 GB | ~0.8 GB | ~23 GB |
| 256K | ~19.4 GB | ~5.0 GB | ~0.25 GB | ~0.8 GB | ~26 GB |

### vLLM (FP8)

| 测试 | 输出长度 | 速度 |
|------|---------|------|
| 短文本 | 40 tokens | ~46 tok/s |
| 中文本 | 256 tokens | ~49 tok/s |
| 长文本 | 512 tokens | ~49 tok/s |

**上下文压力测试**:

| 上下文长度 | TTFT | 生成速度 |
|-----------|------|---------|
| 4K | 0.25s | ~47 t/s |
| 16K | 0.20s | ~47 t/s |
| 32K | 0.16s | ~47 t/s |
| 64K | 0.22s | ~45 t/s |
| 100K | 0.29s | ~42 t/s |
| 120K | 0.43s | ~40 t/s |
| 250K | 0.54s | ~34 t/s |

*注: TTFT 较低是因为重复句子命中了 prefix caching。首次 250K prefill 约 ~10s (24,978 t/s)。*

**并发测试** (RAG 风格短 prompt, 200 token 输出):

| 并发数 | 总吞吐 | 平均延迟 | 错误数 | GPU KV Cache |
|--------|--------|---------|--------|-------------|
| 1 | 48.0 t/s | 3.44s | 0 | 0.3% |
| 2 | 85.7 t/s | 1.85s | 0 | 0.3% |
| 5 | 118.9 t/s | 1.44s | 0 | 1.3% |
| 10 | 126.9 t/s | 1.30s | 0 | 2.6% |
| 20 | 291.2 t/s | 0.58s | 0 | 5.3% |
| 50 | 468.0 t/s | 0.37s | 0 | 13.2% |

## 环境变量

```bash
# CUDA
export PATH="/usr/local/cuda-13.0/bin:$PATH"
export CUDACXX=/usr/local/cuda-13.0/bin/nvcc

# 模型路径
export MODELS_PATH="$HOME/models"
```

## 常用命令

```bash
# 查看 GPU 状态
nvidia-smi

# 启动 llama.cpp (128K)
~/project/llama.cpp/build/bin/llama-server \
  -m ~/models/qwen36-q4ks/Qwen3.6-35B-A3B-UD-Q4_K_S.gguf \
  --host 0.0.0.0 --port 8002 \
  -ngl 99 -fa on -c 128000 --jinja --reasoning off

# 启动 llama.cpp (256K)
~/project/llama.cpp/build/bin/llama-server \
  -m ~/models/qwen36-q4ks/Qwen3.6-35B-A3B-UD-Q4_K_S.gguf \
  --host 0.0.0.0 --port 8002 \
  -ngl 99 -fa on -c 256000 --jinja --reasoning off

# 测试 API
curl http://localhost:8002/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "Qwen3.6-35B-A3B-UD-Q4_K_S", "messages": [{"role": "user", "content": "你好"}]}'

# 启动 vLLM (使用 docker-compose)
cd ~/project/nvidia-dgx/qwen36-dgx-spark
docker compose -f docker-compose-vllm-fp8.yml up -d

# 查看 vLLM 日志
docker logs vllm-qwen36-fp8 -f
```

## 注意事项

1. **统一内存**: 128GB 是 CPU+GPU 共享，注意内存带宽限制 (273 GB/s)
2. **llama.cpp `-fa` 参数**: 必须写成 `-fa on`，裸写 `-fa` 会贪婪消费下一个参数
3. **llama.cpp `--reasoning off`**: Qwen3.6 默认开启思考模式，会导致 API 返回空 `content`。启动时关闭或 prompt 中使用 `/no_think`
4. **vLLM 首次启动**: 需要 ~10-15 分钟捕获 CUDA graphs
5. **vLLM `--reasoning-parser`**: 不添加可能导致首请求 hang 住；添加后所有输出会放入 `reasoning` 字段
6. **模型下载**: 优先使用 ModelScope 加速
   ```bash
   modelscope download --model Qwen/Qwen3.6-35B-A3B-FP8 --local_dir ~/models/Qwen3.6-35B-A3B-FP8
   modelscope download --model unsloth/Qwen3.6-35B-A3B-GGUF --local_dir ~/models/qwen36-q4ks
   ```

## 参考

- [Qwen3.6 官方博客](https://qwen.ai/blog?id=qwen3.6-35b-a3b)
- [Qwen3.6 HuggingFace](https://huggingface.co/Qwen/Qwen3.6-35B-A3B-FP8)
- [llama.cpp GitHub](https://github.com/ggml-org/llama.cpp)
- [vLLM FP8 文档](https://docs.vllm.ai/en/latest/quantization/fp8.html)
- [NVIDIA DGX Spark 文档](https://docs.nvidia.com/dgx/dgx-spark/index.html)
