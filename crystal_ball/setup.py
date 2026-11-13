"""Print reproducible user-run setup steps. Never installs as an import side effect."""
from pathlib import Path
import shlex
import sysconfig

def powershell(argv):
    return '& '+' '.join("'"+str(arg).replace("'","''")+"'" for arg in argv)

def instructions(engine=None):
    import os
    import subprocess
    import sys
    if os.name=='nt':
        from .engines.setup.recipes import requirements_root
        lines=['Print-only commands: nothing installed. Use setup --install for one-confirm managed CPU setup.',
               'Run the following commands in PowerShell; no shell activation is required.',
               'FFmpeg/ffprobe >=6.1 and optional Tesseract are external native tools on trusted PATH.',
               'Microsoft Visual C++ x64 runtime: https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist',
               "TOML paths: python = 'C:\\Crystal Ball\\hear\\Scripts\\python.exe' (literal quotes)"]
        for name in ([engine] if engine else ['hear','see']):
            if name=='read':
                lines.append('Provision Tesseract externally; set read.tessdata to the traineddata directory. No system installer is run.')
                continue
            exe=str(Path('.venv-'+name)/'Scripts/python.exe')
            lines.extend([powershell([sys.executable,'-m','venv','.venv-'+name]),
                          powershell([exe,'-m','pip','install','--require-hashes','--no-deps','-r',str(requirements_root()/'windows'/(name+'-cpu.lock'))])])
            if name=='see':
                lines.append(powershell([exe,'-m','pip','install','--require-hashes','--no-deps','-r',str(requirements_root()/'windows/torch-cpu.lock')]))
            download = "from faster_whisper.utils import download_model; download_model('large-v3-turbo')" if name=='hear' else "from huggingface_hub import snapshot_download; snapshot_download('openai/clip-vit-large-patch14')"
            lines.append(powershell([exe,'-c',download]))
        return '\n'.join(lines)
    groups=[engine] if engine else ['hear','see','read']
    root=Path(__file__).resolve().parent.parent
    requirements=root/'requirements'
    if not (requirements/'hear.lock').is_file():
        requirements=Path(sysconfig.get_path('data'))/'share/crystal-ball/requirements'
    lines=['Run these commands yourself; dependency/model downloads require network access.','Configure the resulting interpreter/model paths in crystal-ball.toml.']
    for group in groups:
        if group in {'hear','see'}:
            lines += [f'python3 -m venv .venv-{group}',f'.venv-{group}/bin/python -m pip install -r {shlex.quote(str(requirements/(group+".lock")))}']
            if group=='hear':
                lines += ['.venv-hear/bin/python -c "from faster_whisper.utils import download_model; download_model(\'large-v3-turbo\')"']
            else:
                lines += ['.venv-see/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download(\'openai/clip-vit-large-patch14\')"']
        else:
            lines += ['sudo apt-get install ffmpeg tesseract-ocr tesseract-ocr-eng tesseract-ocr-osd tesseract-ocr-ara', 'Optional tessdata_best 4.1.0 ara.traineddata SHA256: ab9d157d8e38ca00e7e39c7d5363a5239e053f5b0dbdb3167dde9d8124335896', 'Set read.tessdata to your chosen traineddata directory.']
    return '\n'.join(lines)
