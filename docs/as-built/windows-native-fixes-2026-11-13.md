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
warnings. Native and final Linux verification follows in this record.
