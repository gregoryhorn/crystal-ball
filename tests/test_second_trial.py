"""Second live-trial regressions, using local synthetic media and no models."""
import importlib.util
import copy
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


def test_real_stages_from_host_without_numpy_or_pil(tmp_path, native_engine):
    video=tmp_path/'silent.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i',
                    'color=s=160x90:r=25:d=0.4','-an','-threads','1',str(video)],
                   check=True,capture_output=True,timeout=15)
    # A distinct configured engine path makes accidental host execution detectable.
    engine,launches=native_engine('see-python',False)
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
assert core.core_media_python(req['config']) == req['config']['see']['python']
review=core.run_stage('review',req)
assert review.get('frames'), review
ocr=core.run_stage('ocr',{**req,'review':review})
from crystal_ball.platforms.executables import resolve_tool
try:
    resolve_tool('tesseract')
    has_ocr=True
except FileNotFoundError:
    has_ocr=False
def check_ocr(value):
    if has_ocr:
        assert value.get('lines') == [], value
    else:
        item=value['checks'][0]
        assert item['status']=='SKIP' and item['skip_reason']=='unavailable', value
        assert item['summary']=='Not checked: OCR engine unavailable', value
check_ocr(ocr)
editing=core.run_stage('editing',req)
assert {r['id']:r['status'] for r in editing['checks']} == {'flash':'PASS','pacing':'PASS'}, editing
check_ocr(read_text(req['file'],0,req['config']))
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
    # -S only hides sites in this process; normal child launches restore them.
    # A real core-less host keeps that isolation across the worker boundary.
    import venv
    host=tmp_path/'thin-host'
    venv.EnvBuilder(with_pip=False,system_site_packages=False).create(host)
    host_python=host/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    result=subprocess.run([str(host_python),'-c',code,
                           str(Path(core.__file__).resolve().parent.parent),dumps(req)],
                          env=foreign_python_env(),capture_output=True,text=True,timeout=45)
    assert result.returncode==0,result.stdout+result.stderr
    assert result.stdout.strip()=='ok'
    invoked=launches.read_text()
    for stage in ('review','ocr','editing'):
        assert 'crystal_ball.stage_worker '+stage in invoked


@pytest.mark.parametrize('stage',['review','ocr','editing'])
def test_unavailable_see_runtime_skips_with_reason(tmp_path,stage,monkeypatch):
    # Intentional core-first routing change: this assertion covers a thin host.
    monkeypatch.setattr(core,'core_media_python',lambda cfg:cfg['see']['python'])
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
    original=copy.deepcopy(doc)
    result=core.compact(doc)
    if with_fix:
        result['fix']={'status':'written','file':str(tmp_path/'fixed.mp4'),
                       'verdict':'WARN','report':str(tmp_path/'fixed-report.html')}
    result=api.compact_action('fix' if with_fix else 'check',result)
    expected={(r['id'],r['status']) for r in checks if r['status']!='PASS'}
    assert {(r['id'],r['status']) for r in result['items']}==expected
    assert result['omitted_details']>0
    assert len(dumps(result).encode())<=1500
    assert result['not_checked_omitted_count']==3-len(result['not_checked'])
    assert result.get('more_not_checked_in_report',False)==(result['not_checked_omitted_count']>0)
    assert doc==original


@pytest.mark.parametrize('skip_count',[0,3])
def test_compact_untrimmed_omissions(skip_count):
    checks=[core.row('same','SKIP','reason '+str(i)) for i in range(skip_count)]
    doc={'checks':checks,'platform':'youtube','report':'report.html','frames_dir':'frames'}
    original=copy.deepcopy(doc)
    result=core.compact(doc)
    assert result['not_checked_omitted_count']==0
    assert 'more_not_checked_in_report' not in result
    assert len(result['not_checked'])==skip_count
    assert result['counts']['SKIP']==skip_count
    assert result['report']=='report.html'
    assert result['verdict']==('WARN' if skip_count else 'PASS')
    result.pop('not_checked_omitted_count')
    result['more_not_checked_in_report']=True
    assert core.fit_compact(result)['not_checked_omitted_count']==0
    assert 'more_not_checked_in_report' not in result
    assert doc==original


@pytest.mark.parametrize('removed',[1,3])
def test_compact_exact_detail_entry_count_and_refits(monkeypatch,removed):
    raw={'verdict':'WARN','counts':{'PASS':0,'WARN':0,'FAIL':0,'SKIP':3},
         'items':[{'id':'duplicate','status':'SKIP'}],
         'not_checked':['duplicate: '+('تعذر '*25)+str(i) for i in range(3)],
         'report':'report.html','omitted_details':0,'not_checked_omitted_count':0}
    expected=copy.deepcopy(raw)
    expected['not_checked']=expected['not_checked'][:3-removed]
    expected.update(not_checked_omitted_count=removed,more_not_checked_in_report=True)
    monkeypatch.setattr(core,'MAX_BYTES',len(dumps(expected).encode()))
    result=core.fit_compact(raw)
    assert result==expected
    assert core.fit_compact(result)==expected
    assert api.compact_action('check',result)==expected
    if removed==1:
        result['fix']={'status':'no_safe_fix','reason':'review source '*25}
        result=api.compact_action('fix',result)
        assert result['not_checked_omitted_count']==3-len(result['not_checked'])
        assert result['not_checked_omitted_count']>removed
        assert result['more_not_checked_in_report'] is True
    assert result['counts']['SKIP']==3
    assert result['items']==[{'id':'duplicate','status':'SKIP'}]
    assert len(dumps(result).encode())<=core.MAX_BYTES


@pytest.mark.parametrize('count',[0,2])
@pytest.mark.parametrize('flag',[None,False,True])
def test_compact_legacy_flag_is_derived_before_early_return(count,flag):
    raw={'items':[],'not_checked':[],'not_checked_omitted_count':count}
    if flag is not None:
        raw['more_not_checked_in_report']=flag
    result=core.fit_compact(raw)
    assert result['not_checked_omitted_count']==count
    assert result.get('more_not_checked_in_report',False)==(count>0)
    assert ('more_not_checked_in_report' in result)==(count>0)


def test_compact_shortening_is_not_an_omitted_entry():
    checks=[core.row('skip','SKIP','short reason'),core.row('warning','WARN','تنبيه '*100,[], 'fix '*100)]
    doc={'checks':checks,'platform':'youtube','report':'report.html','frames_dir':'frames'}
    result=core.compact(doc)
    assert result['not_checked']==['skip: short reason']
    assert result['not_checked_omitted_count']==0
    assert 'more_not_checked_in_report' not in result
    assert len(dumps(result).encode())<=1500


def test_compact_counts_metadata_before_budget_return(monkeypatch):
    raw={'items':[{'id':'skip','status':'SKIP'}],'not_checked':['reason '*20],
         'counts':{'SKIP':1},'verdict':'WARN','report':'report.html','omitted_details':0}
    monkeypatch.setattr(core,'MAX_BYTES',len(dumps(raw).encode()))
    result=core.fit_compact(raw)
    assert result['not_checked']==[]
    assert result['not_checked_omitted_count']==1
    assert result['more_not_checked_in_report'] is True
    assert len(dumps(result).encode())<=core.MAX_BYTES


def test_compact_unavoidable_overflow_retains_mandatory_evidence():
    raw={'items':[{'id':'skip','status':'SKIP'}],'not_checked':[],
         'counts':{'SKIP':1},'verdict':'WARN','report':'x'*1600}
    with pytest.raises(ValueError,match='mandatory identities, paths and metadata retained'):
        core.fit_compact(raw)
    assert raw['items']==[{'id':'skip','status':'SKIP'}]
    assert raw['counts']=={'SKIP':1} and raw['report']=='x'*1600
    assert raw['not_checked_omitted_count']==0


def test_maintenance_cli_and_hermes_reports_agree(tmp_path,ocr_required):
    video=tmp_path/'text.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i',
                    'color=c=0x173f65:s=720x1280:r=25:d=3','-vf',
                    "drawtext=font="+('Arial' if os.name=='nt' else 'DejaVuSans-Bold')+":text='NEW PLACE':fontsize=64:fontcolor=white:x=100:y=1190",
                    '-an','-threads','1',str(video)],check=True,capture_output=True,timeout=20)
    rules=tmp_path/'rules.md'; rules.write_text('Use "NEW PLACES".\n')
    with Path(os.environ['CRYSTAL_BALL_CONFIG']).open('a') as config:
        config.write('\n[rules]\nfiles = ['+json.dumps(str(rules))+']\n')
    cli=subprocess.run([sys.executable,'-m','crystal_ball','check',str(video),
                        '--platform','shorts','--expect-text','NEW PLACES','--json'],
                       capture_output=True,text=True,timeout=45)
    assert cli.returncode==1,cli.stderr  # The intentional safe-zone violation FAILs.
    cli_result=json.loads(cli.stdout)
    adapter_result=hermes.invoke('check',file=str(video),platform='shorts',expect_text=['NEW PLACES'])
    for result in (cli_result,adapter_result):
        assert len(dumps(result).encode())<=1500
        report=Path(result['report'])
        assert report.is_file()
        doc=json.loads(report.with_name('full.json').read_text())
        checks=doc['checks']
        assert result['counts']=={s:sum(r['status']==s for r in checks) for s in ('PASS','WARN','FAIL','SKIP')}
        assert result['not_checked_omitted_count']==result['counts']['SKIP']-len(result['not_checked'])
        assert result.get('more_not_checked_in_report',False)==(result['not_checked_omitted_count']>0)
        assert {(r['id'],r['status']) for r in result['items']}=={(r['id'],r['status']) for r in checks if r['status']!='PASS'}
        # Rule extraction also yields PLACES; that is a distinct expected/candidate pair.
        spelling=[r for r in checks if r['id']=='ocr_spelling' and 'vs expected "NEW PLACES"' in r['summary']]
        assert len(spelling)==1 and len(spelling[0]['timestamps'])>=2
        assert 'similarity >=79%, OCR confidence >=70, >=2 sampled frames' in spelling[0]['summary']
        assert doc['stages']['ocr']['lines']
        assert any(r['id']=='expected_text' for r in checks)
    assert cli_result['report']==adapter_result['report']
    assert adapter_result.get('cached',True)


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


def test_see_runtime_without_optional_modules_skips_cleanly(tmp_path,native_engine,monkeypatch):
    monkeypatch.setattr(core,'core_media_python',lambda cfg:cfg['see']['python'])
    from crystal_ball import workers
    monkeypatch.setattr(workers,'core_media_python',lambda cfg:cfg['see']['python'])
    video=tmp_path/'silent.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i',
                    'color=s=160x90:r=25:d=0.4','-an','-threads','1',str(video)],
                   check=True,capture_output=True,timeout=15)
    engine,_=native_engine('empty-see-python',True)
    cfg=load(); cfg['see']['python']=str(engine); cfg['scenes']['python']='missing-scenes'
    req={'file':str(video),'run_dir':str(tmp_path),'config':cfg,'cache_dir':cfg['cache_dir'],
         'platform':'youtube','meta':core.probe(video),'rules':{'terms':[],'active':''},
         'review':{'frames':[{'time':0,'path':'unused.jpg'}]}}
    for stage in ('review','ocr','editing'):
        result=core.run_stage(stage,req)
        assert result['checks'],result
        assert all(r['status']=='SKIP' for r in result['checks']),result
        assert all('ModuleNotFoundError' in r['summary'] for r in result['checks']),result
