"""Signed event client for sensors (standard library only).

A sensor holds one HMAC key and nothing else: no API token, no adapter
credential. If the API is unreachable, events are spooled to disk (mode 0600)
and re-sent later; the server deduplicates on (sensor_id, event_id).
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import signing


def build_event(
    *,
    sensor_id: str,
    category: str,
    environment: str,
    scope: str,
    severity: str = "medium",
    src_ip: str | None = None,
    src_port: int | None = None,
    dst_ip: str | None = None,
    dst_port: int | None = None,
    asset_id: str | None = None,
    attributes: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "schema_version": "1.0",
        "event_id": event_id or f"evt-{uuid.uuid4().hex}",
        "occurred_at": (occurred_at or datetime.now(UTC)).astimezone(UTC).isoformat(),
        "sensor_id": sensor_id,
        "category": category,
        "severity": severity,
        "environment": environment,
        "authorization_scope": scope,
        "attributes": attributes or {},
    }
    for name, value in (("src_ip", src_ip), ("src_port", src_port), ("dst_ip", dst_ip), ("dst_port", dst_port),
                        ("asset_id", asset_id)):
        if value is not None:
            event[name] = value
    return event


def encode(event: dict[str, Any]) -> bytes:
    return json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8")


class SignedClient:
    def __init__(self, api_url: str, sensor_id: str, key: bytes, *, timeout: float = 5.0,
                 spool_dir: str | Path | None = None) -> None:
        if urllib.parse.urlsplit(api_url).scheme not in ("http", "https"):
            raise ValueError("the ingestion API URL must use http or https")
        self.url = api_url.rstrip("/") + "/v1/events"
        self.sensor_id = sensor_id
        self.key = key
        self.timeout = timeout
        self.spool = Path(spool_dir) if spool_dir else None

    def send(self, event: dict[str, Any]) -> tuple[int, dict]:
        body = encode(event)
        headers = signing.signed_headers(self.key, self.sensor_id, body, unix_time=int(time.time()))
        req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")  # noqa: S310 - scheme checked
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 - operator-configured URL
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"{}")
        except (urllib.error.URLError, OSError) as exc:
            self._spool(event)
            return 0, {"status": "spooled", "reason": str(exc)}

    def _spool(self, event: dict[str, Any]) -> None:
        if self.spool is None:
            return
        self.spool.mkdir(parents=True, exist_ok=True)
        path = self.spool / f"{event['event_id']}.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(encode(event))

    def flush_spool(self) -> int:
        if self.spool is None or not self.spool.is_dir():
            return 0
        sent = 0
        for path in sorted(self.spool.glob("*.json")):
            status, _ = self.send(json.loads(path.read_bytes()))
            if status == 0:
                break
            path.unlink()
            sent += 1
        return sent


class AsyncSender:
    """Bounded background queue so a decoy never blocks its responder on the API.
    When the queue is full, events are dropped and counted."""

    def __init__(self, client: SignedClient, maxsize: int = 1000) -> None:
        self.client = client
        self.q: queue.Queue[dict] = queue.Queue(maxsize=maxsize)
        self.dropped = 0
        self.results: list[tuple[int, dict]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="event-sender", daemon=True)
        self._thread.start()

    def submit(self, event: dict[str, Any]) -> None:
        try:
            self.q.put_nowait(event)
        except queue.Full:
            self.dropped += 1

    def _run(self) -> None:
        while not (self._stop.is_set() and self.q.empty()):
            try:
                event = self.q.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self.results.append(self.client.send(event))
            finally:
                self.q.task_done()

    def drain(self) -> None:
        self.q.join()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
