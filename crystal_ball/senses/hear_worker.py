"""Line-delimited JSON worker. Models load once; all diagnostics go to stderr."""
import contextlib
import importlib
import json
import subprocess
import sys

class Engine:
    def __init__(self):
        self.models={}
    def transcribe(self, req):
        import numpy as np
        # PyAV is deliberately bypassed: float32 PCM, mono, 16 kHz.
        raw=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',req['file'],'-vn','-ac','1','-ar','16000','-f','f32le','pipe:1'],capture_output=True,check=True,timeout=180).stdout
        samples=np.frombuffer(raw,dtype='<f4').astype(np.float32,copy=False)
        key=(req['model'],req['device'])
        if key not in self.models:
            from faster_whisper import WhisperModel
            self.models[key]=WhisperModel(req['model'],device=req['device'],compute_type='float16' if req['device']=='cuda' else 'int8',local_files_only=True)
        segments,info=self.models[key].transcribe(samples,word_timestamps=True,vad_filter=True)
        out=[]
        for s in segments:
            out.append({'start':s.start,'end':s.end,'text':s.text.strip(),'words':[{'start':w.start,'end':w.end,'word':w.word.strip(),'probability':w.probability} for w in s.words or []]})
        return {'engine':'faster-whisper','language':info.language,'duration':len(samples)/16000,'segments':out,'text':' '.join(s['text'] for s in out)}

def serve(engine=None, source=None, sink=None):
    engine=engine or Engine(); source=source or sys.stdin; sink=sink or sys.stdout
    for line in source:
        req=None
        try:
            req=json.loads(line)
            if not isinstance(req,dict) or req.get('op')!='transcribe':
                raise ValueError('unsupported operation')
            with contextlib.redirect_stdout(sys.stderr):
                value=engine.transcribe(req)
            response={'id':req.get('id'),'result':value}
        except Exception as exc:
            response={'id':req.get('id') if isinstance(locals().get('req'),dict) else None,'error':f'{type(exc).__name__}: {exc}'[:400]}
        sink.write(json.dumps(response,ensure_ascii=False,allow_nan=False)+'\n'); sink.flush()

if __name__=='__main__':
    serve()
