# Qwen3.8-27B-FP8 on 48 GiB RTX 4090

本项目提供 Qwen3.8-27B-FP8 在单张 48 GiB RTX 4090 上的参考部署：从
ModelScope 下载原生 FP8 多模态权重到 `/data/models`，使用固定 digest 的 vLLM
0.19.0 启动 OpenAI-compatible API，并执行 PR #29 的同题质量测试及补充性能、
湖仓代码、数学推理和图表识别测试。

## 固定配置

| 项目 | 值 |
|---|---|
| 模型 | `Qwen/Qwen3.8-27B-FP8`，ModelScope |
| 权重目录 | `/data/models/modelscope/Qwen3.8-27B-FP8`，约 29 GiB |
| 运行时 | vLLM 0.19.0，镜像 digest 固定于配置文件 |
| GPU | 单张 NVIDIA GeForce RTX 4090，49,140 MiB |
| Context | 65,536 tokens |
| 并发上限 | 4 sequences |
| CPU offload | 0 GiB |
| 宿主内存 | 16 GiB hard limit，memory-swap 与其相同 |
| 默认模式 | non-thinking；每个请求可显式开启 thinking |
| API | 默认 `127.0.0.1:8005/v1` |

模型权重约占 28.51 GiB 显存，空闲服务总显存占用约 43.4 GiB，保留约 5 GiB
余量。vLLM 编译缓存写入 `/var/cache/vllm`；首次冷启动主要受 `/data` HDD 权重
读取和视觉 warmup 影响。

服务默认只监听 loopback。无认证 LAN 暴露必须同时修改 `PUBLISH_HOST` 并显式设置
`ALLOW_UNAUTHENTICATED_LAN=true`；跨网访问应使用认证反向代理和 TLS。

## 下载与启动

依赖 Docker、NVIDIA Container Toolkit、`nvidia-smi`、Python 3 和 curl。

```bash
cd qwen38-rtx4090-vllm
cp config/qwen38.env.example config/qwen38.env
./scripts/download.sh
./scripts/start.sh
```

下载脚本使用固定 Python 镜像和 `modelscope==1.38.1`。现有证据只记录 ModelScope
`master` 与关键元数据哈希；脚本验证 architecture、FP8 quantization、66 个索引权重
文件和未完成文件状态，但没有完整权重分片哈希清单。因此该下载路径是 Reference，
不能据此声称未来的 `master` 与 2026-08-16 实测快照逐字节相同。

常用生命周期命令：

```bash
./scripts/status.sh
docker logs --tail 200 qwen38-vllm
./scripts/stop.sh
```

服务默认关闭 thinking，以保证短输出预算的 API 请求一定能进入 final answer。
复杂数学、编码或 agent 请求可逐次开启：

```json
{
  "model": "qwen3.8-27b-fp8",
  "messages": [{"role": "user", "content": "..."}],
  "chat_template_kwargs": {"enable_thinking": true},
  "reasoning_effort": "low"
}
```

`reasoning_effort` 支持 `low`、`medium` 和 `xhigh`。调用方必须给 thinking 请求预留
足够的输出 token；否则 reasoning 会消耗预算而没有 final content。

## Benchmark

2026-08-16 的 non-thinking PR #29 同题结果：

| 类别 | RTX 4090 FP8 / vLLM | PR #29 RTX 3090 Q3_K_S |
|---|---:|---:|
| 图片识别 | 100.0% | 100.0% |
| 可执行编程 | 100.0% | 100.0% |
| 写作约束 | 68.0% | 76.0% |
| 数学推理 | 58.3% | 58.3% |
| 宏平均 | 81.6% | 83.6% |

补充湖仓代码、数学推理和带数值标签的图表识别均为 3/3。256-token 单流生成
约 19.95 tok/s；1,164 / 8,864 / 33,065 token prefill 的平均 TTFT 分别为
0.372 / 2.182 / 9.132 秒。

Thinking-low 使用与 PR #29 完全相同的 27 题，并把每题输出预算提高到原来的
4 倍：图片 100%、编程 100%、写作 40%、数学 100%，宏平均 85.0%。其中两道
写作题仍在 reasoning 阶段耗尽预算，`finish_reason=length` 且 final content
为空。因此建议只对数学和复杂编程请求显式开启 low thinking；长篇写作保持
non-thinking。该结果不能解读为 thinking 对所有任务都有提升。

vLLM 日志提示 RTX 4090 对该 FP8 block shape 没有专用 kernel 配置，当前使用默认
W8A8 block FP8 kernel；这是单流生成低于 PR #29 RTX 3090 Q3_K_S/llama.cpp
约 30 tok/s 的重要解释。两套硬件、量化和运行时不同，不是严格同机 A/B。

2026-08-17 又与 Qwen3.6-35B-A3B-FP8 完成同机湖仓对比。Qwen3.8 non-thinking
宏平均为 75.0%，高于 Qwen3.6 的 61.1%；Qwen3.8 thinking-low 为 88.9%，高于
Qwen3.6 thinking 的 52.8%，并且没有截断或空 final。因此默认模型维持 Qwen3.8，
复杂 SQL、Python 和故障分析按请求启用 low thinking。完整结果见
[`../model-benchmark-qwen-deepseek/report/lakehouse-thinking.html`](../model-benchmark-qwen-deepseek/report/lakehouse-thinking.html)。

运行已扩展的质量测试：

```bash
./scripts/benchmark.sh
```

原始数据位于 [`receipts/`](receipts/)。48 小时压力测试按本轮计划暂缓。

## 文件

| 路径 | 用途 |
|---|---|
| `config/qwen38.env.example` | 无凭据的部署参数和固定身份哈希 |
| `compose.yaml` | GPU、内存、无 offload 和 healthcheck 约束 |
| `scripts/download.sh` | ModelScope 下载与结构/哈希验证 |
| `scripts/start.sh` | 启动并等待健康状态 |
| `scripts/status.sh` | API、容器资源和 GPU 状态检查 |
| `scripts/stop.sh` | 停止本部署服务 |
| `scripts/benchmark.sh` | non-thinking 与 thinking-low 质量测试 |
| `receipts/*.json` | 脱敏的部署与 benchmark 原始证据 |
| `tests/test_project.py` | 配置安全约束和 receipt 静态测试 |
