"""Engine admission and profile-local installation, without model inference."""
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from crystal_ball import gpu
from crystal_ball.senses.hear_worker import Engine


def test_gpu_admission(monkeypatch):
    # Intentional contract change: tuple admission can never grant unleased CUDA.
    def forbidden():
        raise AssertionError('legacy admission must not initialize CUDA')
    cpu_torch=SimpleNamespace(cuda=SimpleNamespace(is_available=forbidden))
    dev,reason=gpu.admit(torch=cpu_torch)
    assert dev=='cpu' and reason


@pytest.mark.parametrize('oom_at',[None,'load','runtime'])
def test_hear_cpu_before_cpp_and_oom_retry(monkeypatch,oom_at):
    devices=[]; audio=np.zeros(16000,dtype='<f4').tobytes()
    monkeypatch.setattr('crystal_ball.senses.hear_worker.run_owned',lambda *a,**kw:SimpleNamespace(stdout=audio))
    class Lease:
        def complete_gpu_work(self,cleanup): cleanup()
        def release(self): pass
        def stop_heartbeat(self): pass
    if oom_at:
        monkeypatch.setitem(sys.modules,'gpu_broker',SimpleNamespace(acquire=lambda **kw:Lease()))
    class Model:
        def __init__(self,*a,**kw):
            self.dev=kw['device']; devices.append(kw)
            if oom_at=='load' and self.dev=='cuda':
                raise RuntimeError('CUDA out of memory')
        def transcribe(self,*a,**kw):
            def segments():
                if oom_at=='runtime' and self.dev=='cuda':
                    raise RuntimeError('CUDA out of memory')
                yield from []
            return segments(),SimpleNamespace(language='en')
    monkeypatch.setitem(sys.modules,'faster_whisper',SimpleNamespace(WhisperModel=Model))
    result=Engine().transcribe({'file':'synthetic.wav','model':'stub','device':'cuda','cpu_threads':3})
    assert result['engine']=='faster-whisper-cpu' and result['fallback_reason']
    assert [d['device'] for d in devices]==(['cuda','cpu'] if oom_at else ['cpu'])
    assert devices[-1]['compute_type']=='int8' and devices[-1]['cpu_threads']==3


def installer():
    path=Path(__file__).resolve().parents[1]/'scripts/install_hermes.py'
    spec=importlib.util.spec_from_file_location('installer',path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def test_install_uninstall_isolated_home(tmp_path):
    home=tmp_path/'profile'; home.mkdir()
    existing=home/'unrelated.txt'; existing.write_text('keep')
    config=home/'crystal-ball.toml'; config.write_text('# existing config\n')
    tool=installer(); result=tool.install(home)
    assert result['status']=='installed' and config.read_text()=='# existing config\n'
    plugin=home/'plugins/crystal-ball'
    assert (plugin/'_vendor/crystal_ball/api.py').is_file()
    # A fresh interpreter has no installed crystal_ball and no persistent sys.path addition.
    code='''import importlib.util,sys
before=list(sys.path)
spec=importlib.util.spec_from_file_location('plugin',sys.argv[1]); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
assert sys.path==before
import crystal_ball
assert '_vendor' in crystal_ball.__file__
'''
    subprocess.run([sys.executable,'-E','-B','-c',code,str(plugin/'__init__.py')],cwd=tmp_path,check=True,capture_output=True)
    assert tool.install(home)['status']=='installed'
    assert tool.install(home,uninstall=True)['retained_modified']==[]
    assert not plugin.exists() and not (home/'skills/crystal-ball').exists()
    assert existing.is_file() and config.read_text()=='# existing config\n'


def test_install_tracks_created_config_preserves_changed_files(tmp_path):
    tool=installer(); tool.install(tmp_path)
    config=tmp_path/'crystal-ball.toml'
    config.write_text('# operator edit\n')
    result=tool.install(tmp_path,uninstall=True)
    assert result['retained_modified']==[]  # Config is user data, not modified plugin code.
    assert config.read_text()=='# operator edit\n'


def test_clip_inference_oom_retries_once_on_cpu(monkeypatch):
    from crystal_ball.senses.see import cpu_retry,ENGINE_INFO
    calls=[]
    class Model:
        device='cuda'
        def to(self,dev):
            self.device=dev; return self
        def float(self):
            return self
    model=Model()
    monkeypatch.setitem(sys.modules,'torch',SimpleNamespace(cuda=SimpleNamespace(empty_cache=lambda:None)))
    @cpu_retry
    def infer(model,proc,device):
        calls.append(device)
        if device=='cuda':
            raise RuntimeError('CUDA out of memory')
        return 'embedded'
    assert infer(model,None,'cuda')=='embedded'
    assert calls==['cuda','cpu'] and ENGINE_INFO['engine']=='clip-cpu'
    assert ENGINE_INFO['fallback_reason']
    # Subsequent operations stay on the CPU even if the caller retains old dev.
    calls.clear(); assert infer(model,None,'cuda')=='embedded' and calls==['cpu']


def test_installer_collision_does_not_overwrite(tmp_path):
    plugin=tmp_path/'plugins/crystal-ball'; plugin.mkdir(parents=True)
    file=plugin/'__init__.py'; file.write_text('# pre-existing plugin\n')
    with pytest.raises(FileExistsError):
        installer().install(tmp_path)
    assert file.read_text()=='# pre-existing plugin\n'
    assert not (tmp_path/'skills').exists()


def test_clip_load_oom_retries_cpu_without_downloads(monkeypatch):
    from crystal_ball.senses import see
    seen=[]
    class Model:
        def to(self,dev):
            if dev=='cuda':
                raise RuntimeError('CUDA out of memory')
            return self
        def eval(self):
            return self
    class Loader:
        @staticmethod
        def from_pretrained(name,**kw):
            seen.append(kw); return Model()
    monkeypatch.setitem(sys.modules,'torch',SimpleNamespace(float16='fp16',float32='fp32',set_num_threads=lambda n:None,cuda=SimpleNamespace(empty_cache=lambda:None)))
    monkeypatch.setitem(sys.modules,'transformers',SimpleNamespace(CLIPModel=Loader,CLIPProcessor=Loader))
    monkeypatch.setattr(see,'device',lambda:'cuda')
    _,_,device=see.load_model('stub')
    assert device=='cpu'
    assert [s.get('torch_dtype') for s in seen[:2]]==['fp16','fp32']
    assert all(s['local_files_only'] is True for s in seen)
    assert see.ENGINE_INFO['engine']=='clip-cpu' and 'at load' in see.ENGINE_INFO['fallback_reason']
