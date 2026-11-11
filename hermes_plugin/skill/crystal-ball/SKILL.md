---
name: crystal-ball
description: Inspect renders with transcription, CLIP search, OCR and bounded visual critique.
---

# Crystal Ball

Call the `crystal_ball` tool with one action:

- `check`: inspect a finished render. Supply `file`; optionally `platform`,
  `captions`, `script`, `brief`, `expect_text`, and `mode` (`quick` or `full`).
  Quick runs signal checks, sampled OCR and audio; it gates visual critique on
  clean signal checks. Full permits one visual critique call despite signal issues.
- `transcribe`: obtain cached speech with word timestamps. Full transcript is
  in the returned artifact; transcription is uncertain, especially for names.
- `index`: index media in `paths` before semantic search.
- `find`: search by `text` or reference `image`; use `top` and `dir` to narrow.
- `read_text`: read sampled visible text, or a full frame at `at` seconds.
- `fix`: make a new `.cbfix` file for measured loudness/true-peak issues and
  re-check it. Protected paths need explicit `force`; originals are preserved.
- `doctor`: diagnose local engines, model hashes, hardware and fallbacks.
  Doctor never downloads models or calls the vision endpoint.

Prefer quick checks after renders and full checks when a brief needs visual
review. Use configured Markdown rules; do not invent delivery requirements.
Open the report/artifacts for details rather than requesting large tool payloads.
A background FAIL is unacknowledged until a foreground check of that revision.
Finish reminders also arrive through `pre_llm_call`; they do not block execution.

## Critique limits

Static samples cannot hear the media, evaluate continuous motion, or judge
lip-sync. ASR and audio measurements do not constitute listening. Disclose
these limits. OCR confidence and temporal persistence reduce false positives,
but sparse OCR cannot prove missing text. Vision text claims require full-size
OCR corroboration. A distinct CLIP shot is a review hint, not a defect.

**Check passed ≠ approved.** Human creative and delivery approval remains
separate from measured evidence. Explain WARN/SKIP rather than hiding them.

Use at most **two critique rounds** per render task: inspect, apply a concrete
supported correction, and re-check. After round two, present remaining evidence
and ask for direction; do not continue an aesthetic revision loop.
