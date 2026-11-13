"""Optional machine-local GPU authority; no CUDA telemetry or public host paths."""
import math


class Session:
    """Retain one auto-heartbeating lease until synchronous owned cleanup succeeds."""
    def __init__(self, required_gb=3.5, *, purpose, model, enabled=True):
        self.handle = None
        self.device = 'cpu'
        self.reason = None
        self.closed = False
        if not enabled:
            return
        try:
            from gpu_broker import acquire
            self.handle = acquire(profile='crystal-ball', purpose=purpose, model=model,
                                  expected_peak_mib=math.ceil(float(required_gb)*1024), wait=False)
        except Exception as exc:
            self.reason = f'GPU broker unavailable ({type(exc).__name__}); CPU selected'
        else:
            self.device = 'cuda'

    def close(self, cleanup):
        """Never release after failed cleanup/completion. Return a diagnostic if uncertain."""
        if self.closed or self.handle is None:
            return self.reason
        self.closed = True
        try:
            self.handle.complete_gpu_work(cleanup)
            self.handle.release()
        except Exception as exc:
            self.reason = f'GPU cleanup uncertain ({type(exc).__name__}); lease retained'
        finally:
            self.handle.stop_heartbeat()
        return self.reason


def admit(required_gb=3.5, torch=None):
    """Legacy tuple cannot own authority: callers must use Session for CUDA."""
    return 'cpu', 'Retained GPU session required; CPU selected'


def is_oom(exc):
    message=str(exc).lower()
    return 'out of memory' in message or 'cuda_error_out_of_memory' in message or 'cuda out of memory' in message
