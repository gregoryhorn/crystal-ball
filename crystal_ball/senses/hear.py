"""Transcription, script differences, speech intervals and labelled mix estimates."""
import contextlib
import difflib
import json
import math
import os
import re
import selectors
import signal
import subprocess
import sys
import tempfile
import threading
import unicodedata
from pathlib import Path
from ..cache import Store, dumps, runtime_stamp
from ..config import load
from ..util import command, row, skip, engine_python_env, has_audio_stream, StageError, error_result, error_summary

class Worker:
    def __init__(self, config=None):
        self.cfg=config or load(); self.proc=None; self.lock=threading.Lock(); self.counter=0
    def start(self):
        env=engine_python_env(self.cfg['hear']['python'],{'HF_HUB_OFFLINE':'1','OMP_NUM_THREADS':'1'})
        # Discover CUDA library directories using the selected interpreter's prefix.
        prefix=command([self.cfg['hear']['python'],'-c','import sys; print(sys.prefix)'],15,env).strip()
        libs=[str(p) for kind in ('cublas','cudnn') for p in Path(prefix).glob(f'lib/python*/site-packages/nvidia/{kind}/lib')]
        env['LD_LIBRARY_PATH']=os.pathsep.join(libs+([env['LD_LIBRARY_PATH']] if env.get('LD_LIBRARY_PATH') else []))
        # The source checkout is importable even before the user installs the package.
        self.stderr=tempfile.TemporaryFile(mode='w+t')
        try:
            self.proc=subprocess.Popen([self.cfg['hear']['python'],'-u','-m','crystal_ball.senses.hear_worker'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.stderr,text=True,env=env,start_new_session=not bool(os.environ.get('CRYSTAL_BALL_STAGE')))
        except BaseException:
            self.stderr.close()
            raise
    def transcribe(self,file,timeout=300):
        with self.lock:
            if self.proc is None:
                self.start()
            self.counter+=1
            req={'id':self.counter,'op':'transcribe','file':str(file),'model':self.cfg['hear']['model'],'device':self.cfg['hear']['device'],'min_free_vram_gb':self.cfg['hear']['min_free_vram_gb'],'cpu_threads':self.cfg['hear']['cpu_threads']}
            try:
                self.proc.stdin.write(dumps(req)+'\n'); self.proc.stdin.flush()
                with selectors.DefaultSelector() as selector:
                    selector.register(self.proc.stdout,selectors.EVENT_READ)
                    if not selector.select(timeout):
                        raise TimeoutError('hear worker timed out')
                    line=self.proc.stdout.readline()
                if not line:
                    self.stderr.seek(0)
                    raise StageError('hear', self.stderr.read() or 'hear worker exited without a response')
                response=json.loads(line)
                if response.get('id')!=self.counter:
                    raise ValueError('hear response ID mismatch')
                if 'error' in response:
                    raise StageError('hear',response['error'],response.get('log'),response['error'])
                return validate_transcript(response['result'])
            except BaseException:
                self.close()
                raise
    def close(self):
        if self.proc:
            with contextlib.suppress(ProcessLookupError):
                (os.kill if os.environ.get('CRYSTAL_BALL_STAGE') else os.killpg)(self.proc.pid,signal.SIGKILL)
            self.proc.communicate(); self.proc=None
            self.stderr.close()
    def __enter__(self):
        return self
    def __exit__(self,*args):
        self.close()

def validate_transcript(doc):
    if not isinstance(doc,dict) or not isinstance(doc.get('text'),str) or not isinstance(doc.get('segments'),list):
        raise ValueError('invalid transcript')
    for segment in doc['segments']:
        for item in [segment,*segment.get('words',[])]:
            s,e=item['start'],item['end']
            if isinstance(s,bool) or isinstance(e,bool) or not isinstance(s,(int,float)) or not isinstance(e,(int,float)) or not math.isfinite(s) or not math.isfinite(e) or not 0<=s<=e:
                raise ValueError('invalid transcript timestamp')
    return doc

def whispercpp_args(config,input_file,output=None,flags=None):
    flags=list(['-ojf'] if flags is None else flags)
    output_flags={'-otxt','-osrt','-ovtt','-ojson','-olrc','-owts','-ocsv','-oj','-ojf','--output-txt','--output-srt','--output-vtt','--output-json','--output-json-full','--output-lrc','--output-words','--output-csv'}
    if output_flags.intersection(flags) and not output:
        raise ValueError('output formats require -of <output-path>')
    args=[config['whispercpp']['bin'],'-m',config['whispercpp']['model'],'-f',str(input_file),*flags]
    return args+(['-of',str(output)] if output else [])

def whispercpp(file,cfg):
    if not cfg['whispercpp']['bin'] or not cfg['whispercpp']['model']:
        raise RuntimeError('whisper.cpp fallback not configured')
    with tempfile.TemporaryDirectory(prefix='cb-asr-',dir=cfg['cache_dir']) as td:
        wav=Path(td)/'audio.wav'; out=Path(td)/'transcript'
        command(['ffmpeg','-nostdin','-v','error','-i',file,'-vn','-ac','1','-ar','16000',wav],180)
        command(whispercpp_args(cfg,wav,out),300)
        data=json.loads(out.with_suffix('.json').read_text())
        segments=[]
        for s in data.get('transcription',[]):
            words=[]
            for token in s.get('tokens',[]):
                text=token.get('text','').strip()
                if not text or text.startswith('[_'):
                    continue
                offsets=token.get('offsets',{})
                if 'from' in offsets and 'to' in offsets and offsets['from']>=0:
                    words.append({'word':text,'start':offsets['from']/1000,'end':offsets['to']/1000})
            offsets=s['offsets']
            segments.append({'start':offsets['from']/1000,'end':offsets['to']/1000,'text':s['text'].strip(),'words':words})
        return validate_transcript({'engine':'whisper.cpp','fallback_reason':None,'segments':segments,'text':' '.join(s['text'] for s in segments),'duration':max((s['end'] for s in segments),default=0),'word_timing':'token estimates'})

def transcribe(file,config=None,worker=None):
    cfg=config or load(); Path(cfg['cache_dir']).mkdir(parents=True,exist_ok=True)
    if not has_audio_stream(file):
        return skip('audio', 'no audio stream')
    def produce(directory):
        try:
            if worker:
                return worker.transcribe(file)
            with Worker(cfg) as own:
                return own.transcribe(file)
        except Exception as exc:
            try:
                result=whispercpp(file,cfg)
            except Exception as fallback:
                error_result(exc, 'hear', cfg['cache_dir'])
                raise StageError('hear', exc) from fallback
            result['fallback_reason']=error_summary(exc,'hear')
            return result
    return Store(cfg['cache_dir']).get(file,'transcript',{'hear':cfg['hear'],'whispercpp':cfg['whispercpp'],'runtime':runtime_stamp(cfg),'version':1},produce)

def normalize(text):
    text=unicodedata.normalize('NFKC',text).casefold()
    text=''.join(c for c in text if unicodedata.category(c)!='Mn' and c!='ـ')
    text=text.translate(str.maketrans({'أ':'ا','إ':'ا','آ':'ا','ٱ':'ا','ى':'ي'}))
    return ' '.join(re.findall(r'\w+',text))

def _edit_costs(reference, observed):
    previous=list(range(len(observed)+1))
    for i,a in enumerate(reference,1):
        current=[i]
        for j,b in enumerate(observed,1):
            current.append(min(current[-1]+1,previous[j]+1,previous[j-1]+(a!=b)))
        previous=current
    return previous


def _aligned_words(reference, observed):
    """Hirschberg alignment: one observed word/None per reference word, linear space."""
    if not reference:
        return []
    if not observed:
        return [None]*len(reference)
    if len(reference)==1:
        matching=[i for i,word in enumerate(observed) if word==reference[0]]
        return [observed[matching[-1] if matching else -1]]
    mid=len(reference)//2
    left=_edit_costs(reference[:mid],observed)
    right=_edit_costs(reference[mid:][::-1],observed[::-1])
    cut=min(range(len(observed)+1),key=lambda j:left[j]+right[len(observed)-j])
    return _aligned_words(reference[:mid],observed[:cut])+_aligned_words(reference[mid:],observed[cut:])


def script_match(script,transcript,names=()):
    text=transcript['text'] if isinstance(transcript,dict) else transcript
    wanted=normalize(script).split(); heard=normalize(text).split()
    distance=_edit_costs(wanted,heard)[-1]
    aligned=_aligned_words(wanted,heard)
    missing=[]; changed=[]; cursor=0
    for line in script.splitlines():
        tokens=normalize(line).split()
        mapped=aligned[cursor:cursor+len(tokens)]; cursor+=len(tokens)
        if not tokens or re.search(r'(?<!\w)'+re.escape(normalize(line))+r'(?!\w)',normalize(text)):
            continue
        if not any(word is not None for word in mapped):
            missing.append(line)
        else:
            changed.append(line)
    expected_names=list(names)+re.findall(r'\b[A-Z][a-z]{2,}\b',script)
    missing_names=[]; changed_names=[]
    for name in dict.fromkeys(expected_names):
        target=normalize(name); words=target.split()
        if not target or not re.search(r'(?<!\w)'+re.escape(target)+r'(?!\w)',normalize(script)) or re.search(r'(?<!\w)'+re.escape(target)+r'(?!\w)',normalize(text)):
            continue
        missing_names.append(name)
        for i in range(len(wanted)-len(words)+1):
            if wanted[i:i+len(words)]==words:
                mapped=aligned[i:i+len(words)]
                if any(word is not None for word in mapped):
                    changed_names.append({'expected':name,'observed':' '.join(word for word in mapped if word is not None)})
                break
    return {'wer':distance/max(1,len(wanted)),'missing_lines':missing,'changed_lines':changed,
            'missing_or_changed_names':missing_names,'changed_names':changed_names,
            'method':'normalised token Levenshtein and linear-space alignment; ASR uncertainty applies'}


def speech_gaps(transcript,minimum=2.0):
    segments=transcript.get('segments',[])
    intervals=sorted((s['start'],s['end']) for s in segments)
    gaps=[]; end=None
    for s,e in intervals:
        if end is not None and s-end>=minimum:
            gaps.append([end,s])
        end=max(end or 0,e)
    return gaps

def voice_balance(file,transcript,config=None):
    from ..workers import see_request
    return see_request('voice_balance',{'file':str(file),'transcript':transcript},config,500)

def _voice_balance(file,transcript,config=None):
    import numpy as np
    cfg=config or load(); cmd=cfg['hear']['demucs_command']; stem=None
    Path(cfg['cache_dir']).mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cb-balance-',dir=cfg['cache_dir']) as td:
        if cmd:
            command([x.format(input=str(file),output_dir=td) for x in cmd],240)
            stems=list(Path(td).rglob('vocals.wav'))
            if not stems:
                raise RuntimeError('configured demucs command produced no vocals.wav')
            stem=stems[0]
        def pcm(path):
            r=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(path),'-vn','-ac','1','-ar','16000','-f','f32le','pipe:1'],capture_output=True,check=True,timeout=180)
            return np.frombuffer(r.stdout,dtype='<f4')
        mix=pcm(file)
        mask=np.zeros(len(mix),dtype=bool)
        for s in transcript['segments']:
            mask[max(0,int(s['start']*16000)):min(len(mix),int(s['end']*16000))]=True
        def db(a):
            return round(20*math.log10(max(float(np.sqrt(np.mean(a.astype('float64')**2))),1e-10)),2) if len(a) else None
        if stem:
            vocals=pcm(stem); n=min(len(vocals),len(mix))
            return {'method':'demucs vocal stem','vocal_dbfs':db(vocals[:n]),'residual_dbfs':db(mix[:n]-vocals[:n]),'assessment':'measurements only; no mix approval'}
        return {'method':'estimate from ASR speech windows; includes music and effects','speech_window_dbfs':db(mix[mask]),'other_window_dbfs':db(mix[~mask]),'assessment':'voice cannot be separated from music without a vocal stem'}

def audio_stage(req):
    cfg=req.get('config') or load()
    if not has_audio_stream(req['file'], req.get('meta')):
        return skip('audio', 'no audio stream')
    with Worker(cfg) as worker:
        transcript=transcribe(req['file'],cfg,worker)
    checks=[row('transcript','PASS',f"{len(transcript['segments'])} speech segments ({transcript['engine']})")]
    gaps=speech_gaps(transcript)
    checks.append(row('speech_gaps','WARN' if gaps else 'PASS',f'{len(gaps)} internal speech gaps >=2s; may be intentional',gaps))
    details={}
    if req.get('script'):
        match=script_match(Path(req['script']).read_text(),transcript,req['rules']['terms'])
        details['script_match']=match
        checks.append(row('script_match','WARN' if match['wer'] else 'PASS',f"WER {match['wer']:.3f}; ASR comparison, inspect differences"))
    try:
        balance=voice_balance(req['file'],transcript,cfg)
        details['voice_balance']=balance
        checks.append(row('voice_balance','WARN' if balance['method'].startswith('estimate') else 'PASS',balance['method']))
    except Exception as exc:
        failure=error_result(exc,'voice_balance',cfg['cache_dir'])
        checks.append(row('voice_balance','SKIP',failure['error']))
        details['log']=failure['log']
    return {'checks':checks,'transcript':transcript,**details}

def subtitles(doc,kind='srt'):
    def stamp(seconds):
        ms=round(seconds*1000); h,ms=divmod(ms,3600000); m,ms=divmod(ms,60000); s,ms=divmod(ms,1000)
        return f'{h:02}:{m:02}:{s:02}{"." if kind=="vtt" else ","}{ms:03}'
    lines=['WEBVTT',''] if kind=='vtt' else []
    for i,s in enumerate(doc['segments'],1):
        lines.extend([str(i),f"{stamp(s['start'])} --> {stamp(s['end'])}",s['text'],''])
    return '\n'.join(lines)
