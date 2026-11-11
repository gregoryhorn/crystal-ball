"""Configured CLIP interpreter entry point; JSON only on stdout."""
import contextlib
import io
import json
import sys
from types import SimpleNamespace
from pathlib import Path
from . import see
from ..config import load

def main():
    req=json.load(sys.stdin); cfg=load()
    see.CACHE=str(Path(cfg['cache_dir'])/'indexes')
    if req['action']=='index':
        args=SimpleNamespace(paths=req['paths'],model=cfg['see']['model'],every=2.,cap=60,mode='interval',shared=True)
        with contextlib.redirect_stdout(sys.stderr):
            code=see.cmd_index(args)
        result={'status':'indexed' if code==0 else 'failed','code':code,'index_dir':see.CACHE}
    else:
        if int(req.get('top',10))<=0:
            raise ValueError('top must be positive')
        args=SimpleNamespace(model=cfg['see']['model'],dir=req.get('dir'),image=req.get('image'),text=req.get('text'),top=int(req.get('top',10)),gap=4.,json=True)
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            code=see.cmd_query(args)
        result={'status':'found' if code==0 else 'no_index','matches':json.loads(out.getvalue() or '[]')}
    print(json.dumps(result))
if __name__=='__main__':
    main()
