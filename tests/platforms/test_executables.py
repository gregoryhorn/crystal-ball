import os
from pathlib import Path
import pytest
from crystal_ball.platforms.executables import resolve_tool, trusted_path


def test_no_cwd_or_relative_hijack(tmp_path,monkeypatch):
    cwd=tmp_path/'cwd'; trusted=tmp_path/'trusted tools'
    cwd.mkdir(); trusted.mkdir(); monkeypatch.chdir(cwd)
    name='ffmpeg.exe' if os.name=='nt' else 'ffmpeg'
    for root in (cwd,trusted):
        p=root/name; p.write_bytes(b'fixture'); p.chmod(0o755)
    env={'PATH':os.pathsep.join(['','.',str(cwd),str(trusted),str(trusted)]),'PATHEXT':'.EXE;.CMD;.BAT'}
    assert resolve_tool('ffmpeg',env)==str(trusted/name)
    assert trusted_path(env)==str(trusted)
    if os.name=='nt':
        env['PATH']+=os.pathsep+str(trusted).swapcase()
        assert trusted_path(env)==str(trusted)
        assert resolve_tool('ffmpeg',env)==str(trusted/name)


@pytest.mark.parametrize('name',['engine.cmd','engine.bat','C:/engine.CMD'])
def test_refuse_shell_wrappers(name):
    with pytest.raises(ValueError,match='shell wrappers'):
        resolve_tool(name)


def test_missing_tool(tmp_path):
    with pytest.raises(FileNotFoundError,match='trusted PATH'):
        resolve_tool('nonexistent-crystal-ball-executable',{'PATH':str(tmp_path)})
