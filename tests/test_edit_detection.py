"""Synthetic-only detection and stub-based rhythm/alignment tests."""
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from crystal_ball.config import load
from crystal_ball import editing
from crystal_ball.senses import scenes, rhythm


def ffmpeg(*args):
    subprocess.run(['ffmpeg','-nostdin','-v','error',*map(str,args)],check=True,capture_output=True,timeout=60)


def cards(path, fade=False):
    # Uniform cards have exact hard cuts; fade-out/black/fade-in is centred at 4s.
    filters=['color=red:s=160x90:r=25:d=2','color=blue:s=160x90:r=25:d=2','color=green:s=160x90:r=25:d=2']
    if fade:
        filters[1]+=',fade=t=out:st=1.5:d=0.5'
        filters[2]+=',fade=t=in:st=0:d=0.5'
    args=[]
    for source in filters:
        args+=['-f','lavfi','-i',source]
    ffmpeg(*args,'-filter_complex','[0:v][1:v][2:v]concat=n=3:v=1:a=0','-c:v','libx264','-crf','0','-threads','1',path)


def shots(times):
    return [{'start':a,'end':b,'duration':b-a} for a,b in zip(times,times[1:])]


def test_alignment_onbeat_offbeat_and_snaps():
    beat={'beats':np.arange(0,5,.5).tolist(),'onsets':[]}
    on=editing.alignment(shots([0,1,2,3,4]),beat,25,6)
    assert editing.cut_sync(on)['status']=='PASS'
    off=editing.alignment(shots([0,1.2,2.2,3.2,4]),beat,25,6)
    check=editing.cut_sync(off)
    assert check['status']=='WARN' and check['timestamps']
    assert off['median_offset_ms']==200 and off['snaps'][0]['frame_delta']==-5
    assert '1.200s -> 1.000s' in check['fix']
    assert editing.cut_sync(editing.alignment(shots([0,1,2]),{'beats':[]},25))['status']=='SKIP'
    # Either onset or beat supports the cut; snaps still target beats only.
    beat['onsets']=[1.2,2.2,3.2]
    assert editing.cut_sync(editing.alignment(shots([0,1.2,2.2,3.2,4]),beat,25))['status']=='PASS'


def test_pacing_informational_and_hook():
    doc=shots([0,4,6])
    assert editing.pacing(doc,'youtube')['status']=='PASS'
    assert editing.pacing(doc,'shorts')['status']=='WARN'
    assert editing.pacing(doc,'shorts',[1.5])['status']=='PASS'
    assert editing.pacing(shots([0,2,4]),'reels')['status']=='PASS'


def test_flash_rolling_window_not_clock_buckets():
    visual={'flashes':[{'time':t,'kind':'luminance'} for t in [.85,1.05,1.25,1.45]],'method':'test','label':'estimate, not a certified Harding test'}
    result=editing.flash(visual)
    assert result['checks'][0]['status']=='FAIL' and result['max_flashes_per_second']==4
    visual['flashes']=[{'time':i/3,'kind':'luminance'} for i in range(7)]
    assert editing.flash(visual)['checks'][0]['status']=='PASS'


def test_scenes_fallback_known_hard_cuts_and_reuse(tmp_path,monkeypatch):
    from crystal_ball import workers
    file=tmp_path/'cards.mp4'; cards(file)
    cfg=load(); cfg['scenes']['python']='missing-scene-python'
    first=scenes.detect_scenes(str(file),cfg)
    assert first['engine']=='ffmpeg-select' and first['fallback_reason']
    assert first['shot_count']==3
    assert np.allclose([s['start'] for s in first['shots']],[0,2,4],atol=1/25)
    assert [s['cut_type'] for s in first['shots']]==['start','hard cut','hard cut']
    assert all(Path(s['thumbnail']).is_file() for s in first['shots'])
    monkeypatch.setattr(workers,'request',lambda *a: (_ for _ in ()).throw(AssertionError('cached shots must be reused')))
    assert scenes.detect_scenes(str(file),cfg)==first
    paths=scenes.export(first,tmp_path/'export')
    assert len(Path(paths['csv']).read_text().splitlines())==4
    edl=Path(paths['edl']).read_text()
    assert 'FCM: NON-DROP FRAME' in edl and '00:00:02:00' in edl


def test_threshold_fade_fallback(tmp_path):
    file=tmp_path/'fade.mp4'; cards(file,True)
    cfg=load(); cfg['scenes']['python']='missing-scene-python'
    result=scenes.detect_scenes(str(file),cfg)
    assert any(s['cut_type']=='fade' and abs(s['start']-4)<.2 for s in result['shots']),result
    assert any(s['cut_type']=='hard cut' and abs(s['start']-2)<=1/25 for s in result['shots'])


@pytest.mark.parametrize('red',[False,True])
def test_synthetic_flash_fail_and_calm_pass(tmp_path,red):
    from crystal_ball.visual import scan
    flash=tmp_path/'flash.mp4'; calm=tmp_path/'calm.mp4'
    if red:
        source="color=c=black:s=160x90:r=30:d=2,drawbox=c=red:t=fill:enable='lt(mod(n,6),3)'"
    else:
        source="nullsrc=s=160x90:r=30:d=2,geq=lum='if(lt(mod(N,6),3),235,16)':cb=128:cr=128"
    ffmpeg('-f','lavfi','-i',source,'-c:v','libx264','-crf','0','-threads','1',flash)
    ffmpeg('-f','lavfi','-i','color=c=gray:s=160x90:r=30:d=2','-threads','1',calm)
    result=editing.flash(scan(str(flash)))
    assert result['checks'][0]['status']=='FAIL',result
    assert 'estimate, not a certified Harding test' in result['checks'][0]['summary']
    assert editing.flash(scan(str(calm)))['checks'][0]['status']=='PASS'
    if red:
        assert any(e['kind']=='red' for e in result['events'])


def test_small_area_flash_does_not_fail(tmp_path):
    from crystal_ball.visual import scan
    file=tmp_path/'small.mp4'
    ffmpeg('-f','lavfi','-i',"color=c=black:s=160x90:r=30:d=2,drawbox=w=16:h=9:c=white:t=fill:enable='lt(mod(n,6),3)'",'-threads','1',file)
    assert editing.flash(scan(str(file)))['checks'][0]['status']=='PASS'


def test_rhythm_stub_protocol_cache_and_exports(tmp_path,monkeypatch):
    from crystal_ball import workers
    file=tmp_path/'audio.wav'
    ffmpeg('-f','lavfi','-i','sine=d=1',file)
    calls=[]
    doc={'tempo':120,'confidence':.9,'duration':4,'beat_count':8,'beats':np.arange(0,4,.5).tolist(),'onsets':[.5,1.], 'downbeats':[0,2.], 'bars':[{'start':0},{'start':2}], 'sections':[{'start':0,'end':4}], 'engine':'librosa-cpu'}
    def request(python,module,req,timeout):
        calls.append((python,module,req)); return dict(doc)
    monkeypatch.setattr(workers,'request',request)
    cfg=load(); cfg['rhythm']['python']='rhythm-python'
    result=rhythm.beats(str(file),cfg)
    assert rhythm.beats(str(file),cfg)==result and len(calls)==1
    assert calls[0][0]=='rhythm-python' and calls[0][1].endswith('rhythm_worker')
    assert 'speech lowers beat accuracy' in result['analysis']
    paths=rhythm.export(result,tmp_path/'export',fps=25)
    assert json.loads(Path(paths['frames']).read_text())['frames']==[0,12,25,38,50,62,75,88]
    assert len(Path(paths['csv']).read_text().splitlines())==9


def test_index_by_shot_reduces_frame_count(tmp_path,monkeypatch):
    from crystal_ball.senses import see
    file=tmp_path/'long.mp4'
    ffmpeg('-f','lavfi','-i','color=c=blue:s=160x90:r=25:d=12','-threads','1',file)
    cfg=load(); cfg['scenes']['python']='missing-scene-python'
    monkeypatch.setattr(see,'load',lambda:cfg)
    model=SimpleNamespace(config=SimpleNamespace(projection_dim=2))
    monkeypatch.setattr(see,'embed_images',lambda m,p,d,paths:np.ones((len(paths),2),dtype='float32'))
    thumbs=tmp_path/'thumbs'; thumbs.mkdir()
    args=SimpleNamespace(mode='interval',shared=False,every=2.,cap=60,model='stub')
    interval=see.index_file(str(file),args,str(thumbs),model,None,'cpu')
    args.mode='shot'; args.shared=True; args.frames_per_shot=1
    by_shot=see.index_file(str(file),args,str(thumbs),model,None,'cpu')
    assert len(by_shot[0])==1<len(interval[0])
    args.frames_per_shot=3
    three=see.index_file(str(file),args,str(thumbs),model,None,'cpu')
    assert len(three[0])==3


def test_editing_stage_only_enables_sync_for_beat_led(monkeypatch):
    from crystal_ball import visual
    from crystal_ball.senses import scenes,rhythm
    monkeypatch.setattr(scenes,'detect_scenes',lambda *a:{'shots':shots([0,1,2]),'fps':25})
    monkeypatch.setattr(visual,'scan',lambda *a:{'flashes':[],'method':'stub','label':'estimate, not a certified Harding test','visual_changes':[]})
    calls=[]
    def beats(*a):
        calls.append(a); return {'beats':[0,.5,1,1.5,2],'onsets':[]}
    monkeypatch.setattr(rhythm,'beats',beats)
    req={'file':'stub.mp4','platform':'youtube','config':load()}
    assert all(c['id']!='cut_sync' for c in editing.edit_stage(req)['checks']) and not calls
    for update in [{'beat_led':True},{'brief':'A beat-led edit'},{'brief':'MUSIC-LED campaign'}]:
        value=editing.edit_stage({**req,**update})
        assert next(c for c in value['checks'] if c['id']=='cut_sync')['status']=='PASS'
    assert len(calls)==3


def test_actions_and_cli_compact_exports(tmp_path,monkeypatch,capsys):
    from crystal_ball import api,cli
    from crystal_ball.senses import scenes,rhythm
    file=tmp_path/'synthetic.mp4'; file.write_bytes(b'stub')
    beat_doc={'tempo':120,'confidence':1.,'beat_count':8,'beats':np.arange(0,4,.5).tolist(),'onsets':[],'bars':[{'start':0},{'start':2}],'downbeats':[0,2.],'paths':{'json':str(tmp_path/'beats.json')}}
    scene_doc={'shot_count':2,'mean_shot_s':2.,'median_shot_s':2.,'shots':[{**s,'shot':i+1,'cut_type':'start' if i==0 else 'hard cut','thumbnail':'stub'} for i,s in enumerate(shots([0,2,4]))],
               'engine':'stub','fps':25,'paths':{'json':str(tmp_path/'scenes.json')}}
    monkeypatch.setattr(rhythm,'beats',lambda *a,**kw:beat_doc)
    monkeypatch.setattr(scenes,'detect_scenes',lambda *a,**kw:scene_doc)
    assert cli.main(['beats',str(file),'--fps','25','--export',str(tmp_path/'export')])==0
    result=json.loads(capsys.readouterr().out)
    assert result['beat_count']==8 and result['bars']['count']==2 and len(result['beats'])==8
    assert Path(result['paths']['frames']).exists() and Path(result['artifact']).exists()
    assert cli.main(['scenes',str(file),'--first','1','--export',str(tmp_path/'export')])==0
    result=json.loads(capsys.readouterr().out)
    assert result['shot_count']==2 and len(result['shots'])==1 and Path(result['paths']['edl']).is_file()
    assert cli.main(['cuts',str(file),'--music',str(file),'--within-frames','2'])==0
    result=json.loads(capsys.readouterr().out)
    assert result['median_offset_ms']==0 and result['snaps'][0]['frame_delta']==0
    from crystal_ball.cache import dumps
    for action in ('beats','scenes','cuts'):
        full=api.dispatch(action,file=str(file))
        assert len(dumps(api.compact_action(action,full)).encode())<=1500


def test_new_config_paths_and_validation(tmp_path,monkeypatch):
    cfg=tmp_path/'settings.toml'
    cfg.write_text('[rhythm]\npython="./runtime/bin/python"\n[scenes]\npython="scene-python"\ndetector="adaptive"\nthreshold=3.0\nmin_shot_s=.5\n'.replace('min_shot_s=.5','min_shot_s=0.5'))
    monkeypatch.setenv('CRYSTAL_BALL_CONFIG',str(cfg))
    assert load()['rhythm']['python']==str(tmp_path/'runtime/bin/python')
    assert load()['scenes']['python']=='scene-python'
    monkeypatch.setenv('CRYSTAL_BALL_SCENES_THRESHOLD','nan')
    with pytest.raises(ValueError):
        load()


def test_doctor_reports_new_engines_without_inference(monkeypatch):
    from crystal_ball import workers
    from crystal_ball.doctor import doctor
    cfg=load(); cfg['hear']['python']='missing-hear'; cfg['see']['python']='missing-see'
    calls=[]
    def request(python,module,req,timeout):
        calls.append(req['kind']); return {'version':'stub','device':'cpu','inference':False}
    monkeypatch.setattr(workers,'request',request)
    doc=doctor(cfg); rows={r['engine']:r for r in doc['checks']}
    assert calls==['rhythm','scenes']
    assert rows['rhythm']['status']==rows['scenes']['status']=='PASS'
    assert doc['live_inference'] is False


def test_check_integrates_flash_and_reuses_shots(tmp_path):
    from crystal_ball.core import quality_check
    file=tmp_path/'flashing.mp4'
    ffmpeg('-f','lavfi','-i',"nullsrc=s=160x90:r=30:d=2,geq=lum='if(lt(mod(N,6),3),235,16)':cb=128:cr=128",'-threads','1',file)
    result=quality_check(str(file),platform='youtube')
    assert result['verdict']=='FAIL'
    assert any(item['id']=='flash' and item['status']=='FAIL' for item in result['items'])
    full=json.loads(Path(result['report']).with_name('full.json').read_text())
    # MA-r1 retains an explicit omission instead of silently dropping this family.
    assert all(item['status']=='SKIP' for item in full['checks'] if item['id']=='cut_sync')
    assert full['stages']['review']['scenes']==full['stages']['editing']['scenes']['paths']
    assert any(f.get('at_cut') for f in full['stages']['review']['frames'])


@pytest.mark.parametrize('separation',['success','failed','no-speech'])
def test_rhythm_optional_music_stem(tmp_path,monkeypatch,separation):
    from crystal_ball import workers
    from crystal_ball.senses import rhythm
    file=tmp_path/'mix.wav'
    ffmpeg('-f','lavfi','-i','sine=d=1',file)
    cfg=load(); cfg['hear']['demucs_command']=['stub-demucs','{input}','{output_dir}']
    sources=[]; commands=[]
    def command(args,timeout):
        commands.append(args)
        if separation=='failed':
            raise RuntimeError('stub separation failure')
        (Path(args[-1])/'no_vocals.wav').write_bytes(b'synthetic stem')
    def request(python,module,req,timeout):
        sources.append(req['file'])
        return {'beats':[0.,.5],'onsets':[0.,.5],'downbeats':[0.],'duration':1.,'tempo':120.,'confidence':1.,'bars':[],'beat_count':2}
    monkeypatch.setattr(rhythm,'command',command)
    monkeypatch.setattr(workers,'request',request)
    doc=rhythm.beats(str(file),cfg,speech_music=separation!='no-speech')
    if separation=='success':
        assert sources[0].endswith('no_vocals.wav') and 'separated music stem' in doc['analysis']
        assert not Path(sources[0]).exists() # ephemeral stem is removed
    else:
        assert sources[0]==str(file) and 'speech lowers beat accuracy' in doc['analysis']
        if separation=='failed':
            assert doc['separation_reason']
        else:
            assert not commands


def test_review_cache_changes_with_scene_settings(tmp_path):
    from crystal_ball.core import review_stage
    from crystal_ball.frames import probe
    file=tmp_path/'cards.mp4'; cards(file)
    cfg=load(); cfg['scenes']['python']='missing-scenes'
    req={'file':str(file),'config':cfg,'meta':probe(file),'cache_dir':cfg['cache_dir']}
    first=review_stage(req)
    assert review_stage(req)['frames']==first['frames']
    cfg['scenes']['threshold']=90.
    second=review_stage(req)
    assert second['scenes']!=first['scenes'] and second['frames_dir']!=first['frames_dir']
