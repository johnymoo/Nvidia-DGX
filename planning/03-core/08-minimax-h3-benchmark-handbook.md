# MiniMax H3 Benchmark Handbook

Status: accepted on `gb10-2` on 2026-08-13.

## Access

- Visual report: `http://192.168.88.198:8890/`
- Technical evidence: `http://192.168.88.198:8890/evidence.html`
- Normalized JSON: `http://192.168.88.198:8890/benchmark.json`
- ComfyUI remains independently available at `http://192.168.88.198:8188/`.

The report binds `0.0.0.0:8890` for trusted-LAN access. It does not add TLS,
authentication, firewall rules, routes, or a boot-time service.

## Accepted Run

Run `20260812T233711Z` supersedes the initial short-video run. It used the
frozen `trained-max-15s` profile: 512x320, 362 model frames, six sampling
steps, and 24 fps video output. The deployed node identifies approximately
124-362 frames as its trained range; 3600 is only the input validation maximum
and was not represented as a supported duration. All nine formal cases
succeeded: four visual-range cases, two same-prompt/same-seed reproducibility
cases, and three serial stability cases. All outputs are H.264 MP4 plus PNG
frames saved natively by ComfyUI from the same decoded H3 image tensor.

Every MP4 decodes to approximately 15.08 seconds. Each formal case performed
a complete cold execution after `/free {"free_memory": true}` and verified
that no critical generation node was served from the ComfyUI execution cache.
ComfyUI execution time ranged from 128.845 to 130.222 seconds; bounded API
acceptance-to-observation time ranged from 130.210 to 132.268 seconds.

One-second polling produced 135-137 samples per case, including ten seconds of
post-completion recovery. Across the formal suite, observed maxima were 96%
GPU utilization, 86 C, approximately 90.61 W, and approximately 45.04 GiB
ComfyUI RSS. The lowest sampled host available memory was approximately 29.94
GiB. These are polling extrema, not exact continuous peaks.

The repeat pair produced different MP4 file hashes because container metadata
contains prompt/run identity, but the normalized decoded RGB frame-sequence
hashes were equal. This is decoded-frame reproducibility, not bitstream
identity. The bounded ComfyUI and kernel fatal scans found no traceback, CUDA,
OOM, Xid, or worker-loss match.

Canonical evidence:

- `/home/admin/minimax-h3-benchmark/artifacts/runs/20260812T233711Z/benchmark.json`
- `/home/admin/minimax-h3-benchmark/artifacts/latest.json`
- `/home/admin/minimax-h3-benchmark/site/`
- `/home/admin/minimax-h3-benchmark/run/report-process.json`

The initial accepted short-video run `20260812T230850Z` remains immutable but
is superseded for publication by the 15-second run. An earlier run,
`20260812T230652Z`, retained successful media for all three
canary profiles but failed normalization because the first runner expected an
`ffprobe` binary alongside bundled FFmpeg. It is preserved as failure evidence
and is not the published report subject. The accepted runner uses the bundled
FFmpeg's diagnostics and full decode checks.

## Generate And Publish

The benchmark requires an idle ComfyUI queue and preserves the exact ComfyUI
PID, start ticks, boot ID, argv, listener, and protected container identity.
It uses only benchmark-prefixed client IDs and output paths and never clears or
cancels queue/history entries.

```bash
ssh gb10-2 \
  '/home/admin/minimax-h3-benchmark/execution/minimax-h3-benchmark/run-benchmark.sh'
```

Every invocation creates a new immutable run directory and republishes
`site/` only after normalization completes. A partial or failed run remains in
`artifacts/runs/` and must not be presented as passed.

## Report Lifecycle

Start or idempotently validate the report:

```bash
ssh gb10-2 \
  '/home/admin/minimax-h3-benchmark/execution/minimax-h3-benchmark/start-report.sh'
```

Read status:

```bash
ssh gb10-2 \
  '/home/admin/minimax-h3-benchmark/execution/minimax-h3-benchmark/status-report.sh'
```

Restart only the exact receipt-bound report PID:

```bash
ssh gb10-2 \
  '/home/admin/minimax-h3-benchmark/execution/minimax-h3-benchmark/restart-report.sh'
```

Stop only the exact receipt-bound report PID:

```bash
ssh gb10-2 \
  '/home/admin/minimax-h3-benchmark/execution/minimax-h3-benchmark/stop-report.sh'
```

The controls bind process identity to PID, `/proc` start ticks, boot ID, exact
argv, fixed `site/` document root, exclusive listener ownership, and HTTP 200.
Stop refuses any mismatch and never uses a broad process-name kill.

## Recovery

If the website fails, run status first. When identity matches, use restart. If
identity does not match, preserve the receipt and logs and investigate the
reported PID/listener; do not kill it through a broad name match. A stale
receipt with no running process may be removed by the idempotent stop command,
then start can recreate it.

Do not stop ComfyUI, modify `lexdata-ai`, or change Compose, firewall, routes,
RoCE, swap, credentials, or unrelated services to recover this static report.
The report can always be removed from service by the exact stop command while
retaining all generated media and evidence.

## Browser Acceptance

The 15-second published pages were verified at 1440x900 and 390x844. Ten video
elements loaded with ready state, native dimensions 512x320, and browser media
durations of approximately 15.083 seconds; the evidence page showed
nine matrix rows and nine case details. Both pages had zero body overflow,
text clipping, or console errors. The mobile screenshot was nonblank with RGB
channel ranges 0–255 and channel standard deviations 73–76.
