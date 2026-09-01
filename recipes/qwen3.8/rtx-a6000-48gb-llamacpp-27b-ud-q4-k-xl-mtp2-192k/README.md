# Qwen3.8-27B UD-Q4_K_XL on RTX A6000 48 GB

This Reference recipe runs Qwen3.8-27B with llama.cpp on one NVIDIA RTX A6000.
It fixes a 196,608-token context, one parallel slot, F16 KV cache, full GPU
offload, Flash Attention, and the GGUF MTP head. The OpenAI-compatible API uses
port 8006 and binds to loopback by default.

```bash
cd recipes/qwen3.8/rtx-a6000-48gb-llamacpp-27b-ud-q4-k-xl-mtp2-192k
cp config/qwen38.env.example config/qwen38.env
./scripts/download.sh
./scripts/start.sh
./scripts/status.sh
./scripts/benchmark.sh
./scripts/stop.sh
```

The measured reference run completed three warm single-stream samples at
62.43 decode tok/s mean and retrieved deterministic codes at both ends of a
180,028-token prompt. A single post-restart sample is also reported separately;
host page cache was not cleared, so it is not a full cold-start measurement.

The measured deployment published the API on all interfaces at port 8006. To
reproduce that listener on a controlled LAN, set both values below before start:

```dotenv
PUBLISH_HOST=0.0.0.0
ALLOW_UNAUTHENTICATED_LAN=true
```

Changing the bind address away from loopback requires
`ALLOW_UNAUTHENTICATED_LAN=true`. An unauthenticated endpoint must remain on a
controlled network or behind an authenticated reverse proxy. The start and stop
scripts refuse to replace unrelated containers or listeners.
