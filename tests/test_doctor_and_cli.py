import json
import subprocess
import sys
from pathlib import Path
from crystal_ball import cli
from crystal_ball.config import load
from crystal_ball.doctor import doctor,table


def test_offline_doctor_reports_versions_and_missing_engines(tmp_path,monkeypatch):
    cfg=load(); cfg['hear']['python']=str(tmp_path/'missing-hear'); cfg['see']['python']=str(tmp_path/'missing-see')
    result=doctor(cfg)
    assert result['downloads'] is False and result['live_inference'] is False
    rows={r['engine']:r for r in result['checks']}
    assert all(rows[name]['status']=='PASS' for name in ('ffmpeg','ffprobe'))
    from crystal_ball.platforms.executables import resolve_tool
    try:
        tesseract=resolve_tool('tesseract')
    except FileNotFoundError:
        assert rows['tesseract']['status']=='WARN'
        assert rows['tesseract']['detail'].startswith('Not checked: ')
        assert rows['ocr models']['status']=='WARN'
        assert rows['ocr models']['detail'].startswith('Not checked: ')
    else:
        assert rows['tesseract']['status']=='PASS'
        assert rows['tesseract']['path']==tesseract
        from crystal_ball.util import command
        langs=command([tesseract,'--list-langs'],10).splitlines()
        if 'eng' in langs:
            assert rows['ocr eng']['status']=='PASS' and len(rows['ocr eng']['sha256'])==64
        else:
            assert rows['ocr eng']['status']=='WARN'
    assert rows['hear']['status']=='WARN' and rows['see']['status']=='WARN'
    assert rows['hear']['detail'].startswith('Not checked: ')
    assert rows['see']['detail'].startswith('Not checked: ')
    assert rows['judge']['status']=='WARN'
    assert 'PASS' in table(result)


def test_doctor_missing_optional_tesseract_is_not_checked(tmp_path,monkeypatch):
    import importlib
    module=importlib.import_module('crystal_ball.doctor')
    resolve=module.resolve_tool
    run=module.command
    def without_tesseract(name,*args,**kwargs):
        if Path(name).stem=='tesseract':
            raise FileNotFoundError('fixture: optional Tesseract absent')
        return resolve(name,*args,**kwargs)
    def command_without_tesseract(argv,*args,**kwargs):
        if Path(argv[0]).stem=='tesseract':
            raise FileNotFoundError('fixture: optional Tesseract absent')
        return run(argv,*args,**kwargs)
    monkeypatch.setattr(module,'resolve_tool',without_tesseract)
    monkeypatch.setattr(module,'command',command_without_tesseract)
    cfg=load()
    cfg['see']['python']=str(tmp_path/'missing-see')
    rows={r['engine']:r for r in doctor(cfg)['checks']}
    for name in ('tesseract','ocr models'):
        assert rows[name]['status']=='WARN'
        assert rows[name]['detail'].startswith('Not checked: ')
        assert 'optional Tesseract absent' in rows[name]['detail']
    assert all(rows[name]['status']=='PASS' for name in ('ffmpeg','ffprobe'))


def test_cli_setup_and_input_errors(capsys):
    assert cli.main(['setup','hear'])==0
    printed=capsys.readouterr().out
    import os
    lock='hear-cpu.lock' if os.name=='nt' else 'hear.lock'
    interpreter='Scripts\\python.exe' if os.name=='nt' else 'bin/python'
    assert lock in printed and 'download_model' in printed
    assert interpreter in printed
    if os.name=='nt':
        assert 'PowerShell' in printed and 'sudo' not in printed
    assert cli.main(['find'])==2
    assert 'provide text or --image' in capsys.readouterr().err
    assert cli.main(['find','test','--top','0'])==2
    assert '--top must be positive' in capsys.readouterr().err


def test_module_entry_point():
    result=subprocess.run([sys.executable,'-E','-m','crystal_ball','--version'],capture_output=True,text=True,timeout=10)
    assert result.returncode==0 and result.stdout.strip()=='1.1.1'
