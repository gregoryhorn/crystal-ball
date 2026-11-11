"""Explicit configuration; loading never imports an engine or accesses the network."""
import copy
import glob
import os
import re
import sys
import tomllib
from pathlib import Path

DEFAULTS = {
    'cache_dir': '~/.cache/crystal-ball', 'projects_root': None,
    'hear': {'python': sys.executable, 'model': 'large-v3-turbo', 'device': 'cuda', 'demucs_command': []},
    'whispercpp': {'bin': '', 'model': ''},
    'see': {'python': sys.executable, 'model': 'openai/clip-vit-large-patch14'},
    'read': {'tessdata': ''},
    'judge': {'backend': 'off', 'base_url': '', 'model': '', 'api_key_env': ''},
    'rules': {'files': []}, 'fix': {'protected': ['**/final/**']},
}

def load(path=None):
    cfg = copy.deepcopy(DEFAULTS)
    explicit = path or os.environ.get('CRYSTAL_BALL_CONFIG')
    candidates = [Path(explicit).expanduser()] if explicit else [Path.cwd()/'crystal-ball.toml', Path('~/.config/crystal-ball/config.toml').expanduser()]
    chosen = next((p for p in candidates if p.is_file()), None)
    if explicit and chosen is None:
        raise FileNotFoundError('explicit Crystal Ball config does not exist')
    if chosen:
        doc = tomllib.loads(chosen.read_text())
        for key, value in doc.items():
            if key not in cfg:
                raise ValueError(f'unknown configuration key: {key}')
            if isinstance(cfg[key], dict):
                if not isinstance(value, dict) or set(value)-set(cfg[key]):
                    raise ValueError(f'invalid configuration section: {key}')
                cfg[key].update(value)
            else:
                cfg[key] = value
    for section, values in list(cfg.items()):
        entries = values.items() if isinstance(values, dict) else [(None, values)]
        for key, value in list(entries):
            envkey = 'CRYSTAL_BALL_' + '_'.join(x for x in (section, key) if x).upper()
            if envkey in os.environ:
                raw = os.environ[envkey]
                if isinstance(value, list):
                    value = tomllib.loads('value = '+raw)['value']
                else:
                    value = raw
                if key:
                    cfg[section][key] = value
                else:
                    cfg[section] = value
    base = chosen.resolve().parent if chosen else Path.cwd()
    for section, key in [(None,'cache_dir'),(None,'projects_root'),('hear','python'),('see','python'),('read','tessdata'),('whispercpp','model'),('whispercpp','bin')]:
        value = cfg[section][key] if section else cfg[key]
        if value:
            p = Path(os.path.expandvars(str(value))).expanduser()
            # Bare interpreter names are PATH commands, all other paths relative to config.
            if key in {'python','bin'} and len(p.parts) == 1 and not str(value).startswith('.'):
                new = str(p)
            else:
                new = str(p if p.is_absolute() else base/p)
            if section:
                cfg[section][key] = new
            else:
                cfg[key] = new
    for section in ('hear','see'):
        model = str(cfg[section]['model'])
        if model.startswith(('.', '~', '/')):
            p = Path(model).expanduser()
            cfg[section]['model'] = str(p if p.is_absolute() else base/p)
    if cfg['judge']['backend'] not in {'off','hermes-auxiliary','openai-compatible'}:
        raise ValueError('invalid judge backend')
    for section, key in [('rules','files'),('fix','protected'),('hear','demucs_command')]:
        if not isinstance(cfg[section][key], list) or any(not isinstance(x,str) for x in cfg[section][key]):
            raise ValueError(f'{section}.{key} must be an array of strings')
    cfg['_base'] = str(base)
    return cfg

def rules_for(path=None, config=None):
    from .cache import fingerprint
    cfg = config or load()
    files = set()
    for pattern in cfg['rules']['files']:
        p = Path(pattern).expanduser()
        files.update(Path(f) for f in glob.glob(str(p if p.is_absolute() else Path(cfg['_base'])/p), recursive=True) if Path(f).is_file() and Path(f).suffix.lower()=='.md')
    active = '\n'.join(p.read_text(errors='replace') for p in sorted(files))
    terms = re.findall(r'["“`«]([^"”`»\n]{2,80})["”`»]', active)
    terms += re.findall(r'\b[A-Z][a-z]+(?:[ -][A-Z][a-z]+){0,3}\b|\b[A-Z]{2,20}\b', active)
    return {'active': active, 'terms': sorted(set(terms)), 'deps': {str(p):fingerprint(p) for p in sorted(files)}}
