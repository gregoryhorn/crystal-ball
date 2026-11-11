import json
import sys
import time
from pathlib import Path
import pytest
from crystal_ball import hermes
from crystal_ball.api import dispatch

class Context:
    def __init__(self):
        self.tools=[]; self.hooks={}
    def register_tool(self,**kwargs):
        self.tools.append(kwargs)
    def register_hook(self,name,callback):
        self.hooks[name]=callback


def test_profile_config(tmp_path,monkeypatch):
    monkeypatch.delenv('CRYSTAL_BALL_CONFIG')
    monkeypatch.setenv('HERMES_HOME',str(tmp_path))
    monkeypatch.setitem(sys.modules,'hermes_constants',None)
    assert hermes.profile_config() is None
    config=tmp_path/'crystal-ball.toml'; config.write_text('')
    assert hermes.profile_config()==str(config)
    monkeypatch.setenv('CRYSTAL_BALL_CONFIG','explicit.toml')
    assert hermes.profile_config()=='explicit.toml'


def test_registration_all_actions_and_compact_errors(monkeypatch):
    ctx=Context(); hooks=hermes.register(ctx)
    try:
        assert len(ctx.tools)==1 and ctx.tools[0]['name']=='crystal_ball'
        assert set(ctx.hooks)=={'post_tool_call','pre_llm_call','pre_verify','on_session_end'}
        handler=ctx.tools[0]['handler']
        monkeypatch.setattr(hermes,'invoke',lambda action,**params:{'action':action,'status':'ok'})
        for action in hermes.ACTIONS:
            result=json.loads(handler({'action':action,'file':'sample.mp4'}))
            assert result['action']==action
        assert json.loads(handler({'action':'check'}))['status']=='error'
        assert len(handler({'action':'invalid'}).encode())<=1500
    finally:
        hooks.close()


def test_tool_worker_real_error_and_output_budget(tmp_path):
    # Real subprocess path, no patched dispatcher or model calls.
    result=hermes.invoke('check',file=str(tmp_path/'missing.mp4'))
    assert result['status']=='error' and len(json.dumps(result).encode())<=1500


def test_hooks_fail_open(monkeypatch):
    ctx=Context(); hooks=hermes.register(ctx)
    try:
        before=time.monotonic()
        assert hooks.post_tool_call(args={'command':'unmatched "'},session_id='s') is None
        assert hooks.pre_llm_call(session_id='missing') is None
        assert hooks.pre_verify(session_id='missing') is None
        assert time.monotonic()-before<.2
    finally:
        hooks.close()
