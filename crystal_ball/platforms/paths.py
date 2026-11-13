"""Configuration paths and identities, separate from model identifiers."""
import ntpath
import os
from pathlib import Path, PureWindowsPath


def windows():
    return os.name == 'nt'


def cache_home():
    return str(Path(os.environ.get('LOCALAPPDATA', str(Path.home()/'AppData/Local')))/'crystal-ball/cache') if windows() else '~/.cache/crystal-ball'


def config_candidates():
    candidates = [Path.cwd()/'crystal-ball.toml', Path.home()/'.config/crystal-ball/config.toml']
    if windows():
        candidates.append(Path(os.environ.get('APPDATA', str(Path.home()/'AppData/Roaming')))/'crystal-ball/config.toml')
    return candidates


def expand(value):
    value = os.path.expandvars(os.path.expanduser(str(value)))
    return ntpath.expandvars(value) if windows() else value


def resolve_config_path(value, base, executable=False):
    value = expand(value)
    if windows():
        p = PureWindowsPath(value)
        if (p.drive and not p.root) or (p.root and not p.drive):
            raise ValueError(f'ambiguous Windows path: {value}; use a full drive/UNC path')
        if executable and not p.drive and not p.root and len(p.parts) == 1 and not value.startswith('.'):
            return value
        return str(p if p.is_absolute() else PureWindowsPath(base)/p)
    p = Path(value)
    if executable and len(p.parts) == 1 and not value.startswith('.'):
        return value
    return str(p if p.is_absolute() else Path(base)/p)


def resolve_model(value, base):
    value = expand(value)
    p = PureWindowsPath(value) if windows() else Path(value)
    explicit = value.startswith(('.', '~', '/', '\\')) or bool(windows() and p.drive)
    return resolve_config_path(value, base) if explicit else value


def identity(path):
    return os.path.normcase(os.path.abspath(path))
