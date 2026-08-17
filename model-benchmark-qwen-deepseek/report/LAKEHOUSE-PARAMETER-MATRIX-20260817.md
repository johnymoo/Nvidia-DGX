# 湖仓推理参数矩阵（2026-08-17）

交互式报告见 [`lakehouse-parameter-matrix.html`](./lakehouse-parameter-matrix.html)。
DeepSeek 每个处理组完成两次独立运行；Qwen 同机对比各完成一次。全部使用
`lakehouse-thinking-v1` 的固定 18 题：可执行 SQL、隐藏 Python 测试、编码化故障分析各 6 题。

## 决策

- 主推理默认选 `Qwen3.8-27B-FP8`，对复杂 SQL、Python 和故障分析请求设
  `reasoning_effort=low`。同一 RTX 4090、CPU offload 0 下，其宏平均为 88.9%，
  高于 `Qwen3.6-35B-A3B-FP8` thinking 的 75.0%。
- private `DeepSeek-V4-Flash-0731` 若作为专用线路，选 `high / 256K`：平均 79.2%、
  5m03s、约 13.1K 输出 token；它是 private 三个档位里平均质量最高且明显比
  `max / 384K` 稳定的设置。
- online `deepseek-v4-flash` 不将 `max / 384K` 设为默认。它平均 87.5%，但每 18 题
  约 23m52s、约 152K 输出 token。延迟优先时，online `low / 32K` 平均 81.9%、2m05s、
  约 12.4K token。

Qwen 与 DeepSeek 的硬件不同，不能用本报告的时延跨端点比较吞吐。private 使用固定
`deepseek-v4-flash-0731`；online 仅暴露动态别名 `deepseek-v4-flash`，也不能解释为同 revision A/B。
Qwen3.6 的已部署 vLLM `max-model-len` 为 32K，输入 prompt 也计入该窗口，故本轮可接受的
最大输出预算为 28K；Qwen3.8 运行 32K 输出预算。该 Qwen 比较反映当前真实部署，而非严格相同
输出上限的模型能力断言。

## 汇总

| 处理组 | 宏平均 | 标准差 | 18 题平均耗时 | 平均输出 token | HTTP/网络错误 |
|---|---:|---:|---:|---:|---:|
| Qwen3.8 FP8 / low / 32K（n=1） | 88.9% | - | 13m18s | 15.8K | 0 |
| Qwen3.6 FP8 / thinking / 28K（n=1） | 75.0% | - | 10m39s | 70.7K | 0 |
| private DS / low / 32K | 72.2% | 0.0pp | 5m07s | 13.7K | 0 |
| private DS / high / 256K | 79.2% | 2.0pp | 5m03s | 13.1K | 0 |
| private DS / max / 384K | 76.4% | 9.8pp | 5m17s | 14.0K | 0 |
| online DS / low / 32K | 81.9% | 5.9pp | 2m05s | 12.4K | 0 |
| online DS / high / 256K | 80.6% | 3.9pp | 18m42s | 123.0K | 0 |
| online DS / max / 384K | 87.5% | 2.0pp | 23m52s | 152.3K | 0 |

## 504 诊断

之前的 504 出现在 online `high / 256K` 的**非流式**请求。响应头显示 Nginx；客户端
超时是 14,400 秒，仍收到网关 504，因此它不是客户端的 900 秒限制，也没有在 private
`-0731` 的 256K 首轮重现。Nginx 部署在 NAS Ubuntu，现有访问条件不能直接读取该主机的
配置或日志。

矩阵中的 108 次 online 请求改为 SSE 后均完成，HTTP/网络错误为 0。它证明网关可以在
持续向下游转发字节时承受超过五分钟的模型思考；不证明高/max 档位具有可接受的延迟。

应在 NAS Ubuntu 的 Nginx `location /v1/chat/completions` 应用并验证如下配置，然后做一次
非流式长请求回归：

```nginx
proxy_connect_timeout 30s;
proxy_read_timeout 21600s;
proxy_send_timeout 21600s;
send_timeout 21600s;
proxy_buffering off;
```

将超时设为服务级上限后，还应在调用方保留按业务设置的 deadline、并发限制和取消策略；
不要仅靠扩大 Nginx 超时把 `max / 384K` 作为默认请求。

## 可复现运行

从 `model-benchmark-qwen-deepseek` 目录运行，模型地址和密钥只从 `.env` 读取，不写入 JSON、HTML 或 Git：

```bash
DEEPSEEK_MATRIX_REPEATS=2 \
  ./scripts/run_deepseek_parameter_matrix.sh data/lakehouse-parameter-matrix

python3 scripts/generate_parameter_matrix_report.py \
  --input-dir data/lakehouse-parameter-matrix \
  --expected-deepseek-runs 2 \
  --recommendation 'write the measured conclusion here' \
  --output report/lakehouse-parameter-matrix.html
```

`run_deepseek_parameter_matrix.sh` 默认运行三次；`DEEPSEEK_MATRIX_REPEATS` 可显式设定完整重复数。
online 请求强制采用 SSE 和官方 `thinking`/`reasoning_effort` 字段；private 请求使用 DSpark 的
chat-template thinking 开关与官方本地 general 采样配置。
