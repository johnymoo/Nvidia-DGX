# Qwen3.6-35B-A3B-FP8 on 48 GiB RTX 4090

本项目提供 Qwen3.6-35B-A3B-FP8 在单张 48 GiB RTX 4090 上的参考
vLLM 部署，用于和 Qwen3.8-27B-FP8 做同机湖仓推理对比。模型从 ModelScope
下载到 `/data/models`，服务严格禁用 CPU offload，并给宿主内存和 swap 设置相同
的 16 GiB hard limit。

## 固定配置

| 项目 | 值 |
|---|---|
| 模型 | `Qwen/Qwen3.6-35B-A3B-FP8`，ModelScope 官方 FP8 |
| 权重目录 | `/data/models/modelscope/Qwen3.6-35B-A3B-FP8`，约 35 GiB |
| 运行时 | vLLM 0.19.0，镜像 digest 固定于配置文件 |
| GPU | 单张 NVIDIA GeForce RTX 4090，49,140 MiB |
| Context | 32,768 tokens |
| 并发上限 | 2 sequences |
| CPU offload | 0 GiB |
| 宿主内存 | 16 GiB hard limit，memory-swap 与其相同 |
| 默认模式 | non-thinking；请求可显式开启 thinking |
| API | 默认 `127.0.0.1:8006/v1` |

2026-08-17 实机冷启动成功。vLLM 报告模型加载占用 34.23 GiB，健康空闲服务
总显存占用 45,329 MiB，物理余量 3,171 MiB；KV cache 为 114,048 tokens。
启动没有 CPU offload，32K context 可用。

服务默认只监听 loopback。无认证 LAN 暴露必须同时修改 `PUBLISH_HOST` 并显式设置
`ALLOW_UNAUTHENTICATED_LAN=true`；跨网访问应使用认证反向代理和 TLS。

## 下载与启动

依赖 Docker、NVIDIA Container Toolkit、`nvidia-smi`、Python 3 和 curl。

```bash
cd recipes/qwen3.6/rtx4090-48gb-vllm-35b-a3b-fp8-32k-p2
cp config/qwen36.env.example config/qwen36.env
./scripts/download.sh
./scripts/start.sh
```

下载脚本固定 `modelscope==1.38.1`，并验证关键文件 SHA-256、
`Qwen3_5MoeForConditionalGeneration` architecture、FP8 quantization、256 experts、
每 token 8 experts、42 个权重文件和未完成文件状态。

现有证据只记录 ModelScope `master`、关键元数据哈希和权重分片存在性，没有完整
权重分片哈希清单。该下载路径应视为 Reference，不能据此声称未来的 `master` 与
2026-08-17 实测快照逐字节相同。

常用生命周期命令：

```bash
./scripts/status.sh
docker logs --tail 200 qwen36-vllm
./scripts/stop.sh
```

## Thinking

Qwen3.6 的 chat template 只有 thinking 开关，没有 Qwen3.8 的
`reasoning_effort=low` 强度控制：

```json
{
  "model": "qwen3.6-35b-a3b-fp8",
  "messages": [{"role": "user", "content": "..."}],
  "chat_template_kwargs": {"enable_thinking": true}
}
```

调用方必须给 thinking 请求预留足够输出预算。本轮固定 4,096 tokens 时，18 题中
有 8 题在 reasoning 阶段耗尽预算且没有 final content。

## Benchmark

同一 RTX 4090、同一 vLLM digest、相同 18 题和输出预算的结果：

| 模式 | SQL | Python | 故障分析 | 宏平均 | 截断/空 final |
|---|---:|---:|---:|---:|---:|
| Qwen3.6 non-thinking | 33.3% | 66.7% | 83.3% | 61.1% | 0 / 0 |
| Qwen3.6 thinking | 33.3% | 33.3% | 91.7% | 52.8% | 8 / 8 |
| Qwen3.8 non-thinking | 66.7% | 66.7% | 91.7% | 75.0% | 0 / 0 |
| Qwen3.8 thinking-low | 83.3% | 83.3% | 100.0% | 88.9% | 0 / 0 |

因此本服务器默认模型仍应选择 Qwen3.8-27B-FP8；普通请求使用 non-thinking，
复杂 SQL、Python 和故障分析按请求开启 `reasoning_effort=low`。Qwen3.6 生成更快，
但本题集的正确率和可控性不足以抵消这一优势。

运行 Qwen3.6 两组测试：

```bash
./scripts/benchmark.sh
```

完整脱敏 JSON、逐题回答和 HTML 报告位于
[`../../../benchmarks/legacy/qwen-deepseek-cross-model/`](../../../benchmarks/legacy/qwen-deepseek-cross-model/)。48 小时
压力测试不在本轮范围内。

## 文件

| 路径 | 用途 |
|---|---|
| `config/qwen36.env.example` | 无凭据参数、固定镜像和模型身份哈希 |
| `compose.yaml` | GPU、内存、无 offload、healthcheck 约束 |
| `scripts/download.sh` | ModelScope 下载和完整性验证 |
| `scripts/start.sh` | 启动并等待健康状态 |
| `scripts/status.sh` | API、容器和 GPU 状态检查 |
| `scripts/stop.sh` | 停止本部署服务 |
| `scripts/benchmark.sh` | non-thinking 与 thinking 湖仓测试 |
| `receipts/deployment-20260817.json` | 脱敏的实机启动和显存收据 |
| `tests/test_project.py` | 资源边界、固定身份和脚本约束测试 |

## 已知限制

- RTX 4090 没有这些 FP8/MoE shapes 的专用 vLLM kernel 配置，日志会提示使用默认
  W8A8 block FP8 和 MoE 配置，性能仍有优化空间。
- 3,171 MiB 空闲显存余量较小；不要在同一 GPU 启动其他模型或桌面计算负载。
- 本轮 18 题用于服务器选型，不是大型公开 benchmark，也没有执行 48 小时压力测试。
