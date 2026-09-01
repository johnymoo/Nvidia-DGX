# Benchmark Report

## Identity

- Recipe: `qwen3.8.rtx-a6000-48gb.llamacpp-27b-ud-q4-k-xl-mtp2-192k`
- Hardware: one NVIDIA RTX A6000, 49,140 MiB VRAM
- Runtime: llama.cpp image pinned by digest
- Profile: 196,608 context, parallel 1, F16 KV, full GPU offload, Flash Attention, MTP2
- API used for collection: loopback port 8006

## Performance

The `performance-v1@1.0.0` streaming workload ran one warmup and three measured
samples. All three completed successfully. Mean TTFT was 0.267788 s, mean
response time was 21.5902 s, and mean decode throughput was 62.429818 tok/s.
Each sample reported 79 prompt tokens, 1,332 completion tokens, and 75 cached
prompt tokens. Percentiles use linear interpolation over the three measured
samples; the small sample count is a limitation of this Reference result.

One sample after restarting the model container recorded 0.384035 s TTFT,
21.230369 s response time, and 63.849111 decode tok/s with zero cached prompt
tokens. The host page cache was not cleared, so this is a post-restart sample,
not a claim of fully cold model loading.

## Context And Telemetry

A 180,028-token prompt placed deterministic codes near its beginning and end;
both were returned exactly in 292.733602 s. During the long-context run, observed
GPU peaks were approximately 299 W and 87 C. The loaded service used about
31,958 MiB VRAM and left about 976 MiB free in the observed configuration.

## Limitations

The harness did not separately report reasoning-token counts or time to the
first final-answer token. RAM and disk telemetry were not collected. No quality
floor, concurrency sweep, extended reliability run, or safety suite was run.
These omissions are represented as unavailable values rather than zeros and
keep this bundle at Reference maturity.
