"""Isolated entry to the minimally vendored signal checks."""
import importlib
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent/'vendor/ffmpeg_skill'

def load_qc():
    # Only called in stage subprocesses: upstream uses argv/stdout globals.
    sys.path.insert(0,str(SCRIPTS))
    return importlib.import_module('qc')

def platforms():
    from .vendor.ffmpeg_skill import _platforms
    return _platforms
