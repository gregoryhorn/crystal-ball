"""Bounded advisory locks and Windows sharing-violation replacement retry."""
import contextlib
import errno
import os
import time
from pathlib import Path


@contextlib.contextmanager
def file_lock(directory, timeout=30):
    Path(directory).mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + min(30, max(0, timeout))
    with (Path(directory)/'.lock').open('a+b') as handle:
        if os.name == 'nt':
            import msvcrt
            def acquire():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            def release():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            def acquire():
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            def release():
                fcntl.flock(handle, fcntl.LOCK_UN)
        while True:
            try:
                acquire()
                break
            except OSError as exc:
                contention = (exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}) if os.name == 'nt' else exc.errno in {errno.EACCES, errno.EAGAIN}
                if not contention:
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError('artifact lock unavailable after bounded wait') from exc
                time.sleep(min(.05, max(0, deadline-time.monotonic())))
        try:
            yield
        finally:
            release()


def replace(source, destination, timeout=2):
    deadline = time.monotonic()+min(2, max(0, timeout))
    while True:
        try:
            os.replace(source, destination)
            return
        except OSError as exc:
            if os.name != 'nt' or getattr(exc, 'winerror', None) not in {32, 33} or time.monotonic() >= deadline:
                raise
            time.sleep(min(.05, max(0, deadline-time.monotonic())))
