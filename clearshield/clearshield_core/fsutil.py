"""Filesystem primitives: private directories, atomic writes, safe reads, locking.

Every file ClearShield writes lives in a directory owned by the effective user
with mode 0700. Writes go to a temporary file in the same directory, are
fsync'd, then renamed over the target, so an interrupted write leaves either the
old file or the new file, never a partial one.
"""

from __future__ import annotations

import errno
import fcntl
import os
import stat
import tempfile

from .errors import ClearShieldError, ConfigError, InsecurePermissions

_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)


def _describe_mode(mode: int) -> str:
    return format(stat.S_IMODE(mode), "04o")


def make_private_dir(path: str) -> None:
    """Create ``path`` (mode 0700) if it does not exist, then check it."""
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    else:
        os.chmod(path, 0o700)  # mkdir mode is filtered by umask
    check_private_dir(path)


def check_private_dir(path: str) -> None:
    """Fail unless ``path`` is a real directory, owned by us, with no group/other bits."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise ConfigError(f"{path} does not exist. Run 'clearshield.py init' first.") from None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise InsecurePermissions(f"{path} must be a directory, not a symlink or file.")
    if st.st_uid != os.geteuid():
        raise InsecurePermissions(
            f"{path} is owned by uid {st.st_uid}, not the current user (uid {os.geteuid()})."
        )
    if st.st_mode & 0o077:
        raise InsecurePermissions(
            f"{path} has mode {_describe_mode(st.st_mode)}; group/other access is not allowed. "
            f"Fix with: chmod 700 {path}"
        )


def check_private_file_stat(path: str, st: os.stat_result) -> None:
    if not stat.S_ISREG(st.st_mode):
        raise InsecurePermissions(f"{path} is not a regular file.")
    if st.st_uid != os.geteuid():
        raise InsecurePermissions(f"{path} is owned by uid {st.st_uid}, not uid {os.geteuid()}.")
    if st.st_mode & 0o077:
        raise InsecurePermissions(
            f"{path} has mode {_describe_mode(st.st_mode)}; it must not be accessible to "
            f"group/other. Fix with: chmod 600 {path}"
        )


def read_private_file(path: str, max_bytes: int) -> bytes:
    """Read a ClearShield-owned file without following symlinks, with a size cap."""
    try:
        fd = os.open(path, os.O_RDONLY | _O_NOFOLLOW | _O_CLOEXEC)
    except FileNotFoundError:
        raise
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise InsecurePermissions(f"{path} is a symlink; refusing to follow it.") from None
        raise ClearShieldError(f"cannot open {path}: {exc.strerror}") from None
    try:
        check_private_file_stat(path, os.fstat(fd))
        chunks = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(fd, min(remaining, 1 << 20))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
    finally:
        os.close(fd)
    if len(data) > max_bytes:
        raise ClearShieldError(f"{path} exceeds the {max_bytes}-byte limit.")
    return data


def fsync_dir(path: str) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path: str, data: bytes, mode: int = 0o600) -> None:
    """Replace ``path`` with ``data`` atomically (same-directory temp file + rename)."""
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".clearshield-", suffix=".partial")
    tmp_path: str | None = tmp
    try:
        with os.fdopen(fd, "wb") as fh:
            os.fchmod(fh.fileno(), mode)
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        tmp_path = None
        fsync_dir(directory)
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass


def create_exclusive(path: str, data: bytes, mode: int = 0o600) -> None:
    """Create a new file; fail if anything already exists at ``path``."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW | _O_CLOEXEC, mode)
    try:
        os.fchmod(fd, mode)
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    fsync_dir(os.path.dirname(os.path.abspath(path)))


def append_line(path: str, line: bytes) -> None:
    """Append one complete line with O_APPEND and fsync it."""
    fd = os.open(
        path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | _O_NOFOLLOW | _O_CLOEXEC, 0o600
    )
    try:
        check_private_file_stat(path, os.fstat(fd))
        view = memoryview(line)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


class StateLock:
    """Exclusive, non-blocking advisory lock on ``<state_dir>/.lock``.

    Prevents two ClearShield commands from interleaving writes to the same
    state directory. It does not stop a process that ignores the lock.
    """

    def __init__(self, state_dir: str) -> None:
        self.path = os.path.join(state_dir, ".lock")
        self.fd: int | None = None

    def __enter__(self) -> "StateLock":
        self.fd = os.open(
            self.path, os.O_RDWR | os.O_CREAT | _O_NOFOLLOW | _O_CLOEXEC, 0o600
        )
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.fd)
            self.fd = None
            raise ClearShieldError(
                "another ClearShield command is using this state directory; try again."
            ) from None
        return self

    def __exit__(self, *exc: object) -> None:
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None
