"""Bounded, offline interpreter discovery; model libraries stay in engines."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from .process import run_owned


def core_media_python(cfg):
    try:
        if all(importlib.util.find_spec(name) is not None for name in ('numpy', 'PIL')):
            return sys.executable
    except (ImportError, ValueError):
        pass
    return cfg['see']['python']


def describe_runtime(python):
    from ..util import engine_python_env
    code = "import json,sys,sysconfig; print(json.dumps({'python':sys.executable,'prefix':sys.prefix,'sites':list(set(sysconfig.get_path(k) for k in ('purelib','platlib')))}))"
    result = run_owned([python, '-c', code], env=engine_python_env(python), capture_output=True, text=True, timeout=10, check=True)
    return json.loads(result.stdout)


def metadata_paths(python):
    try:
        sites = describe_runtime(python)['sites']
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        return []
    prefixes = ('faster_whisper-', 'ctranslate2-', 'transformers-', 'torch-', 'librosa-', 'scenedetect-', 'numpy-', 'pillow-')
    return [p for site in sites for p in Path(site).glob('*.dist-info/METADATA') if p.parent.name.lower().startswith(prefixes)]
