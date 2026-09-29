"""Private files that GridLens writes the same way on Linux and Windows.

Sessions, audits, job records, and reviewed scripts are files only their user
may read, written without following a symlink that someone else planted.
POSIX provides both through `os.open` flags. Windows has no `O_NOFOLLOW`, and
`os.open` there returns a text-mode descriptor that rewrites line endings, so
the bytes on disk would no longer match a hash recorded for them. The
functions here give both platforms one behavior: owner-only permissions where
the platform has them, no symlinks, and the exact bytes written.

`FileLock` serializes GridLens processes through a lock file, and `replace`
moves a finished file into place, retrying while a reader on Windows still
has the old one open.
"""
from __future__ import annotations

import errno
import os
from pathlib import Path
import stat
import time
from typing import IO

if os.name == "nt":
    import msvcrt
else:
    import fcntl


PRIVATE_MODE = 0o600
_BINARY = getattr(os, "O_BINARY", 0)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
# The reparse points that redirect a path, as a symlink does: symbolic
# links (IO_REPARSE_TAG_SYMLINK) and junctions (IO_REPARSE_TAG_MOUNT_POINT).
# Other reparse points, such as OneDrive placeholders, hold ordinary files.
_LINK_REPARSE_TAGS = frozenset({0xA000000C, 0xA0000003})
_OPEN_FLAGS = {
    "x": os.O_WRONLY | os.O_CREAT | os.O_EXCL,
    "w": os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
    "a": os.O_WRONLY | os.O_CREAT | os.O_APPEND,
    "a+": os.O_RDWR | os.O_CREAT | os.O_APPEND,
}
# The mode of the file object for each way of opening. A new file ("x") is
# opened for writing like "w"; O_EXCL has already made it new.
_OBJECT_MODES = {"x": "w", "w": "w", "a": "a", "a+": "a+"}
# Replacing a file that a reader holds open fails on Windows, so the move is
# retried there; elsewhere it succeeds or fails at once.
_REPLACE_ATTEMPTS = 8 if os.name == "nt" else 1
_REPLACE_FIRST_DELAY_SECONDS = 0.01
_LOCK_POLL_SECONDS = 0.05


def is_link(path: str | Path) -> bool:
    """Return True when path is a symbolic link or a Windows junction."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    return getattr(info, "st_reparse_tag", 0) in _LINK_REPARSE_TAGS


def open_descriptor(path: str | Path, flags: int,
                    mode: int = PRIVATE_MODE) -> int:
    """Open path with os.open in binary mode, refusing a symlink at path.

    Raises OSError with errno ELOOP when path is a symlink or a junction.
    """
    flags |= _BINARY
    if _NOFOLLOW:
        return os.open(path, flags | _NOFOLLOW, mode)
    if is_link(path):
        raise OSError(errno.ELOOP, "Refusing to open a link", str(path))
    return os.open(path, flags, mode)


def open_private(path: str | Path, mode: str = "x", *,
                 binary: bool = False) -> IO:
    """Open a file that only this user may read, without following a symlink.

    mode is "x" to create a new file, "w" to create or truncate one, "a" to
    append, or "a+" to append and read. Text files are UTF-8 and keep the
    line endings they are given, so a file has the same bytes on every
    platform.
    """
    descriptor = open_descriptor(path, _OPEN_FLAGS[mode])
    object_mode = _OBJECT_MODES[mode]
    if binary:
        return os.fdopen(descriptor, object_mode + "b")
    return os.fdopen(descriptor, object_mode, encoding="utf-8", newline="")


def replace(source: str | Path, target: str | Path) -> None:
    """Move source over target in one step, as os.replace does.

    On Windows, replacing a file fails while another process has it open,
    as a GridLens reader briefly may, so the move is retried for up to about
    a second before the error is raised.
    """
    delay = _REPLACE_FIRST_DELAY_SECONDS
    for attempt in range(1, _REPLACE_ATTEMPTS + 1):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS:
                raise
            time.sleep(delay)
            delay *= 2


class FileLock:
    """An exclusive lock that GridLens processes of one user share.

    The lock is held on a separate lock file rather than on the data it
    protects, because a Windows lock also blocks other processes from
    reading the locked bytes. The operating system releases the lock when
    its holder exits, however it exits.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._descriptor: int | None = None

    def acquire(self, *, blocking: bool = True) -> bool:
        """Take the lock; return False if blocking is False and it is held."""
        descriptor = open_descriptor(self.path, os.O_RDWR | os.O_CREAT)
        try:
            locked = _lock(descriptor, blocking)
        except BaseException:
            os.close(descriptor)
            raise
        if not locked:
            os.close(descriptor)
            return False
        self._descriptor = descriptor
        return True

    def release(self) -> None:
        """Release the lock if this object holds it."""
        if self._descriptor is None:
            return
        descriptor, self._descriptor = self._descriptor, None
        try:
            _unlock(descriptor)
        finally:
            os.close(descriptor)

    def __enter__(self) -> FileLock:
        self.acquire()
        return self

    def __exit__(self, *exception: object) -> None:
        self.release()


def _lock(descriptor: int, blocking: bool) -> bool:
    """Lock an open lock file, waiting for it only when blocking is True."""
    if os.name != "nt":
        operation = fcntl.LOCK_EX
        if not blocking:
            operation |= fcntl.LOCK_NB
        try:
            fcntl.flock(descriptor, operation)
        except BlockingIOError:
            return False
        return True
    # msvcrt.LK_LOCK gives up after ten seconds, so a blocking lock polls
    # the non-blocking one instead. The first byte stands for the file.
    while True:
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError:
            if not blocking:
                return False
            time.sleep(_LOCK_POLL_SECONDS)
        else:
            return True


def _unlock(descriptor: int) -> None:
    """Unlock an open lock file."""
    if os.name != "nt":
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return
    os.lseek(descriptor, 0, os.SEEK_SET)
    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
