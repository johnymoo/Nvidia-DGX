"""State computation + discovery parsing tests (host-network and mapped cases)."""

from __future__ import annotations

import json
import tempfile
import unittest

from tests.test_modelctl_schema import HAS_YAML, VALID_REGISTRY, write_registry
from tools.modelctl import discovery
from tools.modelctl.discovery import (
    ComposeProject, Container, Listener, _json_documents, _json_lines, _SS_LINE,
)
from tools.modelctl.runner import FakeRunner, RunResult
from tools.modelctl.schema import load_registry
from tools.modelctl.state import (
    STATE_DEGRADED, STATE_PARTIAL, STATE_RUNNING, STATE_STOPPED,
    collect_host_facts, model_status,
)

# Real-shaped fixtures (values from the gb10 fleet, genericized)
COMPOSE_LS_JSON = r'''
[{"Name":"alpha","Status":"running(1)","ConfigFiles":"/opt/alpha/compose.yml"},
 {"Name":"ghost","Status":"exited(2)","ConfigFiles":"/opt/ghost/compose.yml"}]
'''

DOCKER_PS_LINES = "\n".join([
    json.dumps({
        "Command": "\"bash -lc 'serve'\"", "CreatedAt": "2026-08-25 01:59:23 +0800 CST",
        "ID": "7c1f3591bfb4", "Image": "alpha:v1", "Names": "alpha-engine-1",
        "State": "running", "Status": "Up 4 days",
        "Labels": ("com.docker.compose.project=alpha,com.docker.compose.service=engine,"
                   "com.docker.compose.oneoff=False"),
        "Ports": "",  # host-network: no port mapping visible
    }),
    json.dumps({
        "Command": "\"python /app/proxy.py\"", "CreatedAt": "2026-08-17 20:27:16 +0800 CST",
        "ID": "fcfd6b5cc02f", "Image": "python:3.11-slim", "Names": "guard-1",
        "State": "exited", "Status": "Exited (0) 2 weeks ago",
        "Labels": "com.docker.compose.project=guard",
        "Ports": "0.0.0.0:9002->9002/tcp",
    }),
])

SS_OUTPUT = """LISTEN 0      5            127.0.0.1:18004   0.0.0.0:*
LISTEN 0      2048           0.0.0.0:9000    0.0.0.0:*
LISTEN 0      4096    192.168.1.10:59527     0.0.0.0:*
LISTEN 0      511              [::]:9100       [::]:*
"""


class DiscoveryParsingTest(unittest.TestCase):
    def test_compose_ls_json(self):
        projects = [ComposeProject.from_ls_entry(e) for e in _json_documents(COMPOSE_LS_JSON)]
        by_name = {p.name: p for p in projects}
        self.assertTrue(by_name["alpha"].running)
        self.assertFalse(by_name["ghost"].running)
        self.assertEqual(by_name["ghost"].exit_code, 2)
        self.assertEqual(by_name["alpha"].config_files, ("/opt/alpha/compose.yml",))

    def test_docker_ps_labels_string(self):
        containers = [Container.from_ps_entry(e) for e in _json_lines(DOCKER_PS_LINES)]
        alpha = containers[0]
        self.assertEqual(alpha.project, "alpha")
        self.assertEqual(alpha.service, "engine")
        self.assertEqual(alpha.state, "running")
        self.assertEqual(containers[1].project, "guard")

    def test_ss_parsing_wildcards_and_specifics(self):
        listeners = []
        for line in SS_OUTPUT.splitlines():
            m = _SS_LINE.match(line.strip())
            bind = m.group("bind")
            if bind.startswith("["):
                bind = bind[1:-1]
            listeners.append(Listener(bind=bind, port=int(m.group("port"))))
        self.assertEqual({(l.bind, l.port) for l in listeners},
                         {("127.0.0.1", 18004), ("0.0.0.0", 9000),
                          ("192.168.1.10", 59527), ("::", 9100)})

    def test_discovery_over_runner(self):
        runner = FakeRunner(responses={
            (None, ("docker", "compose", "ls")): RunResult(
                host=None, argv=(), exit_code=0, stdout=COMPOSE_LS_JSON),
            (None, ("docker", "ps")): RunResult(
                host=None, argv=(), exit_code=0, stdout=DOCKER_PS_LINES),
            (None, ("ss",)): RunResult(
                host=None, argv=(), exit_code=0, stdout=SS_OUTPUT),
        })
        projects = discovery.compose_projects(runner, None)
        self.assertEqual([p.name for p in projects], ["alpha", "ghost"])
        containers = discovery.containers(runner, None)
        self.assertEqual(len(containers), 2)
        listeners = discovery.listeners(runner, None)
        self.assertEqual(len(listeners), 4)

    def test_discovery_error_wraps_failure(self):
        runner = FakeRunner(responses={
            (None, ("docker", "compose", "ls")): RunResult(
                host=None, argv=(), exit_code=1, stderr="cannot connect"),
        })
        with self.assertRaises(discovery.DiscoveryError):
            discovery.compose_projects(runner, None)

    def test_container_stats_parsing(self):
        full_cid = "abc" + "1" * 61  # 64-hex docker id (docker stats reports the full id)
        stats_lines = "\n".join([
            json.dumps({"BlockIO": "0B / 0kB", "CPUPerc": "312.15%", "Container": full_cid,
                        "ID": "abc123def4", "MemUsage": "5.7GiB / 119.6GiB", "MemPerc": "4.76%",
                        "Name": "glm53-exl3-head", "NetIO": "1.2MB / 3.4MB", "PIDs": "128"}),
            json.dumps({"BlockIO": "8.1MB / 0kB", "CPUPerc": "0.00%", "Container": "def",
                        "ID": "def456abc7", "MemUsage": "8.5MiB / 119.6GiB", "MemPerc": "0.01%",
                        "Name": "qwen36-8004-proxy", "NetIO": "60B / 0B", "PIDs": "1"}),
        ])
        runner = FakeRunner(responses={
            (None, ("docker", "stats")): RunResult(
                host=None, argv=(), exit_code=0, stdout=stats_lines),
            (None, ("nvidia-smi",)): RunResult(
                host=None, argv=(), exit_code=0, stdout="291083, 95236\n4422, 66\n"),
            (None, ("grep", "-H", ".")): RunResult(
                host=None, argv=(), exit_code=0,
                stdout=f"/proc/291083/cgroup:0::/system.slice/docker-{full_cid}.scope\n"),
        })
        entries = {e["name"]: e for e in discovery.container_stats(runner, None)}
        head = entries["glm53-exl3-head"]
        self.assertEqual(head["cpu"], "312.15%")
        self.assertAlmostEqual(head["cpu_percent"], 312.15)
        self.assertAlmostEqual(head["mem_percent"], 4.76)
        self.assertEqual(head["mem_used_bytes"], int(5.7 * 2**30))
        self.assertEqual(head["mem_limit_bytes"], int(119.6 * 2**30))
        self.assertEqual(head["pids"], "128")
        # device-side memory attributed via nvidia-smi + /proc cgroup
        self.assertEqual(head["gpu_used_bytes"], 95236 * 2**20)
        self.assertEqual(head["gpu_limit_bytes"], int(119.6 * 2**30))
        self.assertAlmostEqual(head["gpu_percent"], 95236 / (119.6 * 2**10) * 100, places=1)
        # non-GPU container carries no gpu fields
        self.assertNotIn("gpu_used_bytes", entries["qwen36-8004-proxy"])

    def test_container_stats_without_nvidia_smi_skips_gpu(self):
        stats_lines = json.dumps({"BlockIO": "0B / 0kB", "CPUPerc": "1.00%", "Container": "abc",
                                  "MemUsage": "8.5MiB / 119.6GiB", "MemPerc": "0.01%",
                                  "Name": "guard-1", "NetIO": "60B / 0B", "PIDs": "1"})
        runner = FakeRunner(responses={
            (None, ("docker", "stats")): RunResult(
                host=None, argv=(), exit_code=0, stdout=stats_lines),
        })  # no nvidia-smi response -> FakeRunner returns empty rc=0 (skipped)
        entries = discovery.container_stats(runner, None)
        self.assertEqual(len(entries), 1)
        self.assertNotIn("gpu_used_bytes", entries[0])
        self.assertNotIn("gpu_percent", entries[0])

    def test_container_stats_error_wraps_failure(self):
        runner = FakeRunner(responses={
            (None, ("docker", "stats")): RunResult(
                host=None, argv=(), exit_code=1, stderr="denied"),
        })
        with self.assertRaises(discovery.DiscoveryError):
            discovery.container_stats(runner, None)


class StateTest(unittest.TestCase):
    def setUp(self):
        if not HAS_YAML:
            self.skipTest("PyYAML not installed")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.registry = load_registry(write_registry(self.tmp.name))

    def facts(self, containers_by_host=None, listeners_by_host=None, reachable=None):
        from tools.modelctl.state import HostFacts
        reachable = reachable if reachable is not None else {"head": True, "worker": True}
        containers_by_host = containers_by_host or {}
        listeners_by_host = listeners_by_host or {}
        return {
            name: HostFacts(host=name, reachable=reachable[name],
                            error=None if reachable[name] else "ssh refused",
                            containers=containers_by_host.get(name, []),
                            listeners=listeners_by_host.get(name, []),
                            projects=[ComposeProject(
                                name="x", status="running(1)",
                                config_files=(), running=True, exit_code=1)])
            for name in ("head", "worker")
        }

    def test_dual_node_running(self):
        alpha = self.registry.models["alpha-llm"]
        facts = self.facts(
            containers_by_host={
                "head": [_c("alpha-engine-1", "alpha")],
                "worker": [_c("alpha-engine-1", "alpha")]})
        status = model_status(alpha, facts, check_health=False)
        self.assertEqual(status.state, STATE_RUNNING)

    def test_partial_when_worker_down(self):
        alpha = self.registry.models["alpha-llm"]
        facts = self.facts(
            containers_by_host={"head": [_c("alpha-engine-1", "alpha")], "worker": []})
        status = model_status(alpha, facts, check_health=False)
        self.assertEqual(status.state, STATE_PARTIAL)

    def test_stopped_when_nothing_runs(self):
        alpha = self.registry.models["alpha-llm"]
        status = model_status(alpha, self.facts(), check_health=False)
        self.assertEqual(status.state, STATE_STOPPED)

    def test_unreachable_host_marks_unknown(self):
        alpha = self.registry.models["alpha-llm"]
        facts = self.facts(reachable={"head": True, "worker": False},
                           containers_by_host={"head": [_c("alpha-engine-1", "alpha")]})
        status = model_status(alpha, facts, check_health=False)
        self.assertEqual(status.state, STATE_PARTIAL)
        self.assertFalse(status.hosts["worker"]["reachable"])

    def test_expected_count_mismatch_is_degraded(self):
        alpha = self.registry.models["alpha-llm"]
        facts = self.facts(
            containers_by_host={
                "head": [_c("alpha-engine-1", "alpha"), _c("alpha-engine-2", "alpha")],
                "worker": [_c("alpha-engine-1", "alpha")]})
        status = model_status(alpha, facts, check_health=False)
        self.assertEqual(status.state, STATE_DEGRADED)

    def test_failing_health_degrades_running_model(self):
        alpha = self.registry.models["alpha-llm"]
        facts = self.facts(
            containers_by_host={
                "head": [_c("alpha-engine-1", "alpha")],
                "worker": [_c("alpha-engine-1", "alpha")]})
        runner = FakeRunner(responses={
            (None, ("curl",)): RunResult(host=None, argv=(), exit_code=7, stderr="refused"),
        })
        status = model_status(alpha, facts, check_health=True, runner=runner,
                              registry=self.registry)
        self.assertEqual(status.state, STATE_DEGRADED)
        self.assertFalse(status.health["ok"])


def _c(name, project):
    return Container(id="id-" + name, names=name, image="img", state="running",
                     status="Up", project=project, service="svc")


if __name__ == "__main__":
    unittest.main()
