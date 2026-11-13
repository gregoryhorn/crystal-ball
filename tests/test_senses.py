import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from crystal_ball.cache import Store, fingerprint
from crystal_ball.config import load
from crystal_ball.senses import hear, hear_worker, read, see


def test_config_precedence(tmp_path,monkeypatch):
    # Explicit env > cwd > user config, and key overrides > TOML.
    monkeypatch.delenv('CRYSTAL_BALL_CONFIG')
    home=tmp_path/'user'
    monkeypatch.setenv('HOME',str(home))
    monkeypatch.setenv('USERPROFILE',str(home))
    monkeypatch.setenv('APPDATA',str(home/'AppData/Roaming'))
    user=home/'.config/crystal-ball/config.toml'; user.parent.mkdir(parents=True)
    user.write_text('cache_dir="user-cache"\n')
    work=tmp_path/'work'; work.mkdir(); monkeypatch.chdir(work)
    from crystal_ball.platforms.paths import cache_home
    from crystal_ball.config import DEFAULTS
    expected_device='cpu' if os.name=='nt' else 'cuda'
    assert DEFAULTS['hear']['device']==expected_device
    assert DEFAULTS['see']['device']==expected_device
    expected_cache=(Path(os.environ.get('LOCALAPPDATA',str(home/'AppData/Local')))/'crystal-ball/cache'
                    if os.name=='nt' else '~/.cache/crystal-ball')
    assert cache_home()==str(expected_cache)
    if os.name=='nt':
        roaming=home/'AppData/Roaming/crystal-ball/config.toml'
        roaming.parent.mkdir(parents=True)
        roaming.write_text('cache_dir="roaming-cache"\n')
        user.unlink()
        assert load()['cache_dir']==str(roaming.parent/'roaming-cache')
        user.write_text('cache_dir="user-cache"\n')
    assert load()['cache_dir']==str(user.parent/'user-cache')
    local=work/'crystal-ball.toml'; local.write_text('cache_dir="local-cache"\n')
    assert load()['cache_dir']==str(work/'local-cache')
    explicit=tmp_path/'custom.toml'; explicit.write_text('cache_dir="explicit-cache"\n[hear]\nmodel="custom"\n')
    monkeypatch.setenv('CRYSTAL_BALL_CONFIG',str(explicit))
    assert load()['cache_dir']==str(tmp_path/'explicit-cache')
    monkeypatch.setenv('CRYSTAL_BALL_HEAR_MODEL','override')
    assert load()['hear']['model']=='override'
    monkeypatch.setenv('CRYSTAL_BALL_RULES_FILES','["rules/*.md"]')
    assert load()['rules']['files']==['rules/*.md']


def test_missing_explicit_config(tmp_path,monkeypatch):
    monkeypatch.setenv('CRYSTAL_BALL_CONFIG',str(tmp_path/'missing.toml'))
    with pytest.raises(FileNotFoundError):
        load()


def test_ocr_false_positive_and_persistence():
    safe=dict(left=.1,right=.1,top=.1,bottom=.1)
    def line(text,t=0,conf=95):
        return dict(text=text,time=t,confidence=conf,box=[0,0,40,20])
    for text in ('2','y'):
        assert all(r['status']!='FAIL' for r in read.filter_lines([line(text),line(text,1)],{0:(100,100),1:(100,100)},safe,'custom'))
    assert read.filter_lines([line('TITLE')],{0:(100,100)},safe,'custom')[0]['status']=='WARN'
    result=read.filter_lines([line('TITLE'),line('TITLE',1)],{0:(100,100),1:(100,100)},safe,'custom')
    assert len(result)==1 and result[0]['status']=='FAIL' and len(result[0]['timestamps'])==2
    assert read.filter_lines([line('TITLE')],{0:(100,100)},safe,'custom',confirmed=['TITLE'])[0]['status']=='FAIL'
    assert read.filter_lines([line('TITLE',conf=69),line('TITLE',1,69)],{0:(100,100),1:(100,100)},safe,'custom')[0]['status']=='WARN'


def test_ocr_groups_words_into_lines():
    header='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
    rows='5\t1\t1\t1\t1\t1\t0\t2\t20\t10\t95\tHELLO\n5\t1\t1\t1\t1\t2\t30\t2\t30\t10\t80\tWORLD\n'
    lines=read.lines_from_tsv(header+rows,{'time':1})
    assert len(lines)==1 and lines[0]['text']=='HELLO WORLD' and lines[0]['box']==[0,2,60,10]


def test_worker_protocol_recovers_and_reuses_engine():
    class Engine:
        calls=0
        def transcribe(self,req):
            self.calls+=1
            print('diagnostic')
            return {'text':req['file'],'loads':1,'calls':self.calls}
    source=io.StringIO('not json\n'+json.dumps({'id':1,'op':'transcribe','file':'a'})+'\n'+json.dumps({'id':2,'op':'transcribe','file':'b'})+'\n')
    sink=io.StringIO(); hear_worker.serve(Engine(),source,sink)
    responses=[json.loads(s) for s in sink.getvalue().splitlines()]
    assert 'error' in responses[0]
    assert responses[1]['id']==1 and responses[2]['result']['calls']==2


def test_hear_ffmpeg_array_not_file(tmp_path,monkeypatch):
    import types
    wav=tmp_path/'tone.wav'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=f=440:d=1',str(wav)],check=True,capture_output=True)
    seen=[]
    class Model:
        def __init__(self,*args,**kwargs):
            seen.append(kwargs)
        def transcribe(self,audio,**kwargs):
            assert isinstance(audio,np.ndarray) and audio.dtype==np.float32 and audio.shape==(16000,)
            assert kwargs['word_timestamps'] is True
            return [],SimpleNamespace(language='en')
    monkeypatch.setitem(sys.modules,'faster_whisper',SimpleNamespace(WhisperModel=Model))
    engine=hear_worker.Engine()
    req={'file':str(wav),'model':'stub','device':'cpu'}
    assert engine.transcribe(req)['duration']==1
    engine.transcribe(req)
    assert len(seen)==1 and seen[0]['local_files_only'] is True


def test_removed_line_changed_name_and_arabic():
    removed=hear.script_match('Hello world\nRemove this line\nGoodbye','Hello world Goodbye')
    assert 'Remove this line' in removed['missing_lines'] and removed['wer']>0
    changed=hear.script_match('Welcome Alexis','Welcome Alexiz',names=['Alexis'])
    assert 'Alexis' in changed['missing_or_changed_names'] and changed['changed_lines']
    assert hear.script_match('أَهْلًا يَا مُوسَى','اهلا يا موسي')['wer']==0


def test_speech_gaps_and_subtitles():
    doc={'segments':[{'start':0,'end':1,'text':'One'},{'start':4,'end':5,'text':'Two'}]}
    assert hear.speech_gaps(doc)==[[1,4]]
    assert hear.subtitles(doc).startswith('1\n00:00:00,000 --> 00:00:01,000')
    assert hear.subtitles(doc,'vtt').startswith('WEBVTT\n')


def test_cache_reuse_and_invalidation(tmp_path):
    p=tmp_path/'source'; p.write_bytes(b'first')
    store=Store(tmp_path/'cache'); calls=[]
    def produce(directory):
        calls.append(1); return {'data':len(calls)}
    assert store.get(p,'transcript',{},produce)==store.get(p,'transcript',{},produce)
    assert len(calls)==1
    stat=p.stat(); p.write_bytes(b'other'); os.utime(p,ns=(stat.st_atime_ns,stat.st_mtime_ns))
    assert store.get(p,'transcript',{},produce)['data']==2


def test_odd_shot_out_and_directory_boundary():
    result=see.odd_shot_out([[1,0],[-1,0],[1,0]])
    assert result[0]['index']==1 and result[0]['distance']==2 and result[0]['status']=='WARN'
    assert see.within('/media/a/clip.mp4','/media/a')
    assert not see.within('/media/another/clip.mp4','/media/a')


def test_cross_action_frame_reuse(tmp_path):
    from crystal_ball.core import review_stage
    from crystal_ball.frames import probe
    from crystal_ball.senses.read import read_text
    file=tmp_path/'sample.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=s=320x180:d=1','-threads','1',str(file)],check=True,capture_output=True)
    cfg=load(); req={'file':str(file),'meta':probe(file),'cache_dir':cfg['cache_dir']}
    frames=review_stage(req)
    original={f['path']:Path(f['path']).stat().st_mtime_ns for f in frames['frames']}
    read_text(str(file),config=cfg)
    assert review_stage(req)['frames']==frames['frames']
    assert all(Path(p).stat().st_mtime_ns==time for p,time in original.items())


def test_compact_all_actions(tmp_path):
    from crystal_ball.api import compact_action
    from crystal_ball.cache import dumps
    for action in ('transcribe','find','read_text','check','fix','doctor'):
        result={'text':'x'*10000,'segments':[{}]*100,'lines':[{'text':'خطأ'*1000}]*10,'matches':[{'file':'x'*1000}]*10,'checks':[]}
        compact=compact_action(action,result)
        assert len(dumps(compact).encode())<=1500
        assert Path(compact['artifact']).exists()


def test_finish_reminder_caps_and_revisions(tmp_path):
    from crystal_ball.hooks import Hooks
    hooks=Hooks()
    try:
        state=hooks.state('s')
        for i in range(6):
            state['files'][str(tmp_path/f'{i}.mp4')]={'result':None,'injected':False,'ack':False,'nudged':False}
        result=hooks.pre_llm_call(session_id='s')
        assert result['context'].count('Run crystal_ball check')==3
        assert hooks.pre_llm_call(session_id='s') is None
        assert hooks.pre_verify(session_id='s') is None
        path=next(iter(state['files']))
        state['files'][path]['nudged']=False
        assert hooks.pre_llm_call(session_id='s') is None
        assert state['reminders']==3
    finally:
        hooks.close()


def test_judge_safe_zone_confirmation_requires_exact_timed_ocr():
    from crystal_ball.senses.judge import crosscheck_vision
    from crystal_ball.util import row
    line={'text':'TITLE','time':1,'confidence':95,'box':[0,0,50,20]}
    ocr={'lines':[line],'checks':[row('ocr_safe_zone','WARN','"TITLE" overlaps UI (unconfirmed OCR)',[[1,1]])]}
    vision={'checks':[row('vision_safe_zone','FAIL','"TITLE" overlaps safe zone',[[1,1]])]}
    checked=crosscheck_vision(vision,ocr)
    assert read.confirm_safe_zones(ocr,checked)['checks'][0]['status']=='FAIL'
    vision['checks'][0]['summary']='"TITLES" overlaps safe zone'
    checked=crosscheck_vision(vision,ocr)
    assert not any(r['id']=='vision_safe_zone' for r in checked['checks'])
    assert read.confirm_safe_zones(ocr,checked)['checks'][0]['status']=='WARN'
    vision['checks'][0]['summary']='"TITLE" overlaps safe zone'; vision['checks'][0]['timestamps']=[[5,5]]
    assert read.confirm_safe_zones(ocr,crosscheck_vision(vision,ocr))['checks'][0]['status']=='WARN'


def test_http_judge_one_call_rules_byte_cap(tmp_path,monkeypatch):
    from crystal_ball.senses import judge
    image=tmp_path/'frame.jpg'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=s=64x64','-frames:v','1','-threads','1',str(image)],check=True,capture_output=True)
    cfg=load(); cfg['judge'].update(backend='openai-compatible',base_url='https://example.invalid/v1',model='configured-model',api_key_env='EXAMPLE_TOKEN')
    monkeypatch.setenv('EXAMPLE_TOKEN','placeholder')
    calls=[]
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self,limit):
            return json.dumps({'choices':[{'message':{'content':'{"checks":[]}'}}]}).encode()
    def urlopen(request,timeout):
        calls.append(json.loads(request.data))
        assert request.full_url=='https://example.invalid/v1/chat/completions'
        assert request.get_header('Authorization')=='Bearer placeholder'
        return Response()
    monkeypatch.setattr(judge,'urlopen',urlopen)
    result=judge.vision_stage({'config':cfg,'review':{'contact_sheet':str(image),'frames':[{'time':i,'path':str(image)} for i in range(6)]},'meta':{'duration':6},'rules':{'active':'ق'*5000}})
    assert len(calls)==1 and result['checks'][0]['status']=='PASS'
    parts=calls[0]['messages'][0]['content']
    assert sum(p['type']=='image_url' for p in parts)==5
    rules=parts[0]['text'].split('Rules (context only):\n')[1]
    assert len(rules.encode())<=2048


def test_engine_change_invalidates_cached_skip(tmp_path):
    from crystal_ball.cache import runtime_stamp
    cfg=load(); cfg['read']['tessdata']=str(tmp_path/'tessdata')
    cfg['hear']['python']=str(tmp_path/'engine/bin/python')
    before=runtime_stamp(cfg)
    p=Path(cfg['read']['tessdata']); p.mkdir()
    (p/'eng.traineddata').write_bytes(b'model placeholder')
    after=runtime_stamp(cfg)
    assert before!=after


def test_cache_recovers_from_partial_artifact(tmp_path):
    store=Store(tmp_path/'cache'); p=tmp_path/'source'; p.write_bytes(b'input')
    def fail(directory):
        (directory/'partial').write_text('partial')
        raise RuntimeError('interrupted extraction')
    with pytest.raises(RuntimeError):
        store.get(p,'frames',{},fail)
    def produce(directory):
        assert not (directory/'partial').exists()
        return {'ok':True}
    assert store.get(p,'frames',{},produce)=={'ok':True}


@pytest.mark.parametrize('suffix,audio_encoder,expected',[('.webm','libopus','opus'),('.mkv','flac','flac')])
def test_fix_preserves_audio_codec_in_other_containers(tmp_path,suffix,audio_encoder,expected):
    from crystal_ball.fix import apply_fix
    from crystal_ball.frames import probe
    from crystal_ball.util import row
    file=tmp_path/('quiet'+suffix)
    video_encoder='libvpx-vp9' if suffix=='.webm' else 'libx264'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=s=320x180:d=2','-f','lavfi','-i','sine=f=440:d=2','-af','volume=.3','-c:v',video_encoder,'-threads','1','-c:a',audio_encoder,'-shortest',str(file)],capture_output=True,check=True,timeout=30)
    original=fingerprint(file)
    result=apply_fix({'file':str(file),'platform':'youtube','checks':[row('loudness','FAIL','-30 LUFS')]})
    assert result['status']=='written',result
    assert fingerprint(file)==original
    assert next(s for s in probe(result['file'])['streams'] if s['codec_type']=='audio')['codec_name']==expected


def test_removed_line_with_repeated_words_uses_ordered_alignment():
    result=hear.script_match('We open the door.\nWe cross the room.\nWe see the sun.','We open the door. We see the sun.')
    assert result['missing_lines']==['We cross the room.']
    assert result['changed_lines']==[]
    changed=hear.script_match('Welcome Alexis','Welcome Alexiz',names=['Alexis'])
    assert {'expected':'Alexis','observed':'alexiz'} in changed['changed_names']


def test_image_index_and_reference_query_share_embedding(tmp_path,monkeypatch):
    file=tmp_path/'image.png'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=128x72','-frames:v','1','-threads','1',str(file)],check=True,capture_output=True)
    cfg=load(); monkeypatch.setattr(see,'CACHE',str(Path(cfg['cache_dir'])/'indexes'))
    model=SimpleNamespace(config=SimpleNamespace(projection_dim=2))
    monkeypatch.setattr(see,'load_model',lambda name:(model,None,'cpu'))
    calls=[]
    def embed(*args):
        calls.append(args[-1]); return np.asarray([[1,0]],dtype='float32')
    monkeypatch.setattr(see,'embed_images',embed)
    args=SimpleNamespace(paths=[str(file)],model='large',every=2.,cap=60,mode='interval',shared=True)
    assert see.cmd_index(args)==0
    query=SimpleNamespace(model='large',dir=None,image=str(file),text=None,top=1,gap=4.,json=True)
    import contextlib
    for _ in range(2):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            assert see.cmd_query(query)==0
        matches=json.loads(out.getvalue())
        assert matches[0]['file']==str(file) and matches[0]['score']==1.0
    assert len(calls)==1


def test_script_match_uses_word_boundaries():
    result=hear.script_match('cat','catch')
    assert result['changed_lines']==['cat'] and result['wer']==1
