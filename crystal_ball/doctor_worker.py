"""Offline engine diagnostics in the selected engine interpreter."""
import hashlib
import importlib.metadata
import json
import sys
from pathlib import Path

def checksums(path):
    p=Path(path)
    files=[p] if p.is_file() else [f for f in p.rglob('*') if f.is_file() and f.suffix in {'.bin','.safetensors','.json'}]
    values={}
    for f in sorted(files):
        h=hashlib.sha256()
        with f.open('rb') as stream:
            for block in iter(lambda:stream.read(8*1024*1024),b''):
                h.update(block)
        values[str(f.relative_to(p)) if p.is_dir() else p.name]=h.hexdigest()
    return values

def main():
    from .platforms.windows.dlls import initialize
    initialize()
    if len(sys.argv)==1:
        req=json.load(sys.stdin); kind=req['kind']
        package={'rhythm':'librosa','scenes':'scenedetect'}[kind]
        # Import as well as reading metadata, so broken binary dependencies surface.
        module=importlib.import_module(package)
        if kind=='rhythm':
            from librosa.beat import beat_track
        else:
            from scenedetect.detectors import ContentDetector, AdaptiveDetector, ThresholdDetector
            import cv2
        print(json.dumps({'version':importlib.metadata.version(package),'device':'cpu','inference':False}))
        return
    kind,model=sys.argv[1:]
    packages=['faster-whisper','ctranslate2','numpy'] if kind=='hear' else ['torch','transformers','numpy','pillow']
    versions={p:importlib.metadata.version(p) for p in packages}
    if kind=='hear':
        import ctranslate2
        gpu=ctranslate2.get_cuda_device_count()
        from faster_whisper.utils import download_model
        path=str(Path(model).expanduser()) if Path(model).expanduser().exists() else download_model(model,local_files_only=True)
    else:
        import torch
        gpu=torch.cuda.device_count()
        from huggingface_hub import snapshot_download
        path=str(Path(model).expanduser()) if Path(model).expanduser().exists() else snapshot_download(model,local_files_only=True)
    hashes=checksums(path)
    if not hashes:
        raise ValueError('no local model weights/config found')
    print(json.dumps({'versions':versions,'gpu_count':gpu,'cpu_available':True,'model':model,'model_path':path,'sha256':hashes}))
if __name__=='__main__':
    main()
