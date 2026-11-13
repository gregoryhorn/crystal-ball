"""Freeze downloaded Windows wheels and verify their native dependency closure.

Run in a development venv with packaging; downloads/temporary data belong under
--wheels (the caller's approved scratch root). Never imports a downloaded wheel.
"""
import argparse
from email.parser import BytesParser
import hashlib
from pathlib import Path
import subprocess
import sys
import zipfile
from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version


def inventory(root):
    result = {}
    for wheel in sorted(root.glob('*.whl')):
        with zipfile.ZipFile(wheel) as archive:
            metadata = BytesParser().parsebytes(archive.read(next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))))
        name = canonicalize_name(metadata['Name'])
        if name in result and result[name][1]['Version'] != metadata['Version']:
            raise ValueError('multiple versions: '+name)
        result[name] = (wheel, metadata)
    return result


def freeze(root, output, torch_root=None):
    env = {**default_environment(), 'os_name':'nt', 'sys_platform':'win32', 'platform_system':'Windows',
           'platform_machine':'AMD64', 'python_version':'3.11', 'python_full_version':'3.11.15', 'extra':''}
    if torch_root:
        # Keep Torch itself on its dedicated index; resolve its PyPI dependencies here.
        torch = inventory(torch_root)['torch']
    else:
        torch = None
    for _ in range(12):
        items = inventory(root)
        if torch:
            items['torch'] = torch
        missing = set()
        for name, (_, meta) in items.items():
            for raw in meta.get_all('Requires-Dist', []):
                req = Requirement(raw)
                if req.marker and not req.marker.evaluate(env):
                    continue
                dep = canonicalize_name(req.name)
                if dep not in items:
                    missing.add(str(Requirement(req.name+str(req.specifier))))
                elif Version(items[dep][1]['Version']) not in req.specifier:
                    raise ValueError(f'conflict: {name} requires {req}, found {items[dep][1]["Version"]}')
        if not missing:
            break
        subprocess.run([sys.executable, '-m', 'pip', 'download', '--no-cache-dir', '--only-binary=:all:', '--no-deps',
                        '--platform', 'win_amd64', '--python-version', '311', '--implementation', 'cp', '--abi', 'cp311',
                        '--dest', str(root), *sorted(missing)], check=True)
    else:
        raise ValueError('dependency closure did not converge')
    lines = ['# CPython 3.11 Windows x64; resolved wheels, not native inference evidence.', '--index-url https://pypi.org/simple', '--only-binary :all:']
    for name, (wheel, meta) in sorted(inventory(root).items()):
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        lines.append(f'{name}=={meta["Version"]} --hash=sha256:{digest}')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    if torch:
        wheel, meta = torch
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        output.with_name('torch-cpu.lock').write_text('# Official CPU index only; install after see-cpu.lock with --no-deps.\n--index-url https://download.pytorch.org/whl/cpu\n--only-binary :all:\ntorch=='+meta['Version']+' --hash=sha256:'+digest+'\n', encoding='utf-8')
    print(f'{output.name}: dependency closure verified for Windows CPython 3.11 ({len(items)} wheels)')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--wheels', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--torch-wheels', type=Path)
    args = ap.parse_args()
    freeze(args.wheels, args.output, args.torch_wheels)
