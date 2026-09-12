# GLM-5.3-Flash EXL3 on dual DGX Spark (GB10)

Maturity: **Reference**

## 目的

记录 `GLM-5.3-Flash`（EXL3/TR3 4bpw 量化，DFlash2 k=7 投机解码）在两台
NVIDIA DGX Spark（GB10）上的双机 vLLM 部署配方与 2026-09-10/11 实测结果，
并给出与同集群 DeepSeek-V4-Flash-Vision 部署的对照数据，用于路由/切换决策。

## 结果摘要（本机实测，2026-09-11）

| 维度 | 实测 |
|---|---|
| decode c1 结构化 | 64.1 tok/s（DFlash2 accept 6.59/step） |
| decode c1 散文 | 24.4 tok/s |
| 并发聚合（结构化） | c2 104.1 / c4 165.7 tok/s |
| prefill 阶梯 | 8k→256k：1,523→1,270 tok/s（TTFT 5.9s→205s） |
| hermes 真实 agent 任务 | 3/3 成功，总 wall 423.9s（对照 DeepSeek 489.6s） |
| 47 项双语菜单视觉任务 | off 32/47、low-thinking 38/47 |
| 上下文 | 300k（本机 UMA 包络），KV 池 309,523 tok（1.03×） |
| 启动到 healthy | 531–544s |

完整对比表见
[`BENCHMARK-RESULTS.md`](BENCHMARK-RESULTS.md)，机器可读数据见
[`benchmark-results-20260911.json`](benchmark-results-20260911.json)，
可视化图表见
[`glm-vs-ds-comparison.html`](glm-vs-ds-comparison.html) /
[`glm-vs-ds-comparison.png`](glm-vs-ds-comparison.png)。

## 上下文

- 服务配方来自上游
  [MiaAI-Lab/GLM-5.3-Flash-EXL3-2x-DGX-Sparks](https://github.com/MiaAI-Lab/GLM-5.3-Flash-EXL3-2x-DGX-Sparks)
  （AGPL-3.0；EXL3 checkpoint 另有自身许可；DFlash2 drafter 为 CC BY-NC-ND，
  **非商业许可**）。本目录只保存本机适配层与实测证据，不复制上游脚本。
- 本 kit 的 GPU 可见统一内存为 119.63 GiB，低于上游参考 kit（约 127 GiB），
  因此上游默认的 850k/0.85 配方不可照抄：`500000/0.84` 会因 KV 池不足
  （需 10.98 GiB）拒绝启动；`450000/0.89` 会在 torch.compile 阶段触发
  host OOM（GB10 统一内存下 GPU 配额就是物理 RAM 包络）。
  **实测安全点为 300k / 0.84**，与同集群 DeepSeek 部署一致。
- 两台主机的共享缓存目录曾被 root 属主的旧实验占用，启动器无法写入
  triton/tilelang 子目录；窗口脚本在启动前做属主检查与修复（无需 sudo，
  通过一次性容器 chown）。
- DeepSeek 对照腿使用同集群既有部署；停/启用走其自带生命周期脚本，
  本配方不复制其内部实现。

## 架构

```text
OpenAI client (:18888)
    |
head DGX Spark (rank 0 + API)
    | vLLM TP=2, nnodes=2, NCCL over RoCE CX7 fabric
worker DGX Spark (rank 1, headless)
```

- 权重：`Mia-AiLab/GLM-5.3-Flash-EXL3-TR3-4bpw`（~164 GiB，两台各一份），
  drafter `incoai/GLM-5.3-Flash-DFlash2`（~2.3 GiB）。
- 镜像：由上游仓库 Dockerfile 在 head 本地构建（GHCR 公共标签早于 E2/E3
  内核），构建需在停止同 host 大模型负载后进行（nvcc 编译期内存峰值高）。
- `scripts/window-step.sh` 编排完整验证窗口：空闲检查 → 停对照服务 →
  构建/启动 GLM → 跑 benchmark → 停 GLM → 恢复对照服务 → 冒烟验证；
  任何启动失败都会留在现场供重试，恢复步骤幂等。

## 文件清单

| 文件 | 说明 |
|------|------|
| `recipe.yaml` | catalog 元数据（Reference maturity，无 Verified receipt） |
| `run.sh` | 本地校验与说明入口；不做任何远程/生命周期操作 |
| `glm53.env.example` | 无凭证、无真实主机信息的配置模板 |
| `scripts/window-step.sh` | 验证窗口编排器（up / restore / status） |
| `scripts/prep_remote.sh` | 窗口前准备：权重完整性、GID/端口检查、权重同步 |
| `scripts/bench_prefill_ladder.py` | 唯一 salt 冷 prefill 阶梯（含 MemAvailable 熔断） |
| `scripts/bench_concurrent.py` | c2/c4 并发流式 decode |
| `scripts/summarize.py` | 汇总各 bench JSON 为 summary.json |
| `scripts/run-hermes-real-tasks.sh` | hermes 真实 agent 任务对比腿（GLM/DS，可选） |
| `BENCHMARK-RESULTS.md` | 方法、数字与 DeepSeek 对照结论 |
| `benchmark-results-20260911.json` | 脱敏机器可读结果 |
| `glm-vs-ds-comparison.html` / `.png` | 对比图表源与导出 |

## 复现要点

1. 两台 DGX Spark（GB10），CX7 直连 fabric，免密 SSH，Docker。
2. clone 上游仓库到 head，按 `glm53.env.example` 填写 `.env`；
   权重可由上游 `download.sh` 预取（两台各 ~166 GiB 磁盘）。
3. `scripts/prep_remote.sh verify` 校验 GID/端口/权重完整性。
4. `scripts/window-step.sh up`（会停止同 host 的大模型负载）→ 依序执行
   decode/prefill/并发/视觉基准 → `restore` 恢复原服务并冒烟。
5. 判读口径与完整数字见 [`BENCHMARK-RESULTS.md`](BENCHMARK-RESULTS.md)。

## 限制

- 上下文被本 kit 统一内存限制在 300k（1.03× 并发）；更大 KV 需要更高
  `GPU_MEM_UTIL`，但 0.85 以上已实测触发编译期 host OOM（含用户会话进程）。
- DFlash2 为非商业许可，商用需切换 MTP k=2（decode 约 25 tok/s 档）或取得
  授权；recipe 脚本本体遵循上游 AGPL-3.0。
- 散文 decode（24.4 tok/s）显著低于对照 DeepSeek（38–50 tok/s）；速度优势
  集中在高接受率结构化内容。
- hermes 真实任务腿依赖私有 hermes 安装与任务集，属可选基准；仓库内仅保留
  runner 与分数，不包含任务提示词。
- 47 项菜单视觉任务的判分 truth 属生产业务数据，本仓库只发布分数与方法，
  不发布 truth 表或生产图片。

## 失效条件

- 上游 overlay / EXL3 checkpoint / DFlash2 版本变更；
- GB10 固件或驱动改变统一内存暴露量（119.63 GiB 基准失效）；
- `GPU_MEM_UTIL`、`MAX_MODEL_LEN`、MNBT、TP 拓扑、投机解码方法任一变更；
- 上游 kit 的 CX7/GID 约定变化。
