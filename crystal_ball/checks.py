"""Isolated entry to the minimally vendored signal checks."""
import importlib
import sys
import os
from pathlib import Path

SCRIPTS = Path(__file__).parent/'vendor/ffmpeg_skill'

def load_qc():
    # Only called in stage subprocesses: upstream uses argv/stdout globals.
    from .platforms.executables import resolve_tool, trusted_path
    selected = [resolve_tool(name) for name in ('ffmpeg','ffprobe')]
    os.environ['PATH'] = os.pathsep.join(dict.fromkeys([*(str(Path(p).parent) for p in selected), trusted_path()]))
    for name, path in zip(('ffmpeg','ffprobe'), selected):
        if resolve_tool(name) != path:
            raise RuntimeError('signal executable selection changed')
    sys.path.insert(0,str(SCRIPTS))
    qc=importlib.import_module('qc')
    runner=importlib.import_module('_common.runner')
    for name,path in zip(('ffmpeg','ffprobe'),selected):
        observed=runner.found_exe(name)
        if os.path.normcase(os.path.realpath(observed))!=os.path.normcase(os.path.realpath(path)):
            raise RuntimeError(f'signal tool selection mismatch: {name}: {observed} != {path}')
    return qc

def platforms():
    from .vendor.ffmpeg_skill import _platforms
    return _platforms
