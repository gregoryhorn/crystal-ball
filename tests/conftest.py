"""Isolate all artifacts in the workspace; no model downloads during ordinary tests."""
import os
import sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

@pytest.fixture(autouse=True)
def isolated_config(tmp_path,monkeypatch,request):
    if request.node.get_closest_marker('live'):
        return
    config=tmp_path/'isolated.toml'
    config.write_text('cache_dir = '+repr(str(tmp_path/'cache'))+'\n[judge]\nbackend = "off"\n[hear]\npython = "missing-asr-interpreter"\n')
    monkeypatch.setenv('CRYSTAL_BALL_CONFIG',str(config))
    monkeypatch.setenv('HF_HUB_OFFLINE','1')
