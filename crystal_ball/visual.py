"""Frame-continuous, downscaled visual measurements; no inference or downloads."""
import re
import subprocess
import tempfile

from .cache import Store
from .config import load

WIDTH,HEIGHT=96,54


def threshold_fades(means, times, threshold=12):
    """Threshold crossings with a gradual ramp; abrupt black cuts stay hard cuts.

    Splits are at the centre of a black interval, or the threshold crossing
    for a terminal fade. Dissolves without black cannot be reliably classified.
    """
    import numpy as np
    values=np.asarray(means); n=len(values); fades=[]
    if n<3:
        return fades
    dark=values<threshold
    changes=np.flatnonzero(dark[1:]!=dark[:-1])+1
    for i,start in enumerate(changes):
        if not dark[start]:
            continue
        end=next((int(j) for j in changes[i+1:] if not dark[j]),n-1)
        def ramp(crossing, direction):
            count=0; k=crossing
            while k>0 and times[crossing]-times[k]<=.5:
                delta=float(values[k]-values[k-1])*direction
                if not .4<delta<30:
                    break
                count+=1; k-=1
            return count>=3
        # A hard black cut has one abrupt step, not a multi-frame ramp.
        gradual=ramp(int(start),-1) or (end<n-1 and ramp(end,1))
        if gradual:
            fades.append({'time':float(times[int(start)] if end==n-1 and dark[-1] else (times[int(start)]+times[end])/2),'type':'fade','start':times[int(start)],'end':times[end]})
    return fades


def scan(file, config=None):
    cfg=config or load()
    def produce(directory):
        import numpy as np
        from .frames import probe
        meta=probe(file)
        video=next(s for s in meta['streams'] if s['codec_type']=='video' and not s.get('disposition',{}).get('attached_pic'))
        rate=video.get('avg_frame_rate','25/1').split('/')
        fps=float(rate[0])/max(1,float(rate[-1])) or 25
        means=[]; visual_changes=[]; raw_events=[]; previous=None
        pending={'luminance':None,'red':None}
        # Stderr is file-backed so continuous stdout reads cannot deadlock.
        with tempfile.TemporaryFile(dir=directory) as log:
            proc=subprocess.Popen(['ffmpeg','-nostdin','-v','info','-threads','1','-i',str(file),'-map','0:V:0','-an','-vf',f'scale={WIDTH}:{HEIGHT},showinfo','-fps_mode','passthrough','-threads','1','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],stdout=subprocess.PIPE,stderr=log)
            try:
                size=WIDTH*HEIGHT*3
                while True:
                    raw=proc.stdout.read(size)
                    if not raw:
                        break
                    if len(raw)!=size:
                        raise RuntimeError('truncated visual frame')
                    image=np.frombuffer(raw,dtype=np.uint8).reshape(HEIGHT,WIDTH,3).astype('float32')/255
                    luma=image @ np.array([.2126,.7152,.0722],dtype='float32')
                    red=np.maximum(0,image[:,:,0]-image[:,:,1]-image[:,:,2])*(image[:,:,0]/np.maximum(image.sum(axis=2),.001)>=.8)
                    index=len(means); means.append(float(image.mean()*255))
                    if previous is not None:
                        # Hook evidence is deliberately coarse; any substantial changed area.
                        if float(np.mean(np.max(abs(image-previous[0]),axis=2)>.12))>=.25:
                            visual_changes.append(index)
                        for kind,value,old,delta in [('luminance',luma,previous[1],.10),('red',red,previous[2],.20)]:
                            diff=value-old
                            pos=diff>=delta; neg=diff<=-delta
                            if kind=='luminance':
                                low=np.minimum(value,old)<.8
                                pos &= low; neg &= low
                            last=pending[kind]
                            if last is not None:
                                area=np.mean((pos & last[2]) | (neg & last[1]))
                                if area>=.25:
                                    raw_events.append({'frame':index,'start_frame':last[0],'kind':kind,'area':round(float(area),3)})
                                    pending[kind]=None
                                    continue
                            if np.mean(pos|neg)>=.25:
                                pending[kind]=(index,pos,neg)
                    previous=(image,luma,red)
                proc.wait(timeout=30)
                if proc.returncode:
                    raise RuntimeError('visual decode failed')
            finally:
                if proc.poll() is None:
                    proc.kill(); proc.wait()
                proc.stdout.close()
            log.seek(0)
            text=log.read().decode(errors='replace')
        times=[float(t) for t in re.findall(r'\bn:\s*\d+.*?pts_time:([\d.eE+\-]+)',text)]
        if len(times)!=len(means):
            raise RuntimeError('visual timestamps do not match decoded frames')
        origin=times[0] if times else 0
        times=[max(0,t-origin) for t in times]
        events=[{'time':times[e['frame']], 'kind':e['kind'],'area':e['area']} for e in raw_events if times[e['frame']]-times[e['start_frame']]<=1]
        return {'fps':fps,'frame_count':len(times),'fades':threshold_fades(means,times),'flashes':events,'visual_changes':[times[i] for i in visual_changes],
                'method':'native-frame timestamps; 96x54 RGB; opposing luminance changes >=0.10 (lower <0.8) or saturated-red changes >=0.20 over >=25% of pixels; paired transitions within 1s',
                'label':'estimate, not a certified Harding test'}
    return Store(cfg['cache_dir']).get(file,'visual-safety',{'version':2},produce)
