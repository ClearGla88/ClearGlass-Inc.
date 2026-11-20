"""Low-interaction HTTP decoy (standard library only).

What it does: answers every request with fixed synthetic content, records
request metadata, fingerprints any honeytoken-shaped string it sees, and sends
a signed event. What it never does: execute, store or echo a request body,
reflect input into a response, follow a redirect, or open an outbound
connection other than to the configured ingestion API.

Observes: method, path (truncated, query values dropped), header names, a
truncated user agent, whether an Authorization or Cookie header was present,
body length and SHA-256 (body read capped at max_capture_bytes), source
address and port. Does not observe: anything past the first max_capture_bytes,
TLS (it speaks plain HTTP; put it behind nothing that terminates TLS for it),
or who the client really is behind NAT or a proxy.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from .. import honeytokens
from .client import build_event

LOGIN_PAGE = (
    b"<!doctype html><html><head><meta charset='utf-8'><title>Staff Portal</title></head><body>"
    b"<h1>Staff Portal</h1><form method='post' action='/login'>"
    b"<label>User <input name='u'></label> <label>Password <input name='p' type='password'></label>"
    b"<button>Sign in</button></form></body></html>"
)
DENIED = b'{"error":"invalid credentials"}'


def _clean(text: str, limit: int) -> str:
    return "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in text)[:limit]


def make_handler(*, sink: Callable[[dict], None], sensor_id: str, environment: str, scope: str,
                 max_capture_bytes: int = 4096, server_header: str = "portal") -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = server_header
        sys_version = ""
        timeout = 5  # per-connection socket timeout: slow clients cannot hold threads open
        protocol_version = "HTTP/1.0"

        def log_message(self, *_args: Any) -> None:  # silence default stderr logging
            return

        def _handle(self) -> None:
            try:
                declared = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                declared = -1
            oversized = declared > max_capture_bytes or declared < 0
            body = b"" if oversized else self.rfile.read(declared)
            parts = urlsplit(self.path)
            scan_text = " ".join(
                [self.headers.get(h, "") for h in ("Authorization", "Cookie", "X-Api-Key")]
                + [parts.query, body.decode("latin-1")]
            )
            attrs: dict[str, Any] = {
                "method": _clean(self.command or "", 16),
                "path": _clean(parts.path, 256),
                "query_keys": [_clean(k, 64) for k, _ in parse_qsl(parts.query, keep_blank_values=True)][:16],
                "header_names": [_clean(h, 64) for h in list(self.headers.keys())[:16]],
                "user_agent": _clean(self.headers.get("User-Agent", ""), 256),
                "has_authorization": "Authorization" in self.headers,
                "has_cookie": "Cookie" in self.headers,
                "body_length": max(declared, 0),
                "body_sha256": hashlib.sha256(body).hexdigest() if body else "",
                "body_oversized": oversized,
            }
            fps = honeytokens.fingerprints_in(scan_text)
            if fps:
                attrs["honeytoken_fingerprints"] = fps
            host, port = self.client_address[0], self.client_address[1]
            sink(build_event(
                sensor_id=sensor_id, category="honeypot.http.request", environment=environment, scope=scope,
                severity="high" if fps else "medium", src_ip=host, src_port=port,
                dst_port=self.server.server_address[1], attributes=attrs,
            ))
            if oversized:
                self._send(413, b"", "text/plain")
            elif self.command == "GET" and parts.path in ("/", "/login"):
                self._send(200, LOGIN_PAGE, "text/html; charset=utf-8")
            elif self.command == "HEAD":
                self._send(200, b"", "text/html; charset=utf-8")
            else:
                self._send(401, DENIED, "application/json")

        def _send(self, code: int, payload: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)

        do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = do_OPTIONS = do_PATCH = _handle

    return Handler


class HttpHoneypot:
    def __init__(self, host: str, port: int, **handler_kwargs: Any) -> None:
        self.server = ThreadingHTTPServer((host, port), make_handler(**handler_kwargs))
        self.server.daemon_threads = True
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self.server.server_address[1]

    def start(self) -> HttpHoneypot:
        self._thread = threading.Thread(target=self.server.serve_forever, name="http-honeypot", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
