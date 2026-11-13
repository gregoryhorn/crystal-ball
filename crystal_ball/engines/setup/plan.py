"""Read-only plan and narrowly scoped, verified TOML key patching."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tomllib
import uuid
from ...config import load
from ...platforms.paths import config_candidates
from .recipes import locks


def digest(data):
    return hashlib.sha256(data).hexdigest()


def trailing_comment(line):
    quote=None; escaped=False
    for index,char in enumerate(line):
        if quote=='"' and char=='\\' and not escaped:
            escaped=True
            continue
        if char==quote and not escaped:
            quote=None
        elif quote is None:
            if char in {'"',"'"}:
                quote=char
            elif char=='#':
                return ' '+line[index:]
        escaped=False
    return ''


def patch_config(text, updates):
    before = tomllib.loads(text.lstrip('\ufeff')) if text else {}
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith('\n'):
        lines[-1]+='\n'
    for section, values in updates.items():
        start = next((i for i,l in enumerate(lines) if re.match(r'^\s*\['+re.escape(section)+r'\]\s*(?:#.*)?$', l.strip())), None)
        if start is None:
            lines.extend(['\n['+section+']\n'])
            start = len(lines)-1
        end = next((i for i in range(start+1,len(lines)) if lines[i].lstrip().startswith('[')),len(lines))
        for key, value in values.items():
            pattern = r'^(\s*'+re.escape(key)+r'\s*=\s*).*?$'
            index = next((i for i in range(start+1,end) if re.match(pattern, lines[i].rstrip('\r\n'))),None)
            replacement = key+' = '+json.dumps(value,ensure_ascii=False)+'\n'
            if index is None:
                lines.insert(end, replacement); end += 1
            else:
                # Preserve trailing comments outside quoted TOML strings.
                raw = lines[index].rstrip('\r\n')
                replacement = replacement.rstrip('\n')+trailing_comment(raw)+'\n'
                lines[index] = replacement
    result = ''.join(lines)
    expected = dict(before)
    for section, values in updates.items():
        expected[section] = {**before.get(section, {}), **values}
    if tomllib.loads(result.lstrip('\ufeff')) != expected:
        raise ValueError('config syntax cannot be safely patched; prior config unchanged')
    return result


def make_plan(engine=None):
    if engine=='read':
        raise ValueError('Read is an external Tesseract installation; use setup read (print-only)')
    selected = [engine] if engine else ['hear','see']
    cfg = load()
    explicit = os.environ.get('CRYSTAL_BALL_CONFIG')
    target = Path(explicit).expanduser().absolute() if explicit else next((p for p in config_candidates() if p.is_file()),config_candidates()[-1])
    original = target.read_bytes() if target.exists() else None
    root = Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'crystal-ball/engines'
    entries = []
    for name in selected:
        generation = root/name/uuid.uuid4().hex
        entry={'engine':name, 'generation':str(generation), 'python':str(generation/'Scripts/python.exe'),
                        'model':cfg[name]['model'], 'download_destination':str(generation/'models'),
                        'locks':[str(p) for p in locks(name)]}
        prior=Path(cfg[name]['python']).parent.parent
        manifest=prior/'manifest.json'
        if prior.is_relative_to(root/name) and manifest.is_file():
            try:
                saved=json.loads(manifest.read_text(encoding='utf-8'))
                expected={str(p):digest(p.read_bytes()) for p in locks(name)}
                if (saved.get('state')=='validated' and saved.get('engine')==name and
                    saved.get('lock_hashes')==expected and saved.get('snapshot')==cfg[name]['model'] and
                    saved.get('python')==cfg[name]['python'] and Path(saved['snapshot']).is_dir()):
                    entry={**entry,'generation':str(prior),'python':cfg[name]['python'],'reuse':True,
                           'download_destination':str(prior/'models')}
            except (OSError,ValueError,KeyError):
                pass
        entries.append(entry)
    return {'engines':entries, 'python':sys.executable, 'recipe':'Windows x64 CPython 3.11 CPU',
            'config':str(target), 'original_digest':digest(original) if original is not None else None,
            'config_diff':{e['engine']:{'python':e['python'],'device':'cpu','model':'validated local snapshot (under download_destination if missing)'} for e in entries},
            'overrides':sorted(k for k in os.environ if any(k.startswith('CRYSTAL_BALL_'+s.upper()+'_') for s in selected)),
            'network_sources':['https://pypi.org/simple','https://download.pytorch.org/whl/cpu','https://huggingface.co'],
            'disk':'size not checked', 'external':['FFmpeg/ffprobe >=6.1','Microsoft Visual C++ x64 runtime'], 'downloads_require_confirmation':True}
