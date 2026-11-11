"""Opt-in inference against user-configured local engines; media is ffmpeg-generated."""
import os
import subprocess
from pathlib import Path
import pytest
from crystal_ball.config import load

pytestmark=[pytest.mark.live,pytest.mark.skipif(os.environ.get('CRYSTAL_BALL_LIVE')!='1',reason='set CRYSTAL_BALL_LIVE=1 and configure local models')]


def ffmpeg(*args):
    subprocess.run(['ffmpeg','-nostdin','-v','error',*map(str,args)],capture_output=True,check=True,timeout=60)


def test_live_hear_cuda_and_cached_word_timestamps(tmp_path):
    from crystal_ball.senses.hear import Worker, transcribe
    cfg=load(); cfg['cache_dir']=str(tmp_path/'cache')
    if 'flite' not in subprocess.run(['ffmpeg','-hide_banner','-filters'],capture_output=True,text=True).stdout:
        pytest.skip('this ffmpeg build has no flite speech synthesizer')
    file=tmp_path/'speech.wav'
    ffmpeg('-f','lavfi','-i','flite=text=Welcome to a bright new day:voice=slt','-ar','16000',file)
    with Worker(cfg) as worker:
        result=transcribe(str(file),cfg,worker)
        assert result['engine']=='faster-whisper'
        assert result['text'] and any(s['words'] for s in result['segments'])
        pid=worker.proc.pid
        result2=worker.transcribe(str(file))
        assert worker.proc.pid==pid and result2['text']
        assert transcribe(str(file),cfg,worker)==result


def test_live_clip_index_text_image_and_atomic_reuse(tmp_path,monkeypatch):
    from crystal_ball.api import dispatch
    config=Path(os.environ['CRYSTAL_BALL_CONFIG']).read_text() if os.environ.get('CRYSTAL_BALL_CONFIG') else ''
    # Preserve user's engine settings, isolate this test's cache through the env override.
    monkeypatch.setenv('CRYSTAL_BALL_CACHE_DIR',str(tmp_path/'cache'))
    media=tmp_path/'media'; media.mkdir()
    image=media/'blue.png'
    ffmpeg('-f','lavfi','-i','color=c=blue:s=320x180','-frames:v','1','-threads','1',image)
    assert dispatch('index',paths=[str(media)])['code']==0
    result=dispatch('find',text='a blue image',top=1)
    assert len(result['matches'])==1
    assert dispatch('find',image=str(image),top=1)['matches'][0]['score']>.9
    metadata=list((tmp_path/'cache/indexes').glob('*/meta.json'))[0]
    old=metadata.read_text()
    assert dispatch('index',paths=[str(media)])['code']==0
    import json
    assert json.loads(old)['frames']==json.loads(metadata.read_text())['frames']


def test_live_ocr_configured_traineddata(tmp_path):
    from crystal_ball.senses.read import read_text
    cfg=load(); cfg['cache_dir']=str(tmp_path/'cache')
    file=tmp_path/'text.mp4'
    ffmpeg('-f','lavfi','-i','color=c=navy:s=1280x720:d=2','-vf',"drawtext=text='CLEAR TITLE':fontcolor=white:fontsize=90:x=100:y=100",'-threads','1',file)
    result=read_text(str(file),at=.5,config=cfg)
    assert any('CLEAR' in line['text'] for line in result['lines'])


def test_live_whispercpp_fallback(tmp_path):
    from crystal_ball.senses.hear import whispercpp
    cfg=load(); cfg['cache_dir']=str(tmp_path/'cache'); Path(cfg['cache_dir']).mkdir()
    if not cfg['whispercpp']['bin'] or not cfg['whispercpp']['model']:
        pytest.skip('optional whisper.cpp fallback not configured')
    file=tmp_path/'tone.wav'; ffmpeg('-f','lavfi','-i','sine=f=440:d=1',file)
    result=whispercpp(str(file),cfg)
    assert result['engine']=='whisper.cpp' and isinstance(result['segments'],list)
