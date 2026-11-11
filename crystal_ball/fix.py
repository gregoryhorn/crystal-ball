"""Conservative loudness/true-peak fixes to a new file; never replace the input."""
import fnmatch
import json
import os
import re
import tempfile
from pathlib import Path
from .cache import fingerprint
from .config import load
from .checks import platforms
from .frames import probe
from .util import command, error_result

def protected(path,patterns):
    p=Path(path).resolve().as_posix()
    return any(fnmatch.fnmatch(p,pattern) or Path(p).match(pattern) for pattern in patterns)

def apply_fix(doc,force=False,config=None):
    cfg=config or load(); path=Path(doc['file']).resolve(); identity=fingerprint(path)
    if doc.get('identity',identity)!=identity:
        return {'status':'refused','reason':'source changed since QC; re-check before fixing'}
    if not force and protected(path,cfg['fix']['protected']):
        return {'status':'refused','reason':'protected path; force required'}
    output=path.with_name(path.stem+'.cbfix'+path.suffix)
    if output.exists() or output.is_symlink():
        return {'status':'refused','reason':'cbfix output already exists; never overwritten'}
    bad={r['id'] for r in doc['checks'] if r['status'] in {'WARN','FAIL'}}
    if not bad & {'loudness','true peak'}:
        return {'status':'no_safe_fix','reason':'no loudness/true-peak correction indicated'}
    measurement=next((r['summary'] for r in doc['checks'] if r['id']=='loudness'),'')
    measured=re.match(r'(-?\d+(?:\.\d+)?)\s+LUFS',measurement)
    if not measured or float(measured[1])<=-40:
        return {'status':'no_safe_fix','reason':'unmeasured or <= -40 LUFS; preserve the existing ambience rule'}
    spec=platforms().PLATFORMS[doc['platform']]['spec']
    if spec['lufs'] is None:
        return {'status':'no_safe_fix','reason':'platform has no loudness target'}
    streams=probe(path)['streams']
    if sum(s['codec_type']=='audio' for s in streams)!=1:
        return {'status':'no_safe_fix','reason':'multiple audio streams require an explicit mixing decision; no audio stream dropped'}
    try:
        with tempfile.TemporaryDirectory(prefix='.cbfix-',dir=path.parent) as td:
            target=Path(td)/output.name
            first=['ffmpeg','-nostdin','-v','info','-i',str(path),'-vn','-af',f"loudnorm=I={spec['lufs']}:TP={spec['tp']}:LRA=11:print_format=json",'-f','null','-']
            import subprocess
            r=subprocess.run(first,capture_output=True,text=True,check=True,timeout=240)
            values=json.JSONDecoder().raw_decode(r.stderr[r.stderr.rfind('{'):])[0]
            names={'input_i':'measured_I','input_tp':'measured_TP','input_lra':'measured_LRA','input_thresh':'measured_thresh','target_offset':'offset'}
            if not all(float('-inf')<float(values[k])<float('inf') for k in names):
                return {'status':'no_safe_fix','reason':'non-finite loudness measurements'}
            filt=f"loudnorm=I={spec['lufs']}:TP={spec['tp']}:LRA=11:linear=true:"+':'.join(f'{dest}={values[src]}' for src,dest in names.items())
            source_audio=next(s for s in streams if s['codec_type']=='audio')
            codec=source_audio.get('codec_name','aac')
            encoder={'opus':'libopus','vorbis':'libvorbis','mp3':'libmp3lame'}.get(codec,codec)
            cmd=['ffmpeg','-nostdin','-v','error','-i',str(path),'-map','0','-c','copy','-c:a',encoder,'-ar',str(source_audio.get('sample_rate','48000')),'-af',filt,'-t',str(probe(path)['duration']),'-n',str(target)]
            command(cmd,240)
            after=probe(target)['streams']
            if sorted(s['codec_type'] for s in streams)!=sorted(s['codec_type'] for s in after):
                return {'status':'no_safe_fix','reason':'output stream inventory differs; manual preservation required'}
            if fingerprint(path)!=identity:
                return {'status':'refused','reason':'source changed during fix'}
            os.link(target,output)
        return {'status':'written','file':str(output),'commands':[first,cmd]}
    except Exception as exc:
        failure=error_result(exc,'fix',cfg['cache_dir'])
        return {'status':'failed','reason':failure['error'],'log':failure['log']}
