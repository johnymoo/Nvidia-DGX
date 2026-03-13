# Qwen3.5-35B-A3B 成功部署日志

**日期**: 2026-03-13  
**设备**: NVIDIA DGX Spark (GB10)  
**状态**: ✅ 成功

---

## 背景

尝试在 GB10 上部署 Qwen3.5-35B-A3B 模型。参考指南 [Qwen3.5-35B-A3B-openclaw-dgx-spark](https://github.com/ZengboJamesWang/Qwen3.5-35B-A3B-openclaw-dgx-spark) 推荐 `CMAKE_CUDA_ARCHITECTURES=120`，但在实际部署中遇到 CUDA 错误。

## 问题

使用 `CMAKE_CUDA_ARCHITECTURES=120` 编译后，启动 llama-server 时出现：

```
CUDA error: no kernel image is available for execution on the device
ggml_cuda_compute_forward: SCALE failed
```

错误发生在 CUDA graph capture 阶段，模型加载成功但在初始化 slots 时崩溃。

## 根本原因

GB10 的计算能力是 **sm_121** (Blackwell)，不是 sm_120。编译时使用 `CMAKE_CUDA_ARCHITECTURES=120` 会生成针对 sm_120a 的内核，但 sm_121 需要不同的内核。

CMake 会自动将 `120` 替换为 `120a`，但这对于 sm_121 仍然不兼容。

## 解决方案

### 关键修复

```bash
# 错误 ❌
-DCMAKE_CUDA_ARCHITECTURES=120

# 正确 ✅
-DCMAKE_CUDA_ARCHITECTURES=121
```

CMake 会自动将 `121` 替换为 `121a`，这是 GB10 (sm_121) 需要的正确架构。

### 完整构建命令

```bash
cd /opt/llama.cpp
rm -rf build

cmake -B build \
    -DGGML_CUDA=ON \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_CUDA_ARCHITECTURES=121 \
    -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc \
    -DCUDAToolkit_ROOT=/usr/local/cuda \
    -DGGML_CUDA_GRAPHS=OFF

cmake --build build --config Release -j $(nproc)
```

### 关键构建选项

| 选项 | 值 | 原因 |
|------|-----|------|
| `CMAKE_CUDA_ARCHITECTURES` | `121` | GB10 是 sm_121，不是 sm_120 |
| `GGML_CUDA_GRAPHS` | `OFF` | 禁用 CUDA graphs，避免 SCALE 内核错误 |
| `--no-warmup` | 运行时标志 | 跳过预热阶段，避免启动时崩溃 |

### 运行命令

```bash
LD_LIBRARY_PATH=/opt/llama.cpp/build/bin \
./build/bin/llama-server \
    --model /opt/llama.cpp/models/Qwen3.5-35B-A3B-UD-Q4_K_XL.gguf \
    --ctx-size 131072 \
    --parallel 1 \
    --host 127.0.0.1 \
    --port 8001 \
    -ngl 99 \
    -fa on \
    --no-warmup
```

## Systemd 服务配置

```ini
[Unit]
Description=llama.cpp server (Qwen3.5-35B-A3B)
After=network.target

[Service]
Type=simple
User=root
Environment=LD_LIBRARY_PATH=/opt/llama.cpp/build/bin
ExecStart=/opt/llama.cpp/build/bin/llama-server \
    --model /opt/llama.cpp/models/Qwen3.5-35B-A3B-UD-Q4_K_XL.gguf \
    --ctx-size 131072 \
    --parallel 1 \
    --host 127.0.0.1 \
    --port 8001 \
    -ngl 99 \
    -fa on \
    --no-warmup
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## 性能结果

| 指标 | 值 |
|------|-----|
| 模型大小 | 20.70 GiB (Q4_K) |
| GPU 显存占用 | ~24 GB |
| Prompt 处理速度 | ~35 t/s |
| 生成速度 | ~60 t/s |
| 上下文长度 | 131072 tokens |

## 验证

```bash
# 健康检查
curl http://127.0.0.1:8001/health
# 返回: {"status":"ok"}

# 服务状态
systemctl status llama-server
# 返回: active (running)
```

## 教训总结

1. **CUDA 架构必须匹配**: GB10 是 sm_121，指南推荐的 sm_120 不兼容
2. **禁用 CUDA graphs**: 某些内核在 sm_121 上可能有问题
3. **跳过预热**: `--no-warmup` 可以避免启动时的内核错误
4. **LD_LIBRARY_PATH**: 需要正确设置以找到共享库

## 参考资源

- 指南: https://github.com/ZengboJamesWang/Qwen3.5-35B-A3B-openclaw-dgx-spark
- 模型: https://huggingface.co/unsloth/Qwen3.5-35B-A3B-GGUF
- llama.cpp: https://github.com/ggml-org/llama.cpp

---

**最后更新**: 2026-03-13 00:42 UTC