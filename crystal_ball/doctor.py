"""Offline diagnostics. Availability is separate from live inference evidence."""
import hashlib
import os
import shutil
import re
import subprocess
from pathlib import Path
from .config import load
from .senses.hear import Worker
from .util import command, process_json

ARABIC_SHA256='ab9d157d8e38ca00e7e39c7d5363a5239e053f5b0dbdb3167dde9d8124335896'

def doctor(config=None):
    cfg=config or load(); rows=[]
    def add(name,status,detail,**extra):
        rows.append({'engine':name,'status':status,'detail':detail,**extra})
    for binary in ('ffmpeg','ffprobe','tesseract'):
        try:
            args=[binary,'--version' if binary=='tesseract' else '-version']
            version=command(args,10).splitlines()[0]
            match=re.search(r'version (\d+)\.(\d+)',version) if binary in {'ffmpeg','ffprobe'} else None
            old=bool(match and tuple(map(int,match.groups()))<(6,1))
            add(binary,'FAIL' if old else 'PASS',version+(' (requires 6.1+)' if old else ''))
        except Exception as exc:
            add(binary,'FAIL',str(exc)[-180:])
    for kind in ('hear','see'):
        try:
            env={**os.environ,'HF_HUB_OFFLINE':'1','PYTHONPATH':str(Path(__file__).resolve().parent.parent)+os.pathsep+os.environ.get('PYTHONPATH','')}
            if kind=='hear':
                prefix=command([cfg[kind]['python'],'-c','import sys; print(sys.prefix)'],15).strip()
                libs=[str(p) for name in ('cublas','cudnn') for p in Path(prefix).glob(f'lib/python*/site-packages/nvidia/{name}/lib')]
                env['LD_LIBRARY_PATH']=os.pathsep.join(libs+[os.environ.get('LD_LIBRARY_PATH','')])
            detail=process_json([cfg[kind]['python'],'-m','crystal_ball.doctor_worker',kind,cfg[kind]['model']],180,env)
            gpu=detail['gpu_count']
            add(kind,'WARN' if kind=='hear' and cfg[kind]['device']=='cuda' and not gpu else 'PASS',f'local model verified; {gpu} GPU(s); CPU available; inference not run',**detail)
        except Exception as exc:
            add(kind,'WARN',f'engine/model unavailable: {str(exc)[-220:]}')
    for kind,package in [('rhythm','librosa'),('scenes','scenedetect')]:
        try:
            from .workers import request
            detail=request(cfg[kind]['python'],'crystal_ball.doctor_worker',{'kind':kind},30)
            add(kind,'PASS',f"{package} {detail['version']}; CPU engine available; inference not run",**detail)
        except Exception as exc:
            suffix='; ffmpeg select fallback available' if kind=='scenes' and shutil.which('ffmpeg') else ''
            add(kind,'WARN',f'engine unavailable: {str(exc)[-180:]}'+suffix)
    wc=cfg['whispercpp']; binary=shutil.which(wc['bin']) if wc['bin'] else None
    if binary and Path(wc['model']).is_file():
        try:
            version=subprocess.run([binary,'--help'],capture_output=True,text=True,timeout=10)
            with Path(wc['model']).open('rb') as model_file:
                digest=hashlib.file_digest(model_file,'sha256').hexdigest()
            add('whisper.cpp','PASS','configured CPU fallback; explicit output prefix; '+(version.stdout or version.stderr).splitlines()[0],sha256=digest)
        except Exception as exc:
            add('whisper.cpp','WARN',str(exc)[-160:])
    else:
        add('whisper.cpp','WARN','optional fallback binary/model not configured or missing')
    env=os.environ.copy()
    if cfg['read']['tessdata']:
        env['TESSDATA_PREFIX']=cfg['read']['tessdata']
    try:
        langs=command(['tesseract','--list-langs'],10,env).splitlines()
        location=cfg['read']['tessdata'] or (langs[0].split('"')[1] if '"' in langs[0] else '')
        for lang in ('eng','osd','ara'):
            p=Path(location)/f'{lang}.traineddata'
            if p.is_file():
                with p.open('rb') as f:
                    digest=hashlib.file_digest(f,'sha256').hexdigest()
                match=lang!='ara' or digest==ARABIC_SHA256
                add('ocr '+lang,'PASS' if match else 'WARN','local traineddata'+(' (differs from documented tessdata_best 4.1.0)' if not match else ''),sha256=digest)
            else:
                add('ocr '+lang,'WARN','traineddata unavailable')
    except Exception as exc:
        add('ocr models','WARN',str(exc)[-160:])
    cmd=cfg['hear']['demucs_command']
    add('demucs','PASS' if cmd and shutil.which(cmd[0]) else 'WARN','configured executable found; separation/model availability not tested' if cmd and shutil.which(cmd[0]) else 'optional command unavailable; voice balance uses a labelled estimate')
    judge=cfg['judge']; backend=judge['backend']; ready=False
    if backend=='hermes-auxiliary':
        try:
            import importlib.util
            ready=importlib.util.find_spec('agent.auxiliary_client') is not None
        except (ModuleNotFoundError,ValueError):
            pass
    elif backend=='openai-compatible':
        ready=bool(judge['base_url'] and judge['model'] and (not judge['api_key_env'] or os.environ.get(judge['api_key_env'])))
    add('judge','PASS' if ready else 'WARN',backend+'; configuration/import availability only; endpoint not called')
    return {'checks':rows,'downloads':False,'live_inference':False}

def table(doc):
    return '\n'.join(['STATUS  ENGINE          DETAIL']+[f"{r['status']:<7} {r['engine']:<15} {r['detail']}" for r in doc['checks']])
