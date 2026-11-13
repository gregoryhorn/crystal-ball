"""Hermes adapter. Hooks schedule work; tool payloads contain paths, never images."""
import contextlib
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from .cache import dumps
from .config import load
from .hooks import Hooks
from .util import error_result, StageError, same_python_env
from .platforms.process import spawn_owned

ACTIONS=['check','transcribe','find','index','read_text','fix','doctor','beats','scenes','cuts']

def profile_config():
    explicit=os.environ.get('CRYSTAL_BALL_CONFIG')
    if explicit:
        return explicit
    try:
        from hermes_constants import get_hermes_home
        home=Path(get_hermes_home())
    except ImportError:
        home=Path(os.environ.get('HERMES_HOME','~/.hermes')).expanduser()
    candidate=home/'crystal-ball.toml'
    return str(candidate) if candidate.is_file() else None

def invoke(action,**params):
    env=same_python_env({'HF_HUB_OFFLINE':'1'})
    config=profile_config()
    if config:
        env['CRYSTAL_BALL_CONFIG']=config
    proc=spawn_owned([sys.executable,'-m','crystal_ball.tool_worker'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
    try:
        out,err=proc.communicate(dumps({'action':action,**params}),timeout=1800)
    except BaseException:
        raise
    finally:
        proc.close()
    if proc.returncode:
        raise StageError('tool',err or out)
    result=json.loads(out)
    if len(dumps(result).encode())>1500:
        raise ValueError('tool response exceeds compact budget')
    return result

def register(ctx):
    hooks=Hooks(check=lambda **kw: invoke('check',**kw),config_loader=lambda:load(profile_config()))
    def handle(params,**kwargs):
        action='tool'
        try:
            params=dict(params); action=params.pop('action')
            if action not in ACTIONS:
                raise ValueError('unknown action')
            file=params.get('file')
            if action in {'check','transcribe','read_text','fix','beats','scenes','cuts'} and not file:
                raise ValueError('file is required for this action')
            result=invoke(action,**params)
            if action in {'check','fix'} and file:
                hooks.acknowledge(kwargs.get('session_id',''),file,result)
            return dumps(result)
        except Exception as exc:
            return dumps(error_result(exc,action))
    props={
        'action':{'type':'string','enum':ACTIONS},
        'file':{'type':'string','description':'Media path'},
        'paths':{'type':'array','items':{'type':'string'},'description':'Directories/files to index'},
        'text':{'type':'string','description':'Semantic search query'},
        'image':{'type':'string','description':'Reference image for find'},
        'top':{'type':'integer','minimum':1,'default':10},
        'dir':{'type':'array','items':{'type':'string'},'description':'Restrict find to directories'},
        'at':{'type':'number','minimum':0,'description':'read_text timestamp in seconds'},
        'platform':{'type':'string'},
        'mode':{'type':'string','enum':['quick','full'],'default':'quick'},
        'beat_led':{'type':'boolean','default':False},
        'music':{'type':'string','description':'Separate soundtrack for cuts, with matching timeline origin'},
        'fps':{'type':'number','exclusiveMinimum':0},
        'within_frames':{'type':'integer','minimum':0,'default':6},
        'first':{'type':'integer','minimum':0,'default':5},
        'export':{'type':'string','description':'Export directory; empty string uses artifact directory'},
        'sampling':{'type':'string','enum':['shot','interval'],'default':'shot'},
        'every':{'type':'number','exclusiveMinimum':0,'default':2},
        'frames_per_shot':{'type':'integer','enum':[1,2,3],'default':1},
        'captions':{'type':'string'},'script':{'type':'string'},'brief':{'type':'string'},
        'expect_text':{'type':'array','items':{'type':'string'}},
        'fix':{'type':'boolean','default':False},'force':{'type':'boolean','default':False},
    }
    ctx.register_tool(name='crystal_ball',toolset='crystal_ball',schema={
        'name':'crystal_ball',
        'description':'Media senses: check, transcribe, CLIP find/index, OCR read_text, beats/scenes/cuts and snap suggestions, mechanical fix, or offline doctor. Compact JSON and artifact/report paths; no images. Sampled visual critique cannot hear or judge lip-sync. Check passed ≠ approved.',
        'parameters':{'type':'object','properties':props,'required':['action'],'additionalProperties':False},
    },handler=handle)
    for name in ('post_tool_call','pre_llm_call','pre_verify','on_session_end'):
        ctx.register_hook(name,getattr(hooks,name))
    return hooks
