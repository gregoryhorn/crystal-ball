# Changelog

## 1.1.1

- Report the exact number of `not_checked` entries left out of a compact result
  (`not_checked_omitted_count`); `more_not_checked_in_report` is now set only
  when entries were actually omitted.
- Cut noisy OCR spelling hints: require OCR confidence >=70, clean single-script
  tokens, no truncated fragments, and the same suspected typo at two or more
  sampled timestamps. The summary now states both thresholds.
- A compact result that still exceeds the byte budget after all optional detail
  is trimmed now returns an error instead of an oversize result.

## 1.1.0 / Milestone 2 (0.2.0 feature milestone)

- Add local librosa beat/onset analysis, estimated 4/4 bars/downbeats and novelty
  sections; JSON, CSV markers and frame-list exports.
- Add PySceneDetect content/adaptive shots, threshold-based fades, ffmpeg fallback,
  shared thumbnails, shot-based CLIP indexing, CSV and CMX3600 EDL exports.
- Add compact beats/scenes/cuts actions to CLI and Hermes, beat/onset alignment
  and advisory frame snap lists; reuse cuts for check and judge review.
- Add opt-in cut_sync, informational pacing/hook evidence and a rolling luminance/
  red flash safety estimate (not a certified Harding test).
- Admit hear/CLIP GPU work by configurable free VRAM; retry CUDA OOM on CPU,
  report actual engine/fallback reason, and keep CPU int8 before whisper.cpp.
- Add manifest-based, self-contained Hermes copy install/uninstall without pip.
- Add synthetic and stub tests, with external-engine inference behind
  CRYSTAL_BALL_LIVE=1. No media, user scripts or models are bundled.

## 1.0.0

- Merge isolated video QC and atomic CLIP indexing into a standalone package.
- Add shared artifacts, configurable engines, JSON audio workers, script matching,
  OCR persistence filtering, validated optional vision and new-file level fixes.
- Add one compact Hermes tool, asynchronous hooks and capped finish reminders.
- Provide CLI, reports, offline doctor/setup instructions, synthetic tests and
  publishing assets. Models and external binaries remain separately installed.
