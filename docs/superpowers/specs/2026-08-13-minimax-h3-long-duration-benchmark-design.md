# MiniMax H3 Long-Duration Benchmark Amendment

Date: 2026-08-13

Status: proposed for final approval

Parent design: `docs/superpowers/specs/2026-08-13-minimax-h3-benchmark-handbook-design.md`

## Intent And Baseline

The user requested that the published short videos be regenerated at the
supported upper duration and that resource use and generation time be recorded.
This amendment preserves baseline `minimax-h3-benchmark-r1` and refines:

- `US-H3-B01`: published representative videos must use the supported duration
  ceiling rather than the prior 33-frame showcase profile.
- `US-H3-B02`: each case must expose generation timing and resource samples.
- `US-H3-B03`: ComfyUI, the report service, and `lexdata-ai` isolation remain
  unchanged.

Given the deployed node metadata, `length` accepts up to 3600 frames but states
that the trained range ends at approximately 362 frames and longer generation
is untested. This design defines "supported upper duration" as 362 model frames,
approximately 15.1 seconds at 24 fps. It does not represent the 3600-frame API
validation ceiling as a supported model capability.

## Selected Change

Regenerate the same nine formal cases serially at one frozen profile:

- 512x320;
- 362 model frames;
- six sampling steps;
- 24 fps;
- unchanged prompts and seeds.

The old run remains immutable failure/comparison evidence. The new run is
published only if all nine cases produce a decodable MP4 and native PNG frame,
the queue remains owned and isolated, fatal scans pass, and the exact pre-run
ComfyUI/protected-service identities remain equal afterward.

Two alternatives are rejected. Using 3600 frames would test an explicitly
untrained range and materially increase OOM and runtime risk. Regenerating only
the four visual cases would make the site's success, reproducibility, and
stability summary refer to mixed duration profiles.

## Timing And Resources

Capture wall-clock and monotonic timestamps at submission, API acceptance,
ComfyUI execution start/success events, and terminal history observation.
Publish API acceptance delay, model execution time when both ComfyUI event
timestamps exist, and bounded end-to-end time. Missing event timestamps remain
unknown rather than inferred.

Poll once per second from before submission through ten seconds after terminal
history:

- host available memory;
- ComfyUI RSS;
- GPU utilization and temperature;
- GPU power draw when the driver exposes it.

For each case publish sample count, minimum available memory, maximum ComfyUI
RSS, maximum sampled GPU utilization/temperature/power, and the raw time series.
These are polling extrema, not exact continuous peaks. The homepage shows the
run duration profile and generation-time range; detailed values remain on the
evidence page and in `benchmark.json`.

## Verification

All prior media, hash, queue, fatal-scan, process-identity, report lifecycle,
desktop, and mobile checks remain required. Additional acceptance requires all
nine published videos to report approximately 15 seconds duration, 362 frozen
model frames in every receipt, nonempty resource series, and visible per-case
timing/resource summaries.

Design playback: `US-H3-B01`, `US-H3-B02`, and `US-H3-B03` Covered; drift score
`0`; gate `DESIGN_ALIGNED`.

