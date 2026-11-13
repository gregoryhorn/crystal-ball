"""Native release banners and disabled models have stable offline semantics."""
import importlib
from pathlib import Path
import pytest
from crystal_ball.config import load
from crystal_ball.cache import runtime_stamp


@pytest.mark.parametrize('release,status',[('n9.0.1-11-ge47273f4d9','PASS'),('6.1.2','PASS'),('n6.0','FAIL'),('5.1.6','FAIL'),('unknown','FAIL')])
def test_doctor_native_release_banner(tmp_path,monkeypatch,release,status):
    module=importlib.import_module('crystal_ball.doctor')
    original=module.command
    def command(argv,*args,**kwargs):
        name=Path(argv[0]).stem
        if name in {'ffmpeg','ffprobe'}:
            return f'{name} version {release} Copyright FFmpeg developers\n'
        return original(argv,*args,**kwargs)
    monkeypatch.setattr(module,'command',command)
    cfg=load()
    for section in ('hear','see','rhythm','scenes'):
        cfg[section]['python']=str(tmp_path/'absent-engine')
    rows={r['engine']:r for r in module.doctor(cfg)['checks']}
    assert rows['ffmpeg']['status']==status
    assert rows['ffprobe']['status']==status


def test_disabled_models_do_not_stamp_cwd_or_unrelated_hub(tmp_path,monkeypatch):
    cfg=load()
    for section in ('hear','see'):
        cfg[section]['model']=''
    cfg['read']['tessdata']=str(tmp_path/'tessdata')
    cwd=tmp_path/'work'; cwd.mkdir()
    (cwd/'unrelated.txt').write_text('not a model')
    hub=tmp_path/'hub'
    refs=hub/'models--unrelated-model'/'refs'; refs.mkdir(parents=True)
    (refs/'main').write_text('unrelated generation')
    monkeypatch.chdir(cwd)
    monkeypatch.setenv('HF_HUB_CACHE',str(hub))
    facts=runtime_stamp(cfg)
    assert not any(Path(value[0])==cwd/'unrelated.txt' for value in facts)
    assert not any('unrelated-model' in value[0] for value in facts)
