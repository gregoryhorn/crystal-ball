"""Selected-engine-only native loader initialization; no machine PATH changes."""
import os
from pathlib import Path
import sysconfig

_HANDLES = []


def initialize():
    if os.name != 'nt':
        return
    roots = {Path(sysconfig.get_path(key)) for key in ('purelib', 'platlib')}
    directories = []
    for root in roots:
        for pattern in ('nvidia/*/bin', 'nvidia/*/lib', 'torch/lib'):
            directories.extend(p for p in root.glob(pattern) if p.is_dir())
    for directory in directories:
        _HANDLES.append(os.add_dll_directory(str(directory)))
    os.environ['PATH'] = os.pathsep.join([*(str(p) for p in directories), os.environ.get('PATH', '')])
