"""Exercise an installed candidate wheel from outside its source tree.

Run with the isolated application venv: python -I path/to/wheel_smoke.py
--scratch APPROVED_TEMP_ROOT. Generates synthetic media only; no model download,
plugin install, profile change or production GPU broker call.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--scratch',required=True,type=Path)
    args=ap.parse_args()
    root=args.scratch.absolute(); root.mkdir(parents=True,exist_ok=True)
    for key in ('TMPDIR','TMP','TEMP'):
        os.environ[key]=str(root)
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONIOENCODING='utf-8')
    from crystal_ball.platforms.executables import resolve_tool
    from crystal_ball.engines.setup.recipes import requirements_root
    from crystal_ball.hermes import invoke
    from PIL import Image
    resources=requirements_root()/'windows'
    assert all((resources/name).is_file() for name in ('hear-cpu.lock','see-cpu.lock','torch-cpu.lock','recipes.json'))
    config=root/'wheel-config.toml'
    config.write_text('cache_dir = '+json.dumps(str(root/'cache'))+'\n[judge]\nbackend="off"\n'+
                      ''.join('['+kind+']\npython="unavailable-wheel-smoke-engine"\n' for kind in ('hear','see','rhythm','scenes')),encoding='utf-8')
    os.environ['CRYSTAL_BALL_CONFIG']=str(config)
    media=root/'wheel media ü.mp4'
    subprocess.run([resolve_tool('ffmpeg'),'-nostdin','-v','error','-f','lavfi','-i','testsrc2=s=320x180:r=25:d=1',
                    '-f','lavfi','-i','sine=f=440:r=48000:d=1','-c:v','libx264','-threads','1','-c:a','aac','-shortest','-y',str(media)],check=True,timeout=30)
    setup=subprocess.run([sys.executable,'-I','-m','crystal_ball','setup'],capture_output=True,text=True,encoding='utf-8',timeout=15)
    assert setup.returncode==0,setup.stderr
    doctor=subprocess.run([sys.executable,'-I','-m','crystal_ball','doctor','--json'],capture_output=True,text=True,encoding='utf-8',timeout=60)
    diagnostic=json.loads(doctor.stdout)
    assert doctor.returncode==0,doctor.stdout+doctor.stderr
    cli=subprocess.run([sys.executable,'-I','-m','crystal_ball','check',str(media),'--platform','youtube','--json'],capture_output=True,text=True,encoding='utf-8',timeout=90)
    assert cli.returncode in (0,1),cli.stderr
    result=json.loads(cli.stdout)
    tool=invoke('check',file=str(media),platform='youtube')
    assert tool['counts']==result['counts'] and tool['verdict']==result['verdict']
    assert len(json.dumps(tool,ensure_ascii=False,separators=(',',':')).encode('utf-8'))<=1500
    report=Path(result['report'])
    assert report.is_file() and report.with_suffix('.html').is_file()
    full=json.loads((report.parent/'full.json').read_text(encoding='utf-8'))
    assert full['stages']['review']['frames']
    assert any(c['status']!='SKIP' for c in full['stages']['signal']['checks'])
    assert full['stages']['audio']['checks'][0]['status']=='SKIP'
    sheet=Path(full['stages']['review']['contact_sheet'])
    with Image.open(sheet) as image:
        image.verify()
    # Reopen persisted files, not a second generation/analysis.
    assert 'wheel media ü.mp4' in report.with_suffix('.html').read_text(encoding='utf-8')
    print(json.dumps({'os':platform.system(),'installed_wheel_smoke':'PASS','resources':4,
                      'doctor_exit':doctor.returncode,'check_exit':cli.returncode,
                      'frames':len(full['stages']['review']['frames']),'counts':result['counts'],
                      'report':str(report),'inference':'not checked','hermes_ui':'not checked'},ensure_ascii=True))


if __name__=='__main__':
    main()
