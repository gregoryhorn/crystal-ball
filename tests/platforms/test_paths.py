"""Windows path grammar tested without pretending Linux is Windows."""
from pathlib import PureWindowsPath
import pytest
from crystal_ball.platforms import paths
from crystal_ball import config, report


@pytest.fixture
def win(monkeypatch):
    monkeypatch.setattr(paths,'windows',lambda:True)


@pytest.mark.parametrize('value', [r'C:\Media Files\title.mp4',r'\\server\share\title.mp4','C:/Media Files/title.mp4'])
def test_native_absolute(win,value):
    assert PureWindowsPath(paths.resolve_config_path(value,r'D:\config'))==PureWindowsPath(value)


@pytest.mark.parametrize('value',[r'C:folder',r'\folder'])
def test_ambiguous_drive_rejected(win,value):
    with pytest.raises(ValueError,match='ambiguous'):
        paths.resolve_config_path(value,r'D:\config')


def test_model_ids_and_explicit_paths(win,monkeypatch):
    assert paths.resolve_model('openai/clip-vit-large-patch14',r'C:\cfg')=='openai/clip-vit-large-patch14'
    assert paths.resolve_model('large-v3-turbo',r'C:\cfg')=='large-v3-turbo'
    assert paths.resolve_model(r'.\models\clip',r'C:\cfg')==r'C:\cfg\models\clip'
    monkeypatch.setenv('MODEL_ROOT',r'D:\models')
    assert paths.resolve_model(r'%MODEL_ROOT%\clip',r'C:\cfg')==r'D:\models\clip'


def test_config_utf8_bom(tmp_path):
    source=tmp_path/'config.toml'
    source.write_text("cache_dir = './cache'\n[see]\nmodel = './models/clip'\ndevice = 'cpu'\n",encoding='utf-8-sig')
    cfg=config.load(source)
    assert cfg['see']['model']==str(tmp_path/'models/clip')
    assert cfg['see']['device']=='cpu'


def test_asset_url_unicode_spaces(tmp_path):
    assert report.asset_url(tmp_path/'frames'/'title ü.jpg',tmp_path)=='frames/title%20%C3%BC.jpg'


def test_windows_asset_url_grammar():
    assert report.asset_url(r'C:\cache\frames\title ü.jpg',r'C:\cache\reports')=='../frames/title%20%C3%BC.jpg'
    assert report.asset_url(r'D:\frames\title ü.jpg',r'C:\cache')=='file:///D:/frames/title%20%C3%BC.jpg'
    assert report.asset_url(r'\\server\share\title ü.jpg',r'C:\cache')=='file://server/share/title%20%C3%BC.jpg'


def test_structured_path_not_split(tmp_path):
    from crystal_ball.hooks import candidate_paths
    value=str(tmp_path/'unquoted title ü.mp4')
    assert candidate_paths({'output':value},cwd=tmp_path)==[value]


def test_different_drive_asset(monkeypatch):
    monkeypatch.setattr(report.os.path,'relpath',lambda *a: (_ for _ in ()).throw(ValueError('different drive')))
    # Path.as_uri is native; use a native absolute fallback even on Linux.
    from pathlib import Path
    p=Path.cwd()/'image ü.jpg'
    assert report.asset_url(p,Path.cwd())==p.as_uri()
