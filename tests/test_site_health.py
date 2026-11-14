"""Tests for tools/site_health.py against a real local HTTP server."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tools import site_health

HTML = b"<!doctype html><html><head><title>ClearGlass</title></head><body>ok</body></html>"


class _Handler(BaseHTTPRequestHandler):
    state: dict = {}

    def log_message(self, *args) -> None:  # keep test output quiet
        pass

    def _send(self, status: int, body: bytes = b"", content_type: str = "text/html",
              headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        hits = self.state.setdefault("hits", {})
        hits[self.path] = hits.get(self.path, 0) + 1
        if self.path in ("/", "/ok.html"):
            self._send(200, HTML)
        elif self.path == "/notitle.html":
            self._send(200, b"<html><body>no title here</body></html>")
        elif self.path == "/data.html":
            self._send(200, b'{"a": 1}', "application/json")
        elif self.path == "/flaky.html":
            if hits[self.path] <= 2:
                self._send(503, b"busy")
            else:
                self._send(200, HTML)
        elif self.path == "/always503.html":
            self._send(503, b"busy")
        elif self.path == "/slow.html":
            time.sleep(1.5)
            self._send(200, HTML)
        elif self.path == "/redirect-same.html":
            self._send(302, headers={"Location": "/ok.html"})
        elif self.path == "/redirect-off.html":
            self._send(302, headers={"Location": "http://example.invalid/"})
        elif self.path == "/big.html":
            self._send(200, HTML + b"x" * 4096)
        elif self.state.get("catch_all"):
            self._send(200, HTML)  # a soft-404 site: everything answers 200
        else:
            self._send(404, b"<html><head><title>Not found</title></head></html>")


@pytest.fixture
def server(monkeypatch):
    # The checker honours proxy settings; local requests must not use one.
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY",
                 "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    _Handler.state = {}
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", _Handler.state
    finally:
        httpd.shutdown()
        httpd.server_close()


def _no_sleep(delays: list[float]):
    return delays.append


def test_healthy_page_passes(server):
    base, _ = server
    result = site_health.check_page(base, "/", sleep=_no_sleep([]))
    assert result.ok, result.problems
    assert result.status == 200 and result.attempts == 1
    assert result.elapsed_ms is not None


@pytest.mark.parametrize(
    ("path", "problem"),
    [
        ("/missing.html", "expected status 200, got 404"),
        ("/notitle.html", "no <title> element"),
        ("/data.html", "expected text/html, got application/json"),
    ],
)
def test_bad_pages_fail_with_a_reason(server, path, problem):
    base, _ = server
    result = site_health.check_page(base, path, retries=2, sleep=_no_sleep([]))
    assert not result.ok
    assert any(problem in p for p in result.problems), result.problems


def test_client_errors_are_not_retried(server):
    base, state = server
    result = site_health.check_page(base, "/missing.html", retries=3, sleep=_no_sleep([]))
    assert result.attempts == 1
    assert state["hits"]["/missing.html"] == 1


def test_transient_5xx_is_retried_with_exponential_backoff(server):
    base, state = server
    delays: list[float] = []
    result = site_health.check_page(base, "/flaky.html", retries=2, backoff=1.5,
                                    sleep=delays.append)
    assert result.ok, result.problems
    assert result.attempts == 3
    assert delays == [1.5, 3.0]
    assert state["hits"]["/flaky.html"] == 3


def test_retries_are_bounded(server):
    base, state = server
    delays: list[float] = []
    result = site_health.check_page(base, "/always503.html", retries=2, sleep=delays.append)
    assert not result.ok
    assert result.attempts == 3 and len(delays) == 2
    assert state["hits"]["/always503.html"] == 3
    assert "expected status 200, got 503" in result.problems


def test_timeout_fails_instead_of_hanging(server):
    base, _ = server
    started = time.monotonic()
    result = site_health.check_page(base, "/slow.html", timeout=0.3, retries=0,
                                    sleep=_no_sleep([]))
    assert not result.ok
    assert result.problems and result.problems[0].startswith("request failed")
    assert time.monotonic() - started < 1.4


def test_same_host_redirect_is_followed(server):
    base, _ = server
    result = site_health.check_page(base, "/redirect-same.html", sleep=_no_sleep([]))
    assert result.ok, result.problems
    assert result.final_url.endswith("/ok.html")


def test_off_host_redirect_is_refused_without_following_or_retrying(server):
    base, state = server
    result = site_health.check_page(base, "/redirect-off.html", retries=3, sleep=_no_sleep([]))
    assert not result.ok
    assert result.attempts == 1
    assert "another host" in result.problems[0]
    assert state["hits"]["/redirect-off.html"] == 1


def test_body_size_cap(server):
    base, _ = server
    result = site_health.check_page(base, "/big.html", max_bytes=1024, sleep=_no_sleep([]))
    assert not result.ok
    assert "body exceeds 1024 bytes" in result.problems


def test_not_found_probe_catches_a_soft_404_site(server):
    base, state = server
    healthy = site_health.check_page(base, site_health.NOT_FOUND_PROBE, expected_status=404,
                                     sleep=_no_sleep([]))
    assert healthy.ok, healthy.problems
    state["catch_all"] = True
    soft = site_health.check_page(base, site_health.NOT_FOUND_PROBE, expected_status=404,
                                  sleep=_no_sleep([]))
    assert not soft.ok
    assert "expected status 404, got 200" in soft.problems


def test_certificate_judgement():
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)
    fresh = site_health.judge_certificate(
        "example.test", {"notAfter": "Feb  1 00:00:00 2027 GMT"}, min_days=14, now=now)
    assert fresh.ok and fresh.days_left == 79  # 16 (Nov) + 31 + 31 + 1
    expiring = site_health.judge_certificate(
        "example.test", {"notAfter": "Nov 20 00:00:00 2026 GMT"}, min_days=14, now=now)
    assert not expiring.ok and "expires in 6 day(s)" in expiring.problem
    missing = site_health.judge_certificate("example.test", {}, min_days=14, now=now)
    assert not missing.ok


def test_cli_passes_and_writes_a_report(server, tmp_path, capsys):
    base, _ = server
    report_path = tmp_path / "health.json"
    code = site_health.main(["--base-url", base, "--allow-http", "--path", "/",
                             "--path", "/ok.html", "--json", str(report_path)])
    assert code == 0
    report = json.loads(report_path.read_text())
    assert report["ok"] is True
    assert [p["path"] for p in report["pages"]] == ["/", "/ok.html", site_health.NOT_FOUND_PROBE]
    assert report["certificate"] is None  # plain http: no TLS check
    assert "PASS" in capsys.readouterr().out


def test_cli_fails_when_any_page_fails(server):
    base, _ = server
    code = site_health.main(["--base-url", base, "--allow-http", "--retries", "0",
                             "--path", "/", "--path", "/missing.html"])
    assert code == 1


@pytest.mark.parametrize(
    "argv",
    [
        ["--base-url", "http://127.0.0.1:1"],  # http without --allow-http
        ["--base-url", "not-a-url"],
        ["--retries", "9"],
        ["--timeout", "0"],
    ],
)
def test_cli_rejects_bad_arguments(argv):
    with pytest.raises(SystemExit) as raised:
        site_health.main(argv)
    assert raised.value.code == 2
