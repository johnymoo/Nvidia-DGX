# DGX Spark (GB10) 系统配置

## 硬件配置

| 组件 | 规格 |
|------|------|
| **设备** | NVIDIA DGX Spark (Project DIGITS) |
| **GPU** | NVIDIA GB10 (Blackwell架构) |
| **GPU 显存** | 128GB 统一内存 (VRAM + 系统内存共享) |
| **内存带宽** | 273 GB/s (LPDDR5X) |
| **存储** | 3.7TB NVMe SSD |
| **CPU** | 20核 ARM64 (Neoverse V2) |
| **网络** | 2x ConnectX-7 (100GbE) |

## 软件环境

| 组件 | 版本 |
|------|------|
| **操作系统** | DGX OS (Ubuntu 24.04 LTS) |
| **内核** | Linux 6.17.0-1008-nvidia (aarch64) |
| **CUDA** | 12.1 |
| **NVIDIA 驱动** | 580.126.09 |
| **Docker** | 已安装，用户组配置完成 |
| **Python** | 3.12 |

## 已部署服务

| 服务 | 端口 | 说明 |
|------|------|------|
| llama.cpp (Qwen3.5-9B) | 8081 | GGUF 格式，Q4_K_M 量化 |
| vLLM (Qwen3.5-9B) | 8000 | Safetensors 格式 |
| Ollama | 11434 | 通用模型服务 |
| ComfyUI | 8188 | 图像生成工作流 |
| Chrome VNC | 4444/5900/7900 | 浏览器自动化 |

## 模型存储

```
~/models/
├── Qwen/
│   ├── Qwen3___5-4B/     # 4B 模型 (8.8GB)
│   └── Qwen3___5-9B/     # 9B 模型 (19GB)
├── gguf/
│   └── Qwen3.5-9B-Q4_K_M.gguf  # 量化模型 (5.3GB)
└── ... 其他模型
```

## 性能基准

| 模型 | 框架 | 量化 | 速度 | 显存占用 |
|------|------|------|------|----------|
| Qwen3.5-9B | llama.cpp | Q4_K_M | **34.6 tok/s** | ~6GB |
| Qwen3.5-9B | vLLM | BF16 | 13 tok/s | ~20GB |

## 环境变量

```bash
# CUDA
export PATH="/usr/local/cuda-13.0/bin:$PATH"
export CUDACXX=/usr/local/cuda-13.0/bin/nvcc

# Docker (无需 sudo)
# 用户已在 docker 组

# 模型路径
export MODELS_PATH="$HOME/models"
```

## 常用命令

```bash
# 查看 GPU 状态
nvidia-smi

# 启动 llama.cpp
~/llama.cpp/build/bin/llama-server \
  -m ~/models/gguf/Qwen3.5-9B-Q4_K_M.gguf \
  -c 8192 --host 0.0.0.0 --port 8081 -ngl 35 --no-mmap

# 测试 API
curl http://localhost:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "Qwen3.5-9B-Q4_K_M", "messages": [{"role": "user", "content": "你好"}]}'
```

## 注意事项

1. **统一内存**: 128GB 是 CPU+GPU 共享，大模型推理时需注意内存带宽限制
2. **--no-mmap**: DGX Spark 必须使用此参数，否则模型加载极慢
3. **量化**: Q4_K_M 是速度与质量的最佳平衡点
4. **单用户**: llama.cpp 适合单用户，vLLM 适合多用户并发

## 参考

- [NVIDIA DGX Spark 文档](https://docs.nvidia.com/dgx/dgx-spark/index.html)
- [GB10 架构白皮书](https://www.nvidia.com/en-us/data-center/dgx-spark/)
