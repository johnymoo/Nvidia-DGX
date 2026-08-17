# Qwen3.8-27B on RTX 3090

本项目提供 Qwen3.8-27B Q3_K_S 在单张 RTX 3090 24 GiB 上的完整、可复现部署：
从 ModelScope 下载到 `/mnt/LLM/Qwen`、校验固定权重、以固定 llama.cpp 镜像启动
OpenAI-compatible API、执行文本/图片/结构化输出/工具调用/并发/长上下文/soak
验收，并生成 deployment receipt。

2026-08-15 的已接受配置与结果保存在
[`receipts/deployment-20260815T144804Z.json`](receipts/deployment-20260815T144804Z.json)。
该历史候选在验收后已停止，不代表当前服务状态。相关三模型 benchmark 见
[`../../../benchmarks/legacy/qwen-deepseek-cross-model/`](../../../benchmarks/legacy/qwen-deepseek-cross-model/)。

## 架构与固定配置

```text
ModelScope -> SHA-256 verification -> /mnt/LLM/Qwen
                                           |
                                           v
RTX 3090 <- NVIDIA Container Toolkit <- pinned llama.cpp container
                                           |
                                           v
                              OpenAI API on 127.0.0.1:18002
                                           |
                                           v
                               acceptance + deployment receipt
```

| 项目 | 固定值 |
|---|---|
| 模型 | `unsloth/Qwen3.8-27B-GGUF` revision `f1bfb127c64f7072bdd2cad55f258b9c8b2910fe` |
| 权重 | `Qwen3.8-27B-Q3_K_S.gguf`, 12,574,489,568 bytes |
| 视觉投影 | `mmproj-F16.gguf`, 927,607,488 bytes |
| 运行时 | 固定 digest 的 `ghcr.io/ggml-org/llama.cpp` |
| Context | 总计 131,072，2 个并行 slot，每 slot 65,536 |
| KV cache | K/V 均为 Q4_0，Flash Attention 开启 |
| 模式 | thinking off，支持文本与图片输入 |

公开示例默认只监听 `127.0.0.1:18002`。需要 LAN 访问时，先配置主机防火墙和认证
反向代理，再将 `PUBLISH_HOST` 改为明确的监听地址；不要直接把无认证 API 暴露到公网。

## 依赖

已接受环境为 Ubuntu 22.04、RTX 3090 24 GiB、NVIDIA driver 590.48.01、Docker
29.2.1、Python 3.10.12、curl 7.81.0、jq 1.6。其他版本可能可用，但不由历史
receipt 覆盖。

主机必须已安装 NVIDIA 驱动、Docker Engine 和 NVIDIA Container Toolkit，并且
当前用户可执行 Docker。先做只读检查：

Ubuntu 22.04 上先按 Docker 官方的
[`Install Docker Engine on Ubuntu`](https://docs.docker.com/engine/install/ubuntu/)
安装 Docker Engine，再按 NVIDIA 官方仓库安装 Container Toolkit：

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey |
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -sL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list |
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#' |
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit jq python3 curl
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

不要把 Docker 安装脚本通过管道直接交给 shell；使用官方 apt repository 可以检查
将要安装的包和版本。完成安装后执行：

```bash
nvidia-smi
docker version
docker info --format '{{json .Runtimes}}' | jq -e '.nvidia'
docker run --rm --gpus all ubuntu:22.04 nvidia-smi
df -h /mnt/LLM/Qwen
```

模型和投影约需 13.5 GB 磁盘；下载时还需要 `.partial` 文件空间。运行期间必须保留
至少 3,072 MiB GPU headroom。不要与另一套占满显存的模型同时启动。

## 安装与下载

```bash
cd recipes/qwen3.8/rtx3090-24gb-llamacpp-27b-q3-k-s-128k-p2
cp config/qwen38.env.example config/qwen38.env
chmod +x scripts/*.sh scripts/*.py
mkdir -p /mnt/LLM/Qwen
./scripts/download.sh
```

`download.sh` 使用 ModelScope 的可续传 HTTPS 对象下载，只有文件大小和冻结
SHA-256 同时匹配才会从 `.partial` 原子改名为正式文件。已存在的文件也会重新校验。
ModelScope 的 `master` 只是传输来源；部署身份由固定对象哈希建立，而不是依赖可变分支名。

若当前用户不能写 `/mnt/LLM/Qwen`，由管理员一次性创建目录并授予合适的组权限；
不要用 root 运行这些主机脚本，也不要把凭据写进配置文件。

## 启动与验证

```bash
./scripts/start.sh
./scripts/status.sh
curl -fsS http://127.0.0.1:18002/v1/models | jq
curl -fsS http://127.0.0.1:18002/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.8-27b-q3-k-s","temperature":0,"max_tokens":32,"messages":[{"role":"user","content":"Reply exactly READY"}]}' | jq
```

启动脚本会拒绝占用端口或同名容器，重新校验两个模型文件，确认主机只暴露一张
24 GiB RTX 3090，仅把 GPU 0 交给容器，拉取固定 digest 镜像，并等待容器
healthcheck。模型目录以只读方式挂载。

完整验收约需数分钟，其中包括 180 秒并发 soak：

```bash
./scripts/accept.sh
```

新证据写入 `${STATE_ROOT}/receipts/acceptance-<UTC>/`，包括容器 inspect、GPU
监控、日志、原始 acceptance JSON 和 deployment receipt。只有全部功能用例通过、
日志无 fatal CUDA/OOM/assertion/process 模式且最低剩余显存不少于 3,072 MiB 才返回
成功。

## 运行、停止与恢复

常用命令：

```bash
./scripts/status.sh
docker logs --tail 200 qwen38-rtx3090
./scripts/stop.sh
```

`status.sh`、`accept.sh` 和 `stop.sh` 都会先核对容器 ownership label、镜像、完整
运行参数、GPU、端口和挂载。`stop.sh` 只在身份匹配后保存日志并删除容器，再确认
端口释放；模型权重和 receipts 不会删除。恢复到本部署只需再次运行 `start.sh` 和
`status.sh`。

如果要替换现有模型服务，必须先保存旧服务的容器 inspect、启动配置和健康结果，
使用 loopback 候选完成 `accept.sh`，再在维护窗口中停止旧服务并修改本项目端口。
切换失败时先执行 `stop.sh`，然后仅用旧服务自己的已记录启动命令恢复。仓库脚本不会
猜测、停止或自动恢复其他模型。

## Receipt 复用

验证已提交 receipt：

```bash
python3 scripts/validate_receipt.py receipts/deployment-20260815T144804Z.json
python3 -m unittest discover -s tests -v
```

仅当模型、投影、镜像 digest、硬件类别和所有运行参数不变时，历史 receipt 可作为
同一部署身份的参考。改变 quantization、context、parallel、KV cache、thinking 模式
或镜像后必须重新验收。receipt 不能替代当前 `status.sh`。

## 文件清单

| 路径 | 用途 |
|---|---|
| `config/qwen38.env.example` | 无凭据的固定配置模板 |
| `scripts/download.sh` | ModelScope 续传下载与对象校验 |
| `scripts/start.sh` | 固定 llama.cpp 容器启动 |
| `scripts/status.sh` | 容器、GPU、health 和模型身份检查 |
| `scripts/acceptance.py` | 功能、并发、长上下文与 soak 验收 |
| `scripts/accept.sh` | GPU/日志监控和 receipt 生成 |
| `scripts/stop.sh` | 保存日志、停止并确认端口释放 |
| `scripts/validate_receipt.py` | receipt schema 与关键约束验证 |
| `receipts/` | 已接受的脱敏历史证据及复用条件 |
| `tests/` | 静态、隐私和 receipt 一致性测试 |

## 已知限制

- Q3_K_S 在此 RTX 3090 配置上的单流速度约 30 tok/s，明显低于同机已测 Qwen3.6
  IQ3_S；模型选择应同时参考 benchmark 的质量与吞吐结果。
- 两个并行 slot 共享总 context，单请求可用上限约 65K；100K 请求不在此 profile 内。
- 历史 receipt 的公开版本已移除私有主机路径和网络地址；原始文件哈希仍保留。
- 原始 acceptance、inspect 和 GPU 监控包含私有环境信息，未提交到公开仓库；公开
  receipt 是可校验内部一致性的脱敏维护者记录，只有持有原件者能核对其 source hashes。
- 脚本不配置 TLS、认证、防火墙、反向代理或系统级自动启动。
