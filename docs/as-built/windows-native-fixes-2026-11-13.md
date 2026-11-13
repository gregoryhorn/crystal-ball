# Native Windows corrections (2026-11-13)

Scope: fix the supplied native failures, retain Linux behavior; local main commits
only, no publication. Input: app-design crystal-ball/windows-support-2026-11-13-design.md
r1 and its r1 acceptance companion, under the canonical design-documents home.
Existing Python stack retained; no UI work or new dependencies.

Implemented: trusted executable discovery preserves display/path casing while
comparing normalized identities; CSV exports avoid doubled Windows newlines;
print-only setup names PowerShell; unavailable doctor probes say Not checked;
direct OCR now returns the same unavailable evidence as staged OCR. FLAC fixes
request 4608-sample encoder blocks after the native FFmpeg 9 failure with block
size 88184 (codec and stream inventory remain preserved).

Tests now set native home variables, compare hook identities using the existing
normalization contract, and explicitly select CUDA for GPU-session tests instead
of depending on the intentionally CPU Windows default. Only three real OCR tests
skip when Tesseract is genuinely absent, after asserting staged and direct APIs
report Not checked. Thin-host and frame reuse tests still execute without OCR.
Added deterministic missing-OCR, explicit CPU/no-broker, CSV translation and
optional-doctor regressions. FFmpeg option reference:
https://ffmpeg.org/ffmpeg-codecs.html (FLAC frame_size).

Initial integrated Linux /usr/bin/python3 non-live suite: 293 passed,
8 deselected, 10 subtests passed (92.07s), exit 0. Two existing PurePath.as_uri
warnings.

## Final verification

Candidate: aea2ceb (following e70fe5b); the final documentation-only commit
contains this record and sanitized captured logs. Windows ran the bundled main
clone at %USERPROFILE%/AppData/Local/Temp/cbv/src using its supplied Python 3.11
venv and Hermes FFmpeg 9.0.1. Only scratch environments were modified.

- Native scripts/windows/verify.ps1: 298 passed, 3 skipped, 8 live tests
  deselected, 10 subtests passed in 109.16s. Privacy PASS (0 findings), wheel and
  sdist builds/archive privacy PASS, wrapper EXIT=0. Three skips are the real
  OCR-specific tests: Tesseract is absent, and the skip fixture first exercises
  and asserts Not checked through staged and direct APIs. No other new skips.
- Linux /usr/bin/python3 (3.14.4): 301 passed, 8 pre-existing opt-in live skips,
  10 subtests passed in 52.35s, exit 0. Two existing PurePath.as_uri warnings.
- Linux scratch crystal-windows-venv (3.11.15): 301 passed, 8 opt-in live skips,
  10 subtests passed in 49.37s, exit 0. This run unset inherited PYTHONPATH and
  PYTHONHOME so Hermes' Python 3.14 numpy cannot contaminate the 3.11 interpreter.
- Linux privacy scan: PASS (0 findings); wheel and sdist archive scans PASS.
- Changed-file AST measurement: 249 functions, largest 92 lines; all <=300.

Linux commands: `python -m pytest -q -rs -p no:cacheprovider --basetemp
$TMPDIR/cb-native-final-{system,venv}` with PYTHONDONTWRITEBYTECODE=1 and the
interpreter selected above. Windows command is printed in final-windows.txt.
Durable evidence (only private-home prefixes replaced):
[evidence/windows-native-2026-11-13/final-windows.txt](evidence/windows-native-2026-11-13/final-windows.txt),
[final-system.txt](evidence/windows-native-2026-11-13/final-system.txt),
[final-venv.txt](evidence/windows-native-2026-11-13/final-venv.txt).

The second native run exposed FFmpeg's legitimate n-prefixed release banner;
doctor now accepts n9.0.1 while continuing to reject <6.1 and unknown banners.
Regression coverage includes old and unknown versions. Disabled model cache
stamps no longer include cwd files or every unrelated Hugging Face model. The
CLI/tool fixture puts model="" in TOML, not an empty environment variable that
Windows native inheritance drops. Failure-isolation assertions verify the full
persisted failure reason and require an explicit omission count when the compact
envelope cannot hold it due to long native paths. No media/security assertions
were removed. Direct still-image OCR also now uses the original image at time
zero instead of calling image_review without a run directory.

The initial build attempt found setuptools 65.5.0 in the provided Windows venv,
below pyproject.toml's existing >=77 requirement. Upgraded only that scratch
venv to setuptools 84.2.1 and wheel 0.48.0; the subsequent native build passed.
PowerShell renders byte-compilation-disabled build warnings as NativeCommandError
text, but the observed verify wrapper EXIT is 0. These warnings are not hidden.

Alignment at handoff: the requested native automated suite and both Linux suites
are green. Actual optional-model inference, production GPU admission, installed
Hermes UI and manual Windows acceptance remain unverified; none are claimed by
these tests. No push, tag, release, model download or live profile install.
