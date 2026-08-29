"""modelctl — unified, non-invasive model Compose management for the GB10 fleet.

Implements Nvidia-DGX issue #26: a single models.yaml registry, a read-only +
controlled-action CLI, and a thin Web UI over a whitelist of modelctl commands.

Design invariants (from the issue):
- never modify existing Compose files; additive overrides only
- models with an external controller (e.g. the DeepSeek service controller)
  delegate start/stop to it, preserving its own state semantics
- read-only commands never alter containers, ports, services, or remote files
- unregistered services are reported, never taken over
- secrets never appear in models.yaml; the loader rejects secret-shaped keys
"""

__version__ = "1.0.0"

SCHEMA_VERSION = 1
JSON_ENVELOPE_VERSION = 1
