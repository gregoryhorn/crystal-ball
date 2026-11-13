import importlib.util
import sys
from crystal_ball.config import load
from crystal_ball.platforms.runtime import core_media_python, describe_runtime, metadata_paths


def test_core_first_ignores_missing_optional_see():
    cfg=load(); cfg['see']['python']='missing-clip-runtime'
    assert core_media_python(cfg)==sys.executable


def test_thin_host_fallback(monkeypatch):
    monkeypatch.setattr(importlib.util,'find_spec',lambda name:None)
    cfg=load(); cfg['see']['python']='configured-engine'
    assert core_media_python(cfg)=='configured-engine'


def test_native_sysconfig_metadata():
    description=describe_runtime(sys.executable)
    assert description['python']==sys.executable
    assert description['sites']
    assert any(p.parent.name.lower().startswith('numpy-') for p in metadata_paths(sys.executable))


def test_runtime_sites_include_existing_system_and_user_dirs(tmp_path, monkeypatch):
    import contextlib
    import io
    import os
    import site
    import subprocess
    import sysconfig
    from crystal_ball.platforms import runtime

    pure, system, user = [tmp_path/name for name in ('pure', 'system', 'user')]
    for directory in (pure, system, user):
        directory.mkdir()
    missing = tmp_path/'missing'
    not_directory = tmp_path/'file'
    not_directory.write_text('not a package directory')
    metadata = system/'numpy-2.3.5.dist-info'/'METADATA'
    metadata.parent.mkdir()
    metadata.write_text('Name: numpy\nVersion: 2.3.5\n')

    def probe(argv, **kwargs):
        # Exercise the actual target-interpreter script against controlled sites.
        output = io.StringIO()
        with monkeypatch.context() as patch, contextlib.redirect_stdout(output):
            patch.setattr(sysconfig, 'get_path', lambda key: str(pure))
            patch.setattr(site, 'getsitepackages', lambda: [str(system), str(pure), str(missing), str(not_directory)])
            patch.setattr(site, 'getusersitepackages', lambda: str(user))
            exec(argv[2], {})
        return subprocess.CompletedProcess(argv, 0, output.getvalue(), '')

    monkeypatch.setattr(runtime, 'run_owned', probe)
    assert describe_runtime(sys.executable)['sites'] == [os.path.normcase(str(p)) for p in (pure, system, user)]
    assert metadata_paths(sys.executable) == [metadata]
