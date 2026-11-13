"""A single pipe reader thread, supported by native Windows and POSIX."""
import queue
import threading


class LineReader:
    def __init__(self, stream):
        self.stream = stream
        self.lines = queue.Queue()
        self.thread = threading.Thread(target=self._read, name='crystal-ball-lines', daemon=True)
        self.thread.start()

    def _read(self):
        try:
            for line in self.stream:
                self.lines.put(line)
        except BaseException as exc:
            self.lines.put(exc)
        finally:
            self.lines.put(None)

    def get(self, timeout):
        try:
            line = self.lines.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError('hear worker timed out') from exc
        if isinstance(line, BaseException):
            raise line
        if line is None:
            raise EOFError('hear worker exited without a complete response')
        if not line.endswith('\n'):
            raise ValueError('truncated hear response')
        return line

    def close(self):
        self.thread.join(timeout=3)
        if self.thread.is_alive():
            raise RuntimeError('hear reader did not stop after owned tree cleanup')
