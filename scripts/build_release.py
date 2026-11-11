#!/usr/bin/env python3
"""Build locally without installs/network, normalize archive identity, and scan contents."""
import contextlib
import gzip
import io
import os
import tarfile
import zipfile
from pathlib import Path
from setuptools import build_meta
from privacy_scan import scan_text

ROOT=Path(__file__).resolve().parents[1]

def normalize_sdist(path):
    # Standard tar creation inherits account ownership; publish only anonymous metadata.
    buffer=io.BytesIO()
    with tarfile.open(path,'r:gz') as source, tarfile.open(fileobj=buffer,mode='w',format=tarfile.PAX_FORMAT) as target:
        for member in source.getmembers():
            member.uid=member.gid=0
            member.uname=member.gname=''
            member.mtime=0
            member.pax_headers={}
            target.addfile(member,source.extractfile(member) if member.isfile() else None)
    path.write_bytes(gzip.compress(buffer.getvalue(),mtime=0))

def inspect_archive(path):
    count=0
    def inspect(name,data):
        nonlocal count
        text=data.decode('utf-8')
        if scan_text(name) or scan_text(text):
            raise ValueError('privacy scan failed in archive member: '+name)
        count+=1
    if path.suffix=='.whl':
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if not name.endswith('/'):
                    inspect(name,archive.read(name))
    else:
        with tarfile.open(path,'r:gz') as archive:
            for member in archive.getmembers():
                if member.uname or member.gname or member.uid or member.gid or member.pax_headers:
                    raise ValueError('unexpected archive identity metadata')
                if member.issym() or member.islnk():
                    raise ValueError('archive links are not expected')
                if member.isfile():
                    inspect(member.name,archive.extractfile(member).read())
    return count

def main():
    os.chdir(ROOT)
    out=ROOT/'dist'; out.mkdir(exist_ok=True)
    # Keep detailed build chatter in an ignored local log.
    with (out/'build.log').open('w') as log, contextlib.redirect_stdout(log):
        wheel=out/build_meta.build_wheel(str(out))
        source=out/build_meta.build_sdist(str(out))
    normalize_sdist(source)
    for path in (wheel,source):
        print(f'{path.name}: PASS ({inspect_archive(path)} privacy-scanned members)')

if __name__=='__main__':
    main()
