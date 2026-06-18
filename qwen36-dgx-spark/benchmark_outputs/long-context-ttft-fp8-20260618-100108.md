# fp8 长上下文 TTFT/TPS

- time: 2026-06-18T10:04:53
- container: `vllm-qwen36-fp8-optimized`
- model: `qwen3.6-35b-fp8`
- endpoint: `http://localhost:8004/v1/chat/completions`

| Context | Prompt tokens | Client TTFT | Server TTFT | Client decode TPS | Server decode TPS | E2E | Finish | Correct |
|---|---:|---:|---:|---:|---:|---:|---|---|
| 64K | 65,510 | 16.56s | 16.52s | 46.7 | 45.3 | 18.55s | stop | ✅ |
| 128K | 131,067 | 45.37s | 45.30s | 41.0 | 39.3 | 47.56s | stop | ✅ |
| 256K | 255,982 | 141.33s | 141.21s | 34.3 | 32.5 | 144.19s | stop | ✅ |