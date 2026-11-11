#!/usr/bin/env python3
"""Copy a self-contained plugin into one Hermes home; never run pip."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MANIFEST='plugins/crystal-ball/install-manifest.json'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def install(home, config_from=None, uninstall=False):
    home=Path(home).expanduser().resolve()
    manifest=home/MANIFEST
    previous=json.loads(manifest.read_text()) if manifest.is_file() else {'files':{},'dirs':[]}
    # Accept historical manifests; only installation paths are removable below.
    def owned(name):
        p=Path(name)
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
            safe=not any(parent.is_symlink() for parent in [p,*p.parents] if parent.is_relative_to(home))
            if safe and p.is_file() and digest(p.read_bytes())==sha:
                p.unlink()
            elif p.exists():
                retained.append(name)
        if retained:
            previous['files']={name:previous['files'][name] for name in retained}
            manifest.write_text(json.dumps(previous,indent=2)+'\n')
        else:
            manifest.unlink(missing_ok=True)
        for name in sorted(previous['dirs'],key=lambda x:len(Path(x).parts),reverse=True):
            p=home/name
            if p.is_dir() and not any(parent.is_symlink() for parent in [p,*p.parents] if parent.is_relative_to(home)):
                try:
                    p.rmdir()
                except OSError:
                    pass
        return {'status':'uninstalled','retained_modified':retained}
    sources={}
    for source, dest in [(ROOT/'hermes_plugin/crystal-ball','plugins/crystal-ball'),(ROOT/'crystal_ball','plugins/crystal-ball/_vendor/crystal_ball'),(ROOT/'hermes_plugin/skill/crystal-ball','skills/crystal-ball')]:
        for p in source.rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc':
                sources[str(Path(dest)/p.relative_to(source))]=p.read_bytes()
    if not config.exists() and not config.is_symlink():
        sources['crystal-ball.toml']=Path(config_from or ROOT/'crystal-ball.example.toml').read_bytes()
    # Check all collisions before writing anything.
    for name,data in sources.items():
        p=home/name
        if p.is_symlink() or any(parent.is_symlink() for parent in p.parents if parent!=home.parent):
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
                dirs.add(str(parent.relative_to(home)))
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
    manifest.write_text(json.dumps({'files':files,'dirs':sorted(dirs),'user_data':['crystal-ball.toml']},indent=2)+'\n')
    return {'status':'installed','files':len(files),'manifest':str(manifest)}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--hermes-home',required=True); ap.add_argument('--config-from'); ap.add_argument('--uninstall',action='store_true')
    args=ap.parse_args()
    print(json.dumps(install(args.hermes_home,args.config_from,args.uninstall)))

if __name__=='__main__':
    main()
