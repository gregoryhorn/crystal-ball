"""One action dispatcher shared by CLI and Hermes."""
import os
import sys
from pathlib import Path
from .cache import atomic, dumps
from .config import load
from .util import process_json

def dispatch(action='check',**params):
    cfg=load()
    if action=='check':
        from .core import quality_check
        return quality_check(**params)
    if action=='transcribe':
        from .senses.hear import transcribe
        return transcribe(str(Path(params['file']).expanduser().resolve()),cfg)
    if action in {'find','index'}:
        import subprocess
        if action=='find' and bool(params.get('text'))==bool(params.get('image')):
            raise ValueError('provide text or image for find')
        if action=='index' and not params.get('paths'):
            raise ValueError('paths are required for index')
        req={'action':action,**params}
        env={**os.environ,'HF_HUB_OFFLINE':'1','PYTHONPATH':str(Path(__file__).resolve().parent.parent)+os.pathsep+os.environ.get('PYTHONPATH','')}
        proc=subprocess.Popen([cfg['see']['python'],'-m','crystal_ball.senses.see_worker'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env,start_new_session=True)
        import contextlib, signal, json
        try:
            out,err=proc.communicate(dumps(req),timeout=1800)
        except BaseException:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid,signal.SIGKILL)
            proc.communicate(); raise
        if proc.returncode:
            raise RuntimeError((err or out)[-400:])
        return json.loads(out)
    if action=='read_text':
        from .senses.read import read_text
        return read_text(params['file'],params.get('at'),cfg)
    if action=='doctor':
        from .doctor import doctor
        return doctor(cfg)
    if action=='fix':
        from .core import quality_check
        params['fix']=True
        return quality_check(**params)
    raise ValueError('unknown action')

def compact_action(action,result,config=None):
    """Keep full data in an artifact; bound every tool response in UTF-8 bytes."""
    import hashlib
    cfg=config or load()
    if action in {'check','fix'} and len(dumps(result).encode())<=1500:
        return result
    data=dumps(result)
    path=Path(cfg['cache_dir'])/'tool-results'/(hashlib.sha256(data.encode()).hexdigest()+'.json')
    atomic(path,data)
    summary={'action':action,'artifact':str(path)}
    if isinstance(result,dict):
        for key in ('verdict','status','report','counts','code'):
            if key in result:
                summary[key]=result[key]
        if action=='transcribe':
            summary.update(engine=result.get('engine'),segments=len(result.get('segments',[])))
        if action=='find':
            summary['matches']=result.get('matches',[])[:3]
        if action=='read_text':
            summary['lines']=result.get('lines',[])[:3]
        if action=='doctor':
            summary['counts']={s:sum(c['status']==s for c in result['checks']) for s in ('PASS','WARN','FAIL')}
    while len(dumps(summary).encode())>1500 and summary.get('matches'):
        summary['matches'].pop()
    while len(dumps(summary).encode())>1500 and summary.get('lines'):
        summary['lines'].pop()
    if len(dumps(summary).encode())>1500:
        summary={'action':action,'artifact':str(path),'details':'see artifact'}
    # Extreme configured paths can themselves exceed the context budget.
    if len(dumps(summary).encode())>1500:
        return {'action':action,'error':'configured artifact path exceeds compact output budget'}
    return summary
