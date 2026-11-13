"""Cached shot boundaries, thumbnails and edit interchange exports."""
import csv
import io
import re
import statistics
from pathlib import Path

from ..cache import Store, atomic, dumps, runtime_stamp
from ..config import load
from ..frames import probe
from ..util import command
from ..platforms.process import run_owned


def ffmpeg_cuts(file, threshold, detector='content'):
    # Heuristic content-score mapping; adaptive ratios have no direct mapping.
    score=.3 if detector=='adaptive' else min(.99,max(.001,float(threshold)/100))
    import subprocess
    result=run_owned(['ffmpeg','-nostdin','-v','info','-threads','1','-i',str(file),'-map','0:V:0','-an','-vf',f"select='gt(scene,{score})',showinfo",'-fps_mode','vfr','-f','null','-'],capture_output=True,text=True,check=True,timeout=180)
    return [float(t) for t in re.findall(r'pts_time:([\d.eE+\-]+)',result.stderr)]


def detect_scenes(file, config=None):
    cfg=config or load()
    def produce(directory):
        from ..visual import scan
        from ..workers import request
        meta=probe(file); dur=meta['duration']
        video=next(s for s in meta['streams'] if s['codec_type']=='video' and not s.get('disposition',{}).get('attached_pic'))
        from fractions import Fraction
        fps=float(Fraction(video.get('avg_frame_rate','25/1'))) or 25
        reason=None
        try:
            result=request(cfg['scenes']['python'],'crystal_ball.senses.scenes_worker',{'file':str(Path(file).resolve()),'scenes':cfg['scenes']},180)
            cuts=result['cuts']; engine=result['engine']
        except (OSError,RuntimeError,ValueError) as exc:
            reason=f'PySceneDetect unavailable: {str(exc)[-200:]}'
            cuts=ffmpeg_cuts(file,cfg['scenes']['threshold'],cfg['scenes']['detector']); engine='ffmpeg-select'
        visual=scan(file,cfg)
        # Both runtimes use the same threshold/ramp evidence to avoid calling an
        # abrupt hard cut to black a fade. ThresholdDetector corroborates when present.
        fades=visual['fades']
        if engine=='pyscenedetect':
            confirmed=[]
            for fade in fades:
                matches=[t for t in result.get('threshold_crossings',[]) if fade['start']-1/fps<=t<=fade['end']+1/fps]
                if matches:
                    confirmed.append({**fade,'time':min(matches,key=lambda t:abs(t-fade['time']))})
            fades=confirmed
        events=[{'time':float(t),'type':'hard cut'} for t in cuts if 0<float(t)<dur]
        for fade in fades:
            events=[e for e in events if not fade['start']-.25<=e['time']<=fade['end']+.25]
            events.append({'time':round(fade['time']*fps)/fps,'type':'fade'})
        events.sort(key=lambda e:e['time'])
        accepted=[]; minimum=float(cfg['scenes']['min_shot_s'])
        for e in events:
            if e['time']>0 and dur-e['time']>=minimum-1e-6 and e['time']-(accepted[-1]['time'] if accepted else 0)>=minimum-1e-6:
                accepted.append(e)
        starts=[{'time':0.,'type':'start'},*accepted]
        shots=[]; paths=[]
        for i,event in enumerate(starts):
            start=event['time']; end=starts[i+1]['time'] if i+1<len(starts) else dur
            if end<=start:
                continue
            thumb=directory/f'shot-{i+1:05}.jpg'
            t=start+min((end-start)/2,.10)
            command(['ffmpeg','-nostdin','-v','error','-threads','1','-ss',str(t),'-i',str(file),'-map','0:V:0','-frames:v','1','-threads','1','-q:v','3',thumb],30)
            shots.append({'shot':i+1,'start':round(start,6),'end':round(end,6),'duration':round(end-start,6),'cut_type':event['type'],'thumbnail':str(thumb),'thumbnail_time':round(t,6)})
            paths.append(str(thumb))
        lengths=[s['duration'] for s in shots]
        output={'engine':engine,'fallback_reason':reason,'fps':fps,'duration':dur,'file':str(Path(file).resolve()),'shot_count':len(shots),'mean_shot_s':statistics.mean(lengths) if lengths else 0,'median_shot_s':statistics.median(lengths) if lengths else 0,'shots':shots,
                'classification':'cut type describes the incoming transition; fades use a black-level threshold with gradual-ramp evidence; dissolves are not reliably detectable',
                'threshold_crossings':result.get('threshold_crossings',[]) if engine=='pyscenedetect' else []}
        full=directory/'scenes.json'; output['paths']={'json':str(full)}
        atomic(full,dumps(output)); output['artifact_paths']=[*paths,str(full)]
        return output
    return Store(cfg['cache_dir']).get(file,'scenes',{'scenes':cfg['scenes'],'runtime':runtime_stamp(cfg),'version':1},produce)


def shot_frames(doc, per_shot=1, config=None):
    if per_shot not in (1,2,3):
        raise ValueError('frames_per_shot must be 1, 2 or 3')
    if per_shot==1:
        return [(s['thumbnail_time'],s['thumbnail']) for s in doc['shots']]
    cfg=config or load()
    def produce(directory):
        frames=[]
        for shot in doc['shots']:
            for j in range(per_shot):
                time=shot['start']+shot['duration']*(j+1)/(per_shot+1)
                target=directory/f"shot-{shot['shot']:05}-{j}.jpg"
                command(['ffmpeg','-nostdin','-v','error','-threads','1','-ss',str(time),'-i',doc['file'],'-map','0:V:0','-frames:v','1','-threads','1','-q:v','3',target],30)
                frames.append({'time':round(time,6),'path':str(target)})
        return {'frames':frames,'artifact_paths':[f['path'] for f in frames]}
    value=Store(cfg['cache_dir']).get(doc['file'],'shot-frames',{'scenes':doc['paths'],'per_shot':per_shot},produce)
    return [(f['time'],f['path']) for f in value['frames']]


def timecode(seconds, fps):
    rate=round(fps); frame=round(seconds*fps)
    h,frame=divmod(frame,rate*3600); m,frame=divmod(frame,rate*60); s,f=divmod(frame,rate)
    return f'{h:02}:{m:02}:{s:02}:{f:02}'


def export(doc, directory):
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
    out=io.StringIO(); writer=csv.writer(out)
    writer.writerow(['shot','start','end','duration','cut_type','thumbnail'])
    for shot in doc['shots']:
        writer.writerow([shot[k] for k in ('shot','start','end','duration','cut_type','thumbnail')])
    csv_path=directory/'scenes.csv'; atomic(csv_path,out.getvalue())
    # A shot list is a straight assembly of one source, with non-drop timecode.
    edl=['TITLE: CRYSTAL BALL SHOT LIST','FCM: NON-DROP FRAME','']
    for shot in doc['shots']:
        a=timecode(shot['start'],doc['fps']); b=timecode(shot['end'],doc['fps'])
        edl += [f"{shot['shot']:03}  AX       V     C        {a} {b} {a} {b}",f"* DETECTED TRANSITION: {shot['cut_type']}",'']
    edl_path=directory/'scenes.edl'; atomic(edl_path,'\n'.join(edl))
    return {'csv':str(csv_path),'edl':str(edl_path)}
