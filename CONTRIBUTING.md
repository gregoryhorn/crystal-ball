# Contributing

Keep changes focused and preserve observable contracts. Open an issue describing
the behavior before proposing a broad change. Use generated fixtures only;
ffmpeg filters, including flite where available, generate all test/example media.
Never submit real footage, transcript content, private configs or model weights.

Use Python 3.11+ and separately installed ffmpeg 6.1+, ffprobe, Tesseract and a
DejaVu font. Install `requirements/test.lock` in your own environment. Run:

```sh
mkdir -p .test-tmp
TMPDIR="$PWD/.test-tmp" python -m pytest --basetemp=.test-tmp/pytest -q
python scripts/privacy_scan.py
```

Live tests require `CRYSTAL_BALL_LIVE=1` and an explicit local engine config.
Report skipped or unavailable engines accurately; a stubbed provider is not an
inference test. Add narrow tests that can falsify the changed behavior. Preserve
real signal/OCR checks and non-overwrite/atomicity coverage.

The code vendors only the ffmpeg-skill dependency closure needed by QC. Keep its
MIT notice and document modifications in THIRD_PARTY_NOTICES.md. Do not pull in
unrelated commands or silently change platform specifications. Runtime/model
licences remain separate from this project's MIT licence.

Before a release, run the offline suite and privacy scan, review the source
archive/wheel contents, and record live inference evidence on your machine.
Use `python scripts/build_release.py` with `requirements/build.lock` installed.
The script normalizes source archive ownership and scans every archive member.
Release upload and a git remote are deliberately outside the build workflow.

Native Windows: use a dedicated CPython 3.11 x64 development venv and external
ffmpeg/ffprobe >=6.1 and Tesseract (English data for OCR tests). From PowerShell:

```powershell
./scripts/windows/verify.ps1 -Python $Python -Scratch $Scratch
```

$Python is the absolute dedicated venv Scripts/python.exe, $Scratch an approved
absolute temporary root. The wrapper makes one run directory, sets offline/temp
variables only for this process, runs all non-live tests/privacy/build and
propagates failure. It downloads/installs nothing. Install requirements/test.lock
and requirements/build.lock in that dev venv beforehand. Windows uses its Arial
font for synthetic title fixtures; Linux retains DejaVu. No broad core skips.

After installing the candidate wheel into a separate dedicated test venv, run
its interpreter from outside the checkout (no activation or profile install):

```powershell
& $WheelPython -I "$Repo/scripts/windows/wheel_smoke.py" --scratch $Scratch
```

This generates synthetic media and reopens CLI/tool reports and a contact sheet,
checks the installed recipe resources and compact counts, and prints observed
results. It uses the approved scratch root and downloads no optional models.
It does not prove native Hermes UI integration or real model inference.

Windows engine locks are grouped in requirements/windows. They are hashed
wheel-only CPython 3.11 x64 sets; Torch uses its separate official CPU index.
scripts/windows/freeze_recipes.py verifies target-Windows dependency markers
(including colorama) from downloaded wheel metadata before freezing. Wheel
resolution on Linux is not native import/inference evidence. Do not install
Windows lockfiles on Linux or Linux CUDA lockfiles on Windows. Ordinary tests
never download models or contact the production broker. See the Windows
as-built for native machine acceptance still outstanding.
