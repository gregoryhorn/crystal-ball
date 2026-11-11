"""Shared, content-addressed artifacts with atomic publication."""
import contextlib
import hashlib
import json
import os
import tempfile
import threading
import uuid
from pathlib import Path

_LOCKS = {}
_LOCK = threading.Lock()

def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)

def fingerprint(path):
    p = Path(path).resolve()
    st = p.stat()
    h = hashlib.sha256()
    with p.open('rb') as f:
        h.update(f.read(1024*1024))
        f.seek(max(0,st.st_size-1024*1024))
        h.update(f.read(1024*1024))
    return [str(p),st.st_size,st.st_mtime_ns,h.hexdigest()]

def atomic(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.cb-',dir=p.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,p)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)

class Store:
    def __init__(self, root=None):
        if root is None:
            from .config import load
            root=load()['cache_dir']
        self.root=Path(root)/'artifacts'

    def get(self, file, kind, options, producer):
        identity=fingerprint(file)
        key=hashlib.sha256(dumps([identity,kind,options]).encode()).hexdigest()
        target=self.root/key/'artifact.json'
        with _LOCK:
            lock=_LOCKS.setdefault(str(target),threading.Lock())
        with lock, file_lock(target.parent):
            if target.exists():
                try:
                    value=json.loads(target.read_text())
                    paths=value.get('artifact_paths',[]) if isinstance(value,dict) else []
                    if all(Path(p).exists() for p in paths):
                        return value
                except (OSError,ValueError):
                    pass
            target.parent.mkdir(parents=True,exist_ok=True)
            generation=target.parent/uuid.uuid4().hex
            generation.mkdir()
            value=producer(generation)
            if fingerprint(file)!=identity:
                raise RuntimeError('source changed during artifact creation')
            atomic(target,dumps(value))
            return value


@contextlib.contextmanager
def file_lock(directory):
    """Serialize artifact creation across independent CLI/engine processes (POSIX)."""
    import fcntl
    Path(directory).mkdir(parents=True,exist_ok=True)
    with (Path(directory)/'.lock').open('a') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle,fcntl.LOCK_UN)


def runtime_stamp(config):
    """Invalidate cached skips/results when configured binaries or local models change."""
    import shutil
    paths=set()
    for section in ('hear','see'):
        exe=shutil.which(config[section]['python'])
        if exe:
            paths.add(Path(exe))
            prefix=Path(exe).parent.parent
            for p in prefix.glob('lib/python*/site-packages/*.dist-info/METADATA'):
                if p.parent.name.startswith(('faster_whisper-','ctranslate2-','transformers-','torch-')):
                    paths.add(p)
        model=Path(config[section]['model']).expanduser()
        if model.is_file():
            paths.add(model)
        elif model.is_dir():
            paths.update(p for p in model.iterdir() if p.is_file())
    for section in ('rhythm','scenes'):
        exe=shutil.which(config.get(section,{}).get('python',''))
        if exe:
            paths.add(Path(exe))
            for p in (Path(exe).parent.parent).glob('lib/python*/site-packages/*.dist-info/METADATA'):
                if p.parent.name.startswith(('librosa-','scenedetect-')):
                    paths.add(p)
    wc=config['whispercpp']
    if wc['bin'] and shutil.which(wc['bin']):
        paths.add(Path(shutil.which(wc['bin'])))
    if wc['model'] and Path(wc['model']).is_file():
        paths.add(Path(wc['model']))
    tess=config['read']['tessdata'] or os.environ.get('TESSDATA_PREFIX')
    if tess:
        paths.update(Path(tess).glob('*.traineddata'))
    else:
        # A system installation or upgrade must invalidate previously unavailable OCR.
        import subprocess
        try:
            result=subprocess.run(['tesseract','--list-langs'],capture_output=True,text=True,timeout=5)
            import re
            match=re.search(r'"([^"]+)"',result.stdout)
            if match:
                paths.update(Path(match[1]).glob('*.traineddata'))
        except (OSError,subprocess.TimeoutExpired):
            pass
    hub=Path(os.environ.get('HF_HUB_CACHE',os.environ.get('HUGGINGFACE_HUB_CACHE',str(Path(os.environ.get('HF_HOME','~/.cache/huggingface')).expanduser()/'hub')))).expanduser()
    for section in ('hear','see'):
        model=config[section]['model']
        if '/' in model and not Path(model).is_absolute():
            roots=[hub/('models--'+model.replace('/','--'))]
        elif not Path(model).is_absolute():
            roots=list(hub.glob('models--*'+model))
        else:
            roots=[]
        for root in roots:
            paths.update((root/'refs').glob('*'))
            # Local-only snapshots can have no ref; include the generation directory marker.
            paths.update((root/'snapshots').glob('*'))
    facts=[]
    for p in sorted(paths):
        try:
            st=p.stat()
            facts.append([str(p),st.st_size,st.st_mtime_ns])
        except OSError:
            pass
    return facts
