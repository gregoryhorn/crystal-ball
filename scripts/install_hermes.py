#!/usr/bin/env python3
"""Copy a self-contained plugin into one Hermes home; never run pip."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import os

ROOT=Path(__file__).resolve().parents[1]
MANIFEST='plugins/crystal-ball/install-manifest.json'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def portable(name):
    if not isinstance(name, str) or PureWindowsPath(name).drive or name.startswith(('/', '\\')):
        raise ValueError('invalid install manifest path')
    name=name.replace('\\','/')
    p=PurePosixPath(name)
    if '..' in p.parts or '.' in name.split('/') or '' in name.split('/'):
        raise ValueError('invalid install manifest path')
    return p.as_posix()


def reparse(path):
    try:
        return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)
    except FileNotFoundError:
        return False


def install(home, config_from=None, uninstall=False):
    home=Path(home).expanduser().resolve()
    manifest=home/MANIFEST
    if any(reparse(p) for p in (manifest, *manifest.parents) if p.is_relative_to(home)):
        raise ValueError('reparse point in install destination')
    previous=json.loads(manifest.read_text(encoding='utf-8')) if manifest.is_file() else {'files':{},'dirs':[]}
    names=[portable(name) for name in previous['files']]
    if len({os.path.normcase(n) for n in names}) != len(names):
        raise ValueError('ambiguous install manifest collision')
    previous['files']=dict(zip(names, previous['files'].values()))
    previous['dirs']=[portable(name) for name in previous['dirs']]
    # Accept historical manifests; only installation paths are removable below.
    def owned(name):
        p=PurePosixPath(name)
        return not p.is_absolute() and '..' not in p.parts and (name=='crystal-ball.toml' or name.startswith(('plugins/crystal-ball/','skills/crystal-ball/')))
    if any(not owned(name) for name in previous['files']) or any(not (name in {'plugins','skills','plugins/crystal-ball','skills/crystal-ball'} or owned(name)) for name in previous['dirs']):
        raise ValueError('invalid install manifest')
    # Migrate old manifests too: even an unchanged installer-created config is data.
    previous['files'].pop('crystal-ball.toml',None)
    previous['user_data']=['crystal-ball.toml']
    config=home/'crystal-ball.toml'
    if config.exists() or config.is_symlink():
        print(f'kept user config: {config}')
    if uninstall:
        retained=[]
        for name,sha in previous['files'].items():
            p=home/name
            safe=not any(reparse(parent) for parent in [p,*p.parents] if parent.is_relative_to(home)) and p.resolve().is_relative_to(home)
            if safe and p.is_file() and digest(p.read_bytes())==sha:
                p.unlink()
            elif p.exists():
                retained.append(name)
        if retained:
            previous['files']={name:previous['files'][name] for name in retained}
            manifest.write_text(json.dumps(previous,indent=2)+'\n', encoding='utf-8')
        else:
            manifest.unlink(missing_ok=True)
        for name in sorted(previous['dirs'],key=lambda x:len(Path(x).parts),reverse=True):
            p=home/name
            if p.is_dir() and not any(reparse(parent) for parent in [p,*p.parents] if parent.is_relative_to(home)):
                try:
                    p.rmdir()
                except OSError:
                    pass
        return {'status':'uninstalled','retained_modified':retained}
    sources={}
    for source, dest in [(ROOT/'hermes_plugin/crystal-ball','plugins/crystal-ball'),(ROOT/'crystal_ball','plugins/crystal-ball/_vendor/crystal_ball'),(ROOT/'hermes_plugin/skill/crystal-ball','skills/crystal-ball')]:
        for p in source.rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc':
                sources[(Path(dest)/p.relative_to(source)).as_posix()]=p.read_bytes()
    if not config.exists() and not config.is_symlink():
        sources['crystal-ball.toml']=Path(config_from or ROOT/'crystal-ball.example.toml').read_bytes()
    # Check all collisions before writing anything.
    for name,data in sources.items():
        p=home/name
        if any(reparse(parent) for parent in [p,*p.parents] if parent.is_relative_to(home)) or not p.resolve().is_relative_to(home):
            raise ValueError('symlink in install destination')
        if p.exists() and (name not in previous['files'] or digest(p.read_bytes())!=previous['files'][name]):
            raise FileExistsError(f'preserving existing file: {name}')
    dirs=set(previous['dirs']); files=dict(previous['files'])
    for name,data in sources.items():
        p=home/name
        for parent in p.parents:
            if parent==home or not parent.is_relative_to(home):
                break
            if not parent.exists():
                dirs.add(parent.relative_to(home).as_posix())
        p.parent.mkdir(parents=True,exist_ok=True)
        if name=='crystal-ball.toml':
            # Exclusive creation also preserves config created during installation.
            try:
                with p.open('xb') as target:
                    target.write(data)
            except FileExistsError:
                print(f'kept user config: {p}')
        else:
            p.write_bytes(data)
            files[name]=digest(data)
    manifest.write_text(json.dumps({'files':files,'dirs':sorted(dirs),'user_data':['crystal-ball.toml']},indent=2)+'\n', encoding='utf-8')
    return {'status':'installed','files':len(files),'manifest':str(manifest)}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--hermes-home',required=True); ap.add_argument('--config-from'); ap.add_argument('--uninstall',action='store_true')
    args=ap.parse_args()
    print(json.dumps(install(args.hermes_home,args.config_from,args.uninstall)))

if __name__=='__main__':
    main()
