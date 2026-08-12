# MiniMax H3 GB10 Benchmark Handbook Design

Date: 2026-08-13

Status: proposed for final approval

## Approval And Baseline

Baseline revision: `minimax-h3-benchmark-r1`.

Authoritative sources:

- User request in the current task: run several tests, generate images and
  videos, publish a benchmark-report-style handbook on `0.0.0.0`, and target
  `gb10-2`.
- User choice `3`: serve both external demonstration and technical
  evaluation/operations audiences.
- Baseline approval: the user explicitly replied `批准` on 2026-08-13.
- Existing deployment contract and evidence:
  `planning/03-core/07-gitee-minimax-h3-preparation.md`.

### Approved Stories

- `US-H3-B01`: As a visitor, I can use the landing page to quickly inspect
  representative images, videos, and key measured conclusions generated on
  `gb10-2`, so that I can see MiniMax H3's real output.
- `US-H3-B02`: As a technical evaluator or operator, I can open a detail page
  containing each test's prompt, parameters, elapsed time, resource evidence,
  output hash, runtime evidence, limitations, and reproduction steps.
- `US-H3-B03`: As an operator, I can access, inspect, restart, and stop the
  report through an independent `0.0.0.0` service without affecting ComfyUI
  on port 8188 or `lexdata-ai`.

| Story | Given | When | Then |
| --- | --- | --- | --- |
| `US-H3-B01` | Completed, verified H3 benchmark artifacts | A visitor opens the landing page | Real representative frames and playable videos appear with measured headline results |
| `US-H3-B02` | The same immutable benchmark artifacts and receipts | An evaluator opens the evidence page | Every published claim links to prompts, parameters, timing, hashes, runtime facts, limits, and reproduction commands |
| `US-H3-B03` | ComfyUI remains on `:8188` and the protected container remains healthy | The report service is started, checked, restarted, or stopped | Only the report-owned PID and unused report port change; protected identities remain equal |

Constraints: use one `gb10-2`; publish only real generated media; adapt to
desktop and mobile; preserve ComfyUI and `lexdata-ai`; do not alter firewall,
routes, RoCE, swap, Compose, credentials, or unrelated workloads.

Non-goals: cross-model comparison, claims of industry leadership or
statistical superiority, model-quality judging by an external model, modifying
the H3 deployment, authentication/TLS, internet exposure, or a boot-time
system service.

## Considered Approaches

### A. Generated Static Two-Page Handbook (selected)

One benchmark runner produces immutable media, per-case receipts, and a
normalized `benchmark.json`. A deterministic renderer creates `index.html`
for visual scanning and `evidence.html` for technical audit. A task-owned
Python static server binds an unused `0.0.0.0` port.

This keeps the serving process small, makes all claims traceable to one data
file, avoids a frontend build toolchain on the GB10, and permits complete
offline review. It is the best fit for both approved audiences.

### B. One Long Static Page

This has the smallest implementation, but media and full receipts compete for
attention, mobile navigation becomes cumbersome, and external viewers must
download and scan technical evidence they do not need.

### C. Dynamic Dashboard With An API

This could add filtering and live telemetry, but creates an unnecessary server
application, runtime dependencies, mutable measurements, and a larger
operational surface. The approved stories require an auditable report, not a
monitoring product.

## Benchmark Contract

The benchmark is a bounded single-host capability report, not a comparative
leaderboard. It runs after a fresh status check and records the exact ComfyUI
process identity, deployment subject, Gitee and ComfyUI revisions, host facts,
and protected container identity.

The runner executes these cases serially through the ComfyUI API:

| Case | Purpose | Prompt class | Required artifact |
| --- | --- | --- | --- |
| `object-motion` | Basic composition and motion | Product-like object, static camera | MP4 plus ComfyUI-saved generated PNG frame |
| `human-motion` | Character, clothing, and body motion | Full-body subject with bounded camera direction | MP4 plus ComfyUI-saved generated PNG frame |
| `environment-motion` | Scene depth and environmental dynamics | Landscape or architectural scene | MP4 plus ComfyUI-saved generated PNG frame |
| `stylized-motion` | Non-photographic visual range | Graphic or stop-motion-like scene | MP4 plus ComfyUI-saved generated PNG frame |
| `determinism-a/b` | Same-workflow repeatability | Identical prompt, seed, and parameters | Two MP4 files, bitstream hashes, and decoded-frame hashes |
| `sequential-stability-1..3` | Bounded repeat operation | Three serial prompts | Three successful histories and post-run health evidence |

All quality showcase cases use one pinned, resource-bounded workflow selected
from the deployed Gitee recipe. Before submission, the runner requires both
`queue_running` and `queue_pending` from `/queue` to be empty. It captures that
state, uses benchmark-prefixed `client_id`, filename prefix, prompt IDs, and
output directories, never cancels or deletes queue/history entries, and stops
submitting if any foreign work appears. The pre-run ComfyUI PID, start ticks,
boot ID, exact argv, and exclusive listener ownership must equal the post-run
identity.

The runner tests a finite profile ladder during canary only: `showcase`
(512x320, 33 frames, 6 steps), then `bounded` (384x240, 17 frames, 4 steps),
then the accepted deployment `minimum` (320x192, 5 frames, 1 step). It records
every attempted profile and failure. The first successful profile is frozen
for every formal case; if `minimum` fails, the suite stops without publishing
a successful benchmark. Formal cases never silently retry with changed
parameters. Failed cases remain in `benchmark.json` and on the evidence page.

Each formal workflow adds native ComfyUI frame selection and `SaveImage` nodes
after H3 video decoding, saving one PNG from the generated frame tensor in the
same prompt that saves the MP4. These are real generated image artifacts, not
FFmpeg screenshots, but they remain frames from the H3 video generation path;
the site does not claim an independent text-to-image capability. The pinned
FFmpeg independently decodes the MP4 and validates that its corresponding
frame pixel hash equals the ComfyUI-saved PNG pixel hash.

For every attempt, capture wall and monotonic timestamps at local submission,
API acceptance, ComfyUI `execution_start`, and terminal history observation.
Report queue/acceptance delay separately from execution elapsed time; if the
history lacks an authoritative execution event, label execution time unknown
and retain wall time. Also capture prompt/workflow JSON, output bytes and
SHA-256, FFprobe media metadata, selected-frame file SHA-256 and normalized
decoded RGB pixel SHA-256, and status. Sample host memory and GPU utilization
before, during, and after generation when observable; label polling samples
rather than claiming exact peaks.

Before the canary, record the active ComfyUI log byte offset and a kernel
journal cursor/timestamp. After the final terminal history, wait 10 seconds,
then scan only the bounded log suffix and kernel interval for CUDA, OOM, Xid,
traceback, and worker-loss failures. An unreadable or rotated boundary is
reported as `unknown`, never `passed`.

Reported metrics are success count, queue delay, execution or bounded wall
time per case, output duration/resolution/frame rate/size, MP4 bitstream
reproducibility, decoded RGB frame-sequence reproducibility, bounded sequential
success, sampled memory/utilization, and fatal-scan result. MP4 inequality is
not interpreted as generation nondeterminism when decoded frame sequences are
equal. Visual quality is presented as inspectable output, without an invented
scalar score.

## Artifact And Data Flow

Project-owned scripts live under `execution/minimax-h3-benchmark/`. Runtime
artifacts live under `/home/admin/minimax-h3-benchmark/` and do not enter Git.

```text
deployed workflow + frozen case manifest
        -> ComfyUI :8188
        -> prompt/history/media receipts
        -> FFmpeg frame extraction + FFprobe metadata
        -> normalized benchmark.json
        -> deterministic static renderer
        -> site/index.html + site/evidence.html + site/assets/*
        -> task-owned static server on 0.0.0.0:<unused-port>
```

The normalized JSON is the only source for page claims. Media paths are
relative, hashes use SHA-256, timestamps use UTC ISO 8601, and missing metrics
remain `null` with a reason rather than being estimated.

## Website Design

The visual language is quiet and technical: white and near-black surfaces,
neutral gray structure, red as a small MiniMax accent, and green/amber only for
measured state. Letter spacing remains zero. Cards are reserved for repeated
media cases; report sections are unframed full-width bands.

`index.html` opens directly on the benchmark, not a marketing landing page. Its
first viewport shows the literal title `MiniMax H3 on NVIDIA GB10`, immutable
run status with its UTC timestamp, host/model identity, headline metrics, and a large real video
with an extracted frame poster. A compact sticky navigation links to Results,
Gallery, Method, Limits, and Evidence. The next content band remains visible at
the fold. The gallery uses stable 16:9 media dimensions, native video controls,
case status, prompt summary, and measured timing. No autoplay with sound is
used.

`evidence.html` provides a dense test matrix, expandable per-case prompt and
workflow facts, artifact hashes, environment identity, resource samples,
failure scans, known limitations, exact reproduction commands, and report
start/status/stop/restart commands. It links back to the corresponding media
case and landing page.

At widths below 720px, navigation becomes horizontally scrollable, summary
metrics use two columns, galleries use one column, tables move into labeled
row layouts or bounded horizontal scroll, and all code blocks scroll within
their own width. Media remains 16:9 and text cannot overlay controls.

## Operations And Isolation

The report uses a currently unused port chosen at deployment time, with `8890`
preferred if still free. Start writes an identity receipt containing PID,
`/proc` start ticks, boot ID, exact argv, root, port, and start time. Status
validates all fields, listener ownership, HTTP 200, and protected service
identity. Stop signals only that exact matching PID and fails closed on any
identity mismatch. Restart is exact stop followed by start.

The server binds `0.0.0.0` for trusted-LAN access with its document root fixed
to the generated `site/` directory. Packaging rejects symlinks and any resolved
asset path outside that root. Normalization allows only the whitelisted public
benchmark fields and never copies request headers, environment variables,
credentials, tokens, cookies, or proxy values. It does not change firewall or
authentication policy. Recovery preserves benchmark artifacts, stops only the
validated report process, and leaves ComfyUI running. The runbook records all
four lifecycle commands and the LAN URL.

## Error Handling

- A rejected ComfyUI prompt records the API response and fails that case.
- A timeout preserves queue/history/log evidence and does not kill ComfyUI.
- A missing or undecodable output fails the case and prevents a success claim.
- A frame extraction failure leaves the video available but marks the still
  missing; the renderer shows the failure rather than a placeholder.
- Any protected-service mismatch stops further benchmark submissions and
  prevents report acceptance.
- A report PID/listener mismatch is never resolved using broad process-kill
  commands.

## Verification

Focused script tests validate manifest schema, receipt normalization, safe
media paths, deterministic rendering, PID identity matching, and fail-closed
stop behavior. Final acceptance requires:

1. Each successful case has a success history, decodable MP4, ComfyUI-saved
   PNG, matching byte count, file and normalized pixel SHA-256, and FFprobe metadata.
2. Bitstream and decoded-frame reproducibility report exact equality or
   inequality honestly; sequential tests
   all complete or retain their failures.
3. Bounded runtime and kernel fatal scans pass, ComfyUI retains the exact
   pre-run process/listener identity and HTTP 200 on `:8188`, and `lexdata-ai`
   retains its container ID, health, and restart count.
4. `benchmark.json` validates and every visible claim is derivable from it.
5. Both pages return HTTP 200 from the chosen `0.0.0.0` listener; all local
   links and media load with no console errors.
6. Browser checks at 1440x900 and 390x844 show nonblank real media, no body
   overflow, no incoherent overlap, readable navigation, and usable video
   controls. A canvas/pixel check confirms screenshots are not blank.
7. Start, status, stop, restart, recovery, and exact LAN URL are added to
   `planning/03-core`.

## Design Playback

| Story | Design evidence | Status |
| --- | --- | --- |
| `US-H3-B01` | Benchmark contract plus `index.html` first viewport and real-media gallery | Covered |
| `US-H3-B02` | Normalized evidence contract and `evidence.html` audit surface | Covered |
| `US-H3-B03` | Exact-identity report controls, unused port, preservation checks, and recovery path | Covered |

Corrections: none. Drift score: `0`. Gate: `DESIGN_ALIGNED`.
