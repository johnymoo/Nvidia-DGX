# DeepSeek V4 Flash on 2x GB10

This workspace records the deployment and verification of
`DeepSeek-V4-Flash-0731` across two DGX Spark / GB10 systems.

## Current State

The initial live inventory was captured on 2026-08-10. The head candidate has
the 0731 model and an upstream two-node vLLM recipe. The worker is reachable but
still needs Docker access for its SSH user, and the ConnectX-7 ports on both
systems currently report no physical carrier.

Two routes are prepared. The initial baseline is the official mixed FP8/FP4
checkpoint with patched vLLM/DSpark TP=2 and NVFP4 MLA KV. The experimental A/B
route is Unsloth `UD-Q4_K_XL` plus its Q8 DSpark sidecar, served through two
llama.cpp CUDA RPC devices over RoCE. The long-term primary will be selected by
live A/B evidence after the fabric is connected.

Start with:

- `planning/02-working/2026-08-10-live-inventory.md`
- `planning/02-working/2026-08-10-unsloth-gguf-research.md`
- `planning/03-core/README.md`

Raw upstream repositories and research live under `planning/01-raw` and are not
tracked by Git.
