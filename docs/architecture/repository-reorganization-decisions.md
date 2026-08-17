# Repository Reorganization Implementation Decisions

Status: implementation clarification for approved baseline `repo-reorg-r2`

These decisions resolve ambiguities found during the independent design review.
They do not expand the approved scope or authorize host access.

## Best Verified Eligibility

The repository stores eligibility policy in `catalog/benchmark-policy.json`.
Selection is deterministic and fail-closed:

- candidates must already be classified `Verified` by an existing subject-bound
  receipt; static migration cannot make a candidate eligible;
- the suite ID and major version, workload ID, concurrency, context floor,
  quality floor, reliability status, and safety status must be explicit;
- missing required values make a candidate ineligible; N/A is valid only when
  the policy marks the field inapplicable;
- candidates are grouped by `hardware_id + model_family`; quantization and
  runtime remain visible and may compete only within that group;
- ties use aggregate TPS, decode TPS, TTFT, then stable result ID ordering;
- when no candidate is eligible, the generated homepage states that no
  eligible Verified result is available. Reference results may appear in a
  separate non-ranked table.

No existing result is inferred into an active suite. Legacy results retain
their recorded workload, concurrency, and metric definitions.

## Recipe Cardinality

One canonical recipe represents one exact model checkpoint family, hardware
class, runtime, and deployment profile. A historical project containing
multiple profiles is split into multiple recipe entries even when its source
files remain together during the first migration.

Each entry has its own maturity, operations, receipts, benchmark references,
limitations, and default flag. A source mapping records which legacy files are
shared. No multi-profile project receives one combined maturity claim.

## Modality And Suite Applicability

Every recipe declares a modality:

- `text-generation`
- `multimodal-generation`
- `media-generation`
- `embedding`
- `application`

`performance-v1` token metrics are mandatory for text and multimodal text
generation. TTFT, first-final-token, token counts, cache data, and token TPS are
N/A for media generation unless the runtime exposes a meaningful token stream.
Media recipes use `media-performance-v1`, which records time to first artifact,
end-to-end generation time, artifact count/duration/resolution, errors,
distributions, and available hardware telemetry.

Media and embedding results do not enter the token-TPS Best Verified selector.
The first implementation publishes them as modality-specific Reference or
Verified records without a cross-modality ranking.
