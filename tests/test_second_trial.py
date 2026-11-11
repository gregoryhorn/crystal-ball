"""Second live-trial regressions, using local synthetic media and no models."""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from crystal_ball import api, core, hermes
from crystal_ball.cache import dumps
from crystal_ball.config import load
from crystal_ball.util import foreign_python_env, same_python_env


def installer():
    path=Path(__file__).resolve().parents[1]/'scripts/install_hermes.py'
    spec=importlib.util.spec_from_file_location('installer',path)
    tool=importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)
    return tool


@pytest.mark.parametrize('legacy',[False,True])
@pytest.mark.parametrize('edited',[False,True])
def test_config_is_user_data_across_reinstall_uninstall(tmp_path,capsys,legacy,edited):
    tool=installer()
    source=tmp_path/'source.toml'; source.write_text('# original user settings\n')
    home=tmp_path/'profile'
    tool.install(home,source)
    config=home/'crystal-ball.toml'; manifest=home/tool.MANIFEST
    data=json.loads(manifest.read_text())
    assert data['user_data']==['crystal-ball.toml']
    assert 'crystal-ball.toml' not in data['files']
    if legacy:
        data.pop('user_data')
        data['files']['crystal-ball.toml']=tool.digest(config.read_bytes())
        manifest.write_text(json.dumps(data))
    if edited:
        config.write_text('# changed user settings\n')
    expected=config.read_bytes()
    source.write_text('# replacement must not overwrite\n')
    # Uninstall old hash-only manifests directly, as well as current manifests.
    tool.install(home,uninstall=True)
    assert config.read_bytes()==expected
    assert f'kept user config: {config}' in capsys.readouterr().out
    tool.install(home,source)
    tool.install(home,source)
    assert config.read_bytes()==expected
    assert json.loads(manifest.read_text())['user_data']==['crystal-ball.toml']
    tool.install(home,uninstall=True)
    assert config.read_bytes()==expected
    assert not (home/'plugins/crystal-ball').exists()


def test_same_interpreter_keeps_injected_paths_across_two_children(tmp_path,monkeypatch):
    injected=tmp_path/'runtime-packages'; injected.mkdir()
    (injected/'runtime_marker.py').write_text('value = 42\n')
    monkeypatch.setattr(sys, "path", [str(injected), *sys.path])
    monkeypatch.setenv('PYTHONPATH',str(tmp_path/'poison'))
    monkeypatch.setenv('PYTHONHOME',str(tmp_path/'poison'))
    # This path exists only in the running parent's sys.path, not its executable.
    code='''import sys
from crystal_ball.util import same_python_env
import runtime_marker
import subprocess
subprocess.run([sys.executable, '-c', 'import runtime_marker; assert runtime_marker.value == 42'], env=same_python_env(), check=True)
'''
    subprocess.run([sys.executable,'-c',code],env=same_python_env(),check=True,
                   capture_output=True,text=True,timeout=15)


def test_hermes_host_worker_uses_effective_path(tmp_path,monkeypatch):
    import crystal_ball.util as util
    injected=tmp_path/'extra'; injected.mkdir()
    monkeypatch.setattr(sys, "path", [str(injected), *sys.path])
    def forbidden(*args,**kwargs):
        raise AssertionError('same interpreter must not use foreign_python_env')
    monkeypatch.setattr(util,'foreign_python_env',forbidden)
    original=subprocess.Popen
    seen=[]
    def launch(cmd,*args,**kwargs):
        seen.append(kwargs['env']['PYTHONPATH'])
        assert str(injected) in kwargs['env']['PYTHONPATH'].split(os.pathsep)
        return original(cmd,*args,**kwargs)
    monkeypatch.setattr(subprocess,'Popen',launch)
    # A validation error avoids model work while exercising the real tool process.
    result=hermes.invoke('find',text='test',top=0)
    assert 'top must be positive' in result['error']
    assert seen


def test_real_stages_from_host_without_numpy_or_pil(tmp_path):
    video=tmp_path/'silent.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i',
                    'color=s=160x90:r=25:d=0.4','-an','-threads','1',str(video)],
                   check=True,capture_output=True,timeout=15)
    # A distinct configured engine path makes accidental host execution detectable.
    engine=tmp_path/'see-python'; launches=tmp_path/'launches'
    engine.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> '+shlex.quote(str(launches))+
                      '\nexec '+shlex.quote(sys.executable)+' "$@"\n')
    engine.chmod(0o755)
    cfg=load(); cfg['see']['python']=str(engine); cfg['scenes']['python']='missing-scenes'
    run=tmp_path/'run'; run.mkdir()
    req={'file':str(video),'run_dir':str(run),'config':cfg,'cache_dir':cfg['cache_dir'],
         'platform':'youtube','rules':{'terms':[],'active':''}}
    code='''import importlib.util, json, sys
sys.path.insert(0, sys.argv[1])
assert importlib.util.find_spec('numpy') is None
assert importlib.util.find_spec('PIL') is None
from crystal_ball import core
from crystal_ball.frames import probe
from crystal_ball.senses.read import read_text
from crystal_ball.senses.hear import voice_balance
req=json.loads(sys.argv[2]); req['meta']=probe(req['file'])
review=core.run_stage('review',req)
assert review.get('frames'), review
ocr=core.run_stage('ocr',{**req,'review':review})
assert ocr.get('lines') == [], ocr
editing=core.run_stage('editing',req)
assert {r['id']:r['status'] for r in editing['checks']} == {'flash':'PASS','pacing':'PASS'}, editing
assert read_text(req['file'],0,req['config'])['lines']==[]
assert core.run_stage('audio',req)['checks'][0]['summary']=='no audio stream'
# No audio makes the balance worker fail cleanly at ffmpeg, rather than on numpy.
try:
    voice_balance(req['file'],{'segments':[]},req['config'])
except Exception as exc:
    assert 'ModuleNotFoundError' not in str(exc), str(exc)
else:
    raise AssertionError('silent video cannot yield PCM')
print('ok')
'''
    result=subprocess.run([sys.executable,'-S','-c',code,
                           str(Path(core.__file__).resolve().parent.parent),dumps(req)],
                          env=foreign_python_env(),capture_output=True,text=True,timeout=45)
    assert result.returncode==0,result.stdout+result.stderr
    assert result.stdout.strip()=='ok'
    invoked=launches.read_text()
    for stage in ('review','ocr','editing'):
        assert 'crystal_ball.stage_worker '+stage in invoked


@pytest.mark.parametrize('stage',['review','ocr','editing'])
def test_unavailable_see_runtime_skips_with_reason(tmp_path,stage):
    cfg=load(); cfg['see']['python']=str(tmp_path/'missing-see')
    result=core.run_stage(stage,{'run_dir':str(tmp_path),'config':cfg,'cache_dir':cfg['cache_dir']})
    assert result['checks'][0]['status']=='SKIP'
    assert 'missing-see' in result['checks'][0]['summary']


def test_host_doctor_reports_missing_imports_and_routing(monkeypatch):
    from crystal_ball import doctor
    original=doctor.importlib.import_module
    def no_optional(name,*args,**kwargs):
        if name in {'numpy','PIL','torch','transformers'}:
            raise ModuleNotFoundError('host lacks '+name)
        return original(name,*args,**kwargs)
    monkeypatch.setattr(doctor.importlib,'import_module',no_optional)
    cfg=load()
    for kind in ('hear','see','rhythm','scenes'):
        cfg[kind]['python']='missing-'+kind
    result=doctor.doctor(cfg)
    host=next(r for r in result['checks'] if r['engine']=='host')
    assert host['status']=='WARN'
    assert all('host lacks '+name in value for name,value in host['modules'].items())
    assert all(name in host['detail'] for name in ('signal','review','OCR','pacing/flash','voice balance'))
    assert host['see_python']=='missing-see'
    assert host['python']==sys.executable


@pytest.mark.parametrize('with_fix',[False,True])
def test_compact_keeps_every_nonpass_identity(tmp_path,with_fix):
    checks=[core.row('fail','FAIL','failure '*80,[[1,2]],'fix '*100)]
    checks += [core.row('warn-'+str(i),'WARN','تنبيه '*80,[[1,2]],'fix '*100) for i in range(10)]
    checks += [core.row('skip-'+str(i),'SKIP','unavailable '*80) for i in range(3)]
    checks += [core.row('good','PASS','ok')]
    doc={'platform':'youtube','report':str(tmp_path/'report.html'),
         'frames_dir':str(tmp_path/'frames'),'checks':checks}
    result=core.compact(doc)
    if with_fix:
        result['fix']={'status':'written','file':str(tmp_path/'fixed.mp4'),
                       'verdict':'WARN','report':str(tmp_path/'fixed-report.html')}
    result=api.compact_action('fix' if with_fix else 'check',result)
    expected={(r['id'],r['status']) for r in checks if r['status']!='PASS'}
    assert {(r['id'],r['status']) for r in result['items']}==expected
    assert result['omitted_details']>0
    assert len(dumps(result).encode())<=1500


def test_host_stage_preserves_injected_auxiliary_package(tmp_path,monkeypatch):
    import crystal_ball.util as util
    package=tmp_path/'injected'/'agent'; package.mkdir(parents=True)
    (package/'__init__.py').write_text('')
    (package/'auxiliary_client.py').write_text(
        'def call_llm(**kwargs): return {"checks": []}\n'
        'def extract_content_or_reasoning(value):\n'
        '    import json\n'
        '    return json.dumps(value)\n')
    monkeypatch.setattr(sys, "path", [str(package.parent), *sys.path])
    def forbidden(*args,**kwargs):
        raise AssertionError('host stage must not use foreign_python_env')
    monkeypatch.setattr(util,'foreign_python_env',forbidden)
    cfg=load(); cfg['judge']['backend']='hermes-auxiliary'
    sheet=tmp_path/'sheet.jpg'; sheet.write_bytes(b'synthetic image bytes')
    req={'run_dir':str(tmp_path),'config':cfg,'cache_dir':cfg['cache_dir'],
         'meta':{'duration':1},'rules':{'active':''},
         'review':{'contact_sheet':str(sheet),'frames':[{'time':0,'path':str(sheet)}]}}
    result=core.run_stage('vision',req)
    assert result['checks'][0]['status']=='PASS',result


def test_see_runtime_without_optional_modules_skips_cleanly(tmp_path):
    video=tmp_path/'silent.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i',
                    'color=s=160x90:r=25:d=0.4','-an','-threads','1',str(video)],
                   check=True,capture_output=True,timeout=15)
    engine=tmp_path/'empty-see-python'
    engine.write_text('#!/bin/sh\nexec '+shlex.quote(sys.executable)+' -S "$@"\n')
    engine.chmod(0o755)
    cfg=load(); cfg['see']['python']=str(engine); cfg['scenes']['python']='missing-scenes'
    req={'file':str(video),'run_dir':str(tmp_path),'config':cfg,'cache_dir':cfg['cache_dir'],
         'platform':'youtube','meta':core.probe(video),'rules':{'terms':[],'active':''},
         'review':{'frames':[{'time':0,'path':'unused.jpg'}]}}
    for stage in ('review','ocr','editing'):
        result=core.run_stage(stage,req)
        assert result['checks'],result
        assert all(r['status']=='SKIP' for r in result['checks']),result
        assert all('ModuleNotFoundError' in r['summary'] for r in result['checks']),result
