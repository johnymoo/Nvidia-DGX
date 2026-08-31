"""Offline tests for tools.modelctl — no docker, no ssh, no cluster access.

Fixtures encode real shapes from the gb10 fleet (docker compose ls --format
json, docker ps --format '{{json .}}', ss -ltnH) including host-network
containers whose ports are invisible to `docker ps` — the exact case that
motivated issue #26.
"""

from __future__ import annotations

import json
import os
import tempfile
import textwrap
import unittest

from tools.modelctl.schema import RegistryError, load_registry

try:
    import yaml  # noqa: F401
    HAS_YAML = True
except ImportError:  # pragma: no cover
    HAS_YAML = False

VALID_REGISTRY = """
schema_version: 1
hosts:
  head:
    hostname: head-host
    ssh_target: null
    labels: [primary]
  worker:
    hostname: worker-host
    ssh_target: ops@10.0.0.2
models:
  alpha-llm:
    description: script-controlled dual-node llm
    kind: llm
    managed: true
    hosts:
      head:
        role: head
        compose:
          project: alpha
          config_files: [/opt/alpha/compose.yml]
      worker:
        role: worker
        compose:
          project: alpha
          config_files: [/opt/alpha/compose.yml]
    controller:
      type: script
      host: head
      start: [/opt/alpha/ctl.sh, --start]
      stop: [/opt/alpha/ctl.sh, --stop, --restore]
      status: [/opt/alpha/ctl.sh, --status]
    start_order: [worker, head]
    ports:
      - {host: head, port: 9000, purpose: api}
    health: {host: head, url: "http://127.0.0.1:9000/health", wait_timeout_s: 60}
    expected_containers: {head: 1, worker: 1}
    conflict_groups: [gpu-head, gpu-worker]
    conflicts_with: [beta-llm]
  beta-llm:
    description: compose-controlled dual-node llm
    kind: llm
    managed: true
    hosts:
      head:
        role: head
        compose:
          project: beta
          config_files: [/opt/beta/head.yml]
          env_files: [/opt/beta/.env]
      worker:
        role: worker
        compose:
          project: beta
          config_files: [/opt/beta/worker.yml]
    controller: {type: compose}
    start_order: [worker, head]
    ports:
      - {host: head, port: 9001, purpose: api}
    expected_containers: {head: 1, worker: 1}
    conflict_groups: [gpu-head, gpu-worker]
  guard-proxy:
    description: protected proxy
    kind: proxy
    managed: false
    protected: true
    hosts:
      head:
        role: standalone
        compose:
          project: guard
          config_files: [/opt/guard/compose.yml]
    ports:
      - {host: head, port: 9002, purpose: proxy}
  rollback:
    description: clashes with guard-proxy on 9002
    kind: llm
    managed: true
    hosts:
      head:
        role: standalone
        compose:
          project: rollback
          config_files: [/opt/rollback/compose.yml]
    controller: {type: compose}
    ports:
      - {host: head, port: 9002, purpose: api}
    conflict_groups: [gpu-head]
    conflicts_with: [guard-proxy]
"""


def write_registry(tmpdir: str, content: str = VALID_REGISTRY) -> str:
    path = os.path.join(tmpdir, "models.yaml")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(textwrap.dedent(content))
    return path


class SchemaTest(unittest.TestCase):
    def setUp(self):
        if not HAS_YAML:
            self.skipTest("PyYAML not installed")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def load(self, content: str = VALID_REGISTRY):
        return load_registry(write_registry(self.tmp.name, content))

    def test_valid_registry_loads(self):
        registry = self.load()
        self.assertEqual(set(registry.models), {"alpha-llm", "beta-llm", "guard-proxy", "rollback"})
        self.assertEqual(set(registry.hosts), {"head", "worker"})
        alpha = registry.models["alpha-llm"]
        self.assertEqual(alpha.start_order, ("worker", "head"))
        self.assertEqual(alpha.stop_order, ("head", "worker"))
        self.assertEqual(alpha.controller.type, "script")

    def test_default_stop_order_is_reversed(self):
        registry = self.load()
        beta = registry.models["beta-llm"]
        self.assertEqual(beta.stop_order, ("head", "worker"))

    def test_worker_must_start_before_head(self):
        content = VALID_REGISTRY.replace(
            "    start_order: [worker, head]\n    ports:\n      - {host: head, port: 9001",
            "    start_order: [head, worker]\n    ports:\n      - {host: head, port: 9001")
        with self.assertRaises(RegistryError) as ctx:
            self.load(content)
        self.assertTrue(any("worker must start before head" in e for e in ctx.exception.details))

    def test_head_must_stop_before_worker(self):
        content = VALID_REGISTRY.replace(
            "    start_order: [worker, head]\n    ports:\n      - {host: head, port: 9000",
            "    start_order: [worker, head]\n    stop_order: [worker, head]\n"
            "    ports:\n      - {host: head, port: 9000")
        with self.assertRaises(RegistryError) as ctx:
            self.load(content)
        self.assertTrue(any("head must stop before worker" in e for e in ctx.exception.details))

    def test_secret_like_keys_rejected(self):
        content = VALID_REGISTRY + """
  sneaky:
    description: tries to smuggle a credential
    kind: llm
    managed: true
    hosts:
      head:
        role: standalone
        compose: {project: sneaky, config_files: [/x.yml]}
    controller: {type: compose}
    api_token: supersecret
"""
        with self.assertRaises(RegistryError) as ctx:
            self.load(content)
        self.assertIn("secret-like", str(ctx.exception.details))

    def test_unmanaged_must_not_declare_controller(self):
        content = VALID_REGISTRY.replace(
            "  guard-proxy:\n    description: protected proxy\n    kind: proxy\n    managed: false\n    protected: true\n",
            "  guard-proxy:\n    description: protected proxy\n    kind: proxy\n    managed: false\n    protected: true\n    controller: {type: compose}\n")
        with self.assertRaises(RegistryError) as ctx:
            self.load(content)
        self.assertTrue(any("must not declare a controller" in e for e in ctx.exception.details))

    def test_managed_requires_controller(self):
        content = VALID_REGISTRY.replace(
            "    controller: {type: compose}\n    ports:\n      - {host: head, port: 9002",
            "    ports:\n      - {host: head, port: 9002")
        with self.assertRaises(RegistryError) as ctx:
            self.load(content)
        self.assertTrue(any("need a controller" in e for e in ctx.exception.details))

    def test_unknown_host_rejected(self):
        content = VALID_REGISTRY.replace(
            "      - {host: head, port: 9001, purpose: api}",
            "      - {host: mars, port: 9001, purpose: api}")
        with self.assertRaises(RegistryError):
            self.load(content)

    def test_unknown_conflicts_with_rejected(self):
        content = VALID_REGISTRY.replace(
            "    conflicts_with: [beta-llm]", "    conflicts_with: [ghost]")
        with self.assertRaises(RegistryError):
            self.load(content)

    def test_bad_ssh_target_rejected(self):
        content = VALID_REGISTRY.replace(
            "    ssh_target: ops@10.0.0.2", "    ssh_target: just-a-hostname")
        with self.assertRaises(RegistryError):
            self.load(content)

    def test_missing_file_raises_registry_error(self):
        with self.assertRaises(RegistryError):
            load_registry(os.path.join(self.tmp.name, "nope.yaml"))


if __name__ == "__main__":
    unittest.main()
