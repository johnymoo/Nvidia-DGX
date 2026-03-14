# Nemotron-3-Super-120B on DGX Spark (GB10) - 部署与测试指南

## 概述

本指南介绍如何在 NVIDIA DGX Spark (GB10) 上部署 NVIDIA Nemotron-3-Super-120B-A12B 模型，包括 llama.cpp 编译、模型下载、服务启动和性能优化。

## 硬件环境

- **设备**: NVIDIA DGX Spark (GB10)
- **GPU**: NVIDIA GB10 (Blackwell, sm_121)
- **内存**: 128GB 统一内存
- **CUDA**: 13.0
- **架构**: sm_121 (⚠️ 重要：不是 sm_120)

## 模型信息

| 属性 | 值 |
|------|-----|
| 模型 | NVIDIA Nemotron-3-Super-120B-A12B |
| 参数量 | 120.67B (12B active, MoE) |
| 专家数 | 512 (22 active per token) |
| 训练 Context | 1,048,576 tokens (1M) |
| 量化 | UD-Q4_K_XL (4-bit) |
| 文件大小 | ~79GB (3 shards) |

### 模型来源

推荐使用 `ggml-org` 提供的 GGUF 格式：

```bash
# Hugging Face
# https://huggingface.co/ggml-org/nemotron-3-super-120b-GGUF

# ModelScope (国内更快)
# https://modelscope.cn/models/ggml-org/nemotron-3-super-120b-GGUF
```

> ⚠️ **注意**: 不要使用 `unsloth` 版本的 GGUF，其 MoE tensor 布局与 llama.cpp 不兼容。

## 部署步骤

### 1. 下载模型

#### 方式一：ModelScope（推荐，国内更快）

```bash
pip install modelscope

python3 << 'EOF'
from modelscope import snapshot_download
snapshot_download(
    'ggml-org/nemotron-3-super-120b-GGUF',
    local_dir='~/models/nemotron-super-modelscope',
    allow_file_pattern='*UD-Q4_K_XL*'
)
EOF
```

#### 方式二：Hugging Face

```bash
cd ~/models
git lfs install
git clone https://huggingface.co/ggml-org/nemotron-3-super-120b-GGUF nemotron-super-modelscope
```

#### 方式三：wget（适合网络不稳定）

```bash
cd ~/models/nemotron-super-modelscope/UD-Q4_K_XL

for i in 1 2 3; do
  wget --tries=100 --retry-connrefused --waitretry=30 --continue \
    "https://huggingface.co/ggml-org/nemotron-3-super-120b-GGUF/resolve/main/UD-Q4_K_XL/NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-0000${i}-of-00003.gguf"
done
```

### 2. 编译 llama.cpp

> ⚠️ **关键**: GB10 的 CUDA 架构是 **sm_121**，不是 sm_120！

```bash
# 克隆仓库
git clone --depth 1 https://github.com/ggml-org/llama.cpp.git ~/llama.cpp

# 设置 CUDA 环境
export PATH="/usr/local/cuda/bin:$PATH"
export CUDACXX=/usr/local/cuda/bin/nvcc

# 编译（启用 CUDA 和正确的架构）
cd ~/llama.cpp
cmake -B build \
    -DGGML_CUDA=ON \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_CUDA_ARCHITECTURES=121 \
    -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc \
    -DCUDAToolkit_ROOT=/usr/local/cuda

cmake --build build --config Release -j$(nproc)
```

#### 编译参数说明

| 参数 | 值 | 说明 |
|------|-----|------|
| `CMAKE_CUDA_ARCHITECTURES` | **121** | GB10 架构，必须使用 121 而非 120 |
| `GGML_CUDA` | ON | 启用 CUDA 支持 |
| `GGML_CUDA_GRAPHS` | OFF (可选) | 某些情况下需要禁用 |

### 3. 启动服务

#### 基础启动（16K Context）

```bash
~/llama.cpp/build/bin/llama-server \
    -m ~/models/nemotron-super-modelscope/UD-Q4_K_XL/NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-00001-of-00003.gguf \
    -ngl 99 \
    -c 16384 \
    --host 0.0.0.0 \
    --port 8090 \
    -fa on
```

#### 大 Context 启动（200K Context）

```bash
~/llama.cpp/build/bin/llama-server \
    -m ~/models/nemotron-super-modelscope/UD-Q4_K_XL/NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-00001-of-00003.gguf \
    -ngl 99 \
    -c 200000 \
    --host 0.0.0.0 \
    --port 8090 \
    -fa on
```

#### 参数说明

| 参数 | 值 | 说明 |
|------|-----|------|
| `-m` | 模型路径 | GGUF 文件路径（第一个 shard） |
| `-ngl` | 99 | GPU 层数（全部加载到 GPU） |
| `-c` | 16384/200000 | Context 大小 |
| `-fa` | on | 启用 Flash Attention（重要） |
| `--host` | 0.0.0.0 | 监听所有接口 |
| `--port` | 8090 | 服务端口 |

### 4. 测试 API

```bash
# 检查模型信息
curl http://localhost:8090/v1/models | jq

# 发送聊天请求
curl http://localhost:8090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nemotron",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 100
  }' | jq
```

## 性能测试结果

### 基础配置（16K Context）

| 指标 | 值 |
|------|-----|
| Prompt 处理 | ~35 t/s |
| 生成速度 | ~60 t/s |
| GPU 显存 | ~24GB |

### 大 Context 配置（200K Context）

| 指标 | 值 |
|------|-----|
| Prompt 处理 | ~28 t/s |
| 生成速度 | ~16 t/s |
| GPU 显存 | ~82GB |

### 内存分配明细（200K Context）

| 组件 | 大小 |
|------|------|
| 模型权重 | 79,345 MiB (~77.5GB) |
| KV Cache | 1,564 MiB (~1.5GB, 8 layers) |
| Recurrent Memory | 659 MiB (~0.6GB, 88 layers) |
| Compute Buffers | ~1GB |
| **总计** | ~82GB |

## Web 聊天界面

提供了一个简单的 Web 界面用于与模型交互：

```bash
cd web
pip install flask psutil requests
python3 app.py
```

访问 http://localhost:5000 即可使用。

功能：
- 与 Nemotron 模型聊天
- 实时显示 CPU/内存/GPU 使用率
- 深色主题 UI

## Systemd 服务（可选）

创建系统服务实现开机自启：

```bash
# 创建服务文件
sudo tee /etc/systemd/system/nemotron-server.service << 'EOF'
[Unit]
Description=Nemotron-3-Super-120B llama.cpp server
After=network.target

[Service]
Type=simple
User=chriswang
WorkingDirectory=/home/chriswang
ExecStart=/home/chriswang/llama.cpp/build/bin/llama-server \
    -m /home/chriswang/models/nemotron-super-modelscope/UD-Q4_K_XL/NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-00001-of-00003.gguf \
    -ngl 99 -c 200000 --host 0.0.0.0 --port 8090 -fa on
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 启用并启动
sudo systemctl daemon-reload
sudo systemctl enable nemotron-server
sudo systemctl start nemotron-server
```

## 故障排除

### 问题 1: "no kernel image is available for execution on the device"

**原因**: CUDA 架构设置错误

**解决**: 确保 `CMAKE_CUDA_ARCHITECTURES=121`，不是 120

```bash
cmake -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=121 ...
```

### 问题 2: 模型加载失败

**原因**: 使用了不兼容的 GGUF 文件

**解决**: 使用 `ggml-org` 提供的 GGUF，不要使用 `unsloth` 版本

### 问题 3: 下载中断

**原因**: 网络不稳定

**解决**: 使用 wget 的 `--tries` 和 `--retry-connrefused` 参数

```bash
wget --tries=100 --retry-connrefused --waitretry=30 --continue <url>
```

### 问题 4: OOM (内存不足)

**原因**: Context 设置过大

**解决**: 
- 检查 GPU 内存使用: `nvidia-smi`
- 减小 `-c` 参数值
- GB10 总内存 128GB，模型占用 ~80GB，剩余 ~48GB 用于 Context

## 参考资源

- [Nemotron 模型卡](https://huggingface.co/nvidia/Nemotron-3-Super-120B-A12B)
- [ggml-org GGUF](https://huggingface.co/ggml-org/nemotron-3-super-120b-GGUF)
- [llama.cpp GitHub](https://github.com/ggml-org/llama.cpp)
- [DGX Spark Playbooks](https://github.com/NVIDIA/dgx-spark-playbooks)
- [GB10 CUDA 架构说明](https://gist.github.com/Sggin1/cd21ed471c861e814a85925ee04dfed6)

---

## 贡献指南

本项目的贡献规则遵循仓库根目录 [README.md](../README.md) 中的「仓库贡献规则」章节。

---

## 更新日志

- **2026-03-14**: 初始版本，支持 16K 和 200K Context 部署