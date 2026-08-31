"""Action tests with a FakeRunner: choreography, delegation, receipts, gates."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from tests.test_modelctl_schema import HAS_YAML, VALID_REGISTRY, write_registry
from tools.modelctl import actions as actions_mod
from tools.modelctl import discovery
from tools.modelctl.runner import FakeRunner, RunResult
from tools.modelctl.schema import load_registry
from tools.modelctl.state import FleetSnapshot, HostFacts, model_status


def make_registry():
    tmp = tempfile.TemporaryDirectory()
    registry = load_registry(write_registry(tmp.name))
    return tmp, registry


def make_actor(registry, responses=None, running=None):
    """Actor whose snapshot is pre-baked; runner records controller invocations."""
    runner = FakeRunner(responses=responses or {})
    snapshot = FleetSnapshot(registry=registry)
    running = running or set()
    containers_by_host = {
        "head": ([_c("alpha-engine-1", "alpha")] if "alpha-llm" in running else [])
                + ([_c("beta-head-1", "beta")] if "beta-llm" in running else [])
                + ([_c("guard-1", "guard")] if "guard-proxy" in running else []),
        "worker": ([_c("alpha-engine-1", "alpha")] if "alpha-llm" in running else [])
                  + ([_c("beta-worker-1", "beta")] if "beta-llm" in running else []),
    }
    for host in registry.hosts.values():
        snapshot.facts[host.name] = HostFacts(
            host=host.name, reachable=True,
            containers=containers_by_host.get(host.name, []),
            listeners=[], projects=[])
    for model in registry.models.values():
        snapshot.statuses[model.name] = model_status(model, snapshot.facts,
                                                     check_health=False, runner=None)
    state_dir = tempfile.mkdtemp()
    return actions_mod.Actor(runner, registry, state_dir, snapshot=snapshot), runner, state_dir


def _compose_config_files(argv):
    """Values of every -f flag in a compose argv."""
    eff = _effective(argv)
    return [eff[i + 1] for i, v in enumerate(eff) if v == "-f"]


class ActionsTest(unittest.TestCase):
    def setUp(self):
        if not HAS_YAML:
            self.skipTest("PyYAML not installed")
        self.addCleanup(lambda: None)

    def test_compose_model_starts_worker_first(self):
        tmp, registry = make_registry()
        self.addCleanup(tmp.cleanup)
        actor, runner, _ = make_actor(registry)
        result = actor.start("beta-llm", wait=False, lock=False)
        ups = [_compose_config_files(argv) for _, argv in runner.calls
               if "up" in _effective(argv)]
        self.assertIn("/opt/beta/worker.yml", ups[0])
        self.assertIn("/opt/beta/head.yml", ups[1])
        self.assertEqual(result["receipt"]["exit_code"], 0)
        self.assertEqual([s["host"] for s in result["receipt"]["steps"]], ["worker", "head"])

    def test_compose_model_stops_head_first(self):
        tmp, registry = make_registry()
        self.addCleanup(tmp.cleanup)
        actor, runner, _ = make_actor(registry, running={"beta-llm"})
        result = actor.stop("beta-llm", lock=False)
        downs = [_compose_config_files(argv) for _, argv in runner.calls
                 if "down" in _effective(argv)]
        self.assertIn("/opt/beta/head.yml", downs[0])
        self.assertIn("/opt/beta/worker.yml", downs[1])

    def test_script_controller_delegation(self):
        tmp, registry = make_registry()
        self.addCleanup(tmp.cleanup)
        actor, runner, _ = make_actor(registry)
        result = actor.start("alpha-llm", wait=False, lock=False)
        effective = [_effective(argv) for _, argv in runner.calls]
        ctl = [argv for argv in effective if argv[:1] == ["/opt/alpha/ctl.sh"]]
        self.assertEqual(len(ctl), 1)
        self.assertEqual(ctl[0][:2], ["/opt/alpha/ctl.sh", "--start"])
        self.assertFalse([argv for argv in effective if "compose" in argv])

    def test_start_refuses_on_conflict_without_flag(self):
        tmp, registry = make_registry()
        self.addCleanup(tmp.cleanup)
        actor, runner, _ = make_actor(registry, running={"alpha-llm"})
        with self.assertRaises(actions_mod.ActionError) as ctx:
            actor.start("beta-llm", wait=False, lock=False)
        self.assertEqual(ctx.exception.code, "CONFLICT")
        kinds = {c["kind"] for c in ctx.exception.details}
        self.assertIn("group", kinds)
        self.assertEqual(runner.calls, [])  # nothing was executed

    def test_switch_stops_conflict_then_starts(self):
        tmp, registry = make_registry()
        self.addCleanup(tmp.cleanup)
        actor, runner, _ = make_actor(registry, running={"alpha-llm"})
        result = actor.switch("beta-llm", wait=False, lock=False)
        self.assertEqual(result["receipt"]["stopping"], ["alpha-llm"])
        effective = [_effective(argv) for _, argv in runner.calls]
        # alpha is script-driven: its controller stop must be invoked
        self.assertTrue(any("--stop" in argv and "ctl.sh" in " ".join(argv) for argv in effective))
        # then beta comes up worker-first
        ups = [argv for argv in effective if "up" in argv]
        self.assertEqual(len(ups), 2)

    def test_switch_to_protected_conflict_requires_confirmation(self):
        tmp, registry = make_registry()
        self.addCleanup(tmp.cleanup)
        actor, runner, _ = make_actor(registry, running={"guard-proxy"})
        with self.assertRaises(actions_mod.ActionError) as ctx:
            actor.switch("rollback", wait=False, lock=False)
        self.assertEqual(ctx.exception.code, "CONFIRMATION_REQUIRED")
        self.assertEqual(runner.calls, [])

    def test_stop_protected_requires_confirmation(self):
        tmp, registry = make_registry()
        self.addCleanup(tmp.cleanup)
        actor, runner, _ = make_actor(registry, running={"guard-proxy"})
        # guard-proxy is unmanaged AND protected: refusal reason is unmanaged,
        # and no flag combination ever lets modelctl stop it
        for kwargs in ({}, {"allow_protected": True}):
            with self.assertRaises(actions_mod.ActionError) as ctx:
                actor.stop("guard-proxy", lock=False, **kwargs)
            self.assertEqual(ctx.exception.code, "UNMANAGED")
        self.assertEqual(runner.calls, [])

    def test_unmanaged_model_cannot_be_started(self):
        tmp, registry = make_registry()
        self.addCleanup(tmp.cleanup)
        actor, runner, _ = make_actor(registry)
        with self.assertRaises(actions_mod.ActionError) as ctx:
            actor.start("guard-proxy", lock=False)
        self.assertEqual(ctx.exception.code, "UNMANAGED")

    def test_receipt_written(self):
        tmp, registry = make_registry()
        self.addCleanup(tmp.cleanup)
        actor, runner, state_dir = make_actor(registry)
        result = actor.start("beta-llm", wait=False, lock=False)
        receipts = os.listdir(os.path.join(state_dir, "receipts"))
        self.assertEqual(len(receipts), 1)
        with open(os.path.join(state_dir, "receipts", receipts[0])) as handle:
            data = json.load(handle)
        self.assertEqual(data["action"], "start")
        self.assertEqual(data["model"], "beta-llm")
        self.assertEqual(len(data["steps"]), 2)

    def test_controller_failure_aborts_start(self):
        tmp, registry = make_registry()
        self.addCleanup(tmp.cleanup)
        actor, runner, _ = make_actor(registry, responses={
            (None, ("/opt/alpha/ctl.sh",)): RunResult(
                host=None, argv=(), exit_code=1, stderr="boom"),
        })
        with self.assertRaises(actions_mod.ActionError) as ctx:
            actor.start("alpha-llm", wait=False, lock=False)
        self.assertEqual(ctx.exception.code, "CONTROLLER_FAILED")


def _effective(argv):
    """Strip the ssh preamble from a FakeRunner-recorded argv."""
    argv = list(argv)
    if argv and argv[0] == "ssh":
        return argv[argv.index("--") + 1:]
    return argv


def _c(name, project):
    return discovery.Container(id="id-" + name, names=name, image="img", state="running",
                               status="Up", project=project, service="svc")


if __name__ == "__main__":
    unittest.main()
