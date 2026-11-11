"""One-shot JSON protocol for separately installed, offline engine runtimes."""
import contextlib
import json
import os
import signal
import subprocess
from pathlib import Path
from .cache import dumps
from .util import engine_python_env, StageError

def see_request(operation, payload, config=None, timeout=300):
    """Image/array work belongs to the configured see runtime, without loading CLIP."""
    from .config import load
    cfg=config or load()
    return request(cfg['see']['python'],'crystal_ball.stage_worker',
                   {'operation':operation,'request':{**payload,'config':cfg}},timeout)


def request(python, module, payload, timeout=300):
    env=engine_python_env(python,{'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','NUMBA_NUM_THREADS':'1','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'})
    proc=subprocess.Popen([python,'-m',module],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env,start_new_session=not bool(os.environ.get('CRYSTAL_BALL_STAGE')))
    try:
        out,err=proc.communicate(dumps(payload),timeout=timeout)
    except BaseException:
        with contextlib.suppress(ProcessLookupError):
            (os.kill if os.environ.get('CRYSTAL_BALL_STAGE') else os.killpg)(proc.pid,signal.SIGKILL)
        proc.communicate(); raise
    if proc.returncode:
        raise StageError(module, err or out or f'exit {proc.returncode}')
    value=json.loads(out)
    if not isinstance(value,dict) or 'error' in value:
        raise ValueError('invalid worker response')
    return value
