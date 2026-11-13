"""MA-r1 real-media dispatch and shared public-interface regressions."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from crystal_ball import core
from crystal_ball.applicability import omitted
from crystal_ball.config import load


def ffmpeg(*args):
    subprocess.run(['ffmpeg','-v','error','-nostdin','-threads','1',*map(str,args)], check=True, capture_output=True, timeout=30)


@pytest.fixture
def media(tmp_path, monkeypatch):
    monkeypatch.setenv('CRYSTAL_BALL_HEAR_MODEL', '')
    image = tmp_path/'still.png'
    still = Image.new('RGB', (320, 180), '#345678')
    ImageDraw.Draw(still).text((20,60), 'HELLO WORLD', fill='white')
    still.save(image)
    values = {'image':image}
    for name, source in [('audio-only','sine=f=440:r=48000:d=1'), ('silent','anullsrc=r=48000:cl=mono:d=1'), ('clipped','aevalsrc=clip(4*sin(2*PI*440*t)\\,-1\\,1):s=48000:d=1')]:
        path = tmp_path/(name+'.wav')
        ffmpeg('-f','lavfi','-i',source,'-c:a','pcm_s16le',path)
        values[name] = path
    for name in ('video','video-without-audio'):
        path = tmp_path/(name+'.mp4')
        args = ['-f','lavfi','-i','testsrc2=s=320x180:r=25:d=1']
        if name == 'video':
            args += ['-i',values['audio-only']]
        ffmpeg(*args,'-c:v','libx264','-threads','1','-pix_fmt','yuv420p',path)
        values[name] = path
    return values


def full(result):
    return json.loads(Path(result['report']).with_name('full.json').read_text())


@pytest.mark.parametrize('kind', ['image','audio-only','video','video-without-audio'])
def test_real_content_routes_and_reports(media, monkeypatch, kind):
    calls=[]
    real=core.run_stage
    def trace(stage, request, timeout=None):
        calls.append(stage)
        return real(stage,request,timeout)
    monkeypatch.setattr(core,'run_stage',trace)
    before=media[kind].read_bytes()
    result=core.quality_check(media[kind], platform='custom')
    doc=full(result)
    assert doc['media_kind']==kind
    assert any(r['id']=='decode' and r['status']=='PASS' for r in doc['checks']), doc
    if kind=='image':
        assert not {'editing','audio'} & set(calls)
        assert len(doc['stages']['review']['frames'])==1
        with Image.open(doc['stages']['review']['frames'][0]['path']) as still:
            assert still.size==(320,180)
        assert not any(r['id']=='frozen' and r['status']=='FAIL' for r in doc['checks'])
    if kind=='audio-only':
        assert not {'editing','review','ocr','vision'} & set(calls)
        assert {r['id'] for r in doc['checks']} >= {'silence','clipping','loudness measurement','true peak'}
        assert next(r for r in doc['checks'] if r['id']=='loudness')['skip_reason']=='not_requested'
    if kind=='video-without-audio':
        assert 'editing' in calls and 'audio' not in calls
        for identity in ('audio','silence','clipping','true peak','A/V drift','cut_sync'):
            assert all(r['status']=='SKIP' for r in doc['checks'] if r['id']==identity)
    skips=[r for r in doc['checks'] if r['status']=='SKIP']
    assert skips and all(r['summary'].startswith('Not checked: ') and r['skip_reason'] in {'not_applicable','not_requested','unavailable','dependency_failed'} for r in skips)
    assert len(core.dumps(result).encode())<=1500
    assert Path(result['report']).with_suffix('.html').is_file()
    assert media[kind].read_bytes()==before


def test_stale_platform_shape_and_cache(media):
    first=core.quality_check(media['image'], platform='youtube', shape='16:9')
    doc=full(first)
    assert doc['platform']=='custom'
    assert next(r for r in doc['checks'] if r['id']=='aspect')['status']=='PASS'
    assert core.quality_check(media['image'], platform='youtube', shape='16:9')['cached']
    mismatch=core.quality_check(media['image'], platform='youtube', shape='1:1')
    assert not mismatch['cached'] and mismatch['verdict']=='FAIL'
    assert next(r for r in full(mismatch)['checks'] if r['id']=='aspect')['status']=='FAIL'


@pytest.mark.parametrize('name,identity', [('silent','silence'),('clipped','clipping')])
def test_audio_real_findings(media,name,identity):
    doc=full(core.quality_check(media[name],platform='youtube'))
    assert doc['media_kind']=='audio-only' and doc['platform']=='custom'
    assert next(r for r in doc['checks'] if r['id']==identity)['status']=='FAIL'


@pytest.mark.parametrize('suffix',['png','wav','mp4'])
def test_corrupt_applicable_decode_fails(tmp_path,suffix,monkeypatch):
    path=tmp_path/('broken.'+suffix); path.write_bytes(b'corrupt supported media')
    calls=[]
    monkeypatch.setattr(core,'run_stage',lambda *a: calls.append(a))
    result=core.quality_check(path)
    assert result['verdict']=='FAIL' and calls==[]
    assert any(r.get('skip_reason')=='dependency_failed' for r in full(result)['checks'])


def test_unsupported_and_animated_not_guessed(tmp_path,monkeypatch):
    path=tmp_path/'unknown.bin'; path.write_bytes(b'unknown')
    assert core.quality_check(path)['verdict']=='WARN'
    animated=tmp_path/'animated.gif'
    Image.new('RGB',(16,16),'red').save(animated,save_all=True,append_images=[Image.new('RGB',(16,16),'blue')],duration=100,loop=0)
    calls=[]
    monkeypatch.setattr(core,'run_stage',lambda *a: calls.append(a))
    doc=full(core.quality_check(animated))
    assert doc['media_kind'] is None and calls==[]
    assert any(r['summary']=='Not checked: unsupported media kind' for r in doc['checks'])


@pytest.mark.parametrize('kind',['image','audio-only','video','video-without-audio'])
def test_cli_and_tool_share_real_media_report(media,kind):
    from crystal_ball.hermes import invoke
    args=[sys.executable,'-m','crystal_ball','check',str(media[kind]),'--platform','custom','--json']
    if kind!='audio-only':
        args+=['--shape','16:9']
    proc=subprocess.run(args,capture_output=True,text=True,timeout=45)
    assert proc.returncode==0,proc.stderr+proc.stdout
    cli=json.loads(proc.stdout)
    tool=invoke('check',file=str(media[kind]),platform='custom',**({'shape':'16:9'} if kind!='audio-only' else {}))
    assert tool['cached'] and tool['counts']==cli['counts'] and tool['verdict']==cli['verdict']
    assert full(tool)['media_kind']==kind


def test_decode_failure_excludes_dependents(media,monkeypatch):
    calls=[]
    def fail(stage,req,timeout=None):
        calls.append(stage)
        return {'checks':[core.row('decode','FAIL','fixture decoder error')]}
    monkeypatch.setattr(core,'run_stage',fail)
    result=core.quality_check(media['video'],platform='custom')
    assert result['verdict']=='FAIL' and calls==['signal']


def test_missing_signal_and_timeout_never_pass(media,monkeypatch):
    monkeypatch.setattr(core,'run_stage',lambda *args: {'checks':[omitted('signal','engine unavailable','unavailable')]})
    result=core.quality_check(media['image'],platform='custom')
    assert result['verdict']=='WARN'
    assert any(r['summary']=='Not checked: no completed applicable decode check' for r in full(result)['checks'])


def test_no_fake_still_spelling_corroboration():
    from crystal_ball.util import spelling_checks
    lines=[{'time':0.,'text':'NEW PLACE','confidence':95}]
    assert not any(r['status']=='FAIL' for r in spelling_checks(lines,['NEW PLACES']))


def test_audio_required_is_separate_output_mismatch(media):
    doc=full(core.quality_check(media['video-without-audio'],platform='custom',brief='Audio is required'))
    assert next(r for r in doc['checks'] if r['id']=='required_output')['status']=='FAIL'
    assert all(r['status']=='SKIP' for r in doc['checks'] if r['id'] in {'audio','silence','clipping','A/V drift'})


def test_selected_video_platform_still_enforces_codec(media,tmp_path):
    path=tmp_path/'unsupported-codec.mkv'
    ffmpeg('-i',media['video'],'-c:v','ffv1','-threads','1','-c:a','pcm_s16le',path)
    selected=full(core.quality_check(path,platform='youtube'))
    assert next(r for r in selected['checks'] if r['id']=='video codec')['status']=='FAIL'
    custom=full(core.quality_check(path,platform='custom'))
    assert not any(r['id']=='video codec' and r['status']=='FAIL' for r in custom['checks'])


def test_cover_art_is_audio_not_video(media,tmp_path):
    path=tmp_path/'cover.mp3'
    ffmpeg('-i',media['audio-only'],'-i',media['image'],'-map','0:a','-map','1:v','-c:a','libmp3lame','-c:v','png','-disposition:v','attached_pic',path)
    assert core.probe(path)['media_kind']=='audio-only'
    doc=full(core.quality_check(path,platform='youtube'))
    assert doc['media_kind']=='audio-only' and 'review' not in doc['stages']


def test_image_orientation_and_disguised_suffix(media,tmp_path):
    portrait=tmp_path/'oriented.jpg'
    image=Image.new('RGB',(180,320),'blue')
    exif=image.getexif(); exif[274]=6
    image.save(portrait,exif=exif)
    doc=full(core.quality_check(portrait,shape='16:9'))
    assert doc['media_kind']=='image'
    assert next(r for r in doc['checks'] if r['id']=='aspect')['status']=='PASS'
    disguised=tmp_path/'actually-video.png'
    disguised.write_bytes(media['video'].read_bytes())
    assert core.probe(disguised)['media_kind']=='video'


def test_missing_ocr_has_explicit_reason(media,monkeypatch,tmp_path):
    from crystal_ball.senses import read
    from crystal_ball.applicability import image_review
    req={'file':str(media['image']),'run_dir':str(tmp_path),'meta':core.probe(media['image']),'platform':'custom','rules':{'terms':[]}}
    req['review']=image_review(req)
    def missing(*args):
        raise FileNotFoundError('missing OCR executable')
    monkeypatch.setattr(read,'ocr_frames',missing)
    result=read.ocr_stage(req)
    assert result['checks']==[omitted('ocr','OCR engine unavailable','unavailable')]


@pytest.mark.parametrize('error',[FileNotFoundError('missing ffprobe'),subprocess.TimeoutExpired('ffprobe',.01)])
def test_missing_probe_and_probe_timeout_are_not_creative_failure(media,monkeypatch,error):
    def fail(path):
        raise error
    monkeypatch.setattr(core,'probe',fail)
    result=core.quality_check(media['image'])
    assert result['verdict']=='WARN' and result['counts']['FAIL']==0
    assert full(result)['checks'][0]['skip_reason']=='unavailable'
    assert any(r['summary']=='Not checked: no completed applicable decode check' for r in full(result)['checks'])


def test_stage_timeout_dependency_omission(media,monkeypatch):
    real=core.process_json
    def timeout(cmd,seconds,env=None):
        if 'signal' in cmd:
            raise subprocess.TimeoutExpired(cmd,seconds)
        return real(cmd,seconds,env)
    monkeypatch.setattr(core,'process_json',timeout)
    result=core.quality_check(media['video'],platform='custom')
    assert result['verdict']=='WARN'
    doc=full(result)
    assert 'review' not in doc['stages'] and 'audio' not in doc['stages']


def test_still_ocr_safe_zone_requires_shape_and_single_time(media,tmp_path):
    req={'file':str(media['image']),'run_dir':str(tmp_path),'meta':core.probe(media['image']),'platform':'custom','rules':{'terms':[]},'config':load()}
    review=core.run_stage('review',req)
    result=core.run_stage('ocr',{**req,'review':review})
    assert next(r for r in result['checks'] if r['id']=='ocr_safe_zone')['skip_reason']=='not_requested'
    assert {line['time'] for line in result.get('lines',[])} <= {0.0}


def test_shape_tolerance_and_generic_caption_inset(media,tmp_path):
    from crystal_ball.applicability import shape_checks
    for width, status in [(101,'PASS'), (102,'FAIL')]:
        req={'meta':{'width':width,'height':100,'media_kind':'image'},'shape':'1:1','platform':'custom'}
        assert next(r for r in shape_checks(req) if r['id']=='aspect')['status']==status
    caps=tmp_path/'safe.ass'
    caps.write_text('[Script Info]\nPlayResX: 320\nPlayResY: 180\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, Alignment, MarginL, MarginR, MarginV\nStyle: Default,Arial,12,2,24,24,24\n[Events]\nFormat: Layer, Start, End, Style, Text\nDialogue: 0,0:00:00.00,0:00:00.50,Default,HELLO\n')
    result=core.quality_check(media['video'],platform='custom',shape='16:9',captions=str(caps))
    check=next(r for r in full(result)['checks'] if r['id']=='caption zone')
    assert check['status']=='PASS' and 'generic 5% inset' in check['summary']
    from crystal_ball.senses.read import filter_lines
    lines=[{'text':'HELLO','time':0.0,'confidence':95,'box':[0,0,50,12]}]
    border=filter_lines(lines,{0.0:(320,180)},dict.fromkeys(('left','right','top','bottom'),.05),'generic 5% inset')
    assert border[0]['status']=='WARN' and 'UI' not in border[0]['summary']
    assert border[0]['timestamps']==[[0.0,0.0]]


def test_compact_exact_budget_and_cli_wire_boundary(monkeypatch,capsys):
    result={'items':[core.row('ocr','WARN','')], 'not_checked':[], 'report':'report.md', 'omitted_details':0, 'not_checked_omitted_count':0}
    result['items'][0]['summary']='x'*(1500-len(core.dumps(result).encode()))
    assert len(core.dumps(result).encode())==1500
    assert len(core.dumps(core.fit_compact(result)).encode())==1500
    from crystal_ball import cli
    monkeypatch.setattr(cli,'dispatch',lambda *args,**kwargs: result)
    assert cli.main(['check','fixture.png','--json'])==0
    assert len(capsys.readouterr().out.encode())==1500


def test_explicit_shape_does_not_cancel_selected_platform_rules(media):
    result=core.quality_check(media['video'],platform='shorts',shape='16:9')
    aspect=[r for r in full(result)['checks'] if r['id']=='aspect']
    assert any(r['status']=='PASS' and 'requested' in r['summary'] for r in aspect)
    assert any(r['status']=='FAIL' for r in aspect) and result['verdict']=='FAIL'


def test_unselected_platform_gate_calls_are_zero(media,tmp_path,monkeypatch):
    from crystal_ball.checks import load_qc
    qc=load_qc()
    def forbidden(*args,**kwargs):
        pytest.fail('video-platform checks executed without an applicable selection')
    monkeypatch.setattr(qc,'run_check',forbidden)
    for kind in ('image','audio-only','video','video-without-audio'):
        result=core.signal_stage({'file':str(media[kind]),'platform':'custom','meta':core.probe(media[kind]),'run_dir':str(tmp_path)})
        assert any(r['id']=='decode' and r['status']=='PASS' for r in result['checks'])

