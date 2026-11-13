"""Wheel-only Windows CPython 3.11 x64 recipes."""
from pathlib import Path
import os
import platform
import sys
import sysconfig


def requirements_root():
    root = Path(__file__).resolve().parents[3]/'requirements'
    if not root.is_dir():
        root = Path(sysconfig.get_path('data'))/'share/crystal-ball/requirements'
    return root


def validate_platform():
    if os.name != 'nt' or sys.version_info[:2] != (3, 11) or platform.machine().lower() not in {'amd64','x86_64'}:
        raise RuntimeError('managed install recipe requires native Windows x64 CPython 3.11; use print-only setup for other runtimes')
    # CTranslate2's external Microsoft prerequisite; do not install it silently.
    import ctypes
    try:
        ctypes.WinDLL('vcruntime140.dll')
        ctypes.WinDLL('msvcp140.dll')
    except OSError as exc:
        raise RuntimeError('Microsoft Visual C++ x64 runtime not installed; see https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist') from exc


def locks(engine):
    root = requirements_root()/'windows'
    names = [engine+'-cpu.lock'] + (['torch-cpu.lock'] if engine=='see' else [])
    result = [root/name for name in names]
    if not all(p.is_file() for p in result):
        raise RuntimeError('Windows CPU wheel recipe not packaged')
    return result
