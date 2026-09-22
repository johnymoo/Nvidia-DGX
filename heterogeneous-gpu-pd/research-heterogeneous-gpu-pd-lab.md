# heterogeneous-gpu-pd-lab（器灵 Soulmate）调研：稠密加速 / 异构 GPU PD

- 调研日期：2026-09-22
- 来源仓库：https://github.com/Soulmate-Halo/heterogeneous-gpu-pd-lab （本地快照：~/project/heterogeneous-gpu-pd-lab-main，无 git 历史 tarball）
- 目的：为「RTX 3090 + 2× DGX Spark GB10」异构组合预研方法论与数据空白点

## 1. 仓库性质（重要）

这是**实验记录仓库，不是开源工具**。作者（v1.6）明确"不公开部署命令、代码补丁、服务地址和切层策略"；`make_*.py` 仅为画图脚本，`results/` + `data/` 是实验详档与 CSV。能拿走的是**方法论与实验设计**，工程实现需用 llama.cpp / vLLM / SGLang 原生能力自行复现。

## 2. 方法论核心（llama.cpp / vLLM 生态可复现）

| 方法 | 机制 | 作者实测锚点 |
|---|---|---|
| 稠密加速 | 小显存卡算前段层 + 大内存主机算后段层，相邻微批在"稠密区"重叠，两机同时出力 | 9B Q6_K：3060+395 组合 Prefill 2129.69，比最快的 3060 单卡还 +34% |
| 阶段分离 PD | 加速卡做全部 Prefill、主机做 Decode | 27B Q4_K_M：TTFT 1073ms 对 395 单机 4825ms（-77.8%），Decode 不掉 |
| 单服务切层 | 一个 llama-server 内 tensor split 0.38/0.62 跨两设备 | Qwen3.8-Flash Q4：C4 Prefill 633.7 / Decode 71.2 tok/s |
| PP2 流水（六卡） | 首段 TP2 双 6000D 专注 Prefill，尾段 TP4 四 Spark 接缓存并生成（DS4.1 Flash CED 架构允许 Prefill 专用路径不装全模型） | 32K Prefill 16000+ tok/s（V8）；同配置 C8 对纯 TP4 提升 4.54×/7.82× |

## 3. 作者记录中所有涉及 DGX Spark 的实验

| 实验 | Spark 数量 | 加速卡 | 模型 | 核心数据 |
|---|---|---|---|---|
| 27B-SPARK-01（09-11） | 1 | RTX 3080 20GB | Qwen3.8-27B Q4_K_M | 组合 Prefill 1603.20 对 3080 单卡 1113.13（**+44.03%**）；Decode 优先档 2K 63.97；均衡 C1–C6 聚合 Prefill ~1088，126/126 |
| FLASH-SPARK-01（09-14） | 1 | RTX 6000D | Qwen3.8-Flash-Next NVFP4 | 8K Prefill 8157.74；C6 聚合输出 414.90；PP2 档 8696.94 / 284.56 |
| DS41-6GPU-01（09-14→20，V1–V8） | 4（TP4 尾段） | 2× RTX 6000Dpro（TP2 首段） | DeepSeek-V4.1-Flash | 32K Prefill 16297–16326 tok/s；短代码 C32 聚合解码 442.02 tok/s |
| EXT-DGX-01 | 外部参考 | — | Qwen3.5-9B / Qwen3.8-27B NVFP4 | 社区数字：~1000 Prefill、25–30 单流 Decode、107 聚合 Decode（C1–C6） |

## 4. 空白格：作者没测过的组合（我们可做的新数据）

1. **2 台 Spark 的段内并行**：Spark 只出现 1 台或 4 台（TP4），从无 TP2×2 Spark 记录。
2. **2× Spark + 消费显卡**：整个仓库无此组合记录。
3. **RTX 3090**：作者明确写"仓库里没有任何 RTX 3090 的实测数据，这张卡在选型阶段就被排除"——原因是 3090 不符合其"小显存加速卡"叙事，非技术缺陷。27B Q4_K_M（~16GB）3090 24GB 可整卡装下。
4. **Spark 单机基线（27B Q4_K_M）**：作者明确"未测"。补这格才能回答"组合是否超过单 Spark"。

## 5. 我们的候选实验（RTX 3090 + 2× DGX Spark）

- E1 基线：3090 单卡、Spark 单机（llama-bench pp/tg + llama-server 服务态），模型对齐 27B-SPARK-01 的 Qwen3.8-27B Q4_K_M，可直接对标其 +44.03% 数字
- E2 三设备稠密/切层：llama.cpp RPC 组网，3090 + 2×Spark tensor-split（复刻 FLASH-SPLIT-01 思路）
- E3 PD：3090 全 Prefill + 2×Spark TP2 Decode（复刻 PD + 段内并行的空白格）
- E4 小模型稠密重叠：9B Q6_K 上复刻 9B-PIPE-01（唯一有双单机基线的设计，最容易得出干净结论）

注意口径：llama-bench 裸算与服务端到端不是同一口径（作者反复强调）；投机解码成绩对输入内容敏感（重复文本 100% 接受率 vs 自然语言 17.7%）。
