"""Conflict-detection tests: wildcard bindings, live listeners, groups, protected."""

from __future__ import annotations

import tempfile
import unittest

from tests.test_modelctl_schema import HAS_YAML, VALID_REGISTRY, write_registry
from tools.modelctl import conflicts as conflicts_mod
from tools.modelctl import discovery
from tools.modelctl.runner import FakeRunner, RunResult
from tools.modelctl.schema import load_registry
from tools.modelctl.state import FleetSnapshot, HostFacts, model_status, build_snapshot


def make_snapshot(registry, listeners_by_host=None, containers_by_host=None):
    listeners_by_host = listeners_by_host or {}
    containers_by_host = containers_by_host or {}
    runner = FakeRunner(responses={})
    snapshot = FleetSnapshot(registry=registry)
    for host in registry.hosts.values():
        snapshot.facts[host.name] = HostFacts(
            host=host.name, reachable=True,
            listeners=listeners_by_host.get(host.name, []),
            containers=containers_by_host.get(host.name, []),
            projects=[],
        )
    for model in registry.models.values():
        snapshot.statuses[model.name] = model_status(
            model, snapshot.facts, check_health=False, runner=None)
    return snapshot, runner


class ConflictsTest(unittest.TestCase):
    def setUp(self):
        if not HAS_YAML:
            self.skipTest("PyYAML not installed")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.registry = load_registry(write_registry(self.tmp.name))

    def test_bind_collision_semantics(self):
        f = conflicts_mod.binds_conflict
        self.assertTrue(f("0.0.0.0", "127.0.0.1"))   # wildcard hits loopback
        self.assertTrue(f("127.0.0.1", "0.0.0.0"))
        self.assertTrue(f("10.0.0.1", "0.0.0.0"))
        self.assertTrue(f("127.0.0.1", "127.0.0.1"))
        self.assertFalse(f("127.0.0.1", "10.0.0.1"))  # distinct specific binds

    def test_free_start_has_no_conflicts(self):
        snapshot, _ = make_snapshot(self.registry)
        beta = self.registry.models["beta-llm"]
        self.assertEqual(conflicts_mod.check_start(self.registry, snapshot, beta), [])

    def test_live_listener_port_conflict(self):
        # head:9000 is alpha's declared API; a live wildcard listener must block beta? no —
        # beta declares 9001; give a phantom listener on 9001 from an unregistered process
        snapshot, _ = make_snapshot(
            self.registry,
            listeners_by_host={"head": [discovery.Listener("0.0.0.0", 9001)]})
        beta = self.registry.models["beta-llm"]
        found = conflicts_mod.check_start(self.registry, snapshot, beta)
        self.assertTrue(any(c.kind == "port" and "unregistered" in c.message for c in found))

    def test_own_listener_does_not_conflict(self):
        # beta already up (its own listener) -> starting beta again is a no-op, no conflict
        snapshot, _ = make_snapshot(
            self.registry,
            listeners_by_host={"head": [discovery.Listener("0.0.0.0", 9001)]},
            containers_by_host={"head": [_container("beta-head-1", "beta", running=True)],
                                "worker": [_container("beta-worker-1", "beta", running=True)]})
        beta = self.registry.models["beta-llm"]
        self.assertEqual(conflicts_mod.check_start(self.registry, snapshot, beta), [])

    def test_group_conflict_between_llms(self):
        # alpha running on both hosts; beta shares gpu groups
        snapshot, _ = make_snapshot(
            self.registry,
            containers_by_host={"head": [_container("alpha-head-1", "alpha", running=True)],
                                "worker": [_container("alpha-worker-1", "alpha", running=True)]})
        beta = self.registry.models["beta-llm"]
        found = conflicts_mod.check_start(self.registry, snapshot, beta)
        self.assertTrue(any(c.kind == "group" and c.other_model == "alpha-llm" for c in found))

    def test_stopping_models_are_exempt(self):
        snapshot, _ = make_snapshot(
            self.registry,
            containers_by_host={"head": [_container("alpha-head-1", "alpha", running=True)],
                                "worker": [_container("alpha-worker-1", "alpha", running=True)]})
        beta = self.registry.models["beta-llm"]
        found = conflicts_mod.check_start(self.registry, snapshot, beta,
                                          stopping={"alpha-llm"})
        self.assertEqual([c for c in found if c.kind == "group"], [])

    def test_explicit_edge_and_protected_gate(self):
        # guard-proxy running on 9002; rollback declares 9002 + explicit edge
        snapshot, _ = make_snapshot(
            self.registry,
            listeners_by_host={"head": [discovery.Listener("0.0.0.0", 9002)]},
            containers_by_host={"head": [_container("guard-1", "guard", running=True)]})
        rollback = self.registry.models["rollback"]
        found = conflicts_mod.check_start(self.registry, snapshot, rollback)
        kinds = {c.kind for c in found}
        self.assertIn("port", kinds)
        self.assertIn("explicit", kinds)
        self.assertIn("protected", kinds)  # gate present without allow_protected

        without_gate = conflicts_mod.check_start(
            self.registry, snapshot, rollback, allow_protected=True)
        self.assertNotIn("protected", {c.kind for c in without_gate})

    def test_partial_running_model_blocks_by_group(self):
        # only alpha's head container runs (partial); beta must still see the group clash
        snapshot, _ = make_snapshot(
            self.registry,
            containers_by_host={"head": [_container("alpha-head-1", "alpha", running=True)],
                                "worker": []})
        self.assertEqual(snapshot.statuses["alpha-llm"].state, "partial")
        beta = self.registry.models["beta-llm"]
        found = conflicts_mod.check_start(self.registry, snapshot, beta)
        self.assertTrue(any(c.kind == "group" for c in found))

    def test_loopback_registration_not_satisfied_by_remote_bind_listener(self):
        # a listener bound only to 10.0.0.1 does NOT cover a loopback registration,
        # and starting the owner of 127.0.0.1:50053 while 10.0.0.1:50053 is taken
        # is still a conflict (binds_conflict is false here -> no port conflict),
        # this test pins that specific-bind-vs-specific-bind is NOT a clash.
        l = discovery.Listener("10.0.0.1", 50053)
        self.assertFalse(l.covers("127.0.0.1"))
        self.assertFalse(conflicts_mod.binds_conflict("10.0.0.1", "127.0.0.1"))


def _container(name, project, running=True):
    return discovery.Container(
        id="abc123", names=name, image="img:latest",
        state="running" if running else "exited",
        status="Up" if running else "Exited",
        project=project, service=name.rsplit("-", 1)[0],
    )


if __name__ == "__main__":
    unittest.main()
