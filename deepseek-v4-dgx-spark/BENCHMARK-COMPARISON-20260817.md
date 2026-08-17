# DeepSeek Private / Online 性能与精度边界（2026-08-17）

## 结论

- **双 GB10 private Flash 适合作为默认私有工程推理线路。** 在 18 道可执行湖仓题上，
  经 Portal 显式透传的 private high 平均 87.5%，与 online Flash high 的
  91.7% 接近；本轮通过 LLM Portal 转发至 private vLLM，
  客户端观测的端到端 TTFT 也明显更低。
- **需要最高成功率时升级到 online Pro high。** Pro high 平均
  97.2%，比 private high 高
  9.7pp；本轮一轮 18/18，
  另一轮 94.4%，没有空 final、截断或 HTTP 错误。
- **不要把 max 设为默认。** Pro max 平均 95.8%，没有超过 high，
  平均输出 120.4K token，约为 low 的
  3.1 倍，并出现分钟级尾延迟。
- **旧 Private max 质量分数无效。** LLM Portal 当时静默丢弃 `reasoning_effort`，所以旧
  87.5% 只是 effective-high 的重复波动，不是 Max 结果。显式透传后，在 High/Max 相同 4K
  上限的有界 A/B 中，High 为 93.1% 且 0/36 截断；True Max
  全请求分为 69.4%，10/36 截断。Max 的 26 个完整 final
  得分 96.2%，说明下降来自 final 覆盖率，不是
  已完成答案的质量变差。
- **Pro 不保证 Agent 工作流单调更好。** 在一个刻意聚焦历史 private 弱项的 5 题集合中，
  Pro high 只完整通过 1/5；历史 online Flash 为 4/5，private Flash 为 2/5。该集合有选择偏差，
  只能说明升级前仍需按真实 Agent workflow 验证。

## 精度

下表只保留 effort 契约已验证的处理组，每组 n=2。Private 与 Pro 使用 v2 harness 的完整
18 题；Online Flash 保留 PR 32 的 v1 裁决结果。4K 行是相同输出上限下的 High/Max 因果 A/B；
32K Private High 是不受本轮截断影响的能力基线。分数以可执行 grader 为主，不使用模型自评。

| 处理组 | 宏平均 | SQL | Python | 故障诊断 | 两轮标准差 |
|---|---:|---:|---:|---:|---:|
| Private Flash high / 32K | 87.5% | 91.7% | 83.3% | 87.5% | 2.0pp |
| Private Flash high / bounded 4K | 93.1% | 100.0% | 91.7% | 87.5% | 5.9pp |
| Private Flash max / bounded 4K | 69.4% | 75.0% | 41.7% | 91.7% | 11.8pp |
| Online Flash low / 32K | 90.3% | 100.0% | 83.3% | 87.5% | 2.0pp |
| Online Flash high / 256K | 91.7% | 100.0% | 83.3% | 91.7% | 3.9pp |
| Online Flash max / 384K | 95.8% | 100.0% | 91.7% | 95.8% | 2.0pp |
| Online Pro low / 32K | 88.9% | 100.0% | 83.3% | 83.3% | 3.9pp |
| Online Pro high / 256K | 97.2% | 100.0% | 100.0% | 91.7% | 3.9pp |
| Online Pro max / 384K | 95.8% | 100.0% | 91.7% | 95.8% | 5.9pp |

旧矩阵请求了 Private low/high/max，但 LiteLLM 将该 deployment 识别为 generic OpenAI-compatible，
`reasoning_effort` 不在支持参数列表且全局 `drop_params=true`，所以三组实际均为 vLLM 默认 High。
三组共六轮的宏平均为 87.0%，范围 80.6%–94.4%；108 个请求全部 `finish_reason=stop`，实际输出
远低于 32K/256K/384K 上限。因此旧 83.3%/90.3%/87.5% 差异既不是 Max 效果，也不是截断造成，
只能视为重复波动。

按 LiteLLM 官方方式加入 `allowed_openai_params=["reasoning_effort"]` 后，直接模板探针从 High 的
11 prompt tokens 变为 Max 的 90 tokens，证明 Max 已真实到达 vLLM。Private high 在相同 32K
输出上限下重跑两轮并完成。32K True Max pilot 在 15 分钟客户端边界内未完成，因此补做相同
`max_tokens=4096` 的 High/Max 有界矩阵，各两轮、每轮 18 题、每组并发 3，总并发不超过 vLLM
`max-num-seqs=6`。

| Private 4K 指标 | High | True Max |
|---|---:|---:|
| 全请求可执行分 | 93.1% | 69.4% |
| final 覆盖率 | 100.0% | 72.2% |
| 完整 final 得分 | 93.1% | 96.2% |
| length 截断 | 0/36 | 10/36 |
| 空 final | 0/36 | 10/36 |
| HTTP/网络错误 | 0/36 | 0/36 |

因此“Max 比 High 精度差”的说法不准确：在 4K 产品边界下，Max 的**任务成功率**更低；但只看
成功返回的 final，Max 并未低于 High。若产品必须使用 Max，需要提高输出预算或实现 reasoning
预算/超时保护，并把空 final 当作显式失败处理。

## 短请求性能

每组 1 次预热、3 次串行 SSE 测量。Private 测量路径是 benchmark client → Synology 反向代理
→ LLM Portal edge/LiteLLM/compat → WireGuard → private vLLM，不是客户端直连 vLLM。
TTFT 是客户端收到首个 reasoning/content delta 的端到端时间；TPS 为 API
completion tokens 除以 TTFT 后生成时间。不同 effort 生成长度不同，因此响应时间不是固定
token 数吞吐 A/B。

| 处理组 | TTFT | 端到端 | 解码 tok/s | 平均输出 tokens |
|---|---:|---:|---:|---:|
| Private Flash high | 0.270s | 12.900s | 32.6 | 412 |
| Private Flash max | 0.479s | 12.251s | 36.7 | 435 |
| Online Flash low | 2.416s | 8.062s | 87.9 | 493 |
| Online Pro low | 2.269s | 6.711s | 45.9 | 204 |
| Online Pro high | 3.766s | 13.408s | 48.2 | 465 |
| Online Pro max | 2.051s | 10.781s | 46.0 | 401 |

Private high 经 LLM Portal 的端到端 TTFT 为 0.270s，
True Max 为 0.479s。两组都固定 `max_tokens=2048`，因此
差异来自 effort 与运行波动，不是输出上限。它们适合用于交互路径判断，但不能解释为裸 vLLM engine latency；
online Pro high 在本题上的端到端时间为 13.408s，
与 private high 的 12.900s 接近，但其网络、调度和硬件
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
| Private max | 4K 下 final 覆盖率 72.2%；仅在能提高预算并处理空 final 时按请求启用 |
| 简单低延迟请求且允许出网 | online Flash low |
| 复杂任务、private 首次失败、需要更高一次成功率 | online Pro high |
| 极难任务且能接受分钟级尾延迟和约 3 倍 low token | Pro max，仅按请求启用 |
| 终端脚本、长文约束、复杂 Agent 工具链 | 先跑工作流级验收，不按模型名直接升级 |

## 测试覆盖矩阵

| 维度 | 本轮纳入 | 未覆盖 | 状态 |
|---|---|---|---|
| 可执行精度 | Verified Private high 32K；Private High/True Max 4K；Online Flash/Pro | True Private Max 32K 未完成；旧 private low/max 不是有效 effort | 主要边界完整 |
| 串行 SSE 性能 | Verified Private high/max；Online Flash low；Online Pro low/high/max | Online Flash high/max | 主要路径完整 |
| Token 与 API 成本 | Online Pro low/high/max | Private 无 API 账单；Flash 未统一计价 | 范围内完整 |
| Agent 聚焦任务 | Online Pro high；Online/Private 历史基线 | 不是九组 effort 全矩阵 | 部分 |

Private 还承担部署运维边界：两台 GB10 必须同时在线，当前 TP=2、最大并发序列 6；online
服务则引入数据出境、动态 alias、网络和供应商调度风险。两类线路应保留自动回退策略，不能
只看本轮宏平均。

## 方法与证据

- Online Flash alias：`deepseek-v4-flash` → `DeepSeek-V4-Flash-0731`。
- Online Pro alias：`deepseek-v4-pro` → `DeepSeek-V4-Pro-0813`。
- Private 请求经 LLM Portal 转发，不是客户端直连 vLLM。Portal access log 记录旧质量矩阵
  108 次请求和旧性能 4 次请求；修正后另有 High 32K 质量 36 次、High/Max 4K 质量 72 次、
  High/Max 性能 8 次请求。
- LiteLLM 官方文档说明 `drop_params=true` 会丢弃不支持参数，`allowed_openai_params` 可显式透传；
  live `get_supported_openai_params()` 也确认该 generic OpenAI deployment 默认不支持 `reasoning_effort`。
- 修正后 Private High/Max 性能均为 client → Portal → vLLM 的端到端指标，不是裸引擎延迟。
- 官方上下文 1M、最大输出 384K、effort 为 low/high/max；默认 high。
- Pro 六个质量 treatment 共 108 请求，0 HTTP/网络错误、0 空 final、0 length 截断。
- Private 4K High/True Max 共 72 请求，0 HTTP/网络错误；High 0 截断，True Max 10 个 length
  截断且对应 10 个空 final。
- Agent 聚焦题的脱敏逐题证据见 `data/online-pro-agent-focus-20260817.json`；原始 sandbox、
  stream 和绝对路径不提交。
- Pro Python 原始评分时固定 sandbox 镜像不可用；保存的完整 final 随后在不可变 ECR Python
  digest 中重新执行。原始 JSON 未覆盖，裁决见
  `data/online-pro-matrix-adjudicated.json`。
- Private 4K High/Max 的 Python final 也在相同不可变 ECR digest 中重新执行；裁决产物为
  `model-benchmark-qwen-deepseek/data/lakehouse-private-effort-bounded-4k-adjudicated.json`。
- 本报告是快速决策 benchmark：每组 n=2、Agent 每题 n=1，不宣称统计显著性。

官方资料：[Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode)、
[Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing)、
[V4 Pro GA](https://api-docs.deepseek.com/news/news260813)、
[LiteLLM Drop Unsupported Params](https://docs.litellm.ai/docs/completion/drop_params)。Portal 参数静默丢弃已记录在
[LLM-Portal #46](https://github.com/shiliai/LLM-Portal/issues/46)。机器可读汇总见
[`data/deepseek-private-online-comparison-20260817.json`](data/deepseek-private-online-comparison-20260817.json)。
