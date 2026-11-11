"""Hermes environment isolation, silent video and compact failure regressions."""
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from crystal_ball import api, cli, core, hermes, tool_worker, workers
from crystal_ball.config import load
from crystal_ball.senses import hear, rhythm
from crystal_ball.util import foreign_python_env


REMOVED = ('PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONUSERBASE', 'PYTHONEXECUTABLE',
           'VIRTUAL_ENV', '__PYVENV_LAUNCHER__', 'PYTHONSAFEPATH', 'CONDA_PREFIX')


@pytest.fixture
def poison(tmp_path, monkeypatch):
    fake = tmp_path / 'fake-stdlib'
    fake.mkdir()
    for module in ('re', 'threading'):
        (fake / (module + '.py')).write_text("raise AssertionError('wrong stdlib')\n")
    for key in (*REMOVED, 'PYTHONPATH'):
        monkeypatch.setenv(key, str(fake))
    return fake


def test_foreign_env_real_child(poison):
    before = dict(os.environ)
    env = foreign_python_env({'HF_HUB_OFFLINE': '1', 'PYTHONHOME': str(poison)})
    assert os.environ == before
    assert all(key not in env for key in REMOVED)
    assert env['PYTHONPATH'] == str(Path(core.__file__).resolve().parent.parent)
    assert env['PYTHONNOUSERSITE'] == '1' and env['HF_HUB_OFFLINE'] == '1'
    proc = subprocess.run([sys.executable, '-c',
        "import re, threading, crystal_ball; print(re.compile('ok').pattern)"],
        env=env, capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == 'ok'


@pytest.fixture
def stub_engine_launches(monkeypatch, poison):
    """Replace engine inference only; launch real Python with the caller's env."""
    original = subprocess.Popen
    seen = []
    code = """
import json, re, threading, sys
kind = sys.argv[1]
if kind == 'hear_worker':
    for line in sys.stdin:
        req = json.loads(line)
        print(json.dumps({'id': req['id'], 'result': {'text': 'ok', 'segments': [], 'engine': 'stub'}}), flush=True)
else:
    if kind != 'doctor_worker' or len(sys.argv) == 2:
        json.load(sys.stdin)
    print(json.dumps({'version': 'stub', 'gpu_count': 0} if kind == 'doctor_worker' else {'status': 'ok'}))
"""
    def launch(cmd, *args, **kw):
        if '-m' in cmd and str(cmd[cmd.index('-m') + 1]).startswith('crystal_ball.'):
            module = cmd[cmd.index('-m') + 1]
            env = kw['env']
            assert all(key not in env for key in REMOVED)
            assert str(poison) not in env['PYTHONPATH']
            seen.append(module)
            cmd = [cmd[0], '-u', '-c', code, module.rsplit('.', 1)[-1], *cmd[cmd.index('-m') + 2:]]
        return original(cmd, *args, **kw)
    monkeypatch.setattr(subprocess, 'Popen', launch)
    return seen


@pytest.mark.parametrize('kind', ['see', 'rhythm', 'scenes'])
def test_each_worker_kind_poisoned(kind, stub_engine_launches):
    result = workers.request(sys.executable, f'crystal_ball.senses.{kind}_worker', {}, 10)
    assert result['status'] == 'ok'


def test_hear_persistent_worker_and_prefix_poisoned(stub_engine_launches):
    cfg = load(); cfg['hear']['python'] = sys.executable
    with hear.Worker(cfg) as worker:
        assert worker.transcribe('stub.wav')['text'] == 'ok'
        assert worker.transcribe('stub.wav')['text'] == 'ok'


def test_see_api_and_doctor_poisoned(monkeypatch, stub_engine_launches):
    from crystal_ball.doctor import doctor
    cfg = load()
    for kind in ('hear', 'see', 'rhythm', 'scenes'):
        cfg[kind]['python'] = sys.executable
    monkeypatch.setattr(api, 'load', lambda: cfg)
    assert api.dispatch('find', text='test')['status'] == 'ok'
    result = doctor(cfg)
    rows = {row['engine']: row for row in result['checks']}
    assert rows['hear']['detail'].startswith('local model verified')
    assert rows['see']['status'] == rows['rhythm']['status'] == rows['scenes']['status'] == 'PASS'
    assert 'crystal_ball.doctor_worker' in stub_engine_launches


@pytest.fixture
def silent_video(tmp_path):
    file = tmp_path / 'silent.mp4'
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                    'color=s=160x90:r=25:d=0.4', '-an', '-threads', '1', str(file)],
                   check=True, capture_output=True, timeout=15)
    return str(file)


def test_no_audio_skips_without_engine_or_extraction(silent_video, monkeypatch, tmp_path, capsys):
    def forbidden(*args, **kw):
        raise AssertionError('audio engine must not run')
    monkeypatch.setattr(hear.Worker, 'start', forbidden)
    monkeypatch.setattr(hear, 'whispercpp', forbidden)
    monkeypatch.setattr(hear, 'voice_balance', forbidden)
    monkeypatch.setattr(workers, 'request', forbidden)
    assert hear.transcribe(silent_video)['checks'][0] == core.row('audio', 'SKIP', 'no audio stream')
    req = {'file': silent_video, 'run_dir': str(tmp_path / 'run'), 'config': load()}
    assert hear.audio_stage(req)['checks'][0]['summary'] == 'no audio stream'
    stage = core.run_stage('audio', req)
    assert stage['checks'][0] == core.row('audio', 'SKIP', 'no audio stream')
    assert 'log' not in stage
    assert cli.main(['transcribe', silent_video, '-o', str(tmp_path / 'out.json')]) == 0
    assert json.loads(capsys.readouterr().out)['checks'][0]['status'] == 'SKIP'
    assert not (tmp_path / 'out.json').exists()


@pytest.mark.parametrize('action', ['beats', 'cuts'])
def test_no_audio_beats_cuts_compact_error(action, silent_video, monkeypatch, capsys):
    def forbidden(*args, **kw):
        raise AssertionError('worker must not run')
    monkeypatch.setattr(workers, 'request', forbidden)
    assert cli.main([action, silent_video]) == 2
    result = json.loads(capsys.readouterr().err)
    assert result['error'] == f'{action}: ValueError: no audio stream; pass --music AUDIO'
    assert len(result['error']) <= 240 and Path(result['log']).is_file()


def fail_with_traceback(*args, **kw):
    # Enough trace text to push the exception beyond the old head truncation.
    from crystal_ball.util import StageError
    raise StageError('rhythm', 'Traceback (most recent call last):\n' +
                     ('  File "engine.py", line 9, in analyse\n' * 20) +
                     'AttributeError: engine exploded')


def assert_failure(result):
    assert result['error'] == 'rhythm: AttributeError: engine exploded'
    assert len(result['error']) <= 240
    log = Path(result['log']).read_text()
    assert 'Traceback (most recent call last):' in log
    assert log.count('in analyse') >= 20
    assert 'AttributeError: engine exploded' in log


def test_cli_and_tool_errors_keep_final_exception_and_full_log(monkeypatch, capsys):
    monkeypatch.setattr(cli, 'dispatch', fail_with_traceback)
    assert cli.main(['beats', 'stub.mp4']) == 2
    assert_failure(json.loads(capsys.readouterr().err))
    monkeypatch.setattr(tool_worker, 'dispatch', fail_with_traceback)
    monkeypatch.setattr(sys, 'stdin', io.StringIO('{"action":"beats","file":"stub.mp4"}'))
    assert tool_worker.main() == 0
    assert_failure(json.loads(capsys.readouterr().out))


def test_stage_error_log_reaches_compact_result(monkeypatch, tmp_path):
    monkeypatch.setattr(core, 'process_json', fail_with_traceback)
    stage = core.run_stage('audio', {'run_dir': str(tmp_path), 'cache_dir': str(tmp_path / 'cache')})
    assert stage['checks'][0]['summary'] == 'rhythm: AttributeError: engine exploded'
    assert Path(stage['log']).read_text().count('in analyse') >= 20
    result = core.compact({'checks': stage['checks'], 'stages': {'audio': stage},
                           'platform': 'youtube', 'report': 'report.html', 'frames_dir': 'frames'})
    assert result['log'] == stage['log']


def test_real_see_error_through_hermes_worker(poison, monkeypatch):
    monkeypatch.setenv('CRYSTAL_BALL_SEE_PYTHON', sys.executable)
    result = hermes.invoke('find', text='test', top=0)
    assert result['error'] == 'see: ValueError: top must be positive'
    assert len(result['error']) <= 240
    log = Path(result['log']).read_text()
    assert 'Traceback (most recent call last):' in log
    assert 'see_worker.py' in log and 'tool_worker.py' in log


def test_cuts_with_separate_music_preserves_audio_source(silent_video, monkeypatch, tmp_path):
    from crystal_ball.senses import scenes
    music = tmp_path / 'music.wav'
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                    'sine=d=0.4', str(music)], check=True, capture_output=True, timeout=15)
    sources = []
    def request(python, module, payload, timeout):
        sources.append(payload['file'])
        return {'beats': [0.], 'onsets': [0.], 'downbeats': [0.], 'duration': .4,
                'tempo': 120., 'confidence': 1., 'bars': [], 'beat_count': 1}
    monkeypatch.setattr(workers, 'request', request)
    monkeypatch.setattr(scenes, 'detect_scenes', lambda *args: {
        'shots': [{'start': 0., 'end': .4, 'duration': .4}], 'fps': 25,
        'shot_count': 1, 'paths': {'json': 'scenes.json'}})
    result = api.dispatch('cuts', file=silent_video, music=str(music))
    assert result['beat_count'] == 1
    assert sources == [str(music)]
