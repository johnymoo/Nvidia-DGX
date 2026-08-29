# operations/modelctl — GB10 车队模型注册表

- `models.example.yaml`:占位符模板,提交进仓库。真实注册表 `models.yaml`
  含主机名/内网地址/家目录路径,按本仓库隐私契约**不入库**,只部署在
  **gb10:~/modelctl/models.yaml**(gb10 为管理主控机,gb10-2 经 BatchMode
  SSH 互信访问,与 DeepSeek controller 共用同一密钥)。

## 快速上手(gb10 上)

```bash
cd ~/modelctl
python3 -m tools.modelctl.cli --config models.yaml list
python3 -m tools.modelctl.cli --config models.yaml --json ports
alias modelctl='python3 -m tools.modelctl.cli --config ~/modelctl/models.yaml'
modelctl check glm53-exl3
modelctl switch glm53-exl3        # DeepSeek → GLM-5.3(双机切换)
modelctl switch deepseek-v4-flash # GLM-5.3 → DeepSeek(controller 接管)
```

## 当前注册(2026-08)

| 模型 | 类型 | 端口 | 互斥 | 状态语义 |
|---|---|---|---|---|
| `deepseek-v4-flash` | 双机 vLLM(script controller) | gb10 :8890 | glm53-exl3、unsloth-ab | controller 维护 active.json |
| `glm53-exl3` | 双机 vLLM(compose,worker→head) | gb10 :8895 | deepseek-v4-flash、unsloth-ab | 首启预热 30–60 min |
| `qwen36-rollback` | 本机 vLLM(compose) | gb10 :8004 | qwen36-proxy(受保护) | 默认停用 |
| `qwen36-proxy` | 反向代理(受保护,不纳管) | gb10 :8004 | qwen36-rollback | 常驻 |
| `unsloth-ab` | llama-server + RPC(不纳管) | :8891 / :50052 / :50053 | 两个 LLM | 常态停用 |
| `comfyui-minimax` | ComfyUI(不纳管) | gb10 :8188 | gpu-gb10 | 按需 |
| `trading-agents` / `pdf2md` / `lexdata-ai` / `podcast-asr` | 受保护/可见性 | :8032 / — / gb10-2 / :8889 | — | 永不被切换停止 |

设计文档:[docs/modelctl.md](../../docs/modelctl.md)
