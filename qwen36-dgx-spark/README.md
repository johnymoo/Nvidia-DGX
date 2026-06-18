# Qwen3.6-35B-A3B on DGX Spark (GB10) - 部署与测试指南

## 概述

本指南介绍如何在 NVIDIA DGX Spark (GB10) 上部署 Qwen3.6-35B-A3B 模型，对比 vLLM (FP8 / NVFP4) 和 llama.cpp (Q4_K_S) 多种推理方案的性能与适用场景。

Qwen3.6-35B-A3B 是 Qwen 系列最新 MoE 模型，总参数量 35B，激活参数量仅 3B，支持 256K 原生上下文，具备 Tool use、Reasoning 和 Code generation 能力。

> 2026-06-18 更新：新增 NVIDIA 官方 DGX Spark / ARM64 recipe 的 `Qwen3.6-35B-A3B-NVFP4` vLLM 部署与 FP8 对比 benchmark。详见 [NVFP4-BENCHMARK-RESULTS.md](./NVFP4-BENCHMARK-RESULTS.md)。

## 硬件环境

- **设备**: NVIDIA DGX Spark (GB10)
- **GPU**: NVIDIA GB10 (Blackwell, SM121)
- **内存**: 128GB 统一内存
- **CUDA**: 12.1

> 📄 **详细配置**见 [CONFIG.md](./CONFIG.md) - 包含完整系统配置、性能基准、内存占用和常用命令。

## 模型准备

### 已下载模型

| 模型 | 大小 | 路径 | 格式 |
|------|------|------|------|
| Qwen3.6-35B-A3B-FP8 | ~35 GB | `~/models/Qwen3.6-35B-A3B-FP8` | Safetensors |
| Qwen3.6-35B-A3B-NVFP4 | ~22 GB | `~/models/Qwen3.6-35B-A3B-NVFP4` | ModelOpt NVFP4 Safetensors |
| Qwen3.6-35B-A3B-Q4_K_S | ~19.4 GB | `~/models/qwen36-q4ks/Qwen3.6-35B-A3B-UD-Q4_K_S.gguf` | GGUF |

### 模型下载

```bash
# 方案 1: ModelScope (推荐，国内加速)
pip install modelscope
modelscope download --model Qwen/Qwen3.6-35B-A3B-FP8 --local_dir ~/models/Qwen3.6-35B-A3B-FP8
modelscope download --model unsloth/Qwen3.6-35B-A3B-GGUF --local_dir ~/models/qwen36-q4ks

# 方案 2: HuggingFace
huggingface-cli download Qwen/Qwen3.6-35B-A3B-FP8 --local-dir ~/models/Qwen3.6-35B-A3B-FP8
huggingface-cli download unsloth/Qwen3.6-35B-A3B-GGUF --local-dir ~/models/qwen36-q4ks
```

---

## 方案一：vLLM 部署 (NVFP4, 官方 DGX Spark recipe)

适合在 DGX Spark / GB10 上部署 NVIDIA ModelOpt NVFP4 checkpoint。该方案使用 ARM64 镜像 `vllm/vllm-openai:nightly-aarch64`，保持外部端口 `8004` 和 served model name `qwen3.6-35b-fp8`，以兼容已有客户端。

### 快速启动

```bash
cd ~/project/nvidia-dgx/qwen36-dgx-spark

docker compose -f docker-compose-vllm-nvfp4-nightly-aarch64.yml up -d

curl http://localhost:8004/health
curl http://localhost:8004/v1/models
```

### 关键参数

| 参数 | 值/说明 |
|------|---------|
| 镜像 | `vllm/vllm-openai:nightly-aarch64` |
| 模型目录 | `~/models/Qwen3.6-35B-A3B-NVFP4` |
| `--served-model-name` | `qwen3.6-35b-fp8`，仅为兼容旧客户端 |
| `--max-model-len` | `262144` |
| `--gpu-memory-utilization` | `0.40`，官方 DGX Spark recipe 建议值 |
| `--kv-cache-dtype` | `fp8` |
| `--attention-backend` | `flashinfer` |
| `--moe-backend` | `marlin` |
| `--speculative-config` | MTP speculative decoding, 3 draft tokens |

### NVFP4 benchmark 摘要

| 测试 | 结果 |
|------|------|
| 16 项常规生成 benchmark | **152.1 tok/s** 平均，0 error |
| vs 旧 8004 FP8 baseline | **+116.7%** 平均 tok/s |
| vs PR200 FP8 | **+109.8%** 平均 tok/s |
| 64K/128K/256K 长上下文正确性 | FP8 / NVFP4 均通过 |
| 轻量质量 sanity suite | FP8 15/16，NVFP4 15/16 |

完整数据见 [NVFP4-BENCHMARK-RESULTS.md](./NVFP4-BENCHMARK-RESULTS.md)。

---

## 方案二：vLLM 部署 (FP8)

适合 **多用户并发** 场景，vLLM 的 continuous batching 在高并发下吞吐优异。

### 快速启动

```bash
# 使用脚本一键部署
./deploy-vllm-fp8.sh

# 或使用 Docker Compose
docker compose -f docker-compose-vllm-fp8.yml up -d
```

### 手动启动

```bash
# 拉取 nightly 镜像（标准镜像不支持 Qwen3.6 MoE）
docker pull vllm/vllm-openai:cu130-nightly

# 启动服务
docker run -d \
  --name vllm-qwen36-fp8 \
  --restart unless-stopped \
  --gpus all --ipc host --shm-size 64gb \
  -p 8004:8000 \
  -v ~/models/Qwen3.6-35B-A3B-FP8:/models:ro \
  -e HF_HOME=/tmp \
  vllm/vllm-openai:cu130-nightly \
  /models \
  --served-model-name qwen3.6-35b-fp8 \
  --port 8000 --host 0.0.0.0 \
  --max-model-len 262144 \
  --gpu-memory-utilization 0.80 \
  --quantization fp8 \
  --dtype bfloat16 \
  --kv-cache-dtype fp8 \
  --reasoning-parser qwen3 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --enable-prefix-caching \
  --trust-remote-code
```

### 关键参数说明

| 参数 | 说明 |
|------|------|
| `--gpu-memory-utilization 0.80` | GPU 内存利用率，0.80 稳定（0.90 运行约 1 小时后可能 OOM） |
| `--quantization fp8` | FP8 权重量化 |
| `--kv-cache-dtype fp8` | FP8 KV cache，进一步节省内存 |
| `--reasoning-parser qwen3` | 解析思考模式输出；**不添加可能导致首请求 hang** |
| `--enable-prefix-caching` | 前缀缓存，重复 prompt 加速明显 |
| `HF_HOME=/tmp` | 挂载本地权重时必须设置，避免缓存混乱 |

### 测试 API

```bash
curl http://localhost:8004/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.6-35b-fp8",
    "messages": [{"role": "user", "content": "你好"}],
    "max_tokens": 100
  }'
```

### vLLM 性能概览

| 指标 | 数值 | 备注 |
|------|------|------|
| 单用户生成速度 | ~49 tok/s | v0.16.1rc1, cu130-nightly |
| 50 并发总吞吐 | **468 tok/s** | 多用户场景优势 |
| 250K 上下文 TTFT | ~0.54s | 命中 prefix cache |
| 内存占用 (250K) | ~70 GB | FP8 量化 |

> **注意**: 单用户 ~49 tok/s 是使用 `benchmark.sh`（中文 prompt, max_tokens=100/500/1000）的测试结果。不同 prompt 和参数可能导致速度差异。

---

## 方案三：llama.cpp 部署 (Q4_K_S)

适合 **单用户高性能** 场景，部署简单、内存占用低、无需容器。

### 前置要求

- llama.cpp 本地编译版本 `9789c4e`+（支持 CUDA sm_121 和 `qwen35moe` 架构）
- 路径: `~/project/llama.cpp/build/bin/llama-server`

### 快速启动

```bash
# 128K 上下文 (默认)
./deploy-llamacpp.sh

# 256K 上下文
CONTEXT=256000 ./deploy-llamacpp.sh
```

### 手动启动

**128K 上下文：**
```bash
~/project/llama.cpp/build/bin/llama-server \
  -m ~/models/qwen36-q4ks/Qwen3.6-35B-A3B-UD-Q4_K_S.gguf \
  --host 0.0.0.0 --port 8002 \
  -ngl 99 -fa on -c 128000 --jinja --reasoning off
```

**256K 上下文 (原生最大)：**
```bash
~/project/llama.cpp/build/bin/llama-server \
  -m ~/models/qwen36-q4ks/Qwen3.6-35B-A3B-UD-Q4_K_S.gguf \
  --host 0.0.0.0 --port 8002 \
  -ngl 99 -fa on -c 256000 --jinja --reasoning off
```

### 关键参数说明

| 参数 | 说明 |
|------|------|
| `-ngl 99` | 将 99 层卸载到 GPU（实际 41 层全部卸载） |
| `-fa on` | 启用 Flash Attention；**必须带 `on`**，裸写会消费下一个参数 |
| `--reasoning off` | 关闭默认思考模式；否则 API 返回空 `content` |
| `--jinja` | 启用 Jinja chat template |
| `-c 256000` | 上下文大小；会警告 `n_ctx_seq < n_ctx_train` 但正常工作 |

### 测试 API

```bash
curl http://localhost:8002/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen3.6-35B-A3B-UD-Q4_K_S",
    "messages": [{"role": "user", "content": "你好"}],
    "max_tokens": 100
  }'
```

### llama.cpp 性能概览

| 指标 | 数值 |
|------|------|
| 单用户生成速度 | **~59 tok/s** |
| 并发吞吐上限 | ~52 tok/s (slot 限制) |
| 250K 上下文 prefill | ~1,300 t/s |
| 内存占用 (128K) | **~23 GB** |
| 内存占用 (256K) | **~26 GB** |

---

## 性能对比总结

| 维度 | vLLM (FP8) | llama.cpp (Q4_K_S) |
|------|-----------|-------------------|
| **单用户速度** | ~49 tok/s | **~59 tok/s** ✅ |
| **高并发吞吐** | **468 tok/s** (50用户) ✅ | ~52 tok/s |
| **内存占用 (128K)** | ~70 GB | **~23 GB** ✅ |
| **内存占用 (256K)** | ~90+ GB | **~26 GB** ✅ |
| **部署复杂度** | 需要 Docker | 单二进制文件 |
| **首次启动时间** | ~10-15 min (CUDA graphs) | 秒级 |
| **Tool use** | ✅ 原生支持 | 需额外配置 |
| **Reasoning 解析** | ✅ `--reasoning-parser` | 需 `--reasoning off` |

**选择建议：**
- **个人使用 / 开发调试** → llama.cpp (简单、快、省内存)
- **生产环境 / 多用户 API 服务** → vLLM (并发吞吐强)

---

## 已知问题与经验教训

### 1. vLLM `--reasoning-parser` 副作用

添加 `--reasoning-parser qwen3` 后，vLLM 会将所有输出放入 `reasoning` 字段，`content` 为空。这可能导致标准 API 消费者解析失败。

** workaround：**
- 如果不需要 reasoning 分离，尝试省略 `--reasoning-parser`（但 nightly 镜像中不添加可能导致首请求 hang）
- 客户端同时读取 `content` 和 `reasoning_content` 字段

### 2. llama.cpp `-fa` 参数陷阱

```bash
# ❌ 错误：-fa 会贪婪消费下一个参数
-fa -c 128000    # 实际等价于 -fa="-c", 然后 128000 成为孤儿参数

# ✅ 正确：必须显式指定 on/off
-fa on -c 128000
```

### 3. llama.cpp `--served-model-name` 不支持

当前 llama.cpp build (9789c4e) 不支持 `--served-model-name`，API 调用时必须使用 GGUF 文件名作为 model 名称。

### 4. vLLM GPU Memory Utilization

`--gpu-memory-utilization 0.90` 在运行约 1 小时后可能 OOM。稳定值为 **0.80**。

### 5. Qwen3.6 默认 Thinking 模式

Qwen3.6 默认 `thinking = 1`，会导致：
- 生成内容放入 `reasoning_content`
- `content` 字段为空
- SVG / 代码生成容易触发生成长度限制

**解决方案：**
- llama.cpp: 启动时加 `--reasoning off`
- Prompt 级别: 使用 `/no_think` 指令
- vLLM: 使用 `--reasoning-parser qwen3` 分离输出

### 6. DeltaNet 架构的内存优势

Qwen3.6 采用混合注意力：30 层 DeltaNet (固定循环状态) + 10 层标准注意力 (KV cache)。

这意味着：
- 128K → 256K 上下文，KV cache 只增加 ~2.5 GB（不是翻倍）
- 256K 总内存仅 ~26 GB，远低于传统 dense 模型

### 7. 模型下载建议

优先使用 ModelScope（国内速度快），fallback HuggingFace：

```bash
# ModelScope
modelscope download --model Qwen/Qwen3.6-35B-A3B-FP8 --local_dir ~/models/Qwen3.6-35B-A3B-FP8

# HuggingFace (fallback)
huggingface-cli download Qwen/Qwen3.6-35B-A3B-FP8 --local-dir ~/models/Qwen3.6-35B-A3B-FP8
```

---

## 测试脚本

### 基础测试 (速度 + 推理准确性)

```bash
# 默认测试 llama.cpp (port 8002)
./benchmark.sh

# 测试 vLLM
API_URL=http://localhost:8004/v1/chat/completions MODEL=qwen3.6-35b-fp8 ./benchmark.sh
```

### 上下文压力测试

```bash
# 测试 4K → 250K 上下文
./benchmark-context.sh

# 测试 vLLM
API_URL=http://localhost:8004/v1/chat/completions MODEL=qwen3.6-35b-fp8 ./benchmark-context.sh
```

---

## 文件清单

| 文件 | 说明 |
|------|------|
| `README.md` | 本文件，部署与测试指南 |
| `CONFIG.md` | 系统配置、性能基准、常用命令 |
| `deploy-vllm-fp8.sh` | vLLM FP8 一键部署脚本 |
| `docker-compose-vllm-fp8.yml` | vLLM Docker Compose 配置 |
| `deploy-llamacpp.sh` | llama.cpp 一键部署脚本 (128K/256K) |
| `benchmark.sh` | 基础性能与推理准确性测试 |
| `benchmark-context.sh` | 上下文长度压力测试 |

---

## 参考资源

- [Qwen3.6 官方博客](https://qwen.ai/blog?id=qwen3.6-35b-a3b)
- [Qwen3.6 HuggingFace](https://huggingface.co/Qwen/Qwen3.6-35B-A3B-FP8)
- [llama.cpp GitHub](https://github.com/ggml-org/llama.cpp)
- [vLLM FP8 文档](https://docs.vllm.ai/en/latest/quantization/fp8.html)
- [NVIDIA DGX Spark 文档](https://docs.nvidia.com/dgx/dgx-spark/index.html)

---

## 贡献指南

本项目的贡献规则遵循仓库根目录 [README.md](../README.md) 中的「仓库贡献规则」章节。请确保在修改前阅读该章节。
