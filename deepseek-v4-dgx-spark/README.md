# DeepSeek V4 Flash on dual DGX Spark

## 目的

本项目记录 `DeepSeek-V4-Flash-0731` Patch4 运行时在两台 NVIDIA DGX Spark
（GB10）上的双机 vLLM 配置，重点说明如何可靠地打开 thinking，并保存一组通过
Claude Code 执行的聚焦评测结果。

## 上下文

仅配置 `--reasoning-parser deepseek_v4` 不等于开启模型 thinking。parser 负责把已经
产生的推理内容映射到协议字段；实际默认行为由 chat template 参数控制。本项目的基础
Compose 默认使用 `{"thinking":false}`，通过 additive override 将其替换为
`{"thinking":true}`，便于清晰审计和回退。

2026-08-17 完成了 private Flash、online Flash 与 online Pro low/high/max 的快速决策
benchmark。结论是 private Flash high 适合作为默认私有线路；复杂失败任务升级到 online
Pro high；max 只按请求启用。完整精度、短请求性能、token 成本、Agent 聚焦结果和适用边界见
[`BENCHMARK-COMPARISON-20260817.md`](BENCHMARK-COMPARISON-20260817.md)。

2026-08-17 已使用私有 OpenAI-compatible endpoint 对 `deepseek-v4-flash-0731` 的原生
`thinking=true` 补跑 18 道湖仓 SQL/Python/故障分析题。结果、逐题输出及与 Qwen 的
边界说明位于
[`../model-benchmark-qwen-deepseek/report/lakehouse-thinking.html`](../model-benchmark-qwen-deepseek/report/lakehouse-thinking.html)。
该补充服务的硬件和网络配置不同于 RTX 4090 Qwen，报告不作跨端点性能排序。

同日还以 `.env` 的 `DS_` 前缀变量通过 online gateway 跑了相同 treatment。online DS
thinking 宏平均为 63.9%，其中 5 题在 4,096-token 预算内没有 final；完整逐题证据也在
同一报告中。online 与私有端点均不替代本双 DGX Spark 部署的独立性能基线。

## 架构

```text
Claude Code
    |
    | Anthropic-compatible /v1/messages
    v
Head DGX Spark :8890
    |
    | vLLM tensor parallel = 2, NCCL over RDMA
    v
Worker DGX Spark
```

- 两台主机使用同一镜像、模型文件和 Compose 配置。
- head 使用 `NODE_RANK=0` 并暴露 API；worker 使用 `NODE_RANK=1` 和
  `HEADLESS=1`。
- worker 先启动，head 后启动；停止时反向执行。
- thinking-on 通过第二个 Compose 文件叠加，不直接修改基础配置。

## 文件清单

| 文件 | 说明 |
|------|------|
| `.env.example` | 无凭证、无真实主机信息的配置模板 |
| `docker-compose.yml` | 双机 Patch4 vLLM 基础配置，默认 thinking off |
| `docker-compose.thinking-on.yml` | 将完整启动命令切换为 thinking on 的 additive override |
| `scripts/verify_thinking.py` | 验证 Compose 渲染结果和 Claude Code JSONL thinking 事件 |
| `tests/test_verify_thinking.py` | 标准库单元测试 |
| `BENCHMARK-RESULTS.md` | 五题聚焦评测方法与结论 |
| `benchmark-results-20260812.json` | 脱敏后的机器可读结果 |
| `benchmark/` | 可复用的 47 题 Claude Code benchmark、沙盒 fixture、grader、runner 和报告生成器 |
| `docs/` | 双 GB10 拓扑、工作流、参数说明、模型下载和上游引用 |

## 深入文档

- [双 GB10 集群拓扑](docs/cluster-topology.md)
- [部署、恢复与 benchmark 工作流](docs/workflows.md)
- [vLLM、NCCL、MLA、MTP 与 thinking 参数说明](docs/parameters.md)
- [模型下载与上游 GitHub/reference](docs/references.md)
- [可复用 benchmark 使用说明](benchmark/README.md)

## 依赖

- 两台 NVIDIA DGX Spark（GB10），可用的 RDMA fabric
- NVIDIA 驱动、CUDA 13 兼容环境和 Docker Compose v2
- 已包含 DeepSeek V4 Flash Patch4 的 vLLM 镜像
- 两台主机上内容一致的 `DeepSeek-V4-Flash-0731` checkpoint
- Python 3.9+，仅使用标准库
- 可选：Claude Code 2.1.207，用于复现本项目记录的 agent 评测协议

## 安装与配置

1. 将本目录同步到两台 DGX Spark。
2. 在每台主机上复制环境模板：

   ```bash
   cp .env.example .env
   ```

3. 填写镜像、模型目录、缓存目录和 RDMA 接口。不要把 `.env` 提交到 Git。
4. head 设置：

   ```dotenv
   NODE_RANK=0
   HEADLESS=
   VLLM_HOST_IP=<head-fabric-address>
   MASTER_ADDR=<head-fabric-address>
   ```

5. worker 设置：

   ```dotenv
   NODE_RANK=1
   HEADLESS=1
   VLLM_HOST_IP=<worker-fabric-address>
   MASTER_ADDR=<head-fabric-address>
   ```

文档中的地址占位符必须替换为本地 fabric 地址；不要把内网地址提交到仓库。

## 使用

### 1. 验证 Thinking 配置

在任一节点渲染最终配置：

```bash
docker compose --env-file .env \
  -f docker-compose.yml \
  -f docker-compose.thinking-on.yml \
  config --format json > /tmp/deepseek-thinking-compose.json

python3 scripts/verify_thinking.py compose /tmp/deepseek-thinking-compose.json
```

成功输出包含：

```json
{"mode": "compose", "service": "vllm-dspark", "status": "passed", "thinking": true}
```

### 2. 启动双机服务

先在 worker 执行：

```bash
docker compose --env-file .env \
  -f docker-compose.yml \
  -f docker-compose.thinking-on.yml \
  up -d vllm-dspark
```

再在 head 执行相同命令。确认模型身份和健康状态：

```bash
curl -fsS http://127.0.0.1:8890/health
curl -fsS http://127.0.0.1:8890/v1/models
```

### 3. 验证 Claude Code Thinking 事件

Claude Code 使用 `--output-format stream-json --verbose` 保存 stream 后执行：

```bash
python3 scripts/verify_thinking.py streams streams/*.jsonl
```

命令要求每个 stream 至少有一个显式 thinking block，并汇总 block 和 token event
数量。不要仅根据回答长度、质量或客户端 `alwaysThinkingEnabled` 设置推断 thinking 已开启。

### 4. 停止与回退

先停止 head，再停止 worker：

```bash
docker compose --env-file .env \
  -f docker-compose.yml \
  -f docker-compose.thinking-on.yml \
  stop vllm-dspark
```

要恢复 thinking-off，停止服务后只使用基础 Compose 文件重新创建容器。不要混用两种
最终渲染配置，也不要在同一 GB10 内存窗口中同时运行不能共存的大模型服务。

## 测试

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/verify_thinking.py tests/test_verify_thinking.py
benchmark/run.sh test
```

完整三模型复测通过 `benchmark/run.sh run` 一次执行。它包含 47 道冻结题目：7 道
先导题，以及终端、服务器运维、中英文写作、Python/TypeScript 编程各 10 道扩展题。
模型服务地址和切换命令只通过环境变量传入，不写入仓库。

若本机安装了 Docker Compose，可使用 `.env.example` 的文档地址渲染配置；实际启动前
必须改为真实的 fabric 参数和可用镜像。

## 已知限制

- 本仓库不发布 Patch4 镜像、模型权重或构建补丁；Compose 只描述已验证的运行合同。
- override 必须替换完整 `command`，因为 Compose 对列表不做逐参数合并；基础命令变化时
  需同步更新两个 Compose 文件。
- 两机模型加载需要数分钟，且统一内存不足时可能出现 NVRM 内存警告。
- 该五题评测每个 treatment 只运行一次，只能作为方向性结果。
- Online DS 与私有部署的 token、缓存和成本口径不同，不应直接比较成本数字。

## 贡献

本项目遵循仓库根目录 [README.md](../README.md) 的贡献规则。相关 Issue：
[#19](https://github.com/johnymoo/Nvidia-DGX/issues/19)、
[#21](https://github.com/johnymoo/Nvidia-DGX/issues/21)。
