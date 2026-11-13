"""Fake-only admission and owned-lifetime regressions; never use live GPU/state."""
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from crystal_ball import gpu
from crystal_ball.senses import see, hear_worker


@pytest.fixture
def broker(monkeypatch):
    events=[]
    class Lease:
        def complete_gpu_work(self,cleanup):
            events.append('complete')
            cleanup()
            events.append('clean')
        def release(self):
            events.append('release')
        def stop_heartbeat(self):
            events.append('stop')
    def acquire(**kw):
        assert kw['wait'] is False and kw['expected_peak_mib']>0
        events.append('acquire')
        return Lease()
    monkeypatch.setitem(sys.modules,'gpu_broker',SimpleNamespace(acquire=acquire))
    return events


@pytest.mark.parametrize('error',[ImportError,RuntimeError,TimeoutError])
def test_broker_failure_cpu_no_cuda(monkeypatch,error):
    def acquire(**kw): raise error('unavailable')
    monkeypatch.setitem(sys.modules,'gpu_broker',SimpleNamespace(acquire=acquire))
    session=gpu.Session(purpose='test',model='fake')
    assert session.device=='cpu' and session.reason
    session.close(lambda:pytest.fail('CPU must not clean CUDA'))


def test_explicit_cpu_no_broker(monkeypatch):
    def acquire(**kw): pytest.fail('CPU must not acquire')
    monkeypatch.setitem(sys.modules,'gpu_broker',SimpleNamespace(acquire=acquire))
    session=gpu.Session(purpose='test',model='fake',enabled=False)
    assert session.device=='cpu' and session.reason is None


def test_failed_cleanup_does_not_release(broker):
    session=gpu.Session(purpose='test',model='fake')
    def cleanup(): raise RuntimeError('memory remains')
    assert 'lease retained' in session.close(cleanup)
    session.close(lambda:None)
    assert broker==['acquire','complete','stop']


def test_clip_without_cuda_preserves_cpu_fallback(monkeypatch,broker):
    monkeypatch.setattr(see,'_session',None)
    monkeypatch.setitem(sys.modules,'torch',SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:False)))
    assert see.device()=='cpu'
    assert 'CUDA unavailable' in see.ENGINE_INFO['fallback_reason']
    assert broker==['acquire','complete','clean','release','stop']
    see.close_models()


@pytest.mark.parametrize('fail',[False,True])
def test_clip_command_owns_load_inference_and_cleanup(monkeypatch,broker,fail):
    see._session=None
    see._owned_models.clear()
    class Model:
        def to(self,dev): broker.append('to-'+dev); return self
        def eval(self): return self
    class Loader:
        @staticmethod
        def from_pretrained(*a,**kw):
            broker.append('load')
            return Model()
    monkeypatch.setitem(sys.modules,'transformers',SimpleNamespace(CLIPModel=Loader,CLIPProcessor=Loader))
    monkeypatch.setitem(sys.modules,'torch',SimpleNamespace(float16='fp16',float32='fp32',set_num_threads=lambda n:None,
        cuda=SimpleNamespace(is_available=lambda:True,synchronize=lambda:broker.append('sync'),empty_cache=lambda:broker.append('empty'))))
    @see.model_work
    def command():
        model,proc,dev=see.load_model('fake')
        assert dev=='cuda'
        broker.append('inference')
        if fail: raise ValueError('inference failed')
    if fail:
        with pytest.raises(ValueError): command()
    else:
        command()
    assert broker.index('acquire')<broker.index('load')<broker.index('inference')<broker.index('sync')
    assert broker.index('sync')<broker.index('to-cpu')<broker.index('empty')<broker.index('release')
    assert see._session is None and not see._owned_models


def test_hear_reacquires_and_drops_only_owned_cuda(monkeypatch,broker):
    monkeypatch.setattr(hear_worker.subprocess,'run',lambda *a,**kw:SimpleNamespace(stdout=np.zeros(16,dtype='<f4').tobytes()))
    class Model:
        def __init__(self,*a,**kw):
            broker.append('load-'+kw['device'])
            self.model=SimpleNamespace(unload_model=lambda:broker.append('unload'))
        def transcribe(self,*a,**kw):
            def segments():
                broker.append('inference')
                yield from []
            return segments(),SimpleNamespace(language='en')
    monkeypatch.setitem(sys.modules,'faster_whisper',SimpleNamespace(WhisperModel=Model))
    engine=hear_worker.Engine()
    cpu=object(); engine.models[('cpu-cache','cpu',4)]=cpu
    for _ in range(2):
        result=engine.transcribe({'file':'fake','model':'stub','device':'cuda'})
        assert result['engine']=='faster-whisper-cuda'
        assert list(engine.models.values())==[cpu]
    assert broker==['acquire','load-cuda','inference','complete','unload','clean','release','stop']*2


def test_broker_completion_rejection_retains_occupancy(monkeypatch):
    events=[]
    def complete(cleanup):
        cleanup()
        raise RuntimeError('owned context still has VRAM')
    handle=SimpleNamespace(complete_gpu_work=complete,release=lambda:pytest.fail('unsafe release'),stop_heartbeat=lambda:events.append('stop'))
    monkeypatch.setitem(sys.modules,'gpu_broker',SimpleNamespace(acquire=lambda **kw:handle))
    session=gpu.Session(purpose='test',model='fake')
    assert 'lease retained' in session.close(lambda:events.append('cleanup'))
    assert events==['cleanup','stop']


@pytest.mark.parametrize('oom',[False,True])
def test_hear_cleanup_failure_retains_lease_and_cpu_retry(monkeypatch,broker,oom):
    monkeypatch.setattr(hear_worker.subprocess,'run',lambda *a,**kw:SimpleNamespace(stdout=b''))
    class Model:
        def __init__(self,*a,**kw):
            self.device=kw['device']
            self.model=SimpleNamespace(unload_model=self.unload)
        def unload(self):
            broker.append('failed-unload')
            raise RuntimeError('allocator cleanup failed')
        def transcribe(self,*a,**kw):
            if oom and self.device=='cuda':
                raise RuntimeError('CUDA out of memory')
            return [],SimpleNamespace(language='en')
    monkeypatch.setitem(sys.modules,'faster_whisper',SimpleNamespace(WhisperModel=Model))
    result=hear_worker.Engine().transcribe({'file':'fake','model':'stub','device':'cuda'})
    assert 'lease retained' in result['cleanup_reason']
    assert result['engine']==('faster-whisper-cpu' if oom else 'faster-whisper-cuda')
    assert broker==['acquire','complete','failed-unload','stop']


def test_clip_denied_path_does_not_touch_cuda(monkeypatch):
    class NoCuda:
        def __getattr__(self,name): pytest.fail('CPU touched CUDA: '+name)
    class Model:
        def to(self,dev): assert dev=='cpu'; return self
        def eval(self): return self
    loader=SimpleNamespace(from_pretrained=lambda *a,**kw:Model())
    monkeypatch.setitem(sys.modules,'transformers',SimpleNamespace(CLIPModel=loader,CLIPProcessor=loader))
    monkeypatch.setitem(sys.modules,'torch',SimpleNamespace(cuda=NoCuda(),float32='fp32',set_num_threads=lambda n:None))
    see._session=None
    @see.model_work
    def command():
        assert see.load_model('fake')[2]=='cpu'
    command()
    assert see.ENGINE_INFO['fallback_reason']
