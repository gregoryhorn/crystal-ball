import importlib
import io
import json
from pathlib import Path
import pytest
from crystal_ball.engines.setup.plan import make_plan, patch_config

installer=importlib.import_module('crystal_ball.engines.setup.install')

class Interactive(io.StringIO):
    def isatty(self): return True


def test_print_only_and_noninteractive(tmp_path,monkeypatch):
    from crystal_ball import setup
    assert 'commands' in setup.instructions()
    def forbidden(*a,**k): raise AssertionError('side effect before consent')
    monkeypatch.setattr(installer,'provision',forbidden)
    with pytest.raises(RuntimeError,match='interactive'):
        installer.install(stdin=io.StringIO('yes\n'))


@pytest.mark.parametrize('answer',['n\n','\n',''])
def test_decline_eof_no_writes(tmp_path,monkeypatch,answer):
    plan=make_plan()
    monkeypatch.setattr(installer,'make_plan',lambda engine:plan)
    def forbidden(*a): raise AssertionError('side effect before yes')
    monkeypatch.setattr(installer,'validate_platform',forbidden)
    monkeypatch.setattr(installer,'provision',forbidden)
    output=io.StringIO()
    assert installer.install(stdin=Interactive(answer),output=output)['status']=='declined'
    assert output.getvalue().count('Install selected engines and models?')==1
    assert all(not Path(e['generation']).exists() for e in plan['engines'])


def test_patch_preserves_unrelated_and_comments():
    text='# comment\ncache_dir = "cache"\n[hear]\n# engine\npython = "old" # keep me\nmodel = "id"\n[judge]\nbackend = "off"\n'
    result=patch_config(text,{'hear':{'python':'C:/new/python.exe','device':'cpu'}})
    assert '# comment' in result and '# keep me' in result and '# engine' in result
    assert '[judge]\nbackend = "off"' in result
    assert 'C:/new/python.exe' in result


def test_config_race_unchanged(tmp_path):
    target=tmp_path/'config.toml'; target.write_text('[judge]\nbackend="off"\n')
    plan={'config':str(target),'original_digest':'different'}
    before=target.read_bytes()
    with pytest.raises(RuntimeError,match='changed concurrently'):
        installer.commit_config(plan,{'hear':{'python':'new'}})
    assert target.read_bytes()==before


def test_success_one_confirmation_and_all_selected(monkeypatch,tmp_path):
    target=tmp_path/'config.toml'
    target.write_text('# original\n[judge]\nbackend="off"\n')
    plan=make_plan()
    plan['config']=str(target); plan['original_digest']=installer.digest(target.read_bytes())
    monkeypatch.setattr(installer,'make_plan',lambda e:plan)
    monkeypatch.setattr(installer,'validate_platform',lambda:None)
    calls=[]
    def provision(entry,python):
        calls.append(entry['engine'])
        return {'python':entry['python'],'model':'local','device':'cpu'}
    monkeypatch.setattr(installer,'provision',provision)
    output=io.StringIO()
    result=installer.install(stdin=Interactive('yes\n'),output=output)
    assert result['status']=='installed' and calls==['hear','see']
    assert output.getvalue().count('Install selected engines and models?')==1
    assert '# original' in target.read_text() and 'backend="off"' in target.read_text()
    assert len(list(tmp_path.glob('config.toml.backup-*')))==1


def test_failed_second_engine_keeps_config(monkeypatch,tmp_path):
    target=tmp_path/'config.toml'; target.write_text('# prior\n')
    plan=make_plan(); plan['config']=str(target)
    monkeypatch.setattr(installer,'make_plan',lambda e:plan)
    monkeypatch.setattr(installer,'validate_platform',lambda:None)
    def provision(entry,python):
        if entry['engine']=='see': raise RuntimeError('probe failed')
        return {'python':'new'}
    monkeypatch.setattr(installer,'provision',provision)
    with pytest.raises(RuntimeError,match='probe failed'):
        installer.install(stdin=Interactive('y\n'),output=io.StringIO())
    assert target.read_text()=='# prior\n'


def test_read_install_refuses():
    with pytest.raises(ValueError,match='external Tesseract'):
        make_plan('read')


@pytest.mark.parametrize('phase',['pip','download','probe'])
def test_provision_failure_records_generation_no_config(tmp_path,monkeypatch,phase):
    entry=make_plan('hear')['engines'][0]
    entry.update(generation=str(tmp_path/'generation'),python=str(tmp_path/'generation/Scripts/python.exe'))
    target=tmp_path/'prior.toml'; target.write_text('# working\n')
    def command(argv,*args):
        if phase=='pip' and 'pip' in argv: raise RuntimeError('pip injected failure')
    def request(argv,*args):
        if '-c' in argv:
            compile(argv[argv.index('-c')+1],'<model downloader>','exec')
            if phase=='download': raise RuntimeError('download injected failure')
            return {'path':str(tmp_path/'model')}
        raise RuntimeError('probe injected failure')
    monkeypatch.setattr(installer,'command',command)
    monkeypatch.setattr(installer,'process_json',request)
    with pytest.raises(RuntimeError,match='injected failure'):
        installer.provision(entry,'python')
    manifest=json.loads((tmp_path/'generation/manifest.json').read_text())
    assert manifest['state']=='failed' and target.read_text()=='# working\n'


def test_validated_generation_reuse_does_not_install(tmp_path,monkeypatch):
    entry=make_plan('see')['engines'][0]
    entry.update(generation=str(tmp_path/'not-created'),reuse=True,model=str(tmp_path/'model'))
    def forbidden(*args): raise AssertionError('reuse must not install')
    monkeypatch.setattr(installer,'command',forbidden)
    calls=[]
    monkeypatch.setattr(installer,'process_json',lambda *args: calls.append(args) or {'offline':True})
    assert installer.provision(entry,'python')['model']==entry['model']
    assert len(calls)==1 and not (tmp_path/'not-created').exists()


def test_toml_comment_inside_string_and_no_trailing_newline():
    from crystal_ball.engines.setup.plan import trailing_comment
    assert trailing_comment("python = 'C:/my # path/python.exe' # actual")== ' # actual'
    result=patch_config("[hear]\nmodel='id'",{'hear':{'python':'native'}})
    assert "model='id'\n" in result
