"""Minimal QC facade; adapted from ffmpeg-skill (MIT, see ../LICENSE)."""
from pathlib import Path
from _common.runner import STATE, add_common, apply_common, ffmpeg_base, require_tool, run, run_analysis, dry_run_input_pending
from _common.emit import die, emit, info
from _common.probe import probe, detect_scenes
from _common.fonts import default_font_file
from _common.drawtext import drawtext_fontfile
