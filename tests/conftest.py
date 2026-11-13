"""Isolate all artifacts in the workspace; no model downloads during ordinary tests."""
import os
import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

@pytest.fixture(autouse=True)
def isolated_config(tmp_path,monkeypatch,request):
    if request.node.get_closest_marker('live'):
        return
    config=tmp_path/'isolated.toml'
    config.write_text('cache_dir = '+json.dumps(str(tmp_path/'cache'))+'\n[judge]\nbackend = "off"\n[hear]\npython = "missing-asr-interpreter"\n', encoding='utf-8')
    monkeypatch.setenv('CRYSTAL_BALL_CONFIG',str(config))
    monkeypatch.setenv('HF_HUB_OFFLINE','1')
    # Non-live tests must never open the machine-local broker's production state.
    from types import SimpleNamespace
    def unavailable(**kwargs):
        raise RuntimeError('isolated test broker unavailable')
    monkeypatch.setitem(sys.modules,'gpu_broker',SimpleNamespace(acquire=unavailable))


@pytest.fixture
def native_engine(tmp_path):
    """Real native interpreter with engine-local launch logging/module hiding."""
    import venv
    import subprocess
    def create(name, hide):
        root=tmp_path/name
        venv.EnvBuilder(with_pip=False,system_site_packages=not hide).create(root)
        exe=root/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        site=Path(subprocess.check_output([str(exe),'-c',"import sysconfig; print(sysconfig.get_path('purelib'))"],text=True).strip())
        site.mkdir(parents=True,exist_ok=True)
        if not hide:
            (site/'test-runtime.pth').write_text('\n'.join(p for p in sys.path if 'site-packages' in p)+'\n',encoding='utf-8')
        launches=tmp_path/(name+'-launches')
        code='import sys\nwith open('+repr(str(launches))+',"a",encoding="utf-8") as f: f.write(" ".join(sys.orig_argv)+"\\n")\n'
        if hide:
            code += '''import importlib.abc
class Hidden(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'numpy','PIL'}:
            raise ModuleNotFoundError('engine deliberately lacks '+fullname)
sys.meta_path.insert(0,Hidden())
'''
        # Debian's stdlib sitecustomize can precede the venv's site-packages.
        # A uniquely named .pth hook runs without relying on that import order.
        (site/'_crystal_ball_test_runtime.py').write_text(code,encoding='utf-8')
        (site/'crystal-ball-test-runtime.pth').write_text('import _crystal_ball_test_runtime\n',encoding='utf-8')
        return exe,launches
    return create


@pytest.fixture
def assert_stopped():
    import time
    import subprocess
    def running(pid):
        if os.name=='nt':
            import ctypes
            from ctypes import wintypes as w
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD]; kernel.OpenProcess.restype=w.HANDLE
            kernel.GetExitCodeProcess.argtypes=[w.HANDLE,ctypes.POINTER(w.DWORD)]
            kernel.CloseHandle.argtypes=[w.HANDLE]
            handle=kernel.OpenProcess(0x1000,False,pid)
            if not handle:
                if ctypes.get_last_error()==87: return False
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                code=w.DWORD()
                if not kernel.GetExitCodeProcess(handle,ctypes.byref(code)):
                    raise ctypes.WinError(ctypes.get_last_error())
                return code.value==259
            finally:
                kernel.CloseHandle(handle)
        stat=Path(f'/proc/{pid}/stat')
        if sys.platform.startswith('linux'):
            return stat.exists() and stat.read_text().split()[2]!='Z'
        result=subprocess.run(['ps','-o','stat=','-p',str(pid)],capture_output=True,text=True,timeout=3)
        return bool(result.stdout.strip()) and not result.stdout.strip().startswith('Z')
    def check(pid):
        deadline=time.monotonic()+3
        while running(pid):
            if time.monotonic()>=deadline:
                raise AssertionError(f'owned descendant {pid} is still executing')
            time.sleep(.02)
    return check
