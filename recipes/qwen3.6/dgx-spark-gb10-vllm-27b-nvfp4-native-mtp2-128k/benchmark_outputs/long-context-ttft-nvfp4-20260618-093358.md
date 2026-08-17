# Qwen3.6 NVFP4 长上下文 TTFT/TPS

- time: 2026-06-18T09:37:46
- model: `qwen3.6-35b-fp8`
- endpoint: `http://localhost:8004/v1/chat/completions`
- method: streaming 客户端时间戳 + vLLM Prometheus metrics delta 交叉验证

| Context | Prompt tokens | Client TTFT | Server TTFT | Client decode TPS | Server decode TPS | E2E | Finish | Correct |
|---|---:|---:|---:|---:|---:|---:|---|---|
| 64K | 65,507 | 16.25s | 16.21s | 104.2 | 100.7 | 17.16s | stop | ✅ |
| 128K | 131,064 | 47.58s | 47.51s | 89.7 | 84.8 | 48.62s | stop | ✅ |
| 256K | 255,979 | 150.34s | 150.20s | 70.4 | 63.3 | 151.51s | stop | ✅ |