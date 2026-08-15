#!/usr/bin/env python3

import copy
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1] / "model-platform"
sys.path.insert(0, str(ROOT))
import model_platform as platform  # noqa: E402
import operations  # noqa: E402


class FakeRunner(platform.Runner):
    def __init__(self, responses):
        self.responses = responses
        self.commands = []

    def run(self, host, command, timeout=20):
        self.commands.append((host, command))
        value = self.responses[(host, command)]
        if isinstance(value, list):
            value = value.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def inspect(project, service, state="running", config_files="/srv/compose.yml", name=None):
    return {
        "Id": "id-{}-{}".format(project, service),
        "Name": "/{}".format(name or "{}-{}-1".format(project, service)),
        "Config": {
            "Image": "example:latest",
            "Labels": {
                "com.docker.compose.project": project,
                "com.docker.compose.service": service,
                "com.docker.compose.project.config_files": config_files,
                "com.docker.compose.project.working_dir": "/srv",
            },
        },
        "State": {"Status": state, "Health": {"Status": "healthy"}},
        "NetworkSettings": {"Ports": {}},
    }


def fixture_registry():
    return {
        "version": 1,
        "api_version": platform.API_VERSION,
        "hosts": {
            "gb10": {"management_ip": "192.168.88.181"},
            "gb10-2": {"management_ip": "192.168.88.198"},
        },
        "models": {
            "pair": {
                "display_name": "Pair",
                "deployments": [
                    {"host": "gb10", "project": "pair", "services": ["server"]},
                    {"host": "gb10-2", "project": "pair", "services": ["server"]},
                ],
                "adapter": {"type": "none"},
                "endpoints": [{"host": "gb10", "bind": "0.0.0.0", "port": 8890, "protocol": "tcp"}],
                "resources": {"exclusive_hosts": ["gb10", "gb10-2"], "gpu_hosts": ["gb10", "gb10-2"]},
                "conflicts": ["worker"],
            },
            "worker": {
                "display_name": "Worker",
                "deployments": [{"host": "gb10-2", "project": "worker", "services": ["server"]}],
                "adapter": {"type": "none"},
                "endpoints": [{"host": "gb10-2", "bind": "192.168.88.198", "port": 8188, "protocol": "tcp"}],
                "resources": {"exclusive_hosts": ["gb10-2"], "gpu_hosts": ["gb10-2"]},
                "conflicts": ["pair"],
            },
        },
    }


class RegistryTests(unittest.TestCase):
    def test_repository_registry_validates_without_pyyaml(self):
        registry = platform.load_registry(ROOT / "models.yaml")
        self.assertEqual(registry["version"], 1)
        self.assertIn("deepseek-v4-flash-0731", registry["models"])
        qwen = registry["models"]["qwen38-nvfp4"]
        self.assertEqual(qwen["identity"]["modalities"], ["text", "image", "video"])
        self.assertEqual(qwen["identity"]["revision"], "16b6615af3548b88e2d8e382457bc705b00479cf")
        schema = json.loads((ROOT / "models.schema.json").read_text())
        self.assertEqual(schema["properties"]["version"]["const"], 1)
        self.assertIn("controller", schema["$defs"])

    def test_qwen_compose_contract_is_pinned(self):
        compose = (ROOT / "qwen38/compose.yml").read_text()
        dockerfile = (ROOT / "qwen38/Dockerfile").read_text()
        env = (ROOT / "qwen38/qwen38.env").read_text()
        controller = (ROOT / "qwen38/controller.sh").read_text()
        manifest = (ROOT / "qwen38/model-manifest.sha256").read_bytes()
        self.assertIn('QWEN38_VLLM_IMAGE=gb10-qwen38-vllm:0.25.0', env)
        self.assertIn('QWEN38_CONTEXT_SIZE=262144', env)
        self.assertIn('{"method":"mtp","num_speculative_tokens":2}', compose)
        self.assertIn('16b6615af3548b88e2d8e382457bc705b00479cf', compose)
        self.assertIn('7531d90bcbe0e43e1f7363029c7e145ce90eebeb494a7b4695fdba0329d7c3c3', dockerfile)
        self.assertNotIn('--trust-remote-code', compose)
        self.assertNotIn('ipc: host', compose)
        self.assertIn('read_only: true', compose)
        self.assertIn('trap \'capture_and_stop_failed_start signal-HUP', controller)
        self.assertIn('QWEN38_STATE_ROOT', controller)
        self.assertEqual(hashlib.sha256(manifest).hexdigest(), '6d979221939858d8f98c7e615028e1e468cffb3ff2d501f943646c1e12ef2cdc')
        self.assertIn('c473512c70eace07e2256fe9fd76596ac03e3295bee7d54cfb72676416afcc05', manifest.decode())

    def test_qwen_is_registered_but_mutation_disabled(self):
        registry = platform.load_registry(ROOT / "models.yaml")
        qwen = registry["models"]["qwen38-nvfp4"]
        self.assertFalse(qwen["availability"]["mutable"])
        self.assertEqual(qwen["adapter"]["working_dir"], "/home/admin/gb10-model-platform/qwen38/current")
        with self.assertRaisesRegex(platform.PlatformError, "lifecycle is unavailable"):
            operations.LifecycleManager(registry, FakeRunner({})).plan("qwen38-nvfp4", "start", {"models": {}})

    def test_unknown_conflict_fails(self):
        registry = fixture_registry()
        registry["models"]["pair"]["conflicts"] = ["missing"]
        with self.assertRaisesRegex(platform.PlatformError, "unknown model"):
            platform.validate_registry(registry)

    def test_health_url_must_be_loopback(self):
        registry = fixture_registry()
        registry["models"]["pair"]["endpoints"][0]["health"] = "http://example.com/"
        with self.assertRaisesRegex(platform.PlatformError, "loopback"):
            platform.validate_registry(registry)

    def test_stdlib_and_jsonschema_reject_same_malformed_corpus(self):
        schema = ROOT / "models.schema.json"
        corpus = []
        unknown = fixture_registry()
        unknown["models"]["pair"]["surprise"] = True
        corpus.append(unknown)
        unsafe = fixture_registry()
        unsafe["models"]["pair"]["adapter"] = {
            "type": "controller", "host": "gb10", "working_dir": "/srv",
            "commands": {key: [["/bin/control", key]] for key in ("check", "start", "status", "stop")},
        }
        corpus.append(unsafe)
        extra_host = fixture_registry()
        extra_host["hosts"]["gb10"]["extra"] = "bad"
        corpus.append(extra_host)
        for registry in corpus:
            with self.assertRaises(platform.PlatformError):
                platform.validate_registry(copy.deepcopy(registry), schema_path=schema, use_jsonschema=False)
            with self.assertRaises(platform.PlatformError):
                platform.validate_registry(copy.deepcopy(registry), schema_path=schema, use_jsonschema=True)


class SocketTests(unittest.TestCase):
    def test_parses_ipv4_ipv6_and_process(self):
        output = "\n".join([
            'tcp LISTEN 0 4096 0.0.0.0:8890 0.0.0.0:* users:((\"python\",pid=7,fd=3))',
            'tcp LISTEN 0 4096 [::]:8004 [::]:*',
            'udp UNCONN 0 0 192.168.192.198:50052 0.0.0.0:*',
        ])
        sockets = platform.parse_sockets("gb10", output)
        self.assertEqual([(item.protocol, item.bind, item.port) for item in sockets], [
            ("tcp", "0.0.0.0", 8890), ("tcp", "::", 8004), ("udp", "192.168.192.198", 50052)
        ])

    def test_wildcard_conflicts(self):
        self.assertTrue(platform.addresses_conflict("0.0.0.0", "127.0.0.1"))
        self.assertTrue(platform.addresses_conflict("::", "192.168.88.181"))
        self.assertFalse(platform.addresses_conflict("127.0.0.1", "192.168.88.181"))


class DiscoveryTests(unittest.TestCase):
    def test_partial_pair_and_unmanaged(self):
        registry = fixture_registry()
        platform.validate_registry(registry)
        responses = {}
        for host in registry["hosts"]:
            projects = [{"Name": "pair", "Status": "running(1)", "ConfigFiles": "/srv/pair.yml"}]
            containers = [inspect("pair", "server")]
            if host == "gb10-2":
                containers = []
                projects.append({"Name": "foreign", "Status": "running(1)", "ConfigFiles": "/other/compose.yml"})
            responses[(host, platform.COMPOSE_COMMAND)] = json.dumps(projects)
            responses[(host, platform.INSPECT_COMMAND)] = json.dumps(containers)
            responses[(host, platform.SOCKET_COMMAND)] = ""
        result = platform.discover(registry, FakeRunner(responses))
        self.assertEqual(result["models"]["pair"]["state"], "Partial")
        self.assertEqual(result["unmanaged"][0]["project"], "foreign")
        self.assertEqual(result["unmanaged"][0]["state"], "Unmanaged")

    def test_config_files_come_from_structured_labels(self):
        item = inspect("pair", "server", config_files="/a/base.yml,/a/override.yml")
        record = platform.container_record("gb10", item)
        self.assertEqual(record["compose"]["config_files"], ["/a/base.yml", "/a/override.yml"])

    def test_port_and_resource_conflicts(self):
        registry = fixture_registry()
        platform.validate_registry(registry)
        discovery = {
            "errors": [],
            "hosts": {
                "gb10": {"compose_projects": [], "containers": [], "sockets": [
                    {"host": "gb10", "protocol": "tcp", "bind": "127.0.0.1", "port": 8890, "process": "foreign"}
                ]},
                "gb10-2": {"compose_projects": [{"Name": "worker", "Status": "running(1)", "ConfigFiles": "/w.yml"}], "containers": [platform.container_record("gb10-2", inspect("worker", "server"))], "sockets": []},
            },
        }
        discovery["models"] = platform.model_statuses(registry, discovery, runner=None)
        result = platform.check_model(registry, discovery, "pair")
        self.assertFalse(result["allowed"])
        self.assertEqual({item["type"] for item in result["conflicts"]}, {"declared_model", "exclusive_host", "port"})

    def test_controller_probe_correlates_distributed_run(self):
        registry = fixture_registry()
        registry["models"]["pair"]["identity"] = {"served_model": "pair-model"}
        registry["models"]["pair"]["status_probe"] = {
            "type": "controller_json", "host": "gb10", "working_dir": "/srv/pair",
            "command": ["bin/status"], "state_field": "state", "running_value": "running",
            "model_field": "model", "run_id_field": "run_id", "rank_fields": ["head", "worker"],
            "verified_hosts": ["gb10", "gb10-2"],
        }
        platform.validate_registry(registry)
        discovery = {"errors": [], "hosts": {host: {"compose_projects": [], "containers": [], "sockets": []} for host in registry["hosts"]}}
        command = "cd /srv/pair && bin/status"
        runner = FakeRunner({("gb10", command): json.dumps({"state": "running", "model": "pair-model", "run_id": "run-1", "head": True, "worker": True})})
        status = platform.model_statuses(registry, discovery, runner)["pair"]
        self.assertEqual(status["state"], "Running")
        self.assertEqual(status["verified_hosts"], ["gb10", "gb10-2"])
        runner.responses[("gb10", command)] = json.dumps({"state": "running", "model": "pair-model", "run_id": "", "head": True, "worker": True})
        self.assertEqual(platform.model_statuses(registry, discovery, runner)["pair"]["state"], "Degraded")

    def test_native_probe_blocks_conflicting_start(self):
        registry = fixture_registry()
        registry["models"]["worker"]["status_probe"] = {
            "type": "controller_json", "host": "gb10-2", "working_dir": "/srv/worker",
            "command": ["bin/status"], "state_field": "running", "running_value": True,
            "rank_fields": ["identity", "listener"], "verified_hosts": ["gb10-2"],
        }
        platform.validate_registry(registry)
        discovery = {"errors": [], "hosts": {host: {"compose_projects": [], "containers": [], "sockets": []} for host in registry["hosts"]}}
        runner = FakeRunner({("gb10-2", "cd /srv/worker && bin/status"): json.dumps({"running": True, "identity": True, "listener": True})})
        discovery["models"] = platform.model_statuses(registry, discovery, runner)
        result = platform.check_model(registry, discovery, "pair")
        self.assertFalse(result["allowed"])
        self.assertIn("worker", [item.get("model") for item in result["conflicts"]])

    def test_partial_target_does_not_hide_foreign_listener(self):
        registry = fixture_registry()
        registry["models"]["pair"]["endpoints"][0]["host"] = "gb10-2"
        discovery = {
            "errors": [],
            "hosts": {
                "gb10": {"compose_projects": [], "containers": [platform.container_record("gb10", inspect("pair", "server"))], "sockets": []},
                "gb10-2": {"compose_projects": [], "containers": [], "sockets": [{"host": "gb10-2", "protocol": "tcp", "bind": "0.0.0.0", "port": 8890, "process": "foreign"}]},
            },
        }
        discovery["models"] = platform.model_statuses(registry, discovery, runner=None)
        self.assertEqual(discovery["models"]["pair"]["state"], "Partial")
        result = platform.check_model(registry, discovery, "pair")
        self.assertTrue(any(item["type"] == "port" for item in result["conflicts"]))


class LifecycleTests(unittest.TestCase):
    def stopped_snapshot(self):
        return {
            "errors": [],
            "hosts": {
                "gb10": {"compose_projects": [], "containers": [], "sockets": []},
                "gb10-2": {"compose_projects": [], "containers": [], "sockets": []},
            },
            "models": {
                "pair": {"state": "Stopped"},
                "worker": {"state": "Stopped"},
            },
        }

    def test_dry_run_requires_exact_confirmation_and_never_mutates(self):
        registry = fixture_registry()
        registry["models"]["pair"]["adapter"] = {
            "type": "controller", "host": "gb10", "working_dir": "/srv/pair",
            "commands": {
                "check": [["bin/control", "check"]], "start": [["bin/control", "start"]],
                "status": [["bin/control", "status"]], "stop": [["bin/control", "stop"]],
            },
        }
        platform.validate_registry(registry)
        runner = FakeRunner({})
        manager = operations.LifecycleManager(registry, runner)
        with self.assertRaisesRegex(platform.PlatformError, "confirmation"):
            manager.execute("pair", "start", "wrong", dry_run=True, snapshot=self.stopped_snapshot())
        plan = manager.execute("pair", "start", "pair", dry_run=True, snapshot=self.stopped_snapshot())
        self.assertTrue(plan["dry_run"])
        self.assertEqual(runner.commands, [])
        self.assertEqual(plan["steps"], ["cd /srv/pair && bin/control start"])

    def test_protected_action_requires_override_and_action_phrase(self):
        registry = fixture_registry()
        registry["models"]["worker"]["protected"] = True
        registry["models"]["worker"]["adapter"] = {
            "type": "controller", "host": "gb10-2", "working_dir": "/srv/worker",
            "commands": {key: [["control", key]] for key in ("check", "start", "status", "stop")},
        }
        platform.validate_registry(registry)
        manager = operations.LifecycleManager(registry, FakeRunner({}))
        with self.assertRaisesRegex(platform.PlatformError, "allow-protected"):
            manager.execute("worker", "stop", "worker", True, self.stopped_snapshot())
        with self.assertRaisesRegex(platform.PlatformError, "PROTECTED stop worker"):
            manager.execute("worker", "stop", "worker", True, self.stopped_snapshot(), allow_protected=True)
        plan = manager.execute("worker", "stop", "PROTECTED stop worker", True, self.stopped_snapshot(), allow_protected=True)
        self.assertTrue(plan["protected"])

    def test_blocked_preflight_executes_nothing(self):
        registry = fixture_registry()
        registry["models"]["pair"]["adapter"] = {
            "type": "controller", "host": "gb10", "working_dir": "/srv/pair",
            "commands": {key: [["control", key]] for key in ("check", "start", "status", "stop")},
        }
        platform.validate_registry(registry)
        snapshot = self.stopped_snapshot()
        snapshot["models"]["worker"]["state"] = "Running"
        runner = FakeRunner({})
        with self.assertRaisesRegex(platform.PlatformError, "preflight blocked"):
            operations.LifecycleManager(registry, runner).execute("pair", "start", "pair", True, snapshot)
        self.assertEqual(runner.commands, [])

    def test_compose_plan_is_registry_derived(self):
        registry = fixture_registry()
        registry["models"]["worker"]["adapter"] = {
            "type": "compose", "host": "gb10-2", "working_dir": "/srv/worker",
            "files": ["compose.yml", "override.yml"], "env_files": ["worker.env"],
            "services": ["server"],
        }
        platform.validate_registry(registry)
        plan = operations.LifecycleManager(registry, FakeRunner({})).plan("worker", "stop", self.stopped_snapshot())
        self.assertEqual(plan["steps"], [
            "cd /srv/worker && docker compose -p worker --env-file worker.env -f compose.yml -f override.yml stop server"
        ])

    def test_host_locks_release_only_owned_token(self):
        acquire = "set -eu; umask 077; mkdir /tmp/model-platform.lock; printf '%s\\n' aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa > /tmp/model-platform.lock/owner"
        release = "set -eu; test \"$(cat /tmp/model-platform.lock/owner)\" = aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; rm -f /tmp/model-platform.lock/owner; rmdir /tmp/model-platform.lock"
        runner = FakeRunner({("gb10", acquire): "", ("gb10", release): ""})
        with operations.HostLocks(runner, ["gb10"], token="a" * 32):
            pass
        self.assertEqual(runner.commands, [("gb10", acquire), ("gb10", release)])

    def test_lock_scope_includes_adapter_and_conflict_hosts(self):
        registry = fixture_registry()
        registry["models"]["worker"]["adapter"] = {
            "type": "controller", "host": "gb10", "working_dir": "/srv/worker",
            "commands": {key: [["control", key]] for key in ("check", "start", "status", "stop")},
        }
        platform.validate_registry(registry)
        self.assertEqual(operations.LifecycleManager(registry, FakeRunner({})).lock_hosts("worker"), ["gb10", "gb10-2"])

    def test_receipt_allocation_is_exclusive_and_output_is_redacted(self):
        registry = fixture_registry()
        with tempfile.TemporaryDirectory() as temporary:
            manager = operations.LifecycleManager(registry, FakeRunner({}), Path(temporary))
            fixed = SimpleNamespace(hex="a" * 32)
            with mock.patch.object(operations.uuid, "uuid4", return_value=fixed):
                first = manager._allocate_receipt("pair", "start", "test")
                with self.assertRaises(FileExistsError):
                    manager._allocate_receipt("pair", "start", "test")
            self.assertEqual(manager.receipt(first["id"])["status"], "queued")
        value = operations.bounded_output("token=abc password: xyz " + "x" * (operations.MAX_COMMAND_OUTPUT + 10))
        self.assertNotIn("abc", value["text"])
        self.assertNotIn("xyz", value["text"])
        self.assertTrue(value["truncated"])

    def test_lock_release_failure_is_reported(self):
        acquire = "set -eu; umask 077; mkdir /tmp/model-platform.lock; printf '%s\\n' aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa > /tmp/model-platform.lock/owner"
        release = "set -eu; test \"$(cat /tmp/model-platform.lock/owner)\" = aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; rm -f /tmp/model-platform.lock/owner; rmdir /tmp/model-platform.lock"
        runner = FakeRunner({("gb10", acquire): "", ("gb10", release): RuntimeError("release failed")})
        locks = operations.HostLocks(runner, ["gb10"], token="a" * 32)
        locks.__enter__()
        self.assertEqual(locks.release()[0]["host"], "gb10")

    def test_async_receipt_runs_authoritative_checks_inside_lock(self):
        registry = {
            "version": 1, "api_version": platform.API_VERSION,
            "hosts": {"gb10": {"management_ip": "192.168.88.181"}},
            "models": {"solo": {
                "display_name": "Solo",
                "deployments": [{"host": "gb10", "project": "solo", "services": ["server"]}],
                "adapter": {"type": "controller", "host": "gb10", "working_dir": "/srv/solo", "commands": {
                    "check": [["control", "check"]], "start": [["control", "start"]],
                    "status": [["control", "status"]], "stop": [["control", "stop"]],
                }},
                "endpoints": [], "resources": {"exclusive_hosts": ["gb10"], "gpu_hosts": ["gb10"], "claims": []}, "conflicts": [],
            }},
        }
        platform.validate_registry(registry)

        class SequenceRunner(platform.Runner):
            def __init__(self):
                self.commands = []
                self.inspect_count = 0

            def run(self, host, command, timeout=20):
                self.commands.append(command)
                if command == platform.COMPOSE_COMMAND:
                    return "[]" if self.inspect_count < 2 else json.dumps([{"Name": "solo", "Status": "running(1)", "ConfigFiles": "/srv/solo.yml"}])
                if command == platform.INSPECT_COMMAND:
                    self.inspect_count += 1
                    return "[]" if self.inspect_count < 3 else json.dumps([inspect("solo", "server")])
                if command == platform.SOCKET_COMMAND or command.startswith("set -eu; test -d"):
                    return ""
                if "mkdir /tmp/model-platform.lock" in command or "rmdir /tmp/model-platform.lock" in command:
                    return ""
                if command == "cd /srv/solo && control check":
                    return "check ok"
                if command == "cd /srv/solo && control start":
                    return "token=do-not-store"
                raise AssertionError(command)

        runner = SequenceRunner()
        with tempfile.TemporaryDirectory() as temporary:
            manager = operations.LifecycleManager(registry, runner, Path(temporary))
            receipt = manager.submit("solo", "start", "solo", actor="test")
            for _ in range(100):
                result = manager.receipt(receipt["id"])
                if result["status"] not in {"queued", "running"}:
                    break
                time.sleep(0.01)
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["before"]["models"]["solo"]["state"], "Stopped")
            self.assertNotIn("do-not-store", json.dumps(result["commands"]))
            lock_index = next(index for index, command in enumerate(runner.commands) if "mkdir /tmp/model-platform.lock" in command)
            action_index = runner.commands.index("cd /srv/solo && control start")
            release_index = next(index for index, command in enumerate(runner.commands) if "rmdir /tmp/model-platform.lock" in command)
            self.assertLess(lock_index, action_index)
            self.assertLess(action_index, release_index)


class WebAndReleaseTests(unittest.TestCase):
    def test_web_contract_is_authenticated_async_and_text_safe(self):
        web_source = (ROOT / "web.py").read_text()
        app_source = (ROOT / "static/app.js").read_text()
        self.assertIn("MODEL_PLATFORM_WEB_TOKEN", web_source)
        self.assertIn("model_platform_session", web_source)
        self.assertIn("HTTPStatus.ACCEPTED", web_source)
        self.assertIn("manager.submit", web_source)
        self.assertIn("pollReceipt", app_source)
        self.assertIn("localStorage", app_source)
        self.assertNotIn("innerHTML", app_source)

    def test_external_state_survives_two_release_switches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "state"
            state.mkdir(mode=0o700)
            artifact = state / "receipt.json"
            artifact.write_text("retained")
            releases = root / "releases"
            (releases / "r1").mkdir(parents=True)
            (releases / "r2").mkdir()
            current = root / "current"
            os.symlink("releases/r1", current)
            replacement = root / "current.new"
            os.symlink("releases/r2", replacement)
            os.replace(replacement, current)
            self.assertEqual(current.resolve(), (releases / "r2").resolve())
            self.assertEqual(artifact.read_text(), "retained")


if __name__ == "__main__":
    unittest.main()
