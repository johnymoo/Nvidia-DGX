# vLLM and Unsloth A/B Results

All values are verified artifacts, not portability claims.

| Profile | Decode / aggregate c1/2/4/6 | Prefill 24.9k / 77.8k | Stability |
| --- | --- | --- | --- |
| Official vLLM DSpark | five-category mean about 68.8 tok/s; peak 85.06; 70.55/107.67/161.51/229.34 | 1753/2575 tok/s | 40m: 621 req, 223268 tokens, 0 errors |
| Unsloth target | 15.42-15.53 tok/s; 15.32/15.44/15.45/15.48 | 447.86/479.23 | 10m: 25 req, 9265 tokens, 0 errors |
| Unsloth DSpark | 16.03-30.35 tok/s; 27.03/27.35/27.29/27.28 | 343.40/359.96 | 10m: 39 req, 13462 tokens, 0 errors |

Unsloth used UD-Q4_K_XL, 256k context, llama.cpp CUDA RPC and the Q8 draft
sidecar. Both profiles passed deterministic, math, JSON, code, Chinese,
cold/warm, tool calls, c2/4/6, agent sanity, five decode categories and
prefill. Its common 128-token exact-response harness adjustment is recorded
in the artifact because 80 tokens truncated a high-entropy UUID on this GGUF.

Selection: official vLLM is the accepted production route. Unsloth DSpark is
an evaluated, lower-throughput alternative with faster decode than Unsloth
target; target has higher measured long-prefill throughput than its DSpark
profile. Artifacts: official acceptance path in 02; Unsloth at
`/home/chriswang/gb10-ds4/artifacts/unsloth-ab/20260811T012256Z` and its worker
peer.
