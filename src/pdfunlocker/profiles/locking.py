"""Reentrant cross-process lock for one PDF Unlocker profile database."""
from __future__ import annotations

import errno
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

_registry_guard = threading.Lock()
_registry: dict[str, threading.RLock] = {}
_thread_state = threading.local()


def _thread_lock(key: str) -> threading.RLock:
    with _registry_guard:
        lock = _registry.get(key)
        if lock is None:
            lock = threading.RLock()
            _registry[key] = lock
        return lock


@contextmanager
def profile_store_lock(database_path: str | Path):
    """Exclusively coordinate threads and processes using one profile database.

    The lock is reentrant within a thread, allowing store helpers to call other
    store helpers safely. A persistent sidecar file provides process exclusion.
    """
    database = Path(database_path).expanduser().resolve()
    lock_path = database.with_name(database.name + ".lock")
    key = str(lock_path)
    thread_lock = _thread_lock(key)
    thread_lock.acquire()
    held = getattr(_thread_state, "held", None)
    if held is None:
        held = {}
        _thread_state.held = held

    if key in held:
        held[key] += 1
        try:
            yield
        finally:
            held[key] -= 1
            thread_lock.release()
        return

    fd = -1
    locked = False
    windows_lock = False
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.chmod(lock_path, 0o600)
        except OSError:
            pass

        if os.name == "nt":
            import msvcrt

            windows_lock = True
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            while True:
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    locked = True
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EDEADLK, errno.EAGAIN):
                        raise
                    time.sleep(0.05)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
            locked = True

        held[key] = 1
        yield
    finally:
        held.pop(key, None)
        try:
            if fd >= 0:
                try:
                    if locked:
                        if windows_lock:
                            import msvcrt
                            os.lseek(fd, 0, os.SEEK_SET)
                            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)
        finally:
            thread_lock.release()
