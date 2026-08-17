# MiniMax H3 Single-DGX-Spark Benchmark

## Verified subject

Published machine-readable evidence is generated from retained raw run
`20260812T233711Z` (`2026-08-12T23:37:11.895Z` to
`2026-08-13T00:01:16.676Z`). The uncommitted raw receipt SHA-256 is
`8974fa3d6f8c2b024c1e2721c61d66b2add498db8b07d66ce056f86fe83a85da`;
per-case artifact hashes are in `benchmark-results.json`.

- Hardware: one NVIDIA DGX Spark / GB10 with 128 GB unified memory
- Recipe revision: `9f9eca9589d4b4c0a01a8081c8c4add279e18868`
- ComfyUI revision: `0764232429b8cfb10b79b6f186c8cb23e0b22897`
- PyTorch: `2.11.0+cu130`
- CUDA runtime: 13.0
- Weight set: 11 files, 176,195,310,067 bytes; every SHA-256 verified
- Formal profile: 512x320, 362 model frames, 6 sampling steps, 24 fps

The H3 node accepts up to 3600 frames but identifies approximately 124-362 as
its trained range. This benchmark uses 362 frames as the supported upper bound,
not the untested 3600-frame validation ceiling.

## Results

All nine formal cases succeeded and decoded to approximately 15.08 seconds.
Each case ran after a ComfyUI execution-cache reset; critical generation nodes
were verified as uncached.

| Case | ComfyUI execution | Bounded wall | Samples | Min available memory | Max ComfyUI RSS | Max GPU | Max temp | Max power |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Object motion | 129.903 s | 130.261 s | 135 | 30.15 GiB | 45.01 GiB | 96% | 84 C | 90.61 W |
| Human motion | 129.798 s | 130.243 s | 136 | 30.04 GiB | 45.02 GiB | 96% | 84 C | 90.30 W |
| Environment motion | 130.222 s | 132.268 s | 137 | 30.11 GiB | 45.03 GiB | 96% | 85 C | 90.31 W |
| Stylized motion | 129.458 s | 130.237 s | 135 | 30.62 GiB | 45.02 GiB | 96% | 85 C | 89.19 W |
| Reproducibility A | 129.155 s | 130.210 s | 135 | 29.98 GiB | 45.03 GiB | 96% | 85 C | 89.38 W |
| Reproducibility B | 129.552 s | 130.272 s | 135 | 29.94 GiB | 45.04 GiB | 96% | 85 C | 90.04 W |
| Sequential 1 | 130.054 s | 130.611 s | 136 | 30.08 GiB | 45.04 GiB | 96% | 86 C | 90.28 W |
| Sequential 2 | 128.845 s | 130.231 s | 135 | 30.07 GiB | 45.02 GiB | 96% | 85 C | 90.15 W |
| Sequential 3 | 129.513 s | 130.236 s | 135 | 29.95 GiB | 45.03 GiB | 96% | 85 C | 89.30 W |

Resource values are one-second polling extrema, not exact continuous peaks.
Sampling spans submission through ten seconds after terminal history.

The same-prompt/same-seed pair had different MP4 byte hashes because the
container includes run metadata, while the normalized decoded RGB frame
sequence hashes were identical. Three serial stability cases succeeded. Bounded
ComfyUI and kernel scans found no traceback, CUDA, OOM, Xid, or worker-loss
match.

## Limits

- This is a capability report for one pinned configuration, not a model ranking.
- Visual quality is not reduced to an invented scalar score.
- Timing includes a consistent cold execution after model/cache release.
- Generated media, raw logs, host paths, process identities, and machine-local
  receipts are intentionally not committed.
