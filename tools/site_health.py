#!/usr/bin/env python3
"""Check that the public ClearGlass site answers correctly.

Read-only: the checker sends GET requests to the pages it is given and opens a
TLS connection to read the certificate. It writes nothing anywhere except the
optional JSON report.

Checks, per page:
  - the final status matches what is expected (200, or 404 for the probe);
  - redirects stay on the same host and never downgrade from https to http
    (an off-host redirect is refused before any request leaves for that host);
  - HTML pages are served as text/html and contain a <title>;
  - the body stays under a size cap.
Site-wide:
  - a path that cannot exist returns 404, so a broken custom domain or a
    catch-all rewrite does not report healthy;
  - the TLS certificate is valid and has at least --min-cert-days left.

Network failures, timeouts, 429, and 5xx are retried a bounded number of
times with exponential backoff. Other 4xx answers are not retried.

Exit status: 0 when every check passes, 1 when any check fails, 2 on a usage
error. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

DEFAULT_BASE_URL = "https://www.clearglassinc.com"
# The pages README.md lists under "Live Platform"; each exists in this tree.
DEFAULT_PATHS: tuple[str, ...] = (
    "/",
    "/products.html",
    "/store.html",
    "/intelligence-platform.html",
    "/data-fabric.html",
    "/Ontario-osint.html",
)
NOT_FOUND_PROBE = "/__site-health-probe-404"
USER_AGENT = "clearglass-site-health/1.0 (+read-only uptime check)"
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class OffHostRedirect(urllib.error.URLError):
    """Raised instead of following a redirect that leaves the checked host."""


class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects only within the original host, never https -> http."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        old = urllib.parse.urlsplit(req.full_url)
        new = urllib.parse.urlsplit(urllib.parse.urljoin(req.full_url, newurl))
        if new.hostname != old.hostname:
            raise OffHostRedirect(f"redirect to another host refused: {new.geturl()}")
        if old.scheme == "https" and new.scheme != "https":
            raise OffHostRedirect(f"redirect downgrades to {new.scheme}: {new.geturl()}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass
class PageResult:
    path: str
    url: str
    ok: bool
    expected_status: int
    status: int | None = None
    final_url: str | None = None
    content_type: str | None = None
    elapsed_ms: int | None = None
    attempts: int = 0
    problems: list[str] = field(default_factory=list)


@dataclass
class CertResult:
    host: str
    ok: bool
    not_after: str | None = None
    days_left: int | None = None
    problem: str | None = None


def build_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_SameHostRedirect())


def _looks_like_html(path: str) -> bool:
    last = path.rsplit("/", 1)[-1]
    return last == "" or last.endswith((".html", ".htm"))


def _fetch_once(
    opener: urllib.request.OpenerDirector, url: str, timeout: float, max_bytes: int
) -> tuple[int, str, str, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    try:
        response = opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        body = error.read(max_bytes + 1) if error.fp else b""
        content_type = error.headers.get("Content-Type", "") if error.headers else ""
        final_url = error.geturl() or url
        error.close()
        return error.code, final_url, content_type, body
    with response:
        body = response.read(max_bytes + 1)
        return (
            response.status,
            response.geturl(),
            response.headers.get("Content-Type", ""),
            body,
        )


def check_page(
    base_url: str,
    path: str,
    *,
    expected_status: int = 200,
    timeout: float = 10.0,
    retries: int = 2,
    backoff: float = 2.0,
    max_bytes: int = 5 * 1024 * 1024,
    opener: urllib.request.OpenerDirector | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> PageResult:
    """Fetch one page and judge it. Never raises for network or HTTP errors."""
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    result = PageResult(path=path, url=url, ok=False, expected_status=expected_status)
    opener = opener or build_opener()

    for attempt in range(retries + 1):
        result.attempts = attempt + 1
        started = time.monotonic()
        try:
            status, final_url, content_type, body = _fetch_once(opener, url, timeout, max_bytes)
        except OffHostRedirect as error:
            result.problems = [str(error.reason)]
            return result  # a policy failure; retrying cannot change it
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as error:
            reason = getattr(error, "reason", error)
            result.problems = [f"request failed: {reason}"]
            if attempt < retries:
                sleep(backoff * (2**attempt))
            continue
        result.elapsed_ms = int((time.monotonic() - started) * 1000)
        result.status, result.final_url, result.content_type = status, final_url, content_type

        if status in RETRYABLE_STATUS and status != expected_status and attempt < retries:
            result.problems = [f"status {status}; retrying"]
            sleep(backoff * (2**attempt))
            continue

        problems: list[str] = []
        if status != expected_status:
            problems.append(f"expected status {expected_status}, got {status}")
        if len(body) > max_bytes:
            problems.append(f"body exceeds {max_bytes} bytes")
        if expected_status == 200 and _looks_like_html(path):
            if not content_type.lower().startswith("text/html"):
                problems.append(f"expected text/html, got {content_type or 'no Content-Type'}")
            if b"<title" not in body[:max_bytes].lower():
                problems.append("no <title> element in the page")
        result.problems = problems
        result.ok = not problems
        return result

    return result


def check_certificate(
    host: str, *, port: int = 443, timeout: float = 10.0, min_days: int = 14,
    now: datetime | None = None,
) -> CertResult:
    """Validate the TLS chain and hostname, then check days until expiry."""
    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                cert = tls.getpeercert()
    except (OSError, ssl.SSLError) as error:
        return CertResult(host=host, ok=False, problem=f"TLS check failed: {error}")
    return judge_certificate(host, cert or {}, min_days=min_days, now=now)


def judge_certificate(
    host: str, cert: dict, *, min_days: int, now: datetime | None = None
) -> CertResult:
    not_after = cert.get("notAfter")
    if not not_after:
        return CertResult(host=host, ok=False, problem="certificate has no notAfter field")
    expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), tz=timezone.utc)
    now = now or datetime.now(timezone.utc)
    days_left = (expires - now).days
    result = CertResult(host=host, ok=days_left >= min_days, not_after=not_after,
                        days_left=days_left)
    if not result.ok:
        result.problem = f"certificate expires in {days_left} day(s); minimum is {min_days}"
    return result


def run(
    base_url: str,
    paths: Sequence[str],
    *,
    timeout: float,
    retries: int,
    backoff: float,
    min_cert_days: int,
    probe_404: bool,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    opener = build_opener()
    pages = [
        check_page(base_url, p, timeout=timeout, retries=retries, backoff=backoff,
                   opener=opener, sleep=sleep)
        for p in paths
    ]
    if probe_404:
        pages.append(check_page(base_url, NOT_FOUND_PROBE, expected_status=404,
                                timeout=timeout, retries=retries, backoff=backoff,
                                opener=opener, sleep=sleep))
    split = urllib.parse.urlsplit(base_url)
    cert = None
    if split.scheme == "https" and min_cert_days > 0:
        cert = check_certificate(split.hostname or "", port=split.port or 443,
                                 timeout=timeout, min_days=min_cert_days)
    ok = all(p.ok for p in pages) and (cert is None or cert.ok)
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base_url": base_url,
        "ok": ok,
        "pages": [asdict(p) for p in pages],
        "certificate": asdict(cert) if cert else None,
    }


def render(report: dict) -> str:
    lines = [f"site-health: {report['base_url']} -> {'PASS' if report['ok'] else 'FAIL'}"]
    for page in report["pages"]:
        mark = "PASS" if page["ok"] else "FAIL"
        detail = "; ".join(page["problems"]) or f"{page['status']} in {page['elapsed_ms']} ms"
        lines.append(f"  {mark} {page['path']} (attempts {page['attempts']}): {detail}")
    cert = report["certificate"]
    if cert:
        mark = "PASS" if cert["ok"] else "FAIL"
        detail = cert["problem"] or f"{cert['days_left']} days left (notAfter {cert['not_after']})"
        lines.append(f"  {mark} TLS certificate for {cert['host']}: {detail}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--path", action="append", dest="paths",
                        help="page path to check (repeatable; default: the Live Platform pages)")
    parser.add_argument("--timeout", type=float, default=10.0, help="seconds per request")
    parser.add_argument("--retries", type=int, default=2, help="retries per page (0-5)")
    parser.add_argument("--backoff", type=float, default=2.0, help="first retry delay, seconds")
    parser.add_argument("--min-cert-days", type=int, default=14,
                        help="minimum days of certificate validity; 0 skips the TLS check")
    parser.add_argument("--no-404-probe", action="store_true",
                        help="skip the check that an unknown path returns 404")
    parser.add_argument("--json", dest="json_path", help="also write the report to this file")
    parser.add_argument("--allow-http", action="store_true",
                        help="accept an http:// base URL (local testing only)")
    args = parser.parse_args(argv)

    split = urllib.parse.urlsplit(args.base_url)
    if split.scheme not in ("https", "http") or not split.hostname:
        parser.error("--base-url must be an absolute http(s) URL")
    if split.scheme == "http" and not args.allow_http:
        parser.error("--base-url must use https (pass --allow-http for local testing)")
    if not 0 <= args.retries <= 5:
        parser.error("--retries must be between 0 and 5")
    if not 0 < args.timeout <= 60:
        parser.error("--timeout must be greater than 0 and at most 60")

    report = run(
        args.base_url, args.paths or list(DEFAULT_PATHS), timeout=args.timeout,
        retries=args.retries, backoff=args.backoff, min_cert_days=args.min_cert_days,
        probe_404=not args.no_404_probe,
    )
    print(render(report))
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
            handle.write("\n")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
