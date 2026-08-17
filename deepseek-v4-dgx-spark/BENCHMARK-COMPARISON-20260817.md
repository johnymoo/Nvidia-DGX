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
  87.5% 只是 effective-high 的重复波动，不是 Max 结果。Issue #46 修复后，无 per-request
  override 的 Portal Max 探针已与 direct vLLM 的 prompt usage、reasoning 和 final 哈希完全一致。
- **把 Private Max 上限提高到 384K 后，截断消失但尾延迟极高。** 修复后的 Portal 为
  94.4%，direct vLLM 为 91.7%；
  两边均 18/18 final、0 截断、0 错误，16/18 题可执行分一致。Portal 最慢题耗时
  50.5 分钟、输出 63.7K tokens，
  因此 384K 是能力验证配置，不适合作为默认产品预算。
- **Pro 不保证 Agent 工作流单调更好。** 在一个刻意聚焦历史 private 弱项的 5 题集合中，
  Pro high 只完整通过 1/5；历史 online Flash 为 4/5，private Flash 为 2/5。该集合有选择偏差，
  只能说明升级前仍需按真实 Agent workflow 验证。

## 精度

下表只保留已完整完成且 effort 契约已验证的处理组。Private High 与 online 各 effort 为 n=2；
Private Max 384K 为 n=1。Private 与 Pro 使用 v2 harness 的完整 18 题；Online Flash 保留 PR 32
的 v1 裁决结果。分数以可执行 grader 为主，不使用模型自评。

| 处理组 | 宏平均 | SQL | Python | 故障诊断 | 运行次数 | 标准差 |
|---|---:|---:|---:|---:|---:|---:|
| Private Flash high / 32K | 87.5% | 91.7% | 83.3% | 87.5% | 2 | 2.0pp |
| Private Flash max / 384K | 94.4% | 100.0% | 100.0% | 83.3% | 1 | N/A |
| Online Flash low / 32K | 90.3% | 100.0% | 83.3% | 87.5% | 2 | 2.0pp |
| Online Flash high / 256K | 91.7% | 100.0% | 83.3% | 91.7% | 2 | 3.9pp |
| Online Flash max / 384K | 95.8% | 100.0% | 91.7% | 95.8% | 2 | 2.0pp |
| Online Pro low / 32K | 88.9% | 100.0% | 83.3% | 83.3% | 2 | 3.9pp |
| Online Pro high / 256K | 97.2% | 100.0% | 100.0% | 91.7% | 2 | 3.9pp |
| Online Pro max / 384K | 95.8% | 100.0% | 91.7% | 95.8% | 2 | 5.9pp |

旧矩阵请求了 Private low/high/max，但 LiteLLM 将该 deployment 识别为 generic OpenAI-compatible，
`reasoning_effort` 不在支持参数列表且全局 `drop_params=true`，所以三组实际均为 vLLM 默认 High。
三组共六轮的宏平均为 87.0%，范围 80.6%–94.4%；108 个请求全部 `finish_reason=stop`，实际输出
远低于 32K/256K/384K 上限。因此旧 83.3%/90.3%/87.5% 差异既不是 Max 效果，也不是截断造成，
只能视为重复波动。

旧矩阵只用于解释历史契约错误，不进入上表或机器可读 `quality`。当前 Private 的正式质量配置
只有 High/32K（n=2）和 Max/384K（n=1），两者均为 18/18 完整 final。

## Private Max 384K 与路由一致性

Portal 修复后，不带 per-request `allowed_openai_params` override 的 Max 探针与 direct vLLM 均为
87 prompt tokens、10 completion tokens，reasoning/final SHA-1 完全一致。随后以 SSE、相同 18 题、
seed 42、`max_tokens=393216`，Portal 与 SSH tunnel direct vLLM 各并发 2 做一轮配对 A/B。

| 384K True Max 指标 | Portal | Direct vLLM |
|---|---:|---:|
| 可执行宏平均 | 94.4% | 91.7% |
| SQL / Python / 故障 | 100.0% / 100.0% / 83.3% | 100.0% / 83.3% / 91.7% |
| final / 截断 / 错误 | 18/18 / 0 / 0 | 18/18 / 0 / 0 |
| 总 completion tokens | 145.3K | 132.0K |
| 最慢单题 | 50.5 分钟 / 63.7K tokens | 27.3 分钟 / 31.4K tokens |

逐题 finish reason 与 prompt token 数均为 18/18 一致，可执行分 16/18 一致；final 与 reasoning
文本哈希均为 0/18 一致。结论是 **Portal 路由语义已经与 direct vLLM 对齐**，2.8pp 分差来自
True Max 单轮采样波动，不能解释为 Portal 改写答案。该 A/B 每条路径 n=1，不声明统计显著性。

## 18 题完整工作负载性能

质量 harness 为每题保存了从请求发出到完整响应结束的 wall time 和 completion tokens，但没有保存
首个 SSE delta 的时间戳；Private High 当时还是非流式请求。因此下表的 TTFT 无法事后恢复，
“有效 E2E tok/s”定义为 `sum(completion_tokens) / sum(response_seconds)`，不是扣除 TTFT 后的 decode TPS。

| 处理组 | 请求数 | 每轮并发 | 平均 response | P95 response | 最大 response | 有效 E2E tok/s | TTFT |
|---|---:|---:|---:|---:|---:|---:|---:|
| Private Flash high / 32K | 36 | 1 | 32.6s | 117.6s | 193.0s | 24.0 | 未采集 |
| Private Flash max / 384K · Portal | 18 | 2 | 403.7s | 3031.2s | 3031.2s | 20.0 | 未采集 |
| Private Flash max / 384K · Direct vLLM | 18 | 2 | 378.4s | 1636.3s | 1636.3s | 19.4 | 未采集 |
| Online Flash low / 32K | 36 | 1 | 6.9s | 17.0s | 20.6s | 99.5 | 未采集 |
| Online Flash high / 256K | 36 | 1 | 62.4s | 316.6s | 532.0s | 109.6 | 未采集 |
| Online Flash max / 384K | 36 | 1 | 79.5s | 350.5s | 392.5s | 106.3 | 未采集 |
| Online Pro low / 32K | 36 | 1 | 33.5s | 106.0s | 130.8s | 63.7 | 未采集 |
| Online Pro high / 256K | 36 | 1 | 78.5s | 255.2s | 598.3s | 68.5 | 未采集 |
| Online Pro max / 384K | 36 | 1 | 100.7s | 372.8s | 399.3s | 66.5 | 未采集 |

这些是实际 18 题运行的描述性 telemetry，但各矩阵的 stream mode、执行时段和并行调度不完全相同，
不能当作严格的跨服务吞吐 A/B。下面的独立短请求实验才提供同一测量定义下的 TTFT 和 decode TPS。

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
| Private max | 384K 为 18/18 final，但单题最长 50.5 分钟，仅按请求启用 |
| 简单低延迟请求且允许出网 | online Flash low |
| 复杂任务、private 首次失败、需要更高一次成功率 | online Pro high |
| 极难任务且能接受分钟级尾延迟和约 3 倍 low token | Pro max，仅按请求启用 |
| 终端脚本、长文约束、复杂 Agent 工具链 | 先跑工作流级验收，不按模型名直接升级 |

## 测试覆盖矩阵

| 维度 | 本轮纳入 | 未覆盖 | 状态 |
|---|---|---|---|
| 可执行精度 | Private High 32K；True Max 384K Portal/direct；Online Flash/Pro | Private Max 384K 与 route A/B 仅 n=1 | 主要边界完整 |
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
  108 次请求和旧性能 4 次请求；正式完成配置另有 High 32K 质量 36 次、Max 384K Portal/direct
  各 18 次、High/Max 性能 8 次请求。
- LiteLLM 官方文档说明 `drop_params=true` 会丢弃不支持参数，`allowed_openai_params` 可显式透传；
  旧 Portal deployment 因此丢弃 `reasoning_effort`。Issue #46 修复后，不带 per-request override 的
  Portal/direct Max 探针 prompt usage 与输出哈希一致。
- 修正后 Private High/Max 性能均为 client → Portal → vLLM 的端到端指标，不是裸引擎延迟。
- 官方上下文 1M、最大输出 384K、effort 为 low/high/max；默认 high。
- Pro 六个质量 treatment 共 108 请求，0 HTTP/网络错误、0 空 final、0 length 截断。
- Private 384K route A/B 共 36 请求，Portal/direct 均 18/18 stop、0 截断、0 错误；逐题 score
  16/18 一致。Portal 最长请求 3031 秒，证明修复后的 SSE 路径跨过旧 600 秒网关边界。
- Agent 聚焦题的脱敏逐题证据见 `data/online-pro-agent-focus-20260817.json`；原始 sandbox、
  stream 和绝对路径不提交。
- Pro Python 原始评分时固定 sandbox 镜像不可用；保存的完整 final 随后在不可变 ECR Python
  digest 中重新执行。原始 JSON 未覆盖，裁决见
  `data/online-pro-matrix-adjudicated.json`。
- 本报告是快速决策 benchmark：Private Max 384K route A/B 与 Agent 每题 n=1，其余质量组 n=2，
  不宣称统计显著性。

官方资料：[Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode)、
[Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing)、
[V4 Pro GA](https://api-docs.deepseek.com/news/news260813)、
[LiteLLM Drop Unsupported Params](https://docs.litellm.ai/docs/completion/drop_params)。Portal 参数静默丢弃已记录在
[LLM-Portal #46](https://github.com/shiliai/LLM-Portal/issues/46)。机器可读汇总见
[`data/deepseek-private-online-comparison-20260817.json`](data/deepseek-private-online-comparison-20260817.json)。
