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
    assert all(rows[name]['status']=='PASS' for name in ('ffmpeg','ffprobe','tesseract'))
    assert rows['hear']['status']=='WARN' and rows['see']['status']=='WARN'
    assert rows['judge']['status']=='WARN'
    assert 'sha256' in rows['ocr eng'] and 'PASS' in table(result)


def test_cli_setup_and_input_errors(capsys):
    assert cli.main(['setup','hear'])==0
    printed=capsys.readouterr().out
    assert 'hear.lock' in printed and 'download_model' in printed
    assert cli.main(['find'])==2
    assert 'provide text or --image' in capsys.readouterr().err
    assert cli.main(['find','test','--top','0'])==2
    assert '--top must be positive' in capsys.readouterr().err


def test_module_entry_point():
    result=subprocess.run([sys.executable,'-E','-m','crystal_ball','--version'],capture_output=True,text=True,timeout=10)
    assert result.returncode==0 and result.stdout.strip()=='1.1.0'
