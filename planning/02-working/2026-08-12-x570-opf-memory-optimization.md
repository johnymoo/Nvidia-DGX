# X570 OPF Memory Optimization

Date: 2026-08-12 (Asia/Shanghai)
Status: production probe passed; DeepSeek multimodal compatibility work not started

## Scope

Optimize RTX 3090 memory on `x570` while preserving the production
privacy-filter API on `:8765`. The user authorized stopping VoxCPM2 on `:8808`.
No GB10, `:8004`, DeepSeek, Ollama, or compatibility-gateway service was
changed.

## Initial State

- VoxCPM2 process group `2578027` used 7,806 MiB and listened on `:8808`.
- Privacy Filter commit `741cdc27c056f4618d88600386b3e75058f99859`
  used 12,180 MiB after 47 days of uptime and listened on `:8765`.
- GPU free memory was 4,059 MiB.

Stopping the captured VoxCPM2 process group closed `:8808`, left `:8765`
healthy, and increased free GPU memory to 11,868 MiB.

## Experiments

All probes used synthetic data only. They covered the eight OPF labels,
Chinese text, a boundary case, a negative control, 40 typical requests, 20
requests at concurrency four, a 198,000-character input, and a 100-request
soak.

| Candidate | 198k latency | Post-probe process VRAM | Result |
| --- | ---: | ---: | --- |
| `e4c7d8c` JIT, default allocator | 4,834 ms | 7,886 MiB | Failed 6 GiB memory threshold |
| `e4c7d8c` JIT, allocator tuning | 4,709 ms | 11,460 MiB | Rejected; memory regression |
| `e4c7d8c` JIT, large-request cache release | 4,671 ms | 3,490 MiB | Passed, but slower than upstream |
| upstream decode, large-request cache release | 2,753 ms | 3,490 MiB | Selected |

The selected candidate preserved exact structured output against the old
production service for all synthetic cases and the 198,000-character input.
The JIT upgrade was not adopted because upstream decode was materially faster
on this X570 while providing the same memory result after explicit release of
unused CUDA cache.

## Production Result

The existing service repository was updated from `741cdc2` to
`99106fe6b087e80b92c2366adb8261ecc7dd01d5`. The patch calls
`torch.cuda.empty_cache()` after a CUDA redaction of at least 65,536
characters. It does not change the model, checkpoint, decoding algorithm,
labels, API schema, port, or systemd unit.

Production acceptance after restart:

- full service test suite: 72 passed;
- changed-file lint and Git diff check: passed;
- `:8765/health`: ready on CUDA;
- expected labels: all detected;
- negative control: zero spans;
- typical p95: 18.6 ms;
- four-concurrent p95: 92.6 ms;
- 198,000-character latency: 2,684 ms per measured production pass;
- 100-request soak p95: 17.5 ms;
- post-probe OPF VRAM: 3,490 MiB;
- post-probe free GPU memory: 20,558 MiB.

Receipt:
`execution/artifacts/opf-x570-memory/20260812T070847Z-production/receipt.json`,
SHA-256 `8caea6910813cad7c9cce8d43abcc468a7c643bc8d6c4e989d7b32a869dda3e1`.

## Remaining Limits

- The samples establish parity with the prior service for the synthetic
  corpus, not absolute OPF model accuracy on every real PII form.
- `empty_cache()` reduces retained allocator memory after large requests; it
  does not reduce temporary peak memory while such a request is running.
- A private vision service must still pass simultaneous OPF plus vision-model
  peak, concurrency, and soak tests before production admission.
