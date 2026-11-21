"""Honeyfile watcher.

On Linux it uses inotify (through ctypes) and reports opens, reads,
modifications, attribute changes, moves and deletion of each decoy file.
Elsewhere it falls back to polling and reports only modification and
deletion: it cannot see a read. ``capabilities()`` says which applies, and
each event carries it, so nothing claims an open was detectable when it was not.

Limits on Linux: inotify does not say which process or user touched the file
(that needs auditd or fanotify, not implemented here); it does not see access
from another machine over a network filesystem; backup, antivirus and desktop
indexers open files too, so expect benign hits; and root can remove the watch.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import select
import struct
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .. import honeytokens
from .client import build_event

IN_ACCESS, IN_MODIFY, IN_ATTRIB, IN_CLOSE_WRITE = 0x1, 0x2, 0x4, 0x8
IN_OPEN, IN_DELETE_SELF, IN_MOVE_SELF, IN_IGNORED = 0x20, 0x400, 0x800, 0x8000
WATCH_MASK = IN_ACCESS | IN_MODIFY | IN_ATTRIB | IN_CLOSE_WRITE | IN_OPEN | IN_DELETE_SELF | IN_MOVE_SELF
ACCESS_BITS = IN_ACCESS | IN_OPEN
_EVENT = struct.Struct("iIII")


def create_honeyfile(path: str | Path, *, endpoint_host: str = "portal.internal.example") -> str:
    """Write a decoy credentials file holding a fresh honeytoken. Returns the token
    so the caller can register its fingerprint. The token unlocks nothing."""
    token = honeytokens.mint()
    content = (
        "[service-account]\n"
        f"endpoint = https://{endpoint_host}/api\n"
        "user = svc-reporting\n"
        f"api_key = {token}\n"
    )
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    return token


def _libc():
    if not sys.platform.startswith("linux"):
        return None
    name = ctypes.util.find_library("c") or "libc.so.6"
    try:
        lib = ctypes.CDLL(name, use_errno=True)
        lib.inotify_init1  # noqa: B018 - presence check
        return lib
    except (OSError, AttributeError):
        return None


class HoneyfileWatcher:
    def __init__(self, paths: list[str | Path], *, sink: Callable[[dict], None], sensor_id: str, environment: str,
                 scope: str, coalesce_seconds: float = 5.0, poll_seconds: float = 1.0) -> None:
        self.paths = [Path(p).resolve() for p in paths]
        for p in self.paths:
            if not p.is_file():
                raise FileNotFoundError(f"honeyfile {p} does not exist")
        self.sink = sink
        self.sensor_id = sensor_id
        self.environment = environment
        self.scope = scope
        self.coalesce = coalesce_seconds
        self.poll_seconds = poll_seconds
        self._lib = _libc()
        self._fd = -1
        self._wd: dict[int, Path] = {}
        self._last: dict[tuple[Path, str], float] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def capabilities(self) -> dict[str, bool | str]:
        native = self._lib is not None
        return {"mechanism": "inotify" if native else "polling", "open_or_read": native, "modify": True,
                "delete_or_move": True, "actor_identity": False}

    def start(self) -> HoneyfileWatcher:
        if self._lib is not None:
            self._fd = self._lib.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
            if self._fd < 0:
                self._lib = None
            else:
                for p in self.paths:
                    wd = self._lib.inotify_add_watch(self._fd, str(p).encode(), WATCH_MASK)
                    if wd < 0:
                        raise OSError(ctypes.get_errno(), f"inotify_add_watch failed for {p}")
                    self._wd[wd] = p
        target = self._inotify_loop if self._lib is not None else self._poll_loop
        self._thread = threading.Thread(target=target, name="honeyfile", daemon=True)
        self._thread.start()
        return self

    def _emit(self, path: Path, kind: str, detail: str) -> None:
        now = time.monotonic()
        if now - self._last.get((path, kind), -1e9) < self.coalesce:
            return
        self._last[(path, kind)] = now
        category = "honeyfile.access" if kind == "access" else "honeyfile.modify"
        self.sink(build_event(
            sensor_id=self.sensor_id, category=category, environment=self.environment, scope=self.scope,
            severity="high", attributes={"file_name": path.name[:128], "change": detail[:64],
                                         "mechanism": self.capabilities()["mechanism"]},
        ))

    def _inotify_loop(self) -> None:
        while not self._stop.is_set():
            ready, _, _ = select.select([self._fd], [], [], 0.2)
            if not ready:
                continue
            try:
                buf = os.read(self._fd, 64 * 1024)
            except BlockingIOError:
                continue
            offset = 0
            while offset + _EVENT.size <= len(buf):
                wd, mask, _cookie, length = _EVENT.unpack_from(buf, offset)
                offset += _EVENT.size + length
                path = self._wd.get(wd)
                if path is None or mask & IN_IGNORED:
                    continue
                if mask & ACCESS_BITS:
                    self._emit(path, "access", "opened" if mask & IN_OPEN else "read")
                if mask & (IN_MODIFY | IN_CLOSE_WRITE | IN_ATTRIB):
                    self._emit(path, "modify", "modified" if mask & (IN_MODIFY | IN_CLOSE_WRITE) else "attributes")
                if mask & (IN_DELETE_SELF | IN_MOVE_SELF):
                    self._emit(path, "modify", "deleted" if mask & IN_DELETE_SELF else "moved")

    def _poll_loop(self) -> None:
        def snap(p: Path):
            try:
                st = p.stat()
                return (st.st_ino, st.st_size, st.st_mtime_ns)
            except FileNotFoundError:
                return None
        state = {p: snap(p) for p in self.paths}
        while not self._stop.wait(self.poll_seconds):
            for p in self.paths:
                cur = snap(p)
                if cur != state[p]:
                    self._emit(p, "modify", "deleted" if cur is None else "modified")
                    state[p] = cur

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1
