"""Shared beat artifacts, estimated meter/sections and timeline exports."""
import csv
import io
import math
import tempfile
from pathlib import Path
from ..cache import Store, atomic, dumps, runtime_stamp
from ..config import load
from ..util import command, has_audio_stream


def beats(file, config=None, speech_music=None):
    cfg=config or load()
    if not has_audio_stream(file):
        raise ValueError('no audio stream; pass --music AUDIO')
    def produce(directory):
        from ..workers import request
        cmd=cfg['hear']['demucs_command']; mixed=speech_music; speech_reason=None
        if cmd and mixed is None:
            try:
                from .hear import transcribe
                mixed=bool(transcribe(file,cfg)['text'].strip())
            except Exception:
                speech_reason='speech detection unavailable'
        with tempfile.TemporaryDirectory(prefix='music-',dir=directory) as td:
            source=str(Path(file).resolve()); method='mix; speech lowers beat accuracy'
            if cmd and mixed:
                try:
                    command([x.format(input=source,output_dir=td) for x in cmd],240)
                    stems=sorted([*Path(td).rglob('no_vocals.wav'),*Path(td).rglob('music.wav')])
                    if not stems:
                        raise RuntimeError('no no_vocals.wav or music.wav produced')
                    source=str(stems[0]); method='separated music stem; estimated rhythm'
                except Exception as exc:
                    speech_reason='optional separation failed: '+str(exc)[-160:]
            result=request(cfg['rhythm']['python'],'crystal_ball.senses.rhythm_worker',{'file':source},300)
        for key in ('beats','onsets','downbeats'):
            values=result.get(key)
            if not isinstance(values,list) or any(isinstance(t,bool) or not isinstance(t,(int,float)) or not math.isfinite(t) or not 0<=t<=result['duration'] for t in values) or values!=sorted(values):
                raise ValueError('invalid rhythm worker timestamps')
        result.update(analysis=method,separation_reason=speech_reason)
        path=directory/'beats.json'; result['paths']={'json':str(path)}
        atomic(path,dumps(result)); result['artifact_paths']=[str(path)]
        return result
    return Store(cfg['cache_dir']).get(file,'rhythm',{'rhythm':cfg['rhythm'],'hear':cfg['hear'],'speech_music':speech_music,'runtime':runtime_stamp(cfg),'version':1},produce)


def export(doc, directory, fps=None):
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
    if fps is not None and (not math.isfinite(float(fps)) or float(fps)<=0):
        raise ValueError('fps must be positive and finite')
    path=directory/'beats.json'; atomic(path,dumps(doc))
    output=io.StringIO(); writer=csv.writer(output)
    writer.writerow(['marker','time_s','bar_estimate','beat_in_bar_estimate'])
    for i,time in enumerate(doc['beats']):
        writer.writerow([f'beat {i+1}',f'{time:.6f}',i//4+1,i%4+1])
    csv_path=directory/'beats.csv'; atomic(csv_path,output.getvalue())
    paths={'json':str(path),'csv':str(csv_path)}
    if fps is not None:
        frame_path=directory/'beat-frames.json'
        atomic(frame_path,dumps({'fps':float(fps),'rounding':'nearest frame, zero based','frames':[round(t*float(fps)) for t in doc['beats']]}))
        paths['frames']=str(frame_path)
    return paths
