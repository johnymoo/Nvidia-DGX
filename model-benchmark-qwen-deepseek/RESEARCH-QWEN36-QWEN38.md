# Qwen3.6 与 Qwen3.8 部署研究记录

更新时间：2026-08-17。范围限定为 Qwen3.6-35B-A3B 与 Qwen3.8-27B，目标硬件为
单张 48 GiB RTX 4090，工作负载为企业湖仓 SQL/Python、故障分析和图片识别。

## 官方资料核验

- [Qwen3.6-35B-A3B 模型卡](https://huggingface.co/Qwen/Qwen3.6-35B-A3B)
  说明其为 35B total / 3B activated MoE，支持视觉输入和 262K 原生 context；官方
  thinking 采样为 temperature 0.6、top-p 0.95、top-k 20、presence penalty 0。
- [Qwen3.6-35B-A3B-FP8 ModelScope](https://www.modelscope.cn/models/Qwen/Qwen3.6-35B-A3B-FP8)
  发布官方 128x128 block FP8 权重，并建议使用 vLLM 0.19 或更新版本。
- [Qwen3.6 官方仓库](https://github.com/QwenLM/Qwen3.6) 提供部署入口和版本说明。
- 本地官方 chat template 进一步确认 Qwen3.6 只有 `enable_thinking` 和
  `preserve_thinking`，没有 `reasoning_effort` 参数；Qwen3.8 的部署则实测支持
  `reasoning_effort=low`。

## 对比设计

两模型都使用 ModelScope 官方 FP8、同一 RTX 4090、同一 vLLM 0.19.0 镜像 digest，
CPU offload 固定为 0。题集包含 6 道 SQLite 可执行 SQL、6 道容器隐藏测试 Python、
6 道固定 cause/action code 的故障分析。四组都固定 seed=42、最大 4,096 输出 tokens；
non-thinking 和 thinking 分别使用官方推荐采样。

Qwen3.6 thinking 与 Qwen3.8 thinking-low 并非相同隐藏推理强度。这里比较的是两套
模型实际能提供的可上线请求策略：Qwen3.6 只能开/关，Qwen3.8 可限制为 low。

## 结论

Qwen3.8 在 non-thinking 和受控 thinking 两条线上均胜出。Qwen3.6 MoE 的生成明显
更快，但 non-thinking 的复杂 SQL 仅 2/6；thinking 又有 8/18 请求耗尽预算且没有
final content。Qwen3.8 thinking-low 达到 SQL 5/6、Python 5/6、故障分析 6/6，
没有截断或空 final。

默认部署选择 Qwen3.8-27B-FP8：普通请求 non-thinking，复杂 SQL/Python 和故障分析
按请求开启 `reasoning_effort=low`。Qwen3.6 不进入长期运行组合。图片能力沿用前一轮
Qwen3.8 实测；embedding 继续由 CPU-only Ollama 运行 BGE-M3，与生成模型隔离。
