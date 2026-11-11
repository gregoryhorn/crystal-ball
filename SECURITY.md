# Security

Use trusted local media and keep ffmpeg, Tesseract, Python and model runtimes
patched. Decoders process complex untrusted files; subprocess isolation is not
a security sandbox. Choose private cache directories: reports contain paths,
OCR and transcripts from your own media. Protect and expire these artifacts
according to your needs. The package does not automatically delete them.

Normal engines use local-only model loading. Optional vision sends sampled
images plus configured brief/rules to your selected backend. Enable it only
for media you may share with that provider. Keep keys in environment variables,
never in TOML, reports, examples or commits. Avoid untrusted endpoints and argv
commands; optional demucs runs the configured executable without a shell.

Mechanical fixes use new files, protected globs, source revision checks and
non-overwriting publication. These controls are not a backup or approval system.
A WARN/SKIP discloses incomplete evidence. Hooks fail open and cannot enforce a
hard finish gate. The two-round critique cap is agent guidance.

For a sensitive vulnerability, contact the repository maintainer privately
through the hosting platform before opening a public issue. Do not attach
private media, transcripts, credentials or machine-specific configuration.
The privacy scanner is a heuristic pre-publication check, not a proof that all
sensitive material has been removed. No hosted contact address is bundled.
