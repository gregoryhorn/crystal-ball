# Crystal Ball media applicability - as built

- Input: MA-r1, full canonical design read before coding:
  `~/.hermes/profiles/app-design/workspace/design-documents/crystal-ball/media-applicability-2026-11-13-r1.md`.
- Alignment/outcome: relevant checks for exact still/audio/video bytes; no new media
  modes or implicit destination/shape targets. Crystal Ball only; Motion Studio is
  separately owned. Uncommitted main-checkout changes on baseline `860a041`;
  no dependency installation, version/release/catalog/profile change or commit.
- `frames.py` classifies ffprobe content/streams, excludes attached cover art and
  checks image frame counts; Pillow supplies oriented still dimensions.
  `applicability.py` owns shape tolerance, single full-resolution still extraction,
  omissions and explicit required-output evidence. Unclassifiable content has no
  supported media kind (null in a successfully probed unsupported report).
- `media_signal.py` reuses vendored decode/measurement functions, but only invokes
  platform checks for selected video destinations. Decode precedes dependent
  engines. Silent-track infinity is retained as explicit text in JSON, not lost
  as a serialization error. Custom audio retains LUFS evidence and a separate
  target-comparison omission; true peak/clipping retain generic thresholds.
- `routing.py` selects applicable stages before dispatch. Still OCR uses exactly
  one oriented full-size PNG; Judge receives that image once. No duplicated
  timestamps manufacture spelling corroboration. Custom shape requests use a
  generic 5% OCR/ASS inset. No-audio video never runs Hear/rhythm/A/V analysis.
  Audio-required mismatch recognizes explicit brief phrases (`audio is required`,
  `required audio`, `must include audio`), not arbitrary natural-language intent.
- CLI/Python/Hermes add optional `shape`; full JSON adds `media_kind` and per-SKIP
  `skip_reason`. Existing compact IDs/counts/omission metadata and 1,500-byte budget
  remain. CLI omits the final newline only when JSON already occupies 1,500 bytes.
  Existing standalone video-platform inference remains; Director must pass custom
  when no destination was selected. Old reports are not rewritten. Shape/config/
  source-code/byte changes participate in existing cache identity.

## Executed verification

Linux, system Python 3.14.4 and existing Python 3.11.15 venv; ffmpeg 8.0.1 and
Tesseract 5.5.0. No install/build/package publication was performed.

```sh
S=~/.hermes/profiles/app-developer/cache/scratch/crystal-ma-r1
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m pytest -q -p no:cacheprovider --basetemp="$S/system-final7"
PYTHONDONTWRITEBYTECODE=1 ~/.hermes/profiles/app-developer/cache/scratch/crystal-windows-venv/bin/python -m pytest -q -p no:cacheprovider --basetemp="$S/venv-final7"
```

Both exited 0: **289 passed, 8 skipped, 10 subtests passed**. System run also
reports two pre-existing PurePath.as_uri deprecation warnings. Durable raw logs:
[system](evidence/media-applicability-2026-11-13/system-python.log),
[3.11](evidence/media-applicability-2026-11-13/python311.log).
`git diff --check` passed; AST measurement of every touched Python file found
no function over 300 lines (largest: `_base_check`, 97 lines).

`tests/test_media_applicability.py` generates real still/WAV/MP4 fixtures and
exercises real CLI JSON plus the existing Hermes adapter/tool subprocess for all
four kinds, cache reopen/shape invalidation, unchanged originals, full reports,
compact identities/omissions/budget, cover art, EXIF orientation, disguised suffix,
animated/unsupported input, silence/clipping, selected codec/aspect violations,
generic caption inset and separate required-audio mismatch. Excluded stage and
unselected-platform gate calls are asserted zero. Missing engines/probe/stage
timeout paths use focused fault injection; existing owned-process tests exercise
real timeouts. Previous regression expectations were updated only for intentional
explicit omissions, decode failure precedence and decode-dependent dispatch.

## Remaining boundaries

The eight live-model tests remain skipped. No live ASR/Judge/rhythm model, native
Windows execution, installed Hermes UI, Motion Studio take/report/ZIP transport,
playback/download or Studio restart retention was qualified here. Real CLI and
adapter subprocess evidence is not a claim of those broader integrations.
OCR remains evidence rather than universal readability proof. Ambiguous/animated
formats remain Not checked; unavailable optional engines remain incomplete WARN.
Parent owns cross-repository review/integration and the eventual commit.
