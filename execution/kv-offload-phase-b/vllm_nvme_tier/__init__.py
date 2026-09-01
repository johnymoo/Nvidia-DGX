# SPDX-License-Identifier: Apache-2.0
"""Out-of-tree per-rank NVMe KV-offload tier for the dspark fork.

Phase B design: planning/02-working/2026-08-31-kv-offload-phase-b-nvme-design.md
(Rev 1 + Rev 2 staging-ring amendment). Mounted through the fork's
OffloadingSpecFactory `spec_module_path` seam — no connector identity
change, no core edits. PYTHONHASHSEED=0 is a REQUIRED companion env
(D0-lite 2026-09-02: without it the offload keys are unstable across
processes and no lookup can ever hit).
"""
