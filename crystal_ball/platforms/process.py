"""Owned process trees with bounded cleanup and binary/text transports."""
import contextlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid
from .executables import media_argv, resolve_tool

# In a foreign engine this inherited value still identifies the core interpreter.
CORE_PYTHON = os.environ.get('CRYSTAL_BALL_CORE_PYTHON', sys.executable)


class OwnedProcess:
    def __init__(self, proc, job=None, group=True):
        self.proc, self.job, self.closed, self.group = proc, job, False, group

    def __getattr__(self, name):
        return getattr(self.proc, name)

    def terminate_tree(self, reason='cancelled'):
        if self.job:
            self.job.terminate()
        elif self.group:
            from .posix import terminate
            terminate(self.proc.pid)
        elif self.proc.poll() is None:
            # Nested POSIX work remains in the outer stage session. Its owner
            # tears down all descendants on return/error; do not kill our parent.
            self.proc.kill()
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f'owned process cleanup timed out ({reason})') from exc

    def communicate(self, input=None, timeout=None):
        try:
            return self.proc.communicate(input=input, timeout=timeout)
        except BaseException:
            self.terminate_tree('communication interrupted')
            # No indefinite drain if an OS termination failed or an escaped pipe exists.
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.proc.communicate(timeout=3)
            raise

    def wait(self, timeout=None):
        try:
            return self.proc.wait(timeout=timeout)
        except BaseException:
            self.terminate_tree('wait interrupted')
            raise

    def kill(self):
        self.terminate_tree()

    def close(self):
        if self.closed:
            return
        try:
            # Clean descendants even when the direct child has already exited.
            self.terminate_tree('close')
        finally:
            if self.job:
                # Closing the final non-inherited handle is a second OS-backed
                # termination path. Never block closing a pipe held by a live reader.
                self.job.close()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    self.proc.wait(timeout=3)
            for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
                if stream and self.proc.poll() is not None:
                    with contextlib.suppress(OSError):
                        stream.close()
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def spawn_owned(argv, env=None, stdin=None, stdout=None, stderr=None, **kwargs):
    if kwargs.pop('shell', False):
        raise ValueError('owned processes require argv with shell=False')
    kwargs.pop('start_new_session', None)
    argv = [str(x) for x in argv]
    env = dict(os.environ if env is None else env)
    env['CRYSTAL_BALL_CORE_PYTHON'] = CORE_PYTHON
    env['PYTHONIOENCODING'] = 'utf-8'
    if kwargs.get('text') or kwargs.get('universal_newlines'):
        kwargs.setdefault('encoding', 'utf-8')
    job = None
    ready = None
    isolate = os.name != 'nt' and not os.environ.get('CRYSTAL_BALL_OWNED_SCOPE')
    if os.name != 'nt':
        env['CRYSTAL_BALL_OWNED_SCOPE'] = '1'
    try:
        argv[0] = resolve_tool(argv[0], env)
        if os.name == 'nt':
            from .windows.jobs import Job
            name = 'CrystalBall-' + uuid.uuid4().hex
            job = Job(name)
            fd, ready = tempfile.mkstemp(prefix='cb-owned-')
            os.close(fd)
            argv = [CORE_PYTHON, str(Path(__file__).parent/'windows/launcher.py'), name, ready, *argv]
        proc = subprocess.Popen(argv, env=env, stdin=stdin, stdout=stdout, stderr=stderr,
                                shell=False, start_new_session=isolate, **kwargs)
        owned = OwnedProcess(proc, job, isolate)
        if ready:
            deadline = time.monotonic()+10
            while not Path(ready).stat().st_size:
                if proc.poll() is not None or time.monotonic() >= deadline:
                    owned.close()
                    raise OSError('Windows job assignment failed; target not available (launcher stderr contains diagnostics)')
                time.sleep(.01)
        return owned
    except (OSError, ValueError) as exc:
        if job:
            job.close()
        from ..util import StageError, error_result
        failure=error_result(exc,'process')
        raise StageError('process', exc, failure['log']) from exc
    finally:
        if ready:
            Path(ready).unlink(missing_ok=True)


def run_owned(argv, input=None, capture_output=False, timeout=None, check=False, **kwargs):
    if capture_output:
        kwargs['stdout'] = kwargs['stderr'] = subprocess.PIPE
    if input is not None:
        kwargs['stdin'] = subprocess.PIPE
    with spawn_owned(argv, **kwargs) as proc:
        out, err = proc.communicate(input, timeout)
        result = subprocess.CompletedProcess(argv, proc.returncode, out, err)
        if check:
            result.check_returncode()
        return result
