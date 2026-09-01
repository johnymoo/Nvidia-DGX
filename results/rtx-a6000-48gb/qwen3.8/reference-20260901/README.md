# RTX A6000 Qwen3.8-27B 192K Reference Result

This sanitized bundle records Qwen3.8-27B UD-Q4_K_XL on one NVIDIA RTX A6000
48 GB with llama.cpp, a 196,608-token allocation, and one parallel slot.

The canonical warm workload used one warmup followed by three streaming samples.
It achieved 62.43 decode tok/s mean, 0.268 s mean TTFT, and 21.59 s mean response
time. A separate post-restart sample is included for context but is not described
as a fully cold host run because the OS page cache was not cleared.

The context check retrieved deterministic codes from both ends of a
180,028-token prompt. This result remains `Reference`: no quality floor,
concurrency sweep, soak, first-final-token timing, reasoning-token split, or
safety qualification was completed.
