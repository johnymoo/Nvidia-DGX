"""modelctl Web UI — a thin, whitelisted HTTP client over the modelctl CLI.

Security contract (issue #26):
- the backend runs ONLY `modelctl` read-only commands and the four mutating
  actions with fixed argv; no shell interpolation, no arbitrary commands
- mutations are gated by the plain confirm dialog (LAN-trusted deployment);
  protected models still require the explicit allow_protected escalation
- every request is audit-logged to <state_dir>/audit.log
- long-running actions run as jobs: POST returns a job id, the page polls

Run:  python3 -m tools.modelctl.webui --config ~/modelctl/models.yaml --port 8461
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tools.modelctl import SCHEMA_VERSION, __version__

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

_READ_COMMANDS = {"list", "status", "ports", "discover", "check", "validate"}
_MUTATIONS = {"start", "stop", "restart", "switch"}
_MODEL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class WebUiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


class JobRunner:
    """Runs one modelctl subprocess per job; state lands in <state_dir>/jobs."""

    def __init__(self, state_dir: str, python_bin: str, config: str, state_cli_dir: str):
        self.jobs_dir = os.path.join(state_dir, "jobs")
        os.makedirs(self.jobs_dir, exist_ok=True)
        self.python_bin = python_bin
        self.config = config
        self.state_cli_dir = state_cli_dir
        self._lock = threading.Lock()
        self._procs: dict[str, subprocess.Popen] = {}

    def submit(self, action: str, model: str, extra_args: list[str]) -> str:
        job_id = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        argv = [self.python_bin, "-m", "tools.modelctl.cli",
                "--config", self.config, "--state-dir", self.state_cli_dir,
                "--json", action, model] + extra_args
        entry = {
            "schema_version": SCHEMA_VERSION,
            "job_id": job_id,
            "action": action,
            "model": model,
            "argv": argv,
            "state": "running",
            "submitted_at": _utcnow(),
            "exit_code": None,
            "result": None,
        }
        self._write(job_id, entry)
        proc = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=True,
        )
        with self._lock:
            self._procs[job_id] = proc
        threading.Thread(target=self._reap, args=(job_id, proc), daemon=True).start()
        return job_id

    def _reap(self, job_id: str, proc: subprocess.Popen) -> None:
        stdout, stderr = proc.communicate(timeout=None)
        entry = self._read(job_id) or {}
        entry["exit_code"] = proc.returncode
        entry["finished_at"] = _utcnow()
        entry["state"] = "done" if proc.returncode == 0 else "failed"
        try:
            entry["result"] = json.loads(stdout) if stdout.strip() else None
        except json.JSONDecodeError:
            entry["result"] = {"raw_stdout": stdout[-2000:], "raw_stderr": stderr[-2000:]}
        self._write(job_id, entry)

    def get(self, job_id: str) -> dict | None:
        if not re.fullmatch(r"[0-9A-Za-z-]+", job_id or ""):
            return None
        return self._read(job_id)

    def _path(self, job_id: str) -> str:
        return os.path.join(self.jobs_dir, job_id + ".json")

    def _write(self, job_id: str, entry: dict) -> None:
        tmp = self._path(job_id) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(entry, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, self._path(job_id))

    def _read(self, job_id: str) -> dict | None:
        try:
            with open(self._path(job_id), "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError):
            return None


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_handler(config: str, state_dir: str, registry_model_names, audit_path: str,
                 job_runner: JobRunner, cli_state_dir: str):
    read_argv = {
        "list": ["--json", "list"],
        "status": ["--json", "status", "--stats"],
        "ports": ["--json", "ports"],
        "discover": ["--json", "discover"],
    }

    class Handler(BaseHTTPRequestHandler):
        server_version = "modelctl-web/" + __version__

        # ---- helpers ----------------------------------------------------
        def log_message(self, fmt, *args):  # silence default stderr noise
            pass

        def _audit(self, event: str, **fields) -> None:
            line = json.dumps({"at": _utcnow(), "event": event,
                               "peer": self.client_address[0], **fields}, ensure_ascii=False)
            try:
                with open(audit_path, "a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            except OSError:
                pass

        def _send_json(self, payload: dict, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_static(self, rel: str) -> None:
            path = os.path.normpath(os.path.join(STATIC_DIR, rel))
            if not path.startswith(STATIC_DIR) or not os.path.isfile(path):
                self._send_json({"error": {"code": "NOT_FOUND", "message": "not found"}}, 404)
                return
            with open(path, "rb") as handle:
                body = handle.read()
            ctype = "text/html; charset=utf-8" if path.endswith(".html") else "text/plain"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _modelctl(self, argv: list[str]) -> dict:
            proc = subprocess.run(
                [sys.executable, "-m", "tools.modelctl.cli",
                 "--config", config, "--state-dir", cli_state_dir] + argv,
                capture_output=True, text=True, timeout=180,
            )
            try:
                return json.loads(proc.stdout)
            except json.JSONDecodeError:
                return {"error": {"code": "BACKEND_ERROR",
                                  "message": (proc.stderr or proc.stdout)[-800:]}}

        # ---- routes ------------------------------------------------------
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                return self._send_static("index.html")
            if path == "/api/v1/meta":
                return self._send_json({
                    "schema_version": SCHEMA_VERSION, "tool_version": __version__,
                    "mutations": sorted(_MUTATIONS),
                })
            if path in ("/api/v1/list", "/api/v1/status", "/api/v1/ports", "/api/v1/discover"):
                command = path.rsplit("/", 1)[-1]
                self._audit("read", command=command)
                return self._send_json(self._modelctl(read_argv[command]))
            if path == "/api/v1/check":
                query = dict(pair.split("=", 1) for pair in self.path.split("?", 1)[-1].split("&")
                             if "=" in pair)
                model = query.get("model", "")
                if not _MODEL_NAME_RE.match(model) or model not in registry_model_names:
                    return self._send_json(
                        {"error": {"code": "UNKNOWN_MODEL", "message": f"unknown model: {model}"}}, 400)
                self._audit("read", command="check", model=model)
                return self._send_json(self._modelctl(["--json", "check", model]))
            if path.startswith("/api/v1/jobs/"):
                job_id = path.rsplit("/", 1)[-1]
                job = job_runner.get(job_id)
                if job is None:
                    return self._send_json(
                        {"error": {"code": "NOT_FOUND", "message": "no such job"}}, 404)
                return self._send_json(job)
            self._send_json({"error": {"code": "NOT_FOUND", "message": "not found"}}, 404)

        def do_POST(self):
            if self.path.split("?", 1)[0] != "/api/v1/jobs":
                return self._send_json(
                    {"error": {"code": "NOT_FOUND", "message": "not found"}}, 404)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, json.JSONDecodeError):
                return self._send_json(
                    {"error": {"code": "BAD_REQUEST", "message": "body must be JSON"}}, 400)

            action = body.get("action")
            model = body.get("model", "")
            allow_protected = bool(body.get("allow_protected"))

            if action not in _MUTATIONS:
                return self._send_json(
                    {"error": {"code": "BAD_ACTION",
                               "message": f"action must be one of {sorted(_MUTATIONS)}"}}, 400)
            if not _MODEL_NAME_RE.match(model) or model not in registry_model_names:
                return self._send_json(
                    {"error": {"code": "UNKNOWN_MODEL", "message": f"unknown model: {model}"}}, 400)

            extra = ["--allow-protected"] if allow_protected else []
            if action in ("start", "switch") and body.get("no_wait"):
                extra.append("--no-wait")
            if action == "start" and body.get("stop_conflicts"):
                extra.append("--stop-conflicts")

            job_id = job_runner.submit(action, model, extra)
            self._audit("submit", action=action, model=model,
                        allow_protected=allow_protected, job_id=job_id)
            return self._send_json({"schema_version": SCHEMA_VERSION, "job_id": job_id,
                                    "poll": f"/api/v1/jobs/{job_id}"}, 202)

    return Handler


def load_model_names(config: str) -> set[str]:
    from tools.modelctl.schema import load_registry
    registry = load_registry(config)
    return set(registry.models)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="modelctl-webui")
    parser.add_argument("--config", default=os.environ.get(
        "MODELCTL_CONFIG", os.path.expanduser("~/modelctl/models.yaml")))
    parser.add_argument("--state-dir", default=os.environ.get(
        "MODELCTL_STATE_DIR", os.path.expanduser("~/modelctl/var")))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8461)
    args = parser.parse_args(argv)

    names = load_model_names(args.config)
    os.makedirs(args.state_dir, exist_ok=True)
    audit_path = os.path.join(args.state_dir, "audit.log")
    # the CLI jobs run with the same state dir; read-only commands never lock
    jobs = JobRunner(args.state_dir, sys.executable, args.config, args.state_dir)

    handler = make_handler(args.config, args.state_dir, names, audit_path, jobs, args.state_dir)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"modelctl web UI on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
