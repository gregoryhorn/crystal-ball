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
