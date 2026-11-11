#!/usr/bin/env python3
"""Generate a test-pattern render with ffmpeg and save its actual compact verdict."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from crystal_ball.cache import atomic, dumps
from crystal_ball.core import quality_check

def main():
    out=ROOT/'.test-tmp/example'; out.mkdir(parents=True,exist_ok=True)
    file=out/'render.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=s=1280x720:r=25:d=3','-f','lavfi','-i','sine=f=440:r=48000:d=3','-af','loudnorm=I=-14:TP=-1:LRA=11','-ar','48000','-c:v','libx264','-preset','ultrafast','-threads','1','-pix_fmt','yuv420p','-c:a','aac','-shortest','-y',str(file)],check=True,timeout=60)
    # Explicit synthetic-only config; no model/provider calls are needed for this example.
    config=out/'config.toml'
    atomic(config,'cache_dir = '+json.dumps(str(out/'cache'))+'\n[hear]\npython = "unavailable-example-asr"\n[judge]\nbackend = "off"\n')
    os.environ['CRYSTAL_BALL_CONFIG']=str(config)
    result=quality_check(str(file),platform='youtube')
    atomic(out/'compact.json',dumps(result))
    print(dumps(result))

if __name__=='__main__':
    main()
