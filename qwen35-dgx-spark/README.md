# Qwen3.5 on DGX Spark (GB10) - 部署与测试指南

## 概述

本指南介绍如何在 NVIDIA DGX Spark (GB10) 上部署 Qwen3.5 模型，对比 vLLM 和 llama.cpp 两种推理框架的性能。

## 硬件环境

- **设备**: NVIDIA DGX Spark (GB10)
- **GPU**: NVIDIA GB10 (Blackwell)
- **内存**: 128GB 统一内存
- **CUDA**: 12.1

## 模型准备

### 已下载模型

| 模型 | 大小 | 路径 |
|------|------|------|
| Qwen3.5-9B | 19GB | `~/models/Qwen/Qwen3___5-9B` |
| Qwen3.5-4B | 8.8GB | `~/models/Qwen/Qwen3___5-4B` |

## 方案一：vLLM 部署

### 安装

```bash
# 拉取 nightly 镜像（官方镜像不支持 Qwen3.5）
docker pull vllm/vllm-openai:cu130-nightly
```

### 启动服务

```bash
docker run -d \
  --name qwen35-9b \
  --restart unless-stopped \
  --gpus all \
  --ipc host \
  --shm-size 64gb \
  -p 8000:8000 \
  -v ~/models:/models \
  vllm/vllm-openai:cu130-nightly \
  /models/Qwen/Qwen3.5-9B \
  --served-model-name qwen3.5-9b \
  --port 8000 \
  --host 0.0.0.0 \
  --gpu-memory-utilization 0.80
```

### 测试 API

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.5-9b",
    "messages": [{"role": "user", "content": "你好"}],
    "max_tokens": 100
  }'
```

### vLLM 性能测试结果

| 输出长度 | 时间 | 速度 |
|---------|------|------|
| 100 tokens | ~8s | ~12-13 tok/s |
| 500 tokens | ~38s | ~13 tok/s |
| 2000 tokens | ~164s | ~12.2 tok/s |

**特点**: 多用户并发设计，单用户有 overhead，适合生产环境。

---

## 方案二：llama.cpp 部署（推荐）

### 编译安装

```bash
# 克隆仓库
git clone --depth 1 https://github.com/ggml-org/llama.cpp.git ~/llama.cpp

# 编译（启用 CUDA）
export PATH="/usr/local/cuda-13.0/bin:$PATH"
export CUDACXX=/usr/local/cuda-13.0/bin/nvcc
cd ~/llama.cpp
cmake -B build -DGGML_CUDA=ON
cmake --build build --config Release -j$(nproc)
```

### 模型转换（Safetensors → GGUF）

```bash
# 安装依赖
pip install transformers torch numpy sentencepiece protobuf

# 1. 转换为 F16 格式
cd ~/llama.cpp
python3 convert_hf_to_gguf.py \
  ~/models/Qwen/Qwen3___5-9B \
  --outfile ~/models/gguf/Qwen3.5-9B-f16.gguf \
  --outtype f16

# 2. 量化为 Q4_K_M（推荐）
./build/bin/llama-quantize \
  ~/models/gguf/Qwen3.5-9B-f16.gguf \
  ~/models/gguf/Qwen3.5-9B-Q4_K_M.gguf \
  Q4_K_M
```

**转换结果**:
- F16: 17.9GB
- Q4_K_M: 5.3GB (压缩率 70%)

### 启动服务

```bash
~/llama.cpp/build/bin/llama-server \
  -m ~/models/gguf/Qwen3.5-9B-Q4_K_M.gguf \
  -c 8192 \
  --host 0.0.0.0 \
  --port 8081 \
  -ngl 35 \
  --no-mmap
```

**参数说明**:
- `-c 8192`: 上下文窗口大小
- `-ngl 35`: GPU 层数（根据显存调整）
- `--no-mmap`: DGX Spark 必须禁用内存映射

### 测试 API

```bash
curl http://localhost:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen3.5-9B-Q4_K_M",
    "messages": [{"role": "user", "content": "你好"}],
    "max_tokens": 100
  }'
```

### llama.cpp 性能测试结果

| 输出长度 | 时间 | 速度 |
|---------|------|------|
| 100 tokens | 2.94s | **34.0 tok/s** |
| 500 tokens | 14.41s | **34.7 tok/s** |
| 1000 tokens | 28.89s | **34.6 tok/s** |

**特点**: 单用户性能最优，速度稳定，适合个人使用。

---

## 性能对比总结

| 框架 | 速度 | 适用场景 | 内存占用 |
|------|------|----------|----------|
| **llama.cpp** | **~34.6 tok/s** ✅ | 单用户、个人使用 | 5.3GB (Q4_K_M) |
| vLLM | ~13 tok/s | 多用户、生产环境 | 19GB (原始模型) |

**结论**: 对于 DGX Spark 单用户场景，llama.cpp 比 vLLM **快 2.6 倍**。

---

## 优化建议

### llama.cpp 进一步优化

```bash
# 使用更多 GPU 层数（如果显存足够）
-ngl 999

# 启用 Flash Attention
--flash-attn

# 量化 KV Cache
-ctk q4_0 -ctv q4_0

# 统一 KV Buffer
--kv-unified

# 调整 batch size
-ub 2048 -b 2048
```

### 推荐配置

```bash
~/llama.cpp/build/bin/llama-server \
  -m ~/models/gguf/Qwen3.5-9B-Q4_K_M.gguf \
  -c 16384 \
  --host 0.0.0.0 \
  --port 8081 \
  -ub 2048 \
  -b 2048 \
  -ngl 999 \
  --flash-attn \
  --no-mmap \
  -ctk q4_0 \
  -ctv q4_0 \
  --kv-unified
```

---

## 模型下载（GGUF 格式）

如果不需要自己转换，可以直接下载 GGUF：

```bash
# Hugging Face
wget https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/main/Qwen3.5-9B-Q4_K_M.gguf

# 或使用 ModelScope
pip install modelscope
python3 -c "
from modelscope import snapshot_download
snapshot_download('unsloth/Qwen3.5-9B-GGUF', 
                  local_dir='~/models/gguf',
                  allow_file_pattern='*Q4_K_M.gguf')
"
```

---

## 参考资源

- [Qwen3.5 GitHub](https://github.com/QwenLM/Qwen3.5)
- [llama.cpp GitHub](https://github.com/ggml-org/llama.cpp)
- [DGX Spark Playbooks](https://github.com/NVIDIA/dgx-spark-playbooks)
- [Qwen3.5 DGX Spark 指南](https://github.com/adadrag/qwen3.5-dgx-spark)

---

## 测试结果脚本

见 `benchmark.sh` 文件，用于批量测试推理速度。
