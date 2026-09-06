# 部署问题日志

GB10 (DGX Spark) 部署过程中遇到的问题、解决方案和经验总结。

---

## 目录

| 日期 | 主题 | 状态 |
|------|------|------|
| [2025-07-22](#2025-07-22---sensevoice-gpu-加速失败) | SenseVoice GPU 加速失败 | ⏳ 待 PyTorch 支持 |
| [2026-02-08](#2026-02-08---cuda-环境配置踩坑) | CUDA 环境配置踩坑 | ✅ 已解决 |
| [2026-03-04](#2026-03-04---cogvideox-5b-内存不足) | CogVideoX-5B 内存不足 | ❌ 硬件限制 |
| [2026-09-05](#2026-09-05---dspark-vision-容器-cudaerrornotpermitted) | DSpark Vision 容器 cudaErrorNotPermitted（daemon-reload 撤销 GPU 设备访问） | 🟡 已缓解，待长时间验证 |
| [2026-09-05](#2026-09-05---dspark-vision-多轮对话累计图片超限-400) | DSpark Vision 多轮对话累计图片超限 400（`At most 8 image(s)`） | ✅ 上限 16 → 32（09-06 同步上游 #231）；网关侧裁剪待做 |

---

## 2025-07-22 - SenseVoice GPU 加速失败

### 场景

部署 SenseVoice-Small 语音识别服务，希望启用 GPU 加速以提升推理速度。

### 遇到的问题

**Blackwell GPU 架构不兼容**

```
RuntimeError: no kernel image is available for execution on the device
```

**技术细节**:
- GB10 使用 NVIDIA Blackwell 架构 (sm_121)
- 当时 PyTorch 2.10 + CUDA 12.6 只支持 sm_80-sm_90 (Hopper/Ada 架构)
- Blackwell 需要 CUDA 12.8+ 和 PyTorch 2.8+ (当时未发布)

### 解决方案

切换到 CPU-only 模式:
- 修改 Dockerfile 使用 PyTorch CPU wheel
- 设置环境变量 `DEVICE=cpu`
- 牺牲速度换取稳定性

### 反思

1. **新硬件有软件生态滞后**: Blackwell 是新架构，软件支持需要时间
2. **CPU fallback 是保底方案**: 虽然 15x 慢于 GPU，但能工作
3. **关注 PyTorch 发布**: 等待官方 2.8+ 版本支持 Blackwell

### 后续

- [ ] 关注 PyTorch 2.8+ 发布进度
- [ ] 测试新版 PyTorch 对 Blackwell 的支持
- [ ] 评估 CUDA 12.8+ 是否可用

---

## 2026-02-08 - CUDA 环境配置踩坑

### 场景

尝试在 GB10 上手动配置 CUDA/cuDNN 环境以运行深度学习模型。

### 遇到的问题

**版本冲突地狱**

- 手动安装 CUDA Toolkit 与系统预装版本冲突
- cuDNN 版本与 CUDA 版本不匹配
- 驱动版本与 CUDA 版本不兼容
- 花费大量时间调试环境问题

### 解决方案

**放弃手动配置，使用 NGC 容器**

```bash
docker run --gpus all -it --rm \
  -v ~/models:/models \
  -v ~/project:/workspace \
  nvcr.io/nvidia/pytorch:latest
```

### 反思

1. **不要重复造轮子**: NVIDIA 官方容器已经解决所有兼容性问题
2. **容器化是最佳实践**: 隔离环境，避免污染宿主系统
3. **时间应该花在模型上**: 而不是折腾环境配置

### 最佳实践

```
✅ 优先使用 NGC PyTorch 容器
✅ 挂载模型和代码目录
✅ 在容器内运行训练和推理
❌ 不要手动安装 CUDA/cuDNN
❌ 不要尝试解决版本冲突
```

---

## 2026-03-04 - CogVideoX-5B 内存不足

### 场景

尝试部署 CogVideoX-5B 视频生成模型，希望利用 GB10 的 128GB 统一内存运行本地视频生成。

### 遇到的问题

**运行时内存需求远超预期**

```
模型大小: 40GB (磁盘空间足够)
运行时内存: 296GB (attention 计算)
GB10 内存: 128GB (统一内存)
```

**测试结果**:
- 49 帧: OOM
- 17 帧: OOM
- 无论帧数多少都失败

### 技术原因

视频生成模型的 attention 计算复杂度:
- 与帧数呈 **平方级** 增长
- 与分辨率呈 **平方级** 增长
- 模型参数大小 ≠ 运行时内存需求

```
Memory ≈ 参数 + (帧数 × 宽 × 高)² × 系数
```

### 解决方案

**选择小模型替代**

| 模型 | VRAM | 分辨率 | 状态 |
|------|------|--------|------|
| Wan-2.1-T2V-1.3B | 8.2GB | 480P/720P | ✅ 可用 |
| CogVideoX-2B | 12-18GB | 720P | ✅ 可用 |
| LTX-Video | 8GB (优化) | 1080P | ✅ 可用 |
| Mochi-1 | 22GB | 480P/720P | ✅ 可用 |
| CogVideoX-5B | 296GB | 720P | ❌ 不可用 |

### 反思

1. **先看运行时内存，再看模型大小**: 很多模型的 attention 计算需要大量内存
2. **视频生成是内存大户**: 帧数和分辨率影响巨大
3. **128GB 不是万能的**: 有硬件天花板，选择合适规模的模型
4. **双机方案**: 两台 Spark 可组成 256GB 内存池，能跑更大的模型

### 后续

- [x] 改用 Wan-2.1-T2V-1.3B (8.2GB VRAM)
- [ ] 测试完整视频生成流程
- [ ] 评估双机 256GB 方案可行性

---

## 2026-09-05 - DSpark Vision 容器 cudaErrorNotPermitted

### 场景

gb10 + gb10-2 双机 TP=2（RoCE 直连）运行 MiaAI-Lab DSpark recipe
（`ghcr.io/anemll/dspark-vllm-gx10:0.1.1`，`deepseek-ai/DeepSeek-V4-Flash-Vision-Exp`，
服务名 `deepseek-v4-flash-0731`）。容器健康运行约 45 小时后，一条多模态请求把
rank 0 的 `Worker_TP0` 打死，两个 rank 随后都在 NCCL 10 分钟超时内退出，
`unless-stopped` 自动拉起，端到端中断约 26 分钟。上游同型报告：
[MiaAI-Lab/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark#216](https://github.com/MiaAI-Lab/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark/issues/216)
（对方 46 小时后同样崩溃，维护者 fresh boot 复现 5/5 通过）。

### 遇到的问题

```
File "/opt/dspark-patches/vision_exp/vision.py", line 135, in forward
    x = F.unfold(x.unsqueeze(0), r, stride=r).squeeze(0).transpose(0, 1)
torch.AcceleratorError: CUDA error: operation not permitted   (cudaErrorNotPermitted)
```

- 崩溃点在 Aligner 的 `F.unfold`，整个 ViT 主干（几十个 kernel，均有 launch check）
  和前一行 `F.pad` 都已成功——这段代码里唯一的 CUDA runtime 调用是 **unfold 输出
  的显存分配**。上游报告的崩溃点（`clone()` / `.to()` / index_put）同样是分配点。
- 崩溃时刻 `dmesg` / `journalctl -k` 一片空白：拒绝发生在驱动之上（VFS/cgroup 层）。
- EngineCore 的 `dump_input` 保留了请求元数据：prompt 98,886 token（98,304 命中前缀
  缓存），图片 63×45 patch（约 1008×720 px，357 个视觉 token），位于提示词末尾。
  encoder 激活只有几 MB，不是容量 OOM。

### 技术原因

这是 NVIDIA Container Toolkit 文档记载的已知问题（[Troubleshooting →
"Containers losing access to GPUs with error: Failed to initialize NVML: Unknown Error"](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/troubleshooting.html)）：

1. 两台主机 Docker 都用 **systemd cgroup driver（cgroup v2）**；compose 用 `gpus: all`
   请求 GPU，由 legacy `nvidia-container-runtime-hook` 直接注入 `/dev/nvidia0`、
   `/dev/nvidiactl`、`/dev/nvidia-uvm`、`/dev/nvidia-uvm-tools` 及其 cgroup 规则，
   **systemd 并不知情**。
2. `systemctl show docker-<id>.scope -p DeviceAllow` 显示白名单里只有 InfiniBand
   （`231:*`，因为 `/dev/infiniband` 是通过 `devices:` 显式传入的）和 tty/null 等，
   **没有 nvidia 设备（195:*、499:*）**。
3. 主机上任何 `systemctl daemon-reload` 都会让 systemd 用这份白名单重写 BPF 设备规则
   → 容器内 `open("/dev/nvidia*")` 返回 EPERM → CUDA 报 `cudaErrorNotPermitted`。
4. 已打开的 fd 继续可用，纯文本流量复用 caching allocator 缓存块可以跑几十小时；
   直到某个请求迫使 allocator 向驱动申请**新内存段**（libcuda 每个新映射要重新
   open 设备节点）才爆——第一张需要新激活内存的大图。
5. gb10 容器启动后 snapd 自动刷新（升级 snapd、chromium）触发了 **7 次
   daemon-reload**；gb10-2 一次都没有——正好对应"rank 0 报 CUDA 错、rank 1 只是
   被 NCCL 超时拖死"。fresh boot 复现不出来，因为还没经历过 reload；"~45 小时"
   只是"长到足够碰上一次主机侧 reload"。

### 解决方案

NVIDIA 文档给出三种修法：改 cgroupfs 驱动（需重启 dockerd，`live-restore=false`
时所有容器都会弹）、**显式 `--device` 传入设备节点**、CDI。采用第二种，改动最小、
与文件里 `/dev/infiniband` 的处理方式一致：

```yaml
    devices:
      - /dev/infiniband:/dev/infiniband
      - /dev/nvidia0
      - /dev/nvidiactl
      - /dev/nvidia-uvm
      - /dev/nvidia-uvm-tools
```

完整 diff 与验证脚本见 [`operations/dspark-vision/`](../dspark-vision/)。
2026-09-05 14:05–14:13 UTC 用 recipe 自带的 stop/start 脚本重建两个 rank（中断约 8 分钟），
两台主机新容器的 `DeviceAllow` 均已包含 `195:0 / 195:255 / 499:0 / 499:1`；
文本冒烟与 1024×768、1600×1200 两张图的多模态冒烟均 HTTP 200。

前置条件：主机上要有 `/dev/char/<major>:<minor>` 符号链接（`71-nvidia.rules` 提供），
否则 runc + systemd 驱动下显式 `--device` 也会失效（见 NVIDIA 文档中的 runc 警告）。

### 反思

1. **"长时间运行后才出现的 CUDA 权限错误"先查容器运行时，再查模型代码**：上游三方
   都在 vision 补丁里找 bug，真正的原因在 cgroup 层。
2. **崩溃点是分配点 + 内核无日志** 是这类问题的指纹；`dump_input` 里有请求元数据，
   别急着说"拿不到"。
3. `gpus: all` 在 systemd 驱动的 Docker 上是**定时炸弹**，任何 GPU compose 都应显式
   列出设备节点（或迁移到 CDI）。
4. 两个 rank 同时挂掉反而让 `unless-stopped` 完成了"整体重启"，无 split-brain。

### 后续

- [ ] 生产上做一次受控 `systemctl daemon-reload` + 新图请求的实弹验证（尚未做，
      当前只有 cgroup 白名单层面的证据）
- [ ] 观察一个包含 snap 自动刷新的长时间运行窗口（≥ 48 h）
- [ ] 其他 `gpus: all` / `runtime: nvidia` 容器（如 `lexdata-ai`，目前已停）重启前
      加显式 `devices:`；评估全机迁移 CDI
- [x] 向上游 #216 提交根因与方案（注明尚未完全确认）

---

## 2026-09-05 - DSpark Vision 多轮对话累计图片超限 400

### 场景

同一套 DSpark Vision 部署（`deepseek-v4-flash-0731`，`:8890`）。当天下午网关（LiteLLM）
侧的客户端连续报错，15:08–15:28 UTC 共 5 次，服务本身健康。

### 遇到的问题

```
litellm.BadRequestError: OpenAIException - At most 8 image(s) may be provided in one prompt.
Set --limit-mm-per-prompt to increase this limit. (parameter=image)
```

不是崩溃：vLLM 在 API 层就拒绝了请求，没进调度器，对其他流量无影响。

### 技术原因

1. recipe 的 compose 默认 `LIMIT_MM_PER_PROMPT=image=8`（`.env.dspark` 里只有注释示例，
   未覆盖），启动参数 `limit_mm_per_prompt={'image': 8}`。
2. vLLM `vllm/multimodal/processing/context.py: validate_num_items` 统计的是**整个
   `messages` 数组里的图片总数**，不是最后一条消息。多轮 agent 会话每轮重发全部历史，
   截图累计到第 9 张之后每一轮都 400——日志里同一来源间隔 2–7 分钟连续失败，正是这个模式。
3. 报错末尾带 "Set `--limit-mm-per-prompt` to increase this limit" 说明图片数 ≤ 模型侧支持
   上限；模型侧上限来自 recipe 的 `patches/vision_exp/processor.py`
   `get_supported_mm_limits() → {"image": 16}`，vLLM 取两者的 `min`。所以不改 patch 最多提到 16。

**提到 16 的显存代价为零（核对过 profiling 逻辑）**：每张图最多 384 token
（`vision_max_n_token`），encoder 预算 = `max_num_batched_tokens` 8192，profiling 每批最多
`8192 // 384 = 21` 张；decoder 侧预算 `6 seqs × 每 prompt 上限`，8 时 48、16 时 96，取 min
都是 21。实际两次启动 KV 预算 12.81 → 12.56 GiB（-2%），但同一次启动两个 rank 之间本来就差
0.3 GiB，且两 rank 的变化量不同（-0.43 / -0.25），是统一内存空闲量抖动而非 profile 变化。

### 解决方案

`.env.dspark`（head；start 脚本会原子推送到 worker）第 401 行：

```diff
-# LIMIT_MM_PER_PROMPT={"image":8}
+LIMIT_MM_PER_PROMPT=image=16
```

**踩坑**：先按 README 的说法写成 JSON `LIMIT_MM_PER_PROMPT={"image":16}`，结果 head 容器
`Restarting (2)`：compose 的 env 文件解析把双引号剥掉，vLLM 收到 `{image:16}` →
`vllm serve: error: argument --limit-mm-per-prompt: Value {image:16} cannot be converted`。
在 `.env.dspark` 里**只能用 `image=N` 形式**（compose 命令自己会转成 JSON）；README/ENVS.md
说"JSON 可用"对 env 文件路径不成立。

15:42–15:53 UTC 用 recipe 的 stop/start 脚本成对重建（含一次因上述踩坑的二次重建，
总中断约 11 分钟）。验证：

- 启动参数 `limit_mm_per_prompt={'image': 16}`；两 rank healthy；`DeviceAllow` 仍含
  `195:*/499:*`（上一条修复未回退）；47/47 warmup ok；`/health` 200；文本冒烟 `ok`。
- `operations/dspark-vision/mm_smoke_multi.py`（多轮 agent 形态，每轮一张图）：
  10 张 → HTTP 200，模型答 "10"（改前必 400）；`16 --single-turn` → 200，答 "16"；
  17 张 → 400 `At most 16 image(s) may be provided in one prompt.`（patch 硬上限，预期）。

### 反思

1. 这类 400 的"病灶"在客户端历史管理，服务端提上限只是把墙往后挪：16 是硬顶，且每张图
   固定占 384 prompt token、历史图片重发会持续冲掉前缀缓存。根治要在网关裁剪旧图为文字
   占位符——已开 shiliai/LLM-Portal#98。
2. 改 recipe 配置前先在 `.env` 里用脚本明确支持的形式，README 的示例不一定经过这条路径。
3. 顺带一个 recipe 已知限制：图片只能在 `user` 消息里，`tool` 消息里的图会被静默丢弃
   （上游 #178），`system`/`assistant` 带图直接 400。

### 后续

- [ ] LLM-Portal 网关侧累计图片裁剪（shiliai/LLM-Portal#98）；建议配置改为
      `max_images: 32, keep_last: 16`（服务端已是 32，见下）
- [x] ~~若确有 >16 张的需求，再评估改 `processor.py` 支持上限~~ → 上游 PR #231 已去掉硬编码
      16，`--limit-mm-per-prompt` 成为唯一上限；随 09-06 同步上游一起生效
- [x] ~~给上游 README/ENVS.md 提 `.env` 中 JSON 形式不可用的勘误~~ → 同一 PR #231 已把
      `.env.dspark.example` 改回 `image=N` 并加 CI gate（他们确认是一次 merge 带回的回归）

### 2026-09-06 跟进：同步上游 main 并把上限提到 32

上游 main（`957890a`，比我们的 pin `d828ddd` 多 77 个提交）合入了 PR #231（去掉 vision patch
硬编码的 16 张上限）和 #204 系列（Vision-Exp MoE 路由类型每次 forward 只分类一次，去掉 43 次
host sync；附带"不允许静默降级"加固）；其余 12 个新 hotfix 全部是默认关闭的 opt-in 开关。
镜像 tag 不变（`dspark-vllm-gx10:0.1.1`）。唯一的默认值变化 `DSPARK_MAX_INFLIGHT_PREFILLS`
2 → 1 对我们无影响（`.env.dspark` 显式为 2）。

**上限选 32 的理由**：预分配批次 `min(8192 // 384 = 21, 6 × N)` 在 8/16/32 下都是 21，对显存零
成本；上游在同样的 2×GB10 TP=2 环境实测 32 → 200、33 → 400；最坏 32 × 384 = 12,288 token 约占
1M 上下文 1.2%。不再往上：任何上限最终都靠网关裁剪兜底，更大只是线性增加请求体积和首 token
延迟，且无人验证过。

**预检（零影响）**：在临时 worktree 里合并后确认 `devices:` 块保留、compose 渲染通过、上游
`scripts/ci-validate.sh` 三次通过（第一次有一个约 3.5 s 的套件偶发失败，不在启动路径上）。
两侧 checkout 都要 merge——start 脚本只向 worker 推送 compose / env / `patches/vision_exp/` 和
vision hotfix，**不推送其他新增的 hotfix 文件**，而新 compose 对它们有 bind mount。

**执行**（11:22–11:28 UTC，中断约 6 分钟）：确认 0 在途请求 → stop → head `git merge origin/main`
（`71ee6bf` = `a0f724b` + `957890a`）、worker 同样（`a96f980` = `fb1d1dc` + `957890a`）→
`.env.dspark` 改 `LIMIT_MM_PER_PROMPT=image=32`（旧文件备份在 `artifacts/`）→ start。
验证：启动参数 `limit_mm_per_prompt={'image': 32}`、`async_scheduling=True`；两 rank healthy，
`DeviceAllow` 仍含 `195:*/499:*`；47/47 warmup ok；`/health` 200；文本冒烟 `ok`；
`mm_smoke_multi.py 32 --single-turn` → 200（4,609 image token，答 "32"）；33 张 → 400
`At most 32 image(s)`；20 张多轮 → 200；1600×1200 单图 → 200。日志无新增告警。

**观察项**：KV 预算三次启动依次 13.1 → 12.67 → 12.15 GiB（1,902,976 → 1,865,527 → 1,804,783
token），权重 80.04 GiB、CUDA graph ~0.7 GiB 均不变，host 上也没有新的大内存进程；GB10 统一
内存下 profile 时刻的空闲量受 page cache 等影响，暂记为观察项，若继续下降再查
（1M 上下文并发仍有 1.72×）。

---

## 经验总结

### 硬件认知

| 项目 | GB10 规格 | 影响 |
|------|----------|------|
| GPU 架构 | Blackwell (sm_121) | 需要新版 PyTorch/CUDA |
| 统一内存 | 128GB | 适合 70B-120B 模型 |
| 内存带宽 | 273GB/s | 容量型，非吞吐量型 |

### 部署原则

1. **容器优先**: NGC PyTorch > 手动配置
2. **内存评估**: 运行时内存 > 模型参数大小
3. **架构兼容**: Blackwell 需要最新软件支持
4. **合理预期**: 128GB 有上限，选择合适模型

### 适用场景

| ✅ 适合 | ❌ 不适合 |
|--------|----------|
| LLM 70B-120B 推理 | 追求极致 token/s |
| 本地隐私计算 | 开箱即用体验 |
| 多 Agent 并发 | 纯性价比优先 |
| 图像生成 | 超大视频模型 |
| 小规模视频生成 | CogVideoX-5B 级别 |

---

## 更新日志

- **2025-07-22**: SenseVoice GPU 兼容性问题
- **2026-02-08**: CUDA 环境配置教训
- **2026-03-04**: CogVideoX-5B 内存问题
- **2026-03-06**: 整理汇总到本文档
- **2026-09-05**: DSpark Vision 容器 cudaErrorNotPermitted（systemd daemon-reload 撤销 GPU 设备访问）
- **2026-09-05**: DSpark Vision 多轮对话累计图片超限 400，`LIMIT_MM_PER_PROMPT` 8 → 16
- **2026-09-06**: DSpark Vision 同步上游 main `957890a`（含 #231 去掉 16 张硬上限、#204 路由分类优化），`LIMIT_MM_PER_PROMPT` 16 → 32

---

*持续更新中...*
