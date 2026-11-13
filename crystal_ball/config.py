"""Explicit configuration; loading never imports an engine or accesses the network."""
import copy
import glob
import os
import re
import sys
import tomllib
from pathlib import Path
from .platforms.paths import cache_home, config_candidates, resolve_config_path, resolve_model, windows

DEFAULTS = {
    'cache_dir': cache_home(), 'projects_root': None,
    'hear': {'python': sys.executable, 'model': 'large-v3-turbo', 'device': 'cpu' if windows() else 'cuda', 'min_free_vram_gb': 3.5, 'cpu_threads': 4, 'demucs_command': []},
    'whispercpp': {'bin': '', 'model': ''},
    'see': {'python': sys.executable, 'model': 'openai/clip-vit-large-patch14', 'device': 'cpu' if windows() else 'cuda', 'min_free_vram_gb': 2.5, 'cpu_threads': 4},
    'rhythm': {'python': sys.executable},
    'scenes': {'python': sys.executable, 'detector': 'content', 'threshold': 27.0, 'min_shot_s': 0.3},
    'read': {'tessdata': ''},
    'judge': {'backend': 'off', 'base_url': '', 'model': '', 'api_key_env': ''},
    'rules': {'files': []}, 'fix': {'protected': ['**/final/**']},
}

def load(path=None):
    cfg = copy.deepcopy(DEFAULTS)
    explicit = path or os.environ.get('CRYSTAL_BALL_CONFIG')
    candidates = [Path(resolve_config_path(explicit, Path.cwd()))] if explicit else config_candidates()
    chosen = next((p for p in candidates if p.is_file()), None)
    if explicit and chosen is None:
        raise FileNotFoundError('explicit Crystal Ball config does not exist')
    if chosen:
        doc = tomllib.loads(chosen.read_text(encoding='utf-8-sig'))
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
    for section, key in [(None,'cache_dir'),(None,'projects_root'),('hear','python'),('see','python'),('rhythm','python'),('scenes','python'),('read','tessdata'),('whispercpp','model'),('whispercpp','bin')]:
        value = cfg[section][key] if section else cfg[key]
        if value:
            new = resolve_config_path(value, base, executable=key in {'python','bin'})
            if section:
                cfg[section][key] = new
            else:
                cfg[key] = new
    for section in ('hear','see'):
        cfg[section]['model'] = resolve_model(cfg[section]['model'], base)
        if cfg[section]['device'] not in {'cpu','cuda'}:
            raise ValueError(f'{section}.device must be cpu or cuda')
    if cfg['judge']['backend'] not in {'off','hermes-auxiliary','openai-compatible'}:
        raise ValueError('invalid judge backend')
    for section, key in [('rules','files'),('fix','protected'),('hear','demucs_command')]:
        if not isinstance(cfg[section][key], list) or any(not isinstance(x,str) for x in cfg[section][key]):
            raise ValueError(f'{section}.{key} must be an array of strings')
    if cfg['scenes']['detector'] not in {'content','adaptive'}:
        raise ValueError('scenes.detector must be content or adaptive')
    for section,key in [('scenes','threshold'),('scenes','min_shot_s'),('hear','min_free_vram_gb'),('see','min_free_vram_gb')]:
        cfg[section][key]=float(cfg[section][key])
        if not 0 < cfg[section][key] < float('inf'):
            raise ValueError(f'{section}.{key} must be positive and finite')
    for section in ('hear','see'):
        cfg[section]['cpu_threads']=int(cfg[section]['cpu_threads'])
        if cfg[section]['cpu_threads']<1:
            raise ValueError('cpu_threads must be positive')
    cfg['_base'] = str(base)
    return cfg

def rules_for(path=None, config=None):
    from .cache import fingerprint
    cfg = config or load()
    files = set()
    for pattern in cfg['rules']['files']:
        p = Path(pattern).expanduser()
        files.update(Path(f) for f in glob.glob(str(p if p.is_absolute() else Path(cfg['_base'])/p), recursive=True) if Path(f).is_file() and Path(f).suffix.lower()=='.md')
    active = '\n'.join(p.read_text(encoding='utf-8', errors='replace') for p in sorted(files))
    terms = re.findall(r'["“`«]([^"”`»\n]{2,80})["”`»]', active)
    terms += re.findall(r'\b[A-Z][a-z]+(?:[ -][A-Z][a-z]+){0,3}\b|\b[A-Z]{2,20}\b', active)
    return {'active': active, 'terms': sorted(set(terms)), 'deps': {str(p):fingerprint(p) for p in sorted(files)}}
