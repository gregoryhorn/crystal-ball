import importlib.util
import sys
from crystal_ball.config import load
from crystal_ball.platforms.runtime import core_media_python, describe_runtime, metadata_paths


def test_core_first_ignores_missing_optional_see():
    cfg=load(); cfg['see']['python']='missing-clip-runtime'
    assert core_media_python(cfg)==sys.executable


def test_thin_host_fallback(monkeypatch):
    monkeypatch.setattr(importlib.util,'find_spec',lambda name:None)
    cfg=load(); cfg['see']['python']='configured-engine'
    assert core_media_python(cfg)=='configured-engine'


def test_native_sysconfig_metadata():
    description=describe_runtime(sys.executable)
    assert description['python']==sys.executable
    assert description['sites']
    assert any(p.parent.name.lower().startswith('numpy-') for p in metadata_paths(sys.executable))
