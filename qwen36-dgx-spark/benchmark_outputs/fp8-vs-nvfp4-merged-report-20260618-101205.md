# Qwen3.6 GB10 FP8 vs NVFP4 合并评测报告

## 结论摘要
- 常规 16 项生成 benchmark：NVFP4 平均 **152.1 tok/s**，相对旧 8004 FP8 **+116.7%**，相对 PR200 FP8 **+109.8%**。
- 长上下文 TTFT：64K 基本持平；128K NVFP4 比 FP8 慢约 **+4.9%**；256K NVFP4 比 FP8 慢约 **+6.4%**。
- 长上下文 decode TPS：NVFP4 明显更快，64K/128K/256K 分别约 **+123.2% / +118.9% / +105.4%**。
- 轻量质量小测：FP8 **15/16**，NVFP4 **15/16**，同分；同一题 `long_two_fact` 两边都错。
- 官方 model card：NVFP4 相比 BF16 在 8 项公开评测上波动约 -0.8 到 +0.5，整体很小；但这不是 FP8 vs NVFP4 的直接表。

## 常规生成 benchmark 总览
| 部署 | 平均 tok/s | 中位 | min | max | errors |
|---|---:|---:|---:|---:|---:|
| 旧 8004 FP8 baseline | 70.2 | 70.0 | 69.1 | 71.7 | 0 |
| PR200 FP8 | 72.5 | 72.5 | 71.1 | 73.7 | 0 |
| 当前 NVFP4 | **152.1** | **159.2** | 66.0 | **179.0** | 0 |

## 长上下文 TTFT/TPS：FP8 vs NVFP4
| Context | FP8 TTFT | NVFP4 TTFT | TTFT 变化 | FP8 decode TPS | NVFP4 decode TPS | TPS 变化 | FP8 E2E | NVFP4 E2E | Correct |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 64K | 16.56s | 16.25s | -1.9% | 46.7 | **104.2** | **+123.2%** | 18.55s | 17.16s | ✅/✅ |
| 128K | 45.37s | 47.58s | +4.9% | 41.0 | **89.7** | **+118.9%** | 47.56s | 48.62s | ✅/✅ |
| 256K | 141.33s | 150.34s | +6.4% | 34.3 | **70.4** | **+105.4%** | 144.19s | 151.51s | ✅/✅ |

## 轻量质量/一致性测试
| Suite | Score | Accuracy |
|---|---:|---:|
| FP8 | 15/16 | 93.8% |
| NVFP4 | 15/16 | 93.8% |

| Test | Category | FP8 | NVFP4 | Note |
|---|---|---:|---:|---|
| `arith_1` | math | ✅ | ✅ |  |
| `arith_2` | math | ✅ | ✅ |  |
| `arith_3` | math | ✅ | ✅ |  |
| `riddle_1` | reasoning | ✅ | ✅ |  |
| `riddle_2` | reasoning | ✅ | ✅ |  |
| `riddle_3` | reasoning | ✅ | ✅ |  |
| `bat_ball` | reasoning | ✅ | ✅ |  |
| `logic_1` | logic | ✅ | ✅ |  |
| `logic_2` | logic | ✅ | ✅ |  |
| `alg_1` | coding | ✅ | ✅ |  |
| `python_1` | coding | ✅ | ✅ |  |
| `json_1` | format | ✅ | ✅ |  |
| `zh_knowledge` | knowledge | ✅ | ✅ |  |
| `en_knowledge` | knowledge | ✅ | ✅ |  |
| `long_retrieve_small` | long_retrieval | ✅ | ✅ |  |
| `long_two_fact` | long_retrieval | ❌ | ❌ | 两边都错；非 NVFP4 独有 |

## 官方 BF16 vs NVFP4 model-card 精度参考
| Benchmark | BF16 | NVFP4 | Δ |
|---|---:|---:|---:|
| MMLU Pro | 85.6 | 85.0 | -0.6 |
| GPQA Diamond | 84.9 | 84.8 | -0.1 |
| τ²-Bench Telecom | 95.5 | 94.7 | -0.8 |
| SciCode | 40.8 | 40.6 | -0.2 |
| AIME 2025 | 89.2 | 88.8 | -0.4 |
| AA-LCR | 62.0 | 62.0 | +0.0 |
| IFBench | 62.3 | 62.8 | +0.5 |
| MMMU Pro | 74.1 | 74.5 | +0.4 |

## 文件
- `/home/chriswang/project/nvidia-dgx/qwen36-dgx-spark/benchmark_outputs/long-context-ttft-fp8-20260618-100108.json`
- `/home/chriswang/project/nvidia-dgx/qwen36-dgx-spark/benchmark_outputs/long-context-ttft-nvfp4-20260618-093358.json`
- `/home/chriswang/project/nvidia-dgx/qwen36-dgx-spark/benchmark_outputs/quality-eval-fp8-20260618-100604.json`
- `/home/chriswang/project/nvidia-dgx/qwen36-dgx-spark/benchmark_outputs/quality-eval-nvfp4-20260618-100928.json`
- `/home/chriswang/benchmark_results_nvfp4_20260618_062149.json`