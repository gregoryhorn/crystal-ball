"""POSIX owned session termination; never target process names."""
import os
import signal


def terminate(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
