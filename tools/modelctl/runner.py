"""Command execution abstraction.

All host access goes through Runner so tests can inject a FakeRunner:
production runs argv locally or over BatchMode SSH; nothing else is allowed
to touch a host (webui included).
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass, field


@dataclass
class RunResult:
    host: str | None
    argv: tuple[str, ...]
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    skipped: bool = False  # FakeRunner matched nothing and defaulted

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class Runner:
    """Executes argv on a registered host (None/'' = local)."""

    def __init__(self, connect_timeout: int = 15, command_timeout: int = 120):
        self.connect_timeout = connect_timeout
        self.command_timeout = command_timeout

    def run(self, host_target: str | None, argv: list[str], timeout: int | None = None) -> RunResult:
        argv = [str(a) for a in argv]
        if not host_target:
            return self._run_local(None, argv, timeout)
        remote_argv = [
            "ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={self.connect_timeout}",
            host_target, "--",
        ]
        remote_argv += [shlex.quote(a) for a in argv]
        return self._run_local(host_target, remote_argv, timeout)

    def _run_local(self, host: str | None, argv: list[str], timeout: int | None) -> RunResult:
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True,
                timeout=timeout or self.command_timeout,
            )
            return RunResult(host=host, argv=tuple(argv), exit_code=proc.returncode,
                             stdout=proc.stdout, stderr=proc.stderr)
        except subprocess.TimeoutExpired as exc:
            return RunResult(host=host, argv=tuple(argv), exit_code=124,
                             stdout=exc.stdout or "", stderr=f"timeout after {timeout or self.command_timeout}s")
        except FileNotFoundError:
            return RunResult(host=host, argv=tuple(argv), exit_code=127, stderr=f"executable not found: {argv[0]}")


@dataclass
class FakeRunner(Runner):
    """Scripted runner for offline tests: maps (target, argv-prefix) -> RunResult.

    An entry's argv is matched by prefix against the requested argv (after the
    ssh preamble is stripped). Callables receive the full argv and return a
    RunResult. Unmatched calls return rc=0 with empty output so read paths can
    be stubbed one endpoint at a time.
    """

    responses: dict = field(default_factory=dict)
    calls: list = field(default_factory=list)

    def run(self, host_target, argv, timeout=None):
        argv = [str(a) for a in argv]
        self.calls.append((host_target, tuple(argv)))
        effective = self._strip_ssh_preamble(host_target, argv)
        for (target, prefix), result in self.responses.items():
            if target == host_target and tuple(effective[: len(prefix)]) == tuple(prefix):
                if callable(result):
                    return result(tuple(effective))
                return result
        return RunResult(host=host_target, argv=tuple(argv), exit_code=0, stdout="", stderr="", skipped=True)

    @staticmethod
    def _strip_ssh_preamble(host_target, argv):
        if host_target and argv and argv[0] == "ssh":
            # ssh -o X -o Y target -- <effective argv>
            try:
                marker = argv.index("--")
                return argv[marker + 1:]
            except ValueError:
                return argv
        return argv


def local_hostname() -> str:
    import socket
    return socket.gethostname().split(".")[0]
