"""Trusted explicit PATH search, without Windows' implicit current directory."""
import os
from pathlib import Path


def trusted_directories(env=None):
    env = os.environ if env is None else env
    cwd = os.path.normcase(os.path.realpath(os.getcwd()))
    found = []
    identities = set()
    for entry in env.get('PATH', os.defpath).split(os.pathsep):
        if not entry or not os.path.isabs(entry):
            continue
        p = os.path.realpath(entry)
        identity = os.path.normcase(p)
        if identity != cwd and identity not in identities:
            found.append(p)
            identities.add(identity)
    return found


def trusted_path(env=None):
    return os.pathsep.join(trusted_directories(env))


def resolve_tool(name, env=None):
    env = os.environ if env is None else env
    p = Path(name)
    if p.suffix.lower() in {'.cmd', '.bat'}:
        raise ValueError('shell wrappers are not supported; select a native executable')
    if p.is_absolute() or p.parent != Path('.'):
        choices = [p.absolute()]
    else:
        suffixes = ['']
        if os.name == 'nt' and not p.suffix:
            suffixes = [ext.lower() for ext in env.get('PATHEXT', '.COM;.EXE').split(';') if ext.lower() not in {'.bat', '.cmd'}]
        choices = [Path(d)/(name+ext) for d in trusted_directories(env) for ext in suffixes]
    for candidate in choices:
        if candidate.is_file() and (os.name == 'nt' or os.access(candidate, os.X_OK)):
            return str(candidate.absolute())
    raise FileNotFoundError(f'native executable not found on trusted PATH: {name}')


def media_argv(argv, env=None):
    args = [str(x) for x in argv]
    if Path(args[0]).name.lower() in {'ffmpeg', 'ffprobe', 'ffmpeg.exe', 'ffprobe.exe'}:
        args[0] = resolve_tool(args[0], env)
    return args
