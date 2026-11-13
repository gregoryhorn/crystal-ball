"""Portable fake-home installer tests, never install into a live profile."""
import importlib.util
import json
from pathlib import Path
import pytest


def installer():
    p=Path(__file__).resolve().parents[2]/'scripts/install_hermes.py'
    spec=importlib.util.spec_from_file_location('windows_installer_test',p)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('path',['C:/escape','C:escape',r'\\server\share\escape','../escape','plugins/crystal-ball/../../escape','plugins/crystal-ball/x:stream'])
def test_escape_rejected(path):
    with pytest.raises(ValueError): installer().portable(path)


def test_historical_backslashes_and_user_data_preserved(tmp_path):
    tool=installer(); home=tmp_path/'fake home'
    tool.install(home)
    path=home/tool.MANIFEST
    doc=json.loads(path.read_text(encoding='utf-8'))
    assert all('\\' not in n for n in doc['files'])
    doc['files']={n.replace('/','\\'):v for n,v in doc['files'].items()}
    doc['dirs']=[n.replace('/','\\') for n in doc['dirs']]
    path.write_text(json.dumps(doc),encoding='utf-8')
    tool.install(home)
    config=home/'crystal-ball.toml'; config.write_text('# user config\n',encoding='utf-8')
    modified=home/'plugins/crystal-ball/__init__.py'; modified.write_text('# changed\n',encoding='utf-8')
    unrelated=home/'unrelated.txt'; unrelated.write_text('keep',encoding='utf-8')
    result=tool.install(home,uninstall=True)
    assert 'plugins/crystal-ball/__init__.py' in result['retained_modified']
    assert config.read_text()=='# user config\n' and modified.read_text()=='# changed\n' and unrelated.read_text()=='keep'


def test_ambiguous_manifest_collision(tmp_path):
    tool=installer(); home=tmp_path/'fake'; tool.install(home)
    path=home/tool.MANIFEST; doc=json.loads(path.read_text())
    key=next(iter(doc['files'])); doc['files'][key.replace('/','\\')]=doc['files'][key]
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError,match='collision'): tool.install(home,uninstall=True)
