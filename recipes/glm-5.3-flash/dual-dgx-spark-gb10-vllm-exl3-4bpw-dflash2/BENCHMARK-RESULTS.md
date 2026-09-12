# GLM-5.3-Flash EXL3 双 GB10 基准结果（2026-09-10/11）

- 硬件：2× NVIDIA DGX Spark（GB10，统一内存；GPU 可见 119.63 GiB），CX7 RoCE 直连
- 服务：MiaAI-Lab EXL3 配方（EXL3/TR3 4bpw + DFlash2 k=7，TP=2 nnodes=2，E3 内核）
- 生效配置：`MAX_MODEL_LEN=300000`、`GPU_MEM_UTIL=0.84`、MNBT 7168、seqs 4、
  rightsize indexer；KV 池 309,523 tokens（fp8_ds_mla，可用 9.87 GiB）
- 对照：同集群 DeepSeek-V4-Flash-Vision（现网生产数字，MTP k=6）
- 状态：单轮验证窗口 + 一晚补测，非统计结论；测量脚本见 `scripts/`

## 1. 启动与配置实测

| 项 | 值 |
|---|---|
| 启动到 healthy | 531–544s（含权重加载、CUDA graph、DFlash2 shape warmup） |
| 本 kit UMA 安全包络 | 300k / 0.84 一次通过；450k / 0.89 在 torch.compile 阶段 host OOM（内核连带终止用户会话进程） |
| KV 池 | 309,523 tok = 300k 的 1.03×；>300k prompt 直接拒绝 |
| 失败启动史 | 500k/0.84 KV 池不足被拒（需 10.98 GiB）；0.89 编译期 OOM；两台 root 属主缓存目录需先修复 |

结论：GB10 上 `GPU_MEM_UTIL` 即物理 RAM 包络；上游参考 kit（约 127 GiB）的
0.85–0.87 配方在 119.63 GiB 的机器上不可照抄。

## 2. Decode（temp 0，thinking off，400 token，5 次取中位）

| 场景 | GLM-5.3-Flash EXL3 | DeepSeek-V4-Flash 对照 |
|---|---:|---:|
| structured c1 | **64.1** tok/s（accept/step 6.59，ratio 0.94） | 43–55 tok/s（结构化文本） |
| prose c1 | 24.4 tok/s（accept/step 2.24） | **38–50** tok/s（生产均值 ~38） |
| c2 structured 聚合 | 104.1 tok/s（每流 55.9） | 未测同口径 |
| c4 structured 聚合 | 165.7 tok/s（每流 44.0） | 未测 |
| c2 prose 聚合 | 26.9 tok/s | 未测 |
| TTFT c1 | structured 0.340s / prose 0.345s | 生产 64%≤0.5s、86%≤1s |
| 并发冷启动 TTFT | c2 4.3s / c4 6.8s（后续流 0.34–0.41s） | — |

投机解码对比：DFlash2 k=7 每步接受数随内容剧烈波动（结构化 6.59，散文 2.24）；
对照 DeepSeek 原生 MTP k=6 稳定在 3.11。DFlash2 为 CC BY-NC-ND 非商业许可。

## 3. Prefill 阶梯（唯一 salt 冷 prompt，prompt tok 为服务端计数）

| 目标档 | 实际 prompt tok | TTFT（两轮） | prefill tok/s（两轮） |
|---|---|---|---|
| 8k | 9,561 / 8,974 | 17.4 / 5.9 s | 550 / 1,523（首轮含启动后 JIT） |
| 16k | 15,661 / 17,998 | 14.9 / 13.7 s | 1,054 / 1,317 |
| 32k | 36,444 / 34,106 | 28.5 / 21.1 s | 1,278 / 1,614 |
| 64k | 73,327 / 73,330 | 55.9 / 52.4 s | 1,312 / 1,398 |
| 128k | 147,102 / 156,439 | 126.6 / 117.1 s | 1,162 / 1,336 |
| 256k | 267,274 / 285,950 | 205.5 / 225.2 s | 1,301 / 1,270 |

上游 README 声明 E3 后 8k–256k 为 1,430–1,640 tok/s：平台期复现，绝对值低 5–8%。
全程采样 MemAvailable，最低 3,040 MB，未触发 1,200 MB 熔断。

## 4. hermes 真实 agent 任务（3 任务 × 2 腿，同晚同条件，thinking=low）

| 任务 | GLM wall | DS wall | GLM decode TPS | DS decode TPS | 输出 tok GLM/DS |
|---|---:|---:|---:|---:|---:|
| codex-quota-reset | **140.5s** | 260.7s | 27.8 | 60.1 | 1,686 / 4,989 |
| daily-stock-price-monitor | 189.4s | **166.9s** | 30.1 | 39.8 | 1,261 / 5,238 |
| hermes-version-check | 93.9s | **62.0s** | 26.0 | 41.6 | 797 / 2,061 |
| 合计 | **423.9s** | 489.6s | 28.2 | 46.7 | 3,744 / 12,288 |

- GLM 3/3 成功：glm47 工具调用 + 多轮 agent 循环全程无失败。
- GLM 输出极简（总输出为对照的 30%），弥补 decode TPS 低 40% 的劣势，总 wall 快 16%。
- 服务端 prefix cache：GLM 84.4% / DS 88.9%；uncached prefill 1,085 / 1,320 tok/s。
- API 差异：GLM usage 不含 cached_tokens 字段（agent 层统计为 0），依赖该字段
  的统计需读服务端 /metrics。
- 任务提示词与判分依赖私有 hermes 安装，不在本仓库发布。

## 5. 视觉任务

| 项 | GLM | DS 对照 |
|---|---:|---:|
| 6 道合成视觉题（颜色/计数/空间） | 6/6 | 6/6 |
| 1024×768 流式 TTFT（off c1） | 1.48s | 1.41s |
| 1024×768 流式聚合 tok/s（off c1 / on c1） | 27.2 / 23.2 | 28.4 / 43.5（high 口径） |
| 47 项双语菜单视觉表单任务 | off **32/47**、low-thinking **38/47**（15–16s） | off **9/47**（13s）；high 无输出（262s 推理循环） |

菜单任务方法：生产来源图片 + 固定 JSON schema 严格判分，47 个字段（表头日期、
星期标签、40 个内容字段）。GLM off 档失败模式为整列错位；low-thinking 收敛为
局部字段错误，且是三个受测模型中唯一 low-thinking 提分的。判分 truth 为生产
业务数据，本仓库只发布分数与方法。GLM 与量化前官方 FP8 的一致性由上游第三方
KLD 面板背书（0.0246 nats，与官方 FP8 自评 0.0246 持平）。

## 6. 结论

- GLM-5.3-Flash EXL3 在本 kit 的 README 速度声明基本复现（结构化 c1 64.1 vs 声明
  62.9；c2 聚合 104.1 vs 103.3；prefill 平台期略低 5–8%）。
- 与 DeepSeek-V4-Flash 对照无全胜方：菜单/视觉质量与结构化吞吐 GLM 显著占优，
  散文速度、上下文（300k vs 1M）、许可（MIT vs CC BY-NC-ND/AGPL）DeepSeek 占优，
  agent 真实任务端到端打平（-16% ~ +13% 逐任务互有胜负）。
- 决策建议：按路由灰度（视觉/表单类 → GLM），文本主力维持现网；或维持现状。
  切换前需解决 usage 字段适配与 DFlash2 许可。

## 复现

```bash
./run.sh validate
# 在 head 上：glm53.env.example -> 上游 checkout 的 .env，然后
# scripts/prep_remote.sh verify && scripts/window-step.sh up   # 停对照服务、起 GLM、跑基准
# scripts/window-step.sh restore                               # 恢复对照服务并冒烟
```

原始窗口日志保留在部署机 `~/glm53-eval/results/`（含主机名与拓扑，不发布）。
