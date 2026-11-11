import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


def test_privacy_matchers_and_placeholder_exceptions():
    p=Path(__file__).resolve().parents[1]/'scripts/privacy_scan.py'
    spec=importlib.util.spec_from_file_location('privacy',p); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    for value in (module.PRIVATE_PATH+'person',module.LAN+'1.1',module.BUILTIN_NAMES[-1],'user'+'@'+'private.invalid','sk-'+'a'*40):
        assert module.scan_text(value)
    assert not module.scan_text('user@example.invalid')
    assert not module.scan_text('Copyright (c) 2026 '+module.BUILTIN_NAMES[0].title()+' Horn')


def test_cache_serializes_independent_processes(tmp_path):
    file=tmp_path/'source'; file.write_text('synthetic')
    counter=tmp_path/'counter'
    code='''from crystal_ball.cache import Store
from pathlib import Path
import sys,time
source,cache,counter=sys.argv[1:]
def produce(directory):
    p=Path(counter)
    value=int(p.read_text())+1 if p.exists() else 1
    time.sleep(.1)
    p.write_text(str(value))
    return {"value":value}
print(Store(cache).get(source,"test",{},produce))
'''
    procs=[subprocess.Popen([sys.executable,'-E','-c',code,str(file),str(tmp_path/'cache'),str(counter)],stdout=subprocess.PIPE,text=True) for _ in range(3)]
    results=[p.communicate(timeout=10)[0] for p in procs]
    assert all(p.returncode==0 for p in procs)
    assert counter.read_text()=='1' and len(set(results))==1
