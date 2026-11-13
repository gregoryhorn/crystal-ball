"""Isolated generations and all-or-nothing selected-engine config publication."""
import json
import os
from pathlib import Path
import sys
import time
from ...cache import atomic, dumps
from ...platforms.locks import file_lock
from ...util import command, engine_python_env, process_json
from .plan import digest, make_plan, patch_config
from .recipes import validate_platform


def provision(entry, python):
    generation = Path(entry['generation'])
    if entry.get('reuse'):
        exe, snapshot=entry['python'],entry['model']
        process_json([exe,'-m','crystal_ball.doctor_worker',entry['engine'],snapshot],300,
                     engine_python_env(exe,{'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'}))
        return {'python':exe,'model':snapshot,'device':'cpu'}
    generation.mkdir(parents=True, exist_ok=False)
    atomic(generation/'manifest.json', dumps({'state':'installing', **entry}))
    try:
        command([python,'-m','venv',str(generation)],120)
        exe = entry['python']
        for lock in entry['locks']:
            command([exe,'-m','pip','install','--no-cache-dir','--no-deps','--require-hashes','-r',lock],1800,engine_python_env(exe))
        probe = 'import ctranslate2; from faster_whisper import WhisperModel' if entry['engine']=='hear' else 'import torch; from transformers import CLIPModel, CLIPProcessor'
        command([exe,'-c',probe],120,engine_python_env(exe,{'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'}))
        env = engine_python_env(exe, {'HF_HUB_OFFLINE':'0','TRANSFORMERS_OFFLINE':'0'})
        # Downloader resolves the configured model or reuses a complete existing local snapshot.
        kind, model = entry['engine'], entry['model']
        code = "import json,sys; from pathlib import Path; model=sys.argv[1]; dest=sys.argv[2]; "
        if kind=='hear':
            code += "from faster_whisper.utils import download_model; fetch=lambda local: download_model(model,local_files_only=local,**({} if local else {'cache_dir':dest}));"
        else:
            code += "from huggingface_hub import snapshot_download; fetch=lambda local: snapshot_download(model,local_files_only=local,**({} if local else {'cache_dir':dest}));"
        code += "\nif Path(model).is_dir(): path=str(Path(model))\nelse:\n try: path=fetch(True)\n except Exception: path=fetch(False)\nprint(json.dumps({'path':path}))"
        value = process_json([exe,'-c',code,model,entry['download_destination']],1800,env)
        snapshot = value['path']
        detail = process_json([exe,'-m','crystal_ball.doctor_worker',kind,snapshot],300,engine_python_env(exe,{'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'}))
        atomic(generation/'manifest.json', dumps({'state':'validated',**entry,'snapshot':snapshot,'probe':detail,
                                                'lock_hashes':{str(p):digest(Path(p).read_bytes()) for p in entry['locks']}}))
        return {'python':exe, 'model':snapshot, 'device':'cpu'}
    except BaseException as exc:
        atomic(generation/'manifest.json',dumps({'state':'failed',**entry,'error':str(exc), 'resume':'rerun setup; downloads retained in download_destination'}))
        raise


def commit_config(plan, updates):
    target = Path(plan['config'])
    # Cooperative serialization plus optimistic comparison against the displayed plan.
    with file_lock(target.parent):
        current = target.read_bytes() if target.exists() else None
        if (digest(current) if current is not None else None) != plan['original_digest']:
            raise RuntimeError('config changed concurrently; unchanged. Generated snippets: '+dumps(updates))
        updated = patch_config(current.decode('utf-8-sig') if current is not None else '',updates)
        if current is not None:
            backup = target.with_name(target.name+'.backup-'+str(time.time_ns()))
            with backup.open('xb') as handle:
                handle.write(current)
        # Compare again after backup, immediately before atomic publication.
        latest = target.read_bytes() if target.exists() else None
        if latest != current:
            raise RuntimeError('config changed concurrently; unchanged. Generated snippets: '+dumps(updates))
        atomic(target, updated)


def install(engine=None, stdin=None, output=None):
    stdin, output = (sys.stdin if stdin is None else stdin), (sys.stdout if output is None else output)
    if not stdin.isatty():
        raise RuntimeError('setup --install requires interactive stdin; use setup for print-only instructions')
    plan = make_plan(engine)
    print(json.dumps(plan,ensure_ascii=False,indent=2),file=output)
    print('Install selected engines and models? [y/N] ',end='',file=output,flush=True)
    if stdin.readline().strip().lower() not in {'y','yes'}:
        return {'status':'declined','changed':False}
    validate_platform()
    updates = {}
    for entry in plan['engines']:
        updates[entry['engine']] = provision(entry,plan['python'])
    commit_config(plan,updates)
    return {'status':'installed','config':plan['config'],'engines':list(updates),'overrides':plan['overrides'],
            'inference':'not checked; run local transcribe/index/find after offline doctor'}
