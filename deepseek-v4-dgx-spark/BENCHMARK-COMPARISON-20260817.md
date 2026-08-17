# DeepSeek Private / Online 性能与精度边界（2026-08-17）

## 结论

- **双 GB10 private Flash 适合作为默认私有工程推理线路。** 在 18 道可执行湖仓题上，
  private high 平均 90.3%，与 online Flash high 的
  91.7% 接近；本轮通过 LLM Portal 转发至 private vLLM，客户端观测的端到端 TTFT
  也明显更低。
- **需要最高成功率时升级到 online Pro high。** Pro high 平均
  97.2%，比 private high 高
  6.9pp；本轮一轮 18/18，
  另一轮 94.4%，没有空 final、截断或 HTTP 错误。
- **不要把 max 设为默认。** Pro max 平均 95.8%，没有超过 high，
  平均输出 120.4K token，约为 low 的
  3.1 倍，并出现分钟级尾延迟。
- **Private max 已测试，但没有改善质量。** 两轮宏平均为 87.5%，低于 private high，
  且标准差为 9.8pp。
- **Pro 不保证 Agent 工作流单调更好。** 在一个刻意聚焦历史 private 弱项的 5 题集合中，
  Pro high 只完整通过 1/5；历史 online Flash 为 4/5，private Flash 为 2/5。该集合有选择偏差，
  只能说明升级前仍需按真实 Agent workflow 验证。

## 精度

九个观测组都生成 18 道 SQL、Python 和故障诊断题，每组 n=2。PR 32 的 Flash/private
使用 v1 题面，其中一题 CDC 因未定义 I/U/D 在独立裁决时排除，最终按 17 题计分；Pro 使用
已修正的 v2 harness，按完整 18 题计分。分数以可执行 grader 为主，不使用模型自评。

| 处理组 | 宏平均 | SQL | Python | 故障诊断 | 两轮标准差 |
|---|---:|---:|---:|---:|---:|
| Private Flash low* / 32K | 83.3% | 100.0% | 66.7% | 83.3% | 0.0pp |
| Private Flash high / 256K | 90.3% | 100.0% | 83.3% | 87.5% | 2.0pp |
| Private Flash max / 384K | 87.5% | 100.0% | 83.3% | 79.2% | 9.8pp |
| Online Flash low / 32K | 90.3% | 100.0% | 83.3% | 87.5% | 2.0pp |
| Online Flash high / 256K | 91.7% | 100.0% | 83.3% | 91.7% | 3.9pp |
| Online Flash max / 384K | 95.8% | 100.0% | 91.7% | 95.8% | 2.0pp |
| Online Pro low / 32K | 88.9% | 100.0% | 83.3% | 83.3% | 3.9pp |
| Online Pro high / 256K | 97.2% | 100.0% | 100.0% | 91.7% | 3.9pp |
| Online Pro max / 384K | 95.8% | 100.0% | 91.7% | 95.8% | 5.9pp |

`*` Private 当前运行时不能独立测试 low：vLLM `deepseek_v4` tokenizer 将 low 和 high 都映射为
high。实测同一消息的 low/high prompt SHA-256 均为
`f0c87d80359c231133820e076d1b5c6dcf61fcee3d09905b0a26eddc4c211de0`；max 才产生不同前缀。
因此 PR 32 中 private-low 与 private-high 的差异应解释为重复运行波动和不同输出上限，
不能解释为 effort 效应。

## 短请求性能

每组 1 次预热、3 次串行 SSE 测量。Private 测量路径是 benchmark client → Synology 反向代理
→ LLM Portal edge/LiteLLM/compat → WireGuard → private vLLM，不是客户端直连 vLLM。
TTFT 是客户端收到首个 reasoning/content delta 的端到端时间；TPS 为 API completion tokens
除以 TTFT 后生成时间。不同 effort 生成长度不同，因此响应时间不是固定 token 数吞吐 A/B。

| 处理组 | TTFT | 端到端 | 解码 tok/s | 平均输出 tokens |
|---|---:|---:|---:|---:|
| Private Flash high | 0.252s | 13.499s | 35.5 | 470 |
| Online Flash low | 2.416s | 8.062s | 87.9 | 493 |
| Online Pro low | 2.269s | 6.711s | 45.9 | 204 |
| Online Pro high | 3.766s | 13.408s | 48.2 | 465 |
| Online Pro max | 2.051s | 10.781s | 46.0 | 401 |

Private high 经 LLM Portal 的端到端 TTFT 为 0.252s，适合交互式内网 Agent，
但不能解释为裸 vLLM engine latency；
online Pro high 在本题上的端到端时间为 13.408s，
与 private high 的 13.499s 接近，但其网络、调度和硬件
不可控。Pro 质量矩阵为缩短总时长采用并发执行，其中 `total_seconds` 不用于性能比较。

## Pro Token 与费用

以下为每轮 18 题的均值。费用按官方 Pro 单价估算，并保守地把全部输入视为 cache miss；
实际账单以服务端计费为准。

| Pro effort | 平均输出 tokens | 非高峰估算 | 高峰估算 |
|---|---:|---:|---:|
| low | 38.4K | $0.077 | $0.154 |
| high | 96.7K | $0.193 | $0.387 |
| max | 120.4K | $0.241 | $0.481 |

## Agent 聚焦题

Claude Code 2.1.207、Pro high、5 个并行隔离 Git sandbox；共观察到
73 个 thinking block。此集合专门选择历史 private 较弱或有差异的题，
不代表总体任务分布；并行耗时也不与历史顺序运行比较。

| 任务 | Pro high hidden checks | 历史 Online Flash | 历史 Private Flash |
|---|---:|---:|---:|
| `ndjson-stream-decoder` | 7/8 | passed | passed |
| `terminal-log-frequency` | 0/1 | passed | passed |
| `ops-oom-cgroup` | 1/2 | failed | failed |
| `writing-zh-incident` | 0/4 | passed | failed |
| `typescript-lru-ttl` | 1/1 | passed | failed |

## 适用边界

| 场景 | 建议 |
|---|---|
| 私密代码、内网数据、稳定日常 SQL/Python/故障诊断 | private Flash high |
| Private max | 两轮 87.5%，未超过 high；本轮未单独测延迟与 Agent，不建议默认启用 |
| 简单低延迟请求且允许出网 | online Flash low |
| 复杂任务、private 首次失败、需要更高一次成功率 | online Pro high |
| 极难任务且能接受分钟级尾延迟和约 3 倍 low token | Pro max，仅按请求启用 |
| 终端脚本、长文约束、复杂 Agent 工具链 | 先跑工作流级验收，不按模型名直接升级 |

## 测试覆盖矩阵

| 维度 | 本轮纳入 | 未覆盖 | 状态 |
|---|---|---|---|
| 可执行精度 | Private / Online Flash / Online Pro：low、high、max | Private low 非独立 prompt | 完整 |
| 串行 SSE 性能 | Private high；Online Flash low；Online Pro low/high/max | Private low/max；Online Flash high/max | 部分 |
| Token 与 API 成本 | Online Pro low/high/max | Private 无 API 账单；Flash 未统一计价 | 范围内完整 |
| Agent 聚焦任务 | Online Pro high；Online/Private 历史基线 | 不是九组 effort 全矩阵 | 部分 |

Private 还承担部署运维边界：两台 GB10 必须同时在线，当前 TP=2、最大并发序列 6；online
服务则引入数据出境、动态 alias、网络和供应商调度风险。两类线路应保留自动回退策略，不能
只看本轮宏平均。

## 方法与证据

- Online Flash alias：`deepseek-v4-flash` → `DeepSeek-V4-Flash-0731`。
- Online Pro alias：`deepseek-v4-pro` → `DeepSeek-V4-Pro-0813`。
- Private 请求经 LLM Portal 转发，不是客户端直连 vLLM。Portal access log 在质量矩阵对应
  时段记录 108 次请求；性能测量对应 4 次成功请求，与 1 次预热加 3 次测量完全一致。
- Private 的 0.252s TTFT 是 client → Portal → vLLM 的端到端指标，不是裸引擎延迟。
- 官方上下文 1M、最大输出 384K、effort 为 low/high/max；默认 high。
- Pro 六个质量 treatment 共 108 请求，0 HTTP/网络错误、0 空 final、0 length 截断。
- Agent 聚焦题的脱敏逐题证据见 `data/online-pro-agent-focus-20260817.json`；原始 sandbox、
  stream 和绝对路径不提交。
- Pro Python 原始评分时固定 sandbox 镜像不可用；保存的完整 final 随后在不可变 ECR Python
  digest 中重新执行。原始 JSON 未覆盖，裁决见
  `data/online-pro-matrix-adjudicated.json`。
- 本报告是快速决策 benchmark：每组 n=2、Agent 每题 n=1，不宣称统计显著性。

官方资料：[Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode)、
[Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing)、
[V4 Pro GA](https://api-docs.deepseek.com/news/news260813)。机器可读汇总见
[`data/deepseek-private-online-comparison-20260817.json`](data/deepseek-private-online-comparison-20260817.json)。
