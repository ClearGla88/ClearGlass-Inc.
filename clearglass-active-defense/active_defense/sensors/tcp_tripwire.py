"""TCP connection tripwire (standard library only).

Accepts a connection, records the peer address and port, and closes it at once.
It sends no banner and reads no bytes, so there is nothing to exploit. Repeat
connections from one source inside dedup_seconds are counted, not re-sent.

Observes: a completed TCP handshake to the listening port. Does not observe:
SYN-only scans, payloads, or the real client behind NAT or a proxy.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable

from .client import build_event


class TcpTripwire:
    def __init__(self, host: str, port: int, *, sink: Callable[[dict], None], sensor_id: str, environment: str,
                 scope: str, dedup_seconds: float = 60.0) -> None:
        self.sink = sink
        self.sensor_id = sensor_id
        self.environment = environment
        self.scope = scope
        self.dedup_seconds = dedup_seconds
        self.sock = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.sock.listen(64)
        self.sock.settimeout(0.2)
        self._last: dict[str, float] = {}
        self.suppressed: dict[str, int] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self.sock.getsockname()[1]

    def start(self) -> TcpTripwire:
        self._thread = threading.Thread(target=self._loop, name="tcp-tripwire", daemon=True)
        self._thread.start()
        return self

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, addr = self.sock.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            conn.close()  # no banner, no read
            src, sport = addr[0], addr[1]
            now = time.monotonic()
            if now - self._last.get(src, -1e9) < self.dedup_seconds:
                self.suppressed[src] = self.suppressed.get(src, 0) + 1
                continue
            self._last[src] = now
            repeats = self.suppressed.pop(src, 0)
            self.sink(build_event(
                sensor_id=self.sensor_id, category="tripwire.tcp.connect", environment=self.environment,
                scope=self.scope, severity="medium", src_ip=src, src_port=sport, dst_port=self.port,
                attributes={"suppressed_repeats": repeats},
            ))

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self.sock.close()
