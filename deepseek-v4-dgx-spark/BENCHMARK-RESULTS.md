# DeepSeek V4 Thinking 聚焦评测结果

## 测试环境

- 日期：2026-08-12
- 硬件：2 台 NVIDIA DGX Spark（GB10）
- 候选执行器：Claude Code 2.1.207
- Online DS：`claude_ds` → `deepseek-v4-flash`
- Private DS：`claude_local` → 双机 Patch4 `deepseek-v4-flash-0731`
- 独立评审：`gpt-5.6-sol/xhigh`，无 fallback
- 隔离：每次候选执行使用独立 Git 工作区，只允许本地工具，不使用网络

本轮只重新执行 Private DS thinking-on。Private DS thinking-off 和 Online DS
复用同一冻结基准中的原始答案。每题综合分为确定性档位与 GPT 三项评分均值的平均值，
范围为 1 到 3。

## Thinking 证据

五个 Claude Code stream 均包含显式 `thinking` block：

| 指标 | 数量 |
|------|-----:|
| Stream | 5 |
| Thinking block | 25 |
| Thinking token event | 2,611 |

`alwaysThinkingEnabled` 客户端设置本身不能证明服务端启用了 thinking。本次同时要求：

1. Compose 最终渲染命令包含 `{"thinking":true}`，且不包含 `thinking:false`；
2. 每个 Claude Code stream 至少包含一个 `thinking` 或 `redacted_thinking` block。

## 结果

| 分类 | Private off（原始） | Private on（重跑） | Online DS（原始） |
|------|--------------------:|-------------------:|-------------------:|
| SWE / Debug | 2.500 | 2.833 | 3.000 |
| 终端 | 2.000 | 2.667 | 3.000 |
| 服务器运维 | 1.833 | 2.167 | 2.500 |
| 中文写作 | 1.833 | 1.667 | 2.667 |
| TypeScript | 1.667 | 1.667 | 2.667 |
| **五题均分** | **1.967** | **2.200** | **2.767** |

Thinking-on 相对原 Private DS 在三题提高、一题持平、一题下降，五题均分提高
0.233；但五题的 GPT 首选仍全部是 Online DS。结果说明 thinking 对该 Private DS
部署有方向性收益，但没有消除与 Online DS 的差距。

完整的脱敏数据、确定性通过数、逐题 thinking 计数和 GPT 结论见
[`benchmark-results-20260812.json`](./benchmark-results-20260812.json)。

## 限制

- 每个 treatment 每题只有一次样本，不能据此声称统计显著性。
- 仅 Private DS thinking-on 是本轮新执行，另外两列复用了冻结结果。
- 中文写作结果表明 thinking 不保证更少的无依据扩写。
- Patch4 镜像和模型权重未随仓库发布。
