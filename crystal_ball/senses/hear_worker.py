"""Line-delimited JSON worker. Models load once; all diagnostics go to stderr."""
import contextlib
import importlib
import json
import subprocess
import sys
from ..util import error_result

class Engine:
    def __init__(self):
        self.models={}
    def transcribe(self, req):
        import numpy as np
        # PyAV is deliberately bypassed: float32 PCM, mono, 16 kHz.
        raw=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',req['file'],'-vn','-ac','1','-ar','16000','-f','f32le','pipe:1'],capture_output=True,check=True,timeout=180).stdout
        samples=np.frombuffer(raw,dtype='<f4').astype(np.float32,copy=False)
        from crystal_ball.gpu import Session, is_oom
        session=Session(req.get('min_free_vram_gb',3.5), purpose='Whisper transcription',
                        model=req['model'], enabled=req['device']=='cuda')
        device=session.device; reason=session.reason
        def run(device):
            key=(req['model'],device,int(req.get('cpu_threads',4)))
            if key not in self.models:
                from faster_whisper import WhisperModel
                self.models[key]=WhisperModel(req['model'],device=device,compute_type='float16' if device=='cuda' else 'int8',cpu_threads=key[2],local_files_only=True)
            segments,info=self.models[key].transcribe(samples,word_timestamps=True,vad_filter=True)
            out=[]
            for s in segments:
                out.append({'start':s.start,'end':s.end,'text':s.text.strip(),'words':[{'start':w.start,'end':w.end,'word':w.word.strip(),'probability':w.probability} for w in s.words or []]})
            return out,info
        try:
            retry=False
            try:
                out,info=run(device)
            except Exception as exc:
                if device!='cuda' or not is_oom(exc):
                    raise
                retry=True
            if retry:
                # CPU retry may proceed, but failed GPU cleanup keeps occupancy.
                session.close(self.drop_cuda_models)
                device='cpu'; reason='CUDA out of memory; retry on CPU int8'
                out,info=run(device)
            result={'engine':'faster-whisper-'+device,'fallback_reason':reason,'language':info.language,'duration':len(samples)/16000,'segments':out,'text':' '.join(s['text'] for s in out)}
        finally:
            cleanup_reason=session.close(self.drop_cuda_models)
            if cleanup_reason and 'lease retained' in cleanup_reason:
                print(cleanup_reason,file=sys.stderr)
        if cleanup_reason and 'lease retained' in cleanup_reason:
            result['cleanup_reason']=cleanup_reason
        return result

    def drop_cuda_models(self):
        """CTranslate2 owns its allocator; unload/destroy only our CUDA models."""
        import gc
        for key in list(self.models):
            if key[1]=='cuda':
                model=self.models[key]
                backend=getattr(model,'model',None)
                if backend is not None:
                    backend.unload_model()
                del self.models[key]
                del model,backend
        gc.collect()

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
            response={'id':req.get('id') if isinstance(locals().get('req'),dict) else None,**error_result(exc,'hear')}
        sink.write(json.dumps(response,ensure_ascii=False,allow_nan=False)+'\n'); sink.flush()

if __name__=='__main__':
    serve()
