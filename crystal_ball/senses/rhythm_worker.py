"""CPU-only librosa rhythm worker; mono PCM is decoded locally with ffmpeg."""
import contextlib
import json
import subprocess
import sys


def analyse(req):
    import numpy as np
    import librosa
    from scipy.ndimage import gaussian_filter1d
    from scipy.signal import find_peaks
    sr=22050; hop=220
    raw=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',req['file'],'-vn','-ac','1','-ar',str(sr),'-f','f32le','pipe:1'],capture_output=True,check=True,timeout=180).stdout
    y=np.frombuffer(raw,dtype='<f4').copy(); duration=len(y)/sr
    if not len(y):
        raise ValueError('no audio samples')
    envelope=librosa.onset.onset_strength(y=y,sr=sr,hop_length=hop,n_fft=1024)
    tempo,frames=librosa.beat.beat_track(onset_envelope=envelope,sr=sr,hop_length=hop,trim=False)
    onset_frames=librosa.onset.onset_detect(onset_envelope=envelope,sr=sr,hop_length=hop,backtrack=False)
    # Refine spectral peak positions against sample-domain transient attacks.
    # This removes STFT latency for sharp hits without inventing a regular grid.
    def refine(seconds):
        result=[]
        for time in seconds:
            a=max(0,int((float(time)-.05)*sr)); b=min(len(y),int((float(time)+.025)*sr))
            if b<=a:
                continue
            signal=np.abs(y[a:b]); peak=float(signal.max())
            candidates=np.flatnonzero(signal>=peak*.25) if peak>1e-6 else []
            t=(a+int(candidates[0]))/sr if len(candidates) else float(time)
            if not result or t-result[-1]>.06:
                result.append(round(t,6))
        return result
    beats=refine(librosa.frames_to_time(frames,sr=sr,hop_length=hop))
    onsets=refine(librosa.frames_to_time(onset_frames,sr=sr,hop_length=hop))
    # librosa's centred onset window can omit an attack right at file start.
    if len(y) and np.max(np.abs(y[:min(len(y),int(.02*sr))]))>.02 and (not onsets or onsets[0]>.1):
        onsets.insert(0,round(int(np.argmax(np.abs(y[:int(.02*sr)])))/sr,6))
    # Refined inter-beat timing is more precise than the tempo-bin resolution.
    gaps=np.diff(beats)
    bpm=float(np.asarray(tempo).reshape(-1)[0]) if np.asarray(tempo).size else 0.
    if len(gaps) and np.median(gaps)>0:
        bpm=60/float(np.median(gaps))
    stability=max(0.,1-float(np.std(gaps)/max(float(np.mean(gaps)),1e-6))) if len(gaps)>1 else 0.
    supported=np.mean([min((abs(t-o) for o in onsets),default=1)<.08 for t in beats]) if beats else 0.
    confidence=float(stability*supported)
    if float(np.max(np.abs(y)))<1e-5:
        beats=[]; onsets=[]; bpm=0.; confidence=0.
    # Novelty is local change in log-mel timbre/energy, smoothed over 0.5s.
    mel=librosa.feature.melspectrogram(y=y,sr=sr,hop_length=hop,n_fft=1024,n_mels=32)
    logged=np.log1p(mel)
    novelty=gaussian_filter1d(np.mean(np.abs(np.diff(logged,axis=1)),axis=0),max(1,.25*sr/hop)) if logged.shape[1]>1 else np.zeros(1)
    peaks,_=find_peaks(novelty,distance=max(1,int(4*sr/hop)),prominence=max(.01,float(np.std(novelty))))
    boundaries=[0.]+[float(p*hop/sr) for p in peaks if 2<float(p*hop/sr)<duration-2]+[duration]
    sections=[{'start':round(a,6),'end':round(b,6),'label':f'estimated section {i+1}'} for i,(a,b) in enumerate(zip(boundaries,boundaries[1:]))]
    bars=[{'bar':i//4+1,'start':beats[i],'end':beats[i+4] if i+4<len(beats) else duration,'beats':beats[i:i+4]} for i in range(0,len(beats),4)]
    return {'engine':'librosa-cpu','fallback_reason':None,'duration':duration,'tempo':round(bpm,3),'confidence':round(confidence,3),'confidence_method':'estimate: beat-spacing stability times onset support; not a calibrated probability',
            'beats':beats,'onsets':onsets,'beat_count':len(beats),'bars':bars,'downbeats':beats[::4],
            'meter':'estimate: assumed 4/4, first detected beat treated as downbeat; musical phase unverified',
            'sections':sections,'sections_method':'estimate: smoothed log-mel spectral novelty; no semantic labels'}


def main():
    req=json.load(sys.stdin)
    with contextlib.redirect_stdout(sys.stderr):
        value=analyse(req)
    print(json.dumps(value,allow_nan=False))

if __name__=='__main__':
    main()
