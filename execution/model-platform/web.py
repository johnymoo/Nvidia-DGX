#!/usr/bin/env python3
"""Loopback-only thin Web API/UI for model-platform."""

from __future__ import annotations

import argparse
import base64
import hmac
import json
import mimetypes
import os
import secrets
import sys
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from model_platform import API_VERSION, PlatformError, SSHRunner, check_model, discover, load_registry, ports_document, status_document
from operations import LifecycleManager


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
MAX_BODY = 16 * 1024


class App:
    def __init__(self, registry_path: Path, operator_token: str):
        if len(operator_token) < 24:
            raise PlatformError("MODEL_PLATFORM_WEB_TOKEN must contain at least 24 characters")
        self.registry_path = registry_path
        self.operator_token = operator_token
        self.csrf = secrets.token_urlsafe(32)
        self.sessions = set()
        self.runner = SSHRunner()

    def registry(self):
        return load_registry(self.registry_path)

    def snapshot(self, registry):
        return discover(registry, self.runner)


def handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "model-platform/1"

        def log_message(self, format, *args):
            return

        def trusted_host(self):
            host = self.headers.get("Host", "")
            name = host.rsplit(":", 1)[0].strip("[]")
            return name in {"127.0.0.1", "localhost", "::1"}

        def authenticated(self):
            cookie = self.headers.get("Cookie", "")
            for item in cookie.split(";"):
                name, separator, value = item.strip().partition("=")
                if separator and name == "model_platform_session" and value in app.sessions:
                    return True
            value = self.headers.get("Authorization", "")
            if not value.startswith("Basic "):
                return False
            try:
                decoded = base64.b64decode(value[6:], validate=True).decode("utf-8")
                username, password = decoded.split(":", 1)
            except (ValueError, UnicodeDecodeError):
                return False
            return hmac.compare_digest(username, "operator") and hmac.compare_digest(password, app.operator_token)

        def bootstrap_session(self):
            parsed = urllib.parse.urlparse(self.path)
            supplied = urllib.parse.parse_qs(parsed.query).get("access_token", [""])[0]
            if not supplied or not hmac.compare_digest(supplied, app.operator_token):
                return False
            session = secrets.token_urlsafe(32)
            app.sessions.add(session)
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", parsed.path or "/")
            self.send_header("Set-Cookie", "model_platform_session={}; HttpOnly; SameSite=Strict; Path=/".format(session))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return True

        def authorize(self):
            if not self.trusted_host():
                self.error_response(HTTPStatus.MISDIRECTED_REQUEST, "untrusted Host header")
                return False
            if not self.authenticated():
                body = json.dumps({"api_version": API_VERSION, "kind": "Error", "error": "operator authentication required"}).encode("utf-8")
                self.send_response(HTTPStatus.UNAUTHORIZED)
                self.send_header("WWW-Authenticate", 'Basic realm="model-platform", charset="UTF-8"')
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return False
            return True

        def audit(self, action, model=""):
            print("model-platform audit operator=operator source={} action={} model={}".format(self.client_address[0], action, model), file=sys.stderr, flush=True)

        def json_response(self, status, document):
            body = json.dumps(document, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def error_response(self, status, message):
            self.json_response(status, {"api_version": API_VERSION, "kind": "Error", "error": message})

        def do_GET(self):
            try:
                if self.trusted_host() and self.bootstrap_session():
                    return
                if not self.authorize():
                    return
                parsed = urllib.parse.urlparse(self.path)
                path = parsed.path
                if path == "/api/v1/session":
                    return self.json_response(HTTPStatus.OK, {"api_version": API_VERSION, "kind": "Session", "csrf": app.csrf})
                registry = app.registry()
                if path == "/api/v1/status":
                    snapshot = app.snapshot(registry)
                    return self.json_response(HTTPStatus.OK, status_document(registry, snapshot, runner=app.runner))
                if path == "/api/v1/ports":
                    host = urllib.parse.parse_qs(parsed.query).get("host", [None])[0]
                    if host and host not in registry["hosts"]:
                        raise PlatformError("unknown host")
                    snapshot = app.snapshot(registry)
                    return self.json_response(HTTPStatus.OK, ports_document(registry, snapshot, host))
                if path.startswith("/api/v1/models/") and path.endswith("/check"):
                    model_id = path[len("/api/v1/models/") : -len("/check")].strip("/")
                    snapshot = app.snapshot(registry)
                    return self.json_response(HTTPStatus.OK, check_model(registry, snapshot, model_id, runner=app.runner))
                if path.startswith("/api/v1/receipts/"):
                    receipt_id = path[len("/api/v1/receipts/") :]
                    return self.json_response(HTTPStatus.OK, LifecycleManager(registry, app.runner).receipt(receipt_id))
                return self.static(path)
            except PlatformError as exc:
                self.error_response(HTTPStatus.BAD_REQUEST, str(exc))
            except Exception as exc:
                self.error_response(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))

        def static(self, path):
            relative = "index.html" if path == "/" else path.lstrip("/")
            if relative not in {"index.html", "app.js", "styles.css"}:
                return self.error_response(HTTPStatus.NOT_FOUND, "not found")
            target = STATIC / relative
            data = target.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            try:
                if not self.authorize():
                    return
                if self.headers.get("X-Model-Platform-CSRF") != app.csrf:
                    return self.error_response(HTTPStatus.FORBIDDEN, "invalid CSRF token")
                origin = self.headers.get("Origin")
                if origin:
                    expected = "http://{}".format(self.headers.get("Host"))
                    if origin != expected:
                        return self.error_response(HTTPStatus.FORBIDDEN, "cross-origin request rejected")
                if self.headers.get_content_type() != "application/json":
                    return self.error_response(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "application/json required")
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY:
                    return self.error_response(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "invalid request size")
                body = json.loads(self.rfile.read(length))
                parsed = urllib.parse.urlparse(self.path)
                parts = parsed.path.strip("/").split("/")
                if len(parts) != 5 or parts[:3] != ["api", "v1", "models"] or parts[4] not in {"start", "stop", "restart"}:
                    return self.error_response(HTTPStatus.NOT_FOUND, "operation not found")
                if set(body) - {"confirm", "dry_run", "allow_protected"}:
                    return self.error_response(HTTPStatus.BAD_REQUEST, "unknown request fields")
                registry = app.registry()
                manager = LifecycleManager(registry, app.runner)
                self.audit(parts[4], parts[3])
                if bool(body.get("dry_run")):
                    result = manager.execute(parts[3], parts[4], body.get("confirm", ""), True, allow_protected=bool(body.get("allow_protected")), actor="web:operator")
                    return self.json_response(HTTPStatus.OK, result)
                result = manager.submit(parts[3], parts[4], body.get("confirm", ""), allow_protected=bool(body.get("allow_protected")), actor="web:operator")
                self.json_response(HTTPStatus.ACCEPTED, result)
            except (PlatformError, ValueError, json.JSONDecodeError) as exc:
                self.error_response(HTTPStatus.BAD_REQUEST, str(exc))
            except Exception as exc:
                self.error_response(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))

    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=ROOT / "models.yaml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args(argv)
    if args.host not in {"127.0.0.1", "::1"}:
        raise SystemExit("Web UI is loopback-only")
    token = os.environ.get("MODEL_PLATFORM_WEB_TOKEN", "")
    try:
        app = App(args.registry, token)
    except PlatformError as exc:
        raise SystemExit(str(exc)) from exc
    server = ThreadingHTTPServer((args.host, args.port), handler(app))
    print("model-platform Web UI listening on http://{}:{}".format(args.host, args.port), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
