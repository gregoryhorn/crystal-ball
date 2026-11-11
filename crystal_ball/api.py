"""One action dispatcher shared by CLI and Hermes."""
import os
import sys
from pathlib import Path
from .cache import atomic, dumps
from .config import load
from .util import process_json, foreign_python_env, StageError

def dispatch(action='check',**params):
    cfg=load()
    if action=='check':
        from .core import quality_check
        return quality_check(**params)
    if action in {'beats','scenes','cuts'}:
        from .senses import rhythm, scenes
        from .editing import alignment
        file=str(Path(params['file']).expanduser().resolve())
        if not Path(file).is_file():
            raise ValueError('file must exist')
        exports=params.get('export')
        if action=='beats':
            result=rhythm.beats(file,cfg)
            if exports is not None:
                directory=exports or str(Path(result['paths']['json']).parent/'exports')
                result={**result,'paths':{**result['paths'],**rhythm.export(result,directory,params.get('fps'))}}
        elif action=='scenes':
            result=scenes.detect_scenes(file,cfg)
            if int(params.get('first',5))<0:
                raise ValueError('first must be non-negative')
            result={**result,'first':int(params.get('first',5))}
            if exports is not None:
                directory=exports or str(Path(result['paths']['json']).parent/'exports')
                result['paths']={**result['paths'],**scenes.export(result,directory)}
        else:
            music=str(Path(params.get('music') or file).expanduser().resolve())
            beat_doc=rhythm.beats(music,cfg)
            shots=scenes.detect_scenes(file,cfg)
            aligned=alignment(shots['shots'],beat_doc,params['fps'] if params.get('fps') is not None else shots['fps'],params.get('within_frames',6))
            result={'shot_count':shots['shot_count'],'beat_count':beat_doc['beat_count'],'tempo':beat_doc['tempo'],'scenes':shots,'rhythm':beat_doc,**aligned,
                    'paths':{'scenes':shots['paths']['json'],'beats':beat_doc['paths']['json']}}
        return result
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
        env=foreign_python_env({'HF_HUB_OFFLINE':'1'})
        proc=subprocess.Popen([cfg['see']['python'],'-m','crystal_ball.senses.see_worker'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env,start_new_session=True)
        import contextlib, signal, json
        try:
            out,err=proc.communicate(dumps(req),timeout=1800)
        except BaseException:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid,signal.SIGKILL)
            proc.communicate(); raise
        if proc.returncode:
            raise StageError('see', err or out)
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
    if isinstance(result,dict) and result.get('checks') and action=='transcribe':
        return result
    if action in {'check','fix'} and len(dumps(result).encode())<=1500:
        return result
    data=dumps(result)
    path=Path(cfg['cache_dir'])/'tool-results'/(hashlib.sha256(data.encode()).hexdigest()+'.json')
    atomic(path,data)
    summary={'action':action,'artifact':str(path)}
    if isinstance(result,dict):
        for key in ('verdict','status','report','counts','code','engine','fallback_reason','log'):
            if key in result:
                summary[key]=result[key]
        if action=='beats':
            summary.update(tempo=result['tempo'],confidence=result['confidence'],beat_count=result['beat_count'],beats=result['beats'][:16],
                           bars={'count':len(result['bars']),'meter':'4/4 estimate','downbeats':result['downbeats'][:4]},paths=result['paths'])
        if action=='scenes':
            summary.update(shot_count=result['shot_count'],mean_shot_s=result['mean_shot_s'],median_shot_s=result['median_shot_s'],
                           shots=[{k:s[k] for k in ('start','end','duration','cut_type')} for s in result['shots'][:result.get('first',5)]],paths=result['paths'],engine=result['engine'],fallback_reason=result.get('fallback_reason'))
        if action=='cuts':
            summary.update(shot_count=result['shot_count'],beat_count=result['beat_count'],median_offset_ms=result['median_offset_ms'],offbeat_fraction=result['offbeat_fraction'],snaps=result['snaps'][:5],paths=result['paths'])
        if action=='transcribe':
            summary.update(engine=result.get('engine'),segments=len(result.get('segments',[])))
        if action=='find':
            summary['matches']=result.get('matches',[])[:3]
        if action=='read_text':
            summary['lines']=result.get('lines',[])[:3]
        if action=='doctor':
            summary['counts']={s:sum(c['status']==s for c in result['checks']) for s in ('PASS','WARN','FAIL')}
    for key in ('shots','snaps'):
        original=len(summary.get(key,[]))
        while len(dumps(summary).encode())>1500 and summary.get(key):
            summary[key].pop()
            summary['omitted_'+key]=original-len(summary[key])
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
