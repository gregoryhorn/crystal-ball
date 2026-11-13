import subprocess
import sys
from crystal_ball.cache import atomic
from crystal_ball.platforms.locks import file_lock
from crystal_ball.util import same_python_env
import pytest


def test_process_contention_and_release(tmp_path):
    code="from crystal_ball.platforms.locks import file_lock; import sys; "
    code+="\nwith file_lock(sys.argv[1],timeout=.1): print('acquired')\n"
    with file_lock(tmp_path):
        result=subprocess.run([sys.executable,'-c',code,str(tmp_path)],capture_output=True,text=True,env=same_python_env(),timeout=5)
        assert result.returncode!=0
        assert 'TimeoutError' in result.stderr
    result=subprocess.run([sys.executable,'-c',code,str(tmp_path)],capture_output=True,text=True,env=same_python_env(),timeout=5)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='acquired'


def test_atomic_failure_keeps_previous(tmp_path,monkeypatch):
    p=tmp_path/'artifact.json'; atomic(p,'old')
    from crystal_ball.platforms import locks
    def denied(*a):
        raise PermissionError('injected publication failure')
    monkeypatch.setattr(locks.os,'replace',denied)
    with pytest.raises(PermissionError):
        atomic(p,'new')
    assert p.read_text()=='old'
    assert not list(tmp_path.glob('.cb-*'))
