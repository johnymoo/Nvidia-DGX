# Qwen 与 DeepSeek 三模型评测

本项目发布 Qwen3.6-35B-A3B、Qwen3.8-27B 与
DeepSeek-V4-Flash-0731 的可复现评测数据、原始回答、冻结 HTML 报告和报告生成器。
评测完成于 2026-08-16，对应 [Issue #28](https://github.com/johnymoo/Nvidia-DGX/issues/28)。
报告现补充 48 GiB RTX 4090 上 Qwen3.8-27B-FP8 / vLLM 的同题质量、性能与
thinking-low 核验结果，部署方案见 [`../qwen38-rtx4090-vllm/`](../qwen38-rtx4090-vllm/)。
2026-08-17 又在同一 RTX 4090 上完成 Qwen3.6-35B-A3B-FP8 与 Qwen3.8-27B-FP8
面向复杂 SQL、Python 和故障分析的四组对比，研究依据见
[`RESEARCH-QWEN36-QWEN38.md`](RESEARCH-QWEN36-QWEN38.md)。

## 目的与上下文

评测用于比较三个已部署模型的实际吞吐和有限范围内的客观质量。两个
Qwen 配置在同一台 RTX 3090 工作站上串行测试；DeepSeek 使用双 NVIDIA
GB10，因此跨平台性能值表示部署实测，不代表同硬件架构效率排名。

DeepSeek-V4-Flash-0731 不是多模态模型。图片识别对 DeepSeek 标记为 N/A，
不发送图片，也不计入其宏平均分。

## 结果摘要

| 类别 | Qwen3.6 | Qwen3.8 | DeepSeek |
|---|---:|---:|---:|
| 图片识别 | 100.0% | 100.0% | N/A |
| 编程 | 100.0% | 100.0% | 100.0% |
| 写作约束 | 76.0% | 76.0% | 60.0% |
| 数学推理 | 75.0% | 58.3% | 100.0% |
| 宏平均 | 87.8%（4 类） | 83.6%（4 类） | 86.7%（3 类） |

单流生成均值分别为 133.2、30.1 和 68.8 tok/s。DeepSeek 在并发 6 时达到
229.3 tok/s；Qwen3.6 与 Qwen3.8 分别为 244.1 和 50.8 tok/s。由于硬件
不同，DeepSeek 与 Qwen 的速度不能视为同机 A/B。

DeepSeek 共执行 21 个非视觉请求，其中 20 个返回 final content。
`risk_memo` 只返回 reasoning、没有 final content，按失败计分并完整保留在
`data/deepseek-quality.json` 中。

Qwen3.8 评测端点为兼容既有客户端而继续暴露旧的公共 model alias，因此
`data/qwen38-quality.json` 的 `model` 字段与 Qwen3.6 相同；`tag=qwen38`
标识本次 treatment。Qwen3.8 的实际权重和运行配置通过部署 receipt 独立
校验，报告不把公共 alias 当作权重身份。完整 RTX 3090 安装/部署方案见
[`../qwen38-rtx3090/`](../qwen38-rtx3090/)。

## 架构

```text
OpenAI-compatible API
        |
        v
quality_benchmark.py --> quality JSON --> compare_quality.py
                                            |
performance JSON ---------------------------+
                                            v
                               generate_html_report.py
                                            |
                                            v
                                  report/index.html
```

编程回答在固定 Python 镜像中执行，容器无网络、只读、非 root，并限制 CPU、
内存、进程数和 capabilities。写作只评分题目明确声明的长度、结构和关键词
约束，不代表主观文学质量。

## 湖仓 Thinking 对比

| 模型与模式 | SQL | Python | 故障分析 | 宏平均 | 总耗时 | 截断/空 final |
|---|---:|---:|---:|---:|---:|---:|
| Qwen3.6 non-thinking | 33.3% | 66.7% | 83.3% | 61.1% | 54.7s | 0 / 0 |
| Qwen3.6 thinking | 33.3% | 33.3% | 91.7% | 52.8% | 485.9s | 8 / 8 |
| Qwen3.8 non-thinking | 66.7% | 66.7% | 91.7% | 75.0% | 254.1s | 0 / 0 |
| Qwen3.8 thinking-low | 83.3% | 83.3% | 100.0% | 88.9% | 797.7s | 0 / 0 |
| DeepSeek V4 Flash thinking | 66.7% | 50.0% | 83.3% | 66.7% | 245.5s | 0 / 0 |
| Online DS Flash thinking | 66.7% | 33.3% | 91.7% | 63.9% | 296.6s | 5 / 5 |

默认推理选择 Qwen3.8-27B-FP8。普通请求保持 non-thinking；复杂 SQL、Python 和
故障分析按请求开启 `reasoning_effort=low`。完整逐题报告见
[`report/lakehouse-thinking.html`](report/lakehouse-thinking.html)。私有 DeepSeek 与
online DS 都使用 `.env` 中的 OpenAI-compatible 变量和原生 `thinking=true`；其硬件、
网络和网关不同，245.5 秒与 296.6 秒总耗时均不参与与 RTX 4090 Qwen 的性能比较。

### 2026-08-17 参数矩阵（DeepSeek n=2）

新的 [`report/lakehouse-parameter-matrix.html`](report/lakehouse-parameter-matrix.html) 将
Qwen 选型、DeepSeek 质量、成本、TTFT、响应时间、TPS、冷启动、完整环境和逐次证据分开显示；
可分享版本为 [`report/lakehouse-parameter-matrix.pdf`](report/lakehouse-parameter-matrix.pdf)。完整结论、可复现命令和
NAS Ubuntu 网关 504 诊断见
[`report/LAKEHOUSE-PARAMETER-MATRIX-20260817.md`](report/LAKEHOUSE-PARAMETER-MATRIX-20260817.md)。

- 独立评审后剔除一题定义不完整的 CDC 测试，并修正拓扑排序 oracle；原始 JSON 不改写。
  同一 RTX 4090：Qwen3.8 裁决后 100.0%（原始 88.9%），Qwen3.6 为 80.6%（原始 75.0%）。
- private `deepseek-v4-flash-0731` 选 `high / 256K`（裁决后 90.3%、5m03s、13.1K token）；
  n=2 只能支持风险保守默认，不能证明稳定性优势。online `max / 384K` 虽为 95.8%，但约
  23m52s 和 152.3K token，不能作默认；延迟优先使用 online `low / 32K`。
- online 改用 SSE 后两轮 108 次请求均无 HTTP/网络错误。旧的非流式长请求 504 指向
  NAS Ubuntu Nginx 上游读取超时的高置信假设，仍需网关配置、日志和 A/B 证据确认。

使用私有 OpenAI-compatible 环境变量重跑 DeepSeek thinking treatment：

```bash
set -a
. /path/to/private/.env
set +a
python3 scripts/lakehouse_thinking_benchmark.py \
  --base-url "$OPENAI_BASE_URL" \
  --model "$MODEL" \
  --tag deepseek-v4-flash-0731-thinking \
  --mode deepseek-thinking \
  --api-key-env OPENAI_API_KEY \
  --max-tokens 4096 \
  --output /tmp/lakehouse-deepseek-thinking.json
```

`--api-key-env` 只读取进程环境；不要将 endpoint 或 token 写入 JSON、HTML 或 Git。

重跑 online DS thinking treatment：

```bash
set -a
. /path/to/private/.env
set +a
python3 scripts/lakehouse_thinking_benchmark.py \
  --base-url "${DS_BASE_URL%/}/v1" \
  --model "$DS_MODEL" \
  --tag online-deepseek-v4-flash-thinking \
  --mode deepseek-thinking \
  --api-key-env DS_AUTH_TOKEN \
  --max-tokens 4096 \
  --output /tmp/lakehouse-online-deepseek-thinking.json
```

## 文件清单

| 路径 | 用途 |
|---|---|
| `scripts/quality_benchmark.py` | 运行图片、编程、写作与数学质量题；支持排除图片类别 |
| `scripts/compare_quality.py` | 校验题目身份并计算三模型类别分数和宏平均 |
| `scripts/generate_html_report.py` | 生成包含配置、图表、题目和原始回答的单文件 HTML |
| `scripts/lakehouse_thinking_benchmark.py` | 运行可执行 SQL、隐藏测试 Python 和编码化故障分析 |
| `scripts/generate_lakehouse_report.py` | 生成 Qwen 与 DeepSeek 逐题对比 HTML |
| `scripts/run_deepseek_parameter_matrix.sh` | 运行 private/online DS 的 low、high、max 参数矩阵；支持 `DEEPSEEK_MATRIX_REPEATS` |
| `scripts/generate_parameter_matrix_report.py` | 生成按质量、成本、稳定性分区的参数矩阵报告 |
| `scripts/adjudicate_lakehouse_results.py` | 在不覆盖 v1 原始证据的前提下应用评分契约勘误 |
| `scripts/inference_latency_benchmark.py` | 计量 SSE TTFT、端到端响应时间和解码 TPS |
| `scripts/vision_quantization_benchmark.py` | 运行 Qwen3.8 量化候选的确定性图片识别回归 |
| `scripts/generate_quantization_report.py` | 生成 FP8、Q4、Q4 + MTP2、Q6 四配置选型报告 |
| `scripts/capture_inference_environment.py` | 采集脱敏的主机、模型、容器配置和服务启动证据 |
| `data/*-quality.json` | 三个模型的逐题原始输出和客观验证结果 |
| `data/performance-comparison.json` | 两个 Qwen 配置的同机性能比较 |
| `data/deepseek-performance.json` | DeepSeek 双 GB10 性能结果 |
| `data/quality-comparison.json` | 从三份质量 JSON 重建的汇总 |
| `data/lakehouse-*.json` | 六个 treatment 的逐题原始输出与客观评分 |
| [`report/index.html`](./report/index.html) | 2026-08-16 已完成评测的冻结 HTML 基线报告 |
| [`report/lakehouse-thinking.html`](./report/lakehouse-thinking.html) | 2026-08-17 Qwen 同机 thinking 与 DeepSeek 补充对比 |
| [`report/lakehouse-parameter-matrix.html`](./report/lakehouse-parameter-matrix.html) | DS 参数矩阵的可视化汇总（n=2） |
| [`report/lakehouse-parameter-matrix.pdf`](./report/lakehouse-parameter-matrix.pdf) | 嵌入 Noto CJK 中文字体的 A4 分享版 |
| [`report/qwen38-quantization.html`](./report/qwen38-quantization.html) | RTX 4090 上 Qwen3.8 四种推理配置的交互式选型报告 |
| [`report/qwen38-quantization.pdf`](./report/qwen38-quantization.pdf) | 嵌入 Noto CJK 中文字体的 Qwen3.8 选型分享版 |
| [`report/README.md`](./report/README.md) | 报告哈希、输入身份和可直接复用条件 |

`report/index.html` 是为后续同题集直接参考而保留的冻结证据快照；普通重新
生成的文件写入 `report/generated/`，该目录由 `.gitignore` 排除。

## 安装与依赖

报告与比较脚本只依赖 Python 3.10+ 标准库。重新运行编程质量题还需要
Docker，以及脚本中固定 digest 的 Python 镜像。项目没有第三方 Python
依赖，因此不需要创建 `requirements.txt` 或 `pyproject.toml`。

## 配置

质量评测通过命令行参数接收 API 地址和模型 ID。不要把生产地址、内网 IP、
凭证或主机名写入仓库；本项目提交的数据统一使用 `localhost` 占位符。

```bash
python3 scripts/quality_benchmark.py \
  --base-url http://localhost:8890/v1 \
  --model deepseek-v4-flash-0731 \
  --tag deepseek-v4-flash-0731 \
  --exclude-category image_recognition \
  --output /tmp/deepseek-quality.json
```

## 生成报告

从项目目录执行：

```bash
python3 scripts/compare_quality.py \
  --qwen36 data/qwen36-quality.json \
  --qwen38 data/qwen38-quality.json \
  --deepseek data/deepseek-quality.json \
  --output data/quality-comparison.json

mkdir -p report/generated
python3 scripts/generate_html_report.py \
  --performance data/performance-comparison.json \
  --deepseek-performance data/deepseek-performance.json \
  --qwen36-quality data/qwen36-quality.json \
  --qwen38-quality data/qwen38-quality.json \
  --deepseek-quality data/deepseek-quality.json \
  --quality-comparison data/quality-comparison.json \
  --qwen38-4090-quality ../qwen38-rtx4090-vllm/receipts/quality-instruct-20260816.json \
  --qwen38-4090-performance ../qwen38-rtx4090-vllm/receipts/benchmark-20260816.json \
  --qwen38-4090-thinking-quality ../qwen38-rtx4090-vllm/receipts/quality-thinking-low-20260816.json \
  --deepseek-endpoint-label http://localhost:8890/v1 \
  --final-model Qwen3.6 \
  --output report/generated/index.html

python3 -m http.server 8766 --bind 0.0.0.0 --directory report/generated
```

重新生成湖仓 thinking 报告：

```bash
python3 scripts/generate_lakehouse_report.py \
  --q36-off data/lakehouse-qwen36-off.json \
  --q36-thinking data/lakehouse-qwen36-thinking.json \
  --q38-off data/lakehouse-qwen38-off.json \
  --q38-thinking data/lakehouse-qwen38-thinking-low.json \
  --deepseek-thinking data/lakehouse-deepseek-thinking.json \
  --online-deepseek-thinking data/lakehouse-online-deepseek-thinking.json \
  --recommendation '默认 Qwen3.8；复杂请求按需开启 reasoning_effort=low。' \
  --output report/generated/lakehouse-thinking.html
```

重新生成 Qwen3.8 量化与 MTP2 报告：

```bash
python3 scripts/generate_quantization_report.py
```

浏览器打开 `http://<服务器地址>:8766/`。不重新生成时，也可以直接查看已提交的
[`report/index.html`](./report/index.html)。

若缺少 DeepSeek 性能输入，可省略 `--deepseek-performance`；报告会将缺失指标和
相关比率显示为 N/A。

## 验证

```bash
python3 -m py_compile scripts/*.py
python3 scripts/compare_quality.py \
  --qwen36 data/qwen36-quality.json \
  --qwen38 data/qwen38-quality.json \
  --deepseek data/deepseek-quality.json \
  --output /tmp/quality-comparison.json
cmp data/quality-comparison.json /tmp/quality-comparison.json
```

## 已知限制

- 质量集合只有 27 道题；DeepSeek 适用其中 21 道，不是统计学意义上的大型基准。
- 写作分数只衡量客观约束遵循。
- 三模型量化、硬件和并行配置不同；只有两个 Qwen 的性能属于同机 A/B。
- Qwen3.8 的兼容 model alias 不能单独证明底层权重身份，复现实验时应另存
  模型清单或引用
  [`../qwen38-rtx3090/receipts/deployment-20260815T144804Z.json`](../qwen38-rtx3090/receipts/deployment-20260815T144804Z.json)。
- 原始 JSON 包含模型输出和 reasoning，文件体积会随新增题目增长。
- 公开版性能 JSON 保留采集结果的原始小数精度，最多六位且不补零；完整精度的
  原始 receipt 不进入公开仓库。
- 服务状态描述是评测时快照，不应代替当前部署健康检查。
