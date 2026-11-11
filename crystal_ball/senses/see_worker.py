"""Configured CLIP interpreter entry point; JSON only on stdout."""
import contextlib
import io
import json
import sys
from types import SimpleNamespace
from pathlib import Path
from . import see
from ..config import load
from ..cache import runtime_stamp

def main():
    req=json.load(sys.stdin); cfg=load()
    see.CACHE=str(Path(cfg['cache_dir'])/'indexes')
    if req['action']=='index':
        sampling=req.get('sampling','shot')
        if sampling not in {'shot','interval'}:
            raise ValueError('sampling must be shot or interval')
        per_shot=int(req.get('frames_per_shot',1))
        if per_shot not in (1,2,3):
            raise ValueError('frames_per_shot must be 1, 2 or 3')
        args=SimpleNamespace(paths=req['paths'],model=cfg['see']['model'],every=float(req.get('every',2.)),cap=60,mode=sampling,shared=True,frames_per_shot=per_shot,
                             sampling_options={'scenes':cfg['scenes'],'per_shot':per_shot,'runtime':runtime_stamp(cfg)} if sampling=='shot' else None)
        with contextlib.redirect_stdout(sys.stderr):
            code=see.cmd_index(args)
        result={'status':'indexed' if code==0 else 'failed','code':code,'index_dir':see.CACHE,'sampling':sampling}
        if code==0:
            result['frame_count']=sum(len(meta['frames']) for path in Path(see.CACHE).glob('*/meta.json') if (meta:=see.load_index(str(path.parent))))
    else:
        if int(req.get('top',10))<=0:
            raise ValueError('top must be positive')
        args=SimpleNamespace(model=cfg['see']['model'],dir=req.get('dir'),image=req.get('image'),text=req.get('text'),top=int(req.get('top',10)),gap=4.,json=True)
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            code=see.cmd_query(args)
        result={'status':'found' if code==0 else 'no_index','matches':json.loads(out.getvalue() or '[]')}
    result.update(see.ENGINE_INFO)
    print(json.dumps(result))
if __name__=='__main__':
    main()
