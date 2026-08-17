# Qwen3.8-27B UD-Q4_K_XL on RTX 4090 48 GiB

这是 RTX 4090 48 GiB 的默认 Qwen3.8 推理部署。2026-08-17 的同机测试中，
Unsloth Dynamic `UD-Q4_K_XL` 与 `UD-Q6_K_XL` 都在 18 项湖仓 thinking-low
基准中通过 17 项、在 6 项视觉基准中全部通过。Q4 基线达到 46.57 tok/s；启用
GGUF 内置 MTP head 后达到 94.33 tok/s，质量仍为 17/18、视觉仍为 6/6。因此默认
选择 Q4 + MTP2，而不是在未观察到质量收益时承担 Q6 的额外显存与延迟。

固定配置：单张 48 GiB RTX 4090、262,144 context、单并发 slot、F16 KV、全 GPU
offload、Flash Attention、MTP speculative decoding（n-max 2，p-min 0）和
OpenAI-compatible API。权重和 `mmproj` 从 ModelScope 下载，
以字节数与 SHA-256 固定；运行时使用固定 OCI digest。

```bash
cd qwen38-rtx4090-llamacpp
cp config/qwen38.env.example config/qwen38.env
chmod +x scripts/*.sh
./scripts/download.sh
./scripts/start.sh
./scripts/status.sh
```

默认监听 `127.0.0.1:8005`，模型 ID 为 `qwen3.8-27b`，另保留精确变体 ID
`qwen3.8-27b-ud-q4-k-xl`。无认证 LAN 暴露必须同时修改 `PUBLISH_HOST` 并显式设置
`ALLOW_UNAUTHENTICATED_LAN=true`；公网访问必须经过认证反向代理。

```bash
curl -fsS http://127.0.0.1:8005/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.8-27b","messages":[{"role":"user","content":"Reply exactly READY"}],"max_tokens":32}' | jq
./scripts/benchmark.sh
./scripts/stop.sh
```

`--n-gpu-layers 999` 明确要求全 GPU 放置；48 GiB 主机内存 cgroup 上限用于限制异常
资源增长。脚本不会停止其他容器，端口或容器名冲突时会拒绝启动。完整对比报告见
[`../../../benchmarks/legacy/qwen-deepseek-cross-model/report/qwen38-quantization.html`](../../../benchmarks/legacy/qwen-deepseek-cross-model/report/qwen38-quantization.html)。

MTP 主要优化单流 decode。当前 recipe 在本机 128-token 与约 1,100-token 输出中均有
收益；245,034-token 实际提示也完成首尾双校验码精确召回。256K 档位空载占用
36,645 MiB 显存，保留 11,855 MiB；如需为其他 GPU 服务保留更多余量，可将
`CTX_SIZE` 调回 `131072`，该档位空载占用 27,685 MiB。并发 2/4 与 48 小时压力测试
仍待完成；增加并发、变更上下文、KV 类型或
llama.cpp 镜像后必须重新评测。参数来源与社区数据见
[`sudoingX/qwen38-mtp`](https://github.com/sudoingX/qwen38-mtp)。
