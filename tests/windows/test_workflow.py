"""Real media worker flow, runnable on both Linux and native Windows."""
import json
from pathlib import Path
import subprocess
import sys
from crystal_ball.util import same_python_env


def test_core_only_unicode_report_and_tool_parity(tmp_path,monkeypatch):
    from crystal_ball.config import load
    from crystal_ball import core,hermes
    media=tmp_path/'media ü space.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=s=320x180:r=25:d=1',
                    '-f','lavfi','-i','sine=f=440:r=48000:d=1','-c:v','libx264','-threads','1','-c:a','aac','-shortest',str(media)],check=True,capture_output=True,timeout=20)
    # Nonexistent See/Hear must not disable core frames/signal/editing.
    monkeypatch.setenv('CRYSTAL_BALL_SEE_PYTHON','missing-optional-see')
    monkeypatch.setenv('CRYSTAL_BALL_RHYTHM_PYTHON','missing-optional-rhythm')
    monkeypatch.setenv('CRYSTAL_BALL_SCENES_PYTHON','missing-optional-scenes')
    env=same_python_env()
    cli=subprocess.run([sys.executable,'-m','crystal_ball','check',str(media),'--platform','youtube','--json'],
                       env=env,capture_output=True,text=True,encoding='utf-8',timeout=60)
    assert cli.returncode in (0,1),cli.stderr
    result=json.loads(cli.stdout)
    tool=hermes.invoke('check',file=str(media),platform='youtube')
    assert tool['counts']==result['counts'] and tool['verdict']==result['verdict']
    assert len(json.dumps(tool,ensure_ascii=False,separators=(',',':')).encode())<=1500
    report=Path(result['report'])
    assert report.is_file() and report.with_suffix('.html').is_file()
    full=json.loads((report.parent/'full.json').read_text(encoding='utf-8'))
    assert full['stages']['review']['frames']
    assert Path(full['stages']['review']['contact_sheet']).is_file()
    assert any(r['status']!='SKIP' for r in full['stages']['signal']['checks'])
    assert full['stages']['audio']['checks'][0]['status']=='SKIP'
    assert 'not_checked' in result
    html=report.with_suffix('.html').read_text(encoding='utf-8')
    assert 'media ü space.mp4' in html and '<img ' in html
    assert report.read_text(encoding='utf-8')
