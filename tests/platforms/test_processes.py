import io
import json
import os
import subprocess
import sys
import time
import pytest
from crystal_ball.platforms.process import spawn_owned, run_owned
from crystal_ball.platforms.streams import LineReader
from crystal_ball.util import same_python_env


def test_utf8_binary_and_environment():
    result=run_owned([sys.executable,'-c',"print('héllo')"],capture_output=True,text=True,env=same_python_env(),timeout=5,check=True)
    assert result.stdout=='héllo\n'
    raw=run_owned([sys.executable,'-c',"import sys; sys.stdout.buffer.write(bytes([0,255]))"],capture_output=True,timeout=5)
    assert raw.stdout==b'\x00\xff'


def test_deadline_kills_descendant_not_sentinel(tmp_path,assert_stopped):
    code="import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c',\"import time; time.sleep(60)\"]); print(p.pid,flush=True); time.sleep(60)"
    sentinel=spawn_owned([sys.executable,'-c','import time; time.sleep(60)'])
    proc=spawn_owned([sys.executable,'-u','-c',code],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=same_python_env())
    try:
        pid=int(proc.stdout.readline())
        with pytest.raises(subprocess.TimeoutExpired):
            proc.communicate(timeout=.1)
        assert sentinel.poll() is None
        assert_stopped(pid)
    finally:
        proc.close(); sentinel.close()


def test_reader_two_requests_large_stderr(tmp_path):
    code="import sys,json,os; sys.stderr.write('x'*200000); sys.stderr.flush();\nfor line in sys.stdin:\n r=json.loads(line); print(json.dumps({'id':r['id'],'text':'héllo','pid':os.getpid()}),flush=True)"
    with (tmp_path/'stderr').open('wb') as err:
        proc=spawn_owned([sys.executable,'-u','-c',code],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,text=True,env=same_python_env())
        reader=LineReader(proc.stdout)
        try:
            ids=[]
            for i in (1,2):
                proc.stdin.write(json.dumps({'id':i})+'\n'); proc.stdin.flush()
                value=json.loads(reader.get(5)); assert value['id']==i; assert value['text']=='héllo'; ids.append(value['pid'])
            assert ids[0]==ids[1]
        finally:
            proc.stdin.close(); proc.proc.wait(timeout=3); proc.close(); reader.close()


@pytest.mark.parametrize('text,error',[('',EOFError),('partial',ValueError)])
def test_reader_eof_and_partial(text,error):
    reader=LineReader(io.StringIO(text))
    with pytest.raises(error): reader.get(1)
    reader.close()
