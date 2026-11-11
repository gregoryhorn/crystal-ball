#!/usr/bin/env python3
"""Post-render quality gate: run once after every render, before telling anyone it is done.

Runs check.py's platform checks (duration, aspect, fps, codec, loudness, true peak, ...) in-process,
then one full decode of the file (`-f null`, single pass) that also measures black segments, frozen
segments, silence gaps and audio clipping, and finally exports review frames plus one contact sheet
for a visual critique (skills/media/render-review). Prints a PASS/WARN/FAIL table; exit 1 on FAIL.

  PASS/WARN/FAIL  as check.py; SKIP = could not be checked (said why, never silently passed)
  black           WARN any span >= --black-min; FAIL a span >= --black-fail away from the start/end
                  (a fade in/out is an edit choice) or >= 95% of the video
  frozen          WARN with timestamps, never FAIL: a hold or still card is often intentional
  silence         WARN a gap >= --max-silence s inside a track that has sound; FAIL when the track is silent
  clipping        astats overall peak and peak count (samples sitting on the maximum): WARN a few, FAIL many
  A/V drift       end (and start) time of the audio vs the video stream: > 1 frame WARN, > 100 ms FAIL
  caption zone    caption.py's .ass margins/alignment/\\pos against _platforms.py's safe zone; an .srt
                  carries no position, so it is SKIP
  decode          every decoder error in the one full decode

Examples:
  python3 qc.py final.mp4 --platform reels
  python3 qc.py final.mp4 --platform tiktok --captions subs.ass --frames-dir /tmp/review
  python3 qc.py final.mp4 --platform youtube --json
  python3 qc.py final.mp4 --platform reels --max-silence 1.5 --no-loudness

Frames land in --frames-dir (default <profile>/cache/qc/<name>/), never beside the media: start,
25/50/75 %, end and one frame just after each scene cut (at most 12), and qc_contact_sheet.jpg.
A passing qc is mechanical evidence, not creative approval: look at the frames and listen.
"""
import argparse
import contextlib
import io
import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from _platforms import PLATFORMS, PLATFORM_CHOICES, resolve as resolve_platform
from _common.probe import SILENT_PEAK_DBFS, CONTENT_BLACK_PIX_TH, CONTENT_FREEZE_NOISE, _BLACK_RE, _FREEZE_RE, SIL_RE
from _common import (STATE, add_common, apply_common, default_font_file, die, drawtext_fontfile, emit, ffmpeg_base,
                     detect_scenes, info, probe, require_tool, run, run_analysis, dry_run_input_pending)

PROFILE_DIR = Path(os.environ.get("CRYSTAL_BALL_CACHE_DIR", "~/.cache/crystal-ball")).expanduser()   # <profile>/skills/ffmpeg-skill/scripts/qc.py
FROZEN_MIN_S = 1.0          # freezedetect minimum run reported (check.py --content uses 0.5)
BLACK_ALL = 0.95            # black share of the duration that means the picture is missing
EDGE_S = 0.15               # black this close to the start/end is a fade, not a hole
CLIP_WARN, CLIP_FAIL = 3, 100   # samples on the peak value: a few is a touch, many is hard clipping
CLIP_OVER_FAIL_DB = 0.5     # a lossy (AAC) decode this far over full scale was clipped before encoding; the count is smeared
DRIFT_WARN_FRAMES, DRIFT_FAIL_S = 1.0, 0.100
MAX_CUT_FRAMES = 12
DECODE_ERR_RE = re.compile(r"(error while decoding|invalid data|corrupt|concealing|missing reference|"
                           r"decode_slice_header|invalid nal|no frame|overread|truncated|illegal)", re.I)
FILTER_TAGS = ("blackdetect", "freezedetect", "silencedetect", "astats", "Parsed_", "null @", "scale @")

Row = Dict[str, Any]


# ---------------------------------------------------------------- check.py, in-process
def run_check(path: str, platform: Optional[str], no_loudness: bool) -> List[Row]:
    """check.py's own rows, from its main() run in-process (its JSON document, not its table)."""
    import check as check_mod
    argv = [path, "--json"] + (["--platform", platform] if platform else []) + (["--no-loudness"] if no_loudness else [])
    saved = sys.argv
    sys.argv = ["check.py"] + argv
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                check_mod.main()
            except SystemExit:
                pass
    finally:
        sys.argv = saved
    text = out.getvalue().strip()
    try:
        doc = json.loads(text[text.index("{"):]) if text else {}
    except ValueError:
        doc = {}
    rows = doc.get("checks") or []
    if not rows:
        return [{"check": "check.py", "status": "FAIL", "value": "no result", "expected": "platform checks",
                 "fix": (err.getvalue().strip() or text)[-300:], "source": "check.py"}]
    return [{"check": r["check"], "status": r["status"], "value": r["value"], "expected": r["expected"],
             "fix": r.get("fix", ""), "source": "check.py"} for r in rows]


# ---------------------------------------------------------------- the one decode pass
def decode_pass(path: str, meta: Dict[str, Any], max_silence: float, black_min: float) -> Dict[str, Any]:
    """One ffmpeg run, one decode of every stream: blackdetect + freezedetect on a 320 px copy of the picture,
    silencedetect + astats on the audio, and the decoder's own errors from stderr."""
    v, a = meta.get("video"), meta.get("audio")
    dur = meta.get("duration") or 0.0
    cmd = [require_tool("ffmpeg"), "-hide_banner", "-nostdin", "-i", path]
    if v:
        cmd += ["-map", "0:V:0", "-vf", f"scale=320:-2,blackdetect=d={black_min}:pix_th={CONTENT_BLACK_PIX_TH},"
                f"freezedetect=n={CONTENT_FREEZE_NOISE}:d={FROZEN_MIN_S}", "-f", "null", "-"]
    if a:
        cmd += ["-map", "0:a:0", "-af", f"silencedetect=noise={SILENT_PEAK_DBFS:g}dB:d={max_silence},astats=metadata=0",
                "-f", "null", "-"]
    proc = run_analysis(cmd, check=False, record=True)
    err = proc.stderr
    res: Dict[str, Any] = {"returncode": proc.returncode}
    res["black"] = [(float(s), min(float(e), dur) if dur else float(e)) for s, e in _BLACK_RE.findall(err)]
    frozen: List[Tuple[float, float]] = []
    start = None
    for kind, val in _FREEZE_RE.findall(err):
        if kind == "start":
            start = float(val)
        elif start is not None:
            frozen.append((start, float(val)))
            start = None
    if start is not None:
        frozen.append((start, dur))
    # black is trivially "frozen" too; report it once, as black
    res["frozen"] = [(s, e) for s, e in frozen
                     if not any(min(e, be) - max(s, bs) >= 0.9 * (e - s) for bs, be in res["black"])]
    sil: List[Tuple[float, float]] = []
    start = None
    for kind, val in SIL_RE.findall(err):
        if kind == "start":
            start = float(val)
        elif start is not None:
            sil.append((start, min(float(val), dur) if dur else float(val)))
            start = None
    if start is not None:
        sil.append((start, dur))
    res["silence"] = sil
    # astats prints per-channel blocks then "Overall"; take the numbers after the last "Overall"
    overall = err.rsplit("Overall", 1)[1] if "Overall" in err else ""
    def num(label: str) -> Optional[float]:
        m = re.search(label + r":\s*(-?inf|-?[0-9.]+(?:e[+-]?\d+)?)", overall)
        try:
            return float(m.group(1)) if m else None
        except ValueError:
            return None
    res["peak_db"], res["peak_count"], res["samples"] = num("Peak level dB"), num("Peak count"), num("Number of samples")
    errors: List[str] = []
    for line in err.splitlines():
        s = line.strip()
        if not s or s.startswith(("frame=", "size=", "video:", "Stream", "Output", "Input", "Metadata", "Duration", "[out#", "[in#", "[vost", "[aost")):
            continue
        if any(t in s for t in FILTER_TAGS) and not DECODE_ERR_RE.search(s):
            continue
        if DECODE_ERR_RE.search(s) or s.startswith("Error"):
            errors.append(s[:160])
    seen: Dict[str, int] = {}
    for e in errors:
        seen[e] = seen.get(e, 0) + 1
    res["errors"] = [f"{e}" + (f" (x{n})" if n > 1 else "") for e, n in seen.items()]
    return res


def stream_times(path: str) -> Dict[str, Dict[str, float]]:
    proc = run_analysis([require_tool("ffprobe"), "-v", "error", "-show_entries",
                         "stream=codec_type,start_time,duration,avg_frame_rate", "-of", "json", path], check=False)
    out: Dict[str, Dict[str, float]] = {}
    try:
        streams = json.loads(proc.stdout).get("streams", [])
    except ValueError:
        return out
    for s in streams:
        kind = s.get("codec_type")
        if kind not in ("video", "audio") or kind in out:
            continue
        try:
            st = float(s.get("start_time") or 0.0)
            du = float(s["duration"])
        except (KeyError, ValueError, TypeError):
            continue
        d = {"start": st, "end": st + du}
        if kind == "video":
            try:
                n, m = s.get("avg_frame_rate", "0/1").split("/")
                d["fps"] = float(n) / float(m) if float(m) else 0.0
            except ValueError:
                d["fps"] = 0.0
        out[kind] = d
    return out


# ---------------------------------------------------------------- caption safe zone
def _ass_time(t: str) -> float:
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def _cols(line: str) -> List[str]:
    return [c.strip() for c in line.split(":", 1)[1].split(",")]


def caption_zone(path: str, platform: Optional[str], w: int, h: int) -> Tuple[str, str, str]:
    """(status, value, fix) for the captions against the platform's UI safe zone."""
    ext = Path(path).suffix.lower()
    if not os.path.exists(path):
        return "FAIL", f"{path} not found", "pass the caption file that was burned in"
    if ext == ".srt":
        return "SKIP", "not checked: SRT has no position or margins", \
            "burn from the .ass: caption.py --platform X writes safe margins; pass that .ass here"
    if ext not in (".ass", ".ssa"):
        return "SKIP", f"not checked: {ext or 'unknown'} caption format", "use .ass or .srt"
    zone = PLATFORMS.get(platform or "", {}).get("safe")
    if not platform or not PLATFORMS[platform].get("frame") or not zone:
        return "SKIP", "not checked: no platform with a safe zone (pass --platform reels|tiktok|shorts|...)", ""
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    prx = pry = None
    styles: Dict[str, Dict[str, str]] = {}
    sfmt: List[str] = []
    efmt: List[str] = []
    events: List[Dict[str, Any]] = []
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("["):
            section = line.lower()
        elif section == "[script info]":
            if line.lower().startswith("playresx:"):
                prx = float(line.split(":", 1)[1])
            elif line.lower().startswith("playresy:"):
                pry = float(line.split(":", 1)[1])
        elif "styles" in section:
            if line.lower().startswith("format:"):
                sfmt = [c.lower() for c in _cols(line)]
            elif line.lower().startswith("style:") and sfmt:
                vals = _cols(line)
                styles[vals[0]] = dict(zip(sfmt, vals))
        elif section == "[events]":
            if line.lower().startswith("format:"):
                efmt = [c.lower() for c in _cols(line)]
            elif line.lower().startswith("dialogue:") and efmt:
                vals = [c.strip() for c in line.split(":", 1)[1].split(",", len(efmt) - 1)]
                events.append(dict(zip(efmt, vals)))
    if not events:
        return "SKIP", "not checked: no Dialogue lines in the caption file", ""
    pry = pry or 288.0
    prx = prx or pry * w / h
    sx, sy = w / prx, h / pry
    worst: List[Tuple[float, str, bool]] = []   # (overlap px, description, exact)
    animated = 0
    for ev in events:
        st = styles.get(ev.get("style", ""), next(iter(styles.values()), {}))
        body = ev.get("text", "")
        tags = " ".join(re.findall(r"\{[^}]*\}", body))
        if r"\move" in tags:
            animated += 1
            continue
        plain = re.sub(r"\{[^}]*\}", "", body).replace(r"\h", " ")
        lines_t = re.split(r"\\N|\\n", plain)
        fs = float((re.search(r"\\fs([0-9.]+)", tags) or [0, st.get("fontsize", 20)])[1]) * sy
        an = int((re.search(r"\\an([1-9])", tags) or [0, st.get("alignment", 2)])[1])
        ml = float(ev.get("marginl") not in (None, "0", "0000") and ev.get("marginl") or st.get("marginl", 10)) * sx
        mr = float(ev.get("marginr") not in (None, "0", "0000") and ev.get("marginr") or st.get("marginr", 10)) * sx
        mv = float(ev.get("marginv") not in (None, "0", "0000") and ev.get("marginv") or st.get("marginv", 10)) * sy
        pad = (float(st.get("outline", 0) or 0) + float(st.get("shadow", 0) or 0)) * sy
        wide = max(sum(fs * (0.9 if ord(c) > 0x2E80 else 0.45) for c in ln) for ln in lines_t)
        avail = max(w - ml - mr, 1.0)
        n_lines = sum(max(1, math.ceil((sum(fs * (0.9 if ord(c) > 0x2E80 else 0.45) for c in ln)) / avail)) for ln in lines_t)
        tw, th = min(wide, avail) + 2 * pad, n_lines * fs * 1.05 + 2 * pad
        pos = re.search(r"\\pos\(([-0-9.]+),\s*([-0-9.]+)\)", tags)
        col = (an - 1) % 3
        rowk = (an - 1) // 3          # 0 bottom, 1 middle, 2 top
        if pos:
            ax, ay = float(pos.group(1)) * sx, float(pos.group(2)) * sy
        else:
            ax = ml if col == 0 else (w - mr if col == 2 else (ml + w - mr) / 2)
            ay = h - mv if rowk == 0 else (mv if rowk == 2 else h / 2)
        x0 = ax if col == 0 else (ax - tw if col == 2 else ax - tw / 2)
        y0 = ay - th if rowk == 0 else (ay if rowk == 2 else ay - th / 2)
        x1, y1 = x0 + tw, y0 + th
        when = f"{_ass_time(ev['start']):.1f}s"
        # the edge the text is anchored to is exact; the opposite extent is an estimate from the font size
        tol_y, tol_x = 0.01 * h, 0.01 * w   # outline width / margin rounding is not an overlap
        if y1 > h * (1 - zone["bottom"]) + tol_y:
            worst.append((y1 - h * (1 - zone["bottom"]), f"bottom {when} (text ends {y1 / h * 100:.0f}% down, UI from {100 - zone['bottom'] * 100:.0f}%)", rowk == 0 or bool(pos)))
        if y0 < h * zone["top"] - tol_y:
            worst.append((h * zone["top"] - y0, f"top {when} (text starts {y0 / h * 100:.0f}% down, UI to {zone['top'] * 100:.0f}%)", rowk == 2 or bool(pos)))
        if x0 < w * zone["left"] - tol_x:
            worst.append((w * zone["left"] - x0, f"left {when} (text from {x0 / w * 100:.0f}% across, UI to {zone['left'] * 100:.0f}%)", False))
        if x1 > w * (1 - zone["right"]) + tol_x:
            worst.append((x1 - w * (1 - zone["right"]), f"right {when} (text to {x1 / w * 100:.0f}% across, UI from {100 - zone['right'] * 100:.0f}%)", False))
    note = f"; {animated} \\move event(s) not checked" if animated else ""
    if not worst:
        return "PASS", f"{len(events)} captions inside the {platform} safe zone (estimated from style margins){note}", ""
    worst.sort(key=lambda t: -t[0])
    exact = any(e for _, _, e in worst)
    shown = "; ".join(d for _, d, _ in worst[:3])
    return ("FAIL" if exact else "WARN"), f"{len(worst)} overlap(s) with the {platform} UI: {shown}{note}", \
        f"caption.py --platform {platform} (sets margins inside the safe zone), or raise MarginV"


# ---------------------------------------------------------------- review frames
def export_frames(path: str, meta: Dict[str, Any], outdir: Path, cuts: List[float]) -> Dict[str, Any]:
    v = meta.get("video") or {}
    dur = meta.get("duration") or 0.0
    fps = v.get("fps") or 30.0
    last = max(0.0, dur - max(2.0 / fps, 0.05))
    plan: List[Tuple[str, float]] = [("start", 0.0), ("25pct", dur * 0.25), ("50pct", dur * 0.5), ("75pct", dur * 0.75), ("end", last)]
    after = [min(c + 0.1, last) for c in cuts if c > 0.05]
    if len(after) > MAX_CUT_FRAMES:
        step = len(after) / MAX_CUT_FRAMES
        after = [after[int(i * step)] for i in range(MAX_CUT_FRAMES)]
    taken = [t for _, t in plan]
    for t in after:
        if all(abs(t - u) > 0.2 for u in taken):
            plan.append(("cut", t))
            taken.append(t)
    plan.sort(key=lambda p: p[1])
    outdir.mkdir(parents=True, exist_ok=True)
    for old in list(outdir.glob("frame_*.jpg")) + list(outdir.glob("qc_contact_sheet.jpg")):
        try:
            old.unlink()   # only this tool's own earlier output
        except OSError:
            pass
    frames: List[Dict[str, Any]] = []
    for i, (label, t) in enumerate(plan):
        out = outdir / f"frame_{i:02d}_{label}_{t:.2f}s.jpg"
        run(ffmpeg_base() + ["-ss", f"{t:.3f}", "-i", path, "-map", "0:V:0", "-frames:v", "1",
                             "-vf", "scale='min(iw,1080)':-2", "-q:v", "3", str(out)], quiet=True, check=False)
        if STATE.dry_run or out.exists():
            frames.append({"label": label, "time": round(t, 3), "path": str(out)})
    sheet = None
    if frames and not STATE.dry_run:
        sheet = _contact_sheet(frames, v, outdir)
    return {"frames": frames, "contact_sheet": sheet}


def _contact_sheet(frames: List[Dict[str, Any]], v: Dict[str, Any], outdir: Path) -> Optional[str]:
    FONT = "fontsize=h/18:fontcolor=white:x=8:y=8"
    w, h = v.get("width") or 16, v.get("height") or 9
    if v.get("rotation") in (90, -90, 270, -270):
        w, h = h, w
    portrait = h > w
    cols = min(len(frames), 6 if portrait else 4)
    rows = math.ceil(len(frames) / cols)
    tw = 240 if portrait else 400
    th = max(2, round(tw * h / w / 2) * 2)
    font = default_font_file("DejaVu Sans")
    prefix = f"{drawtext_fontfile(font)}:" if font else ""
    cmd = ffmpeg_base()
    chains = []
    for i, f in enumerate(frames):
        cmd += ["-i", f["path"]]
        label = f"{f['label']} {f['time']:.2f}s"
        chains.append(f"[{i}:v]scale={tw}:{th},drawtext=text='{label}':{prefix}{FONT.replace('x=8:y=8', 'x=4:y=4').replace('h/18', 'h/12')}[t{i}]")
    inputs = "".join(f"[t{i}]" for i in range(len(frames)))
    fc = ";".join(chains) + f";{inputs}concat=n={len(frames)}:v=1:a=0,tile={cols}x{rows}:padding=2:margin=2:color=0x202020[out]"
    out = outdir / "qc_contact_sheet.jpg"
    run(cmd + ["-filter_complex", fc, "-map", "[out]", "-frames:v", "1", "-q:v", "3", str(out)], quiet=True, check=False)
    return str(out) if out.exists() else None


# ---------------------------------------------------------------- main
def spans_text(spans: List[Tuple[float, float]], limit: int = 6) -> str:
    s = ", ".join(f"{a:.2f}-{b:.2f}s" for a, b in spans[:limit])
    return s + (f" (+{len(spans) - limit} more)" if len(spans) > limit else "")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--platform", choices=PLATFORM_CHOICES, default=None,
                    help="delivery spec to check against (as check.py; without it judgement rows are WARN)")
    ap.add_argument("--captions", metavar="FILE", help="the .ass (margins checked) or .srt (not checkable) that was burned in")
    ap.add_argument("--frames-dir", metavar="DIR",
                    help="where review frames and the contact sheet go (default <profile>/cache/qc/<name>/; never beside the media)")
    ap.add_argument("--no-frames", action="store_true", help="skip the frame and contact-sheet export")
    ap.add_argument("--max-silence", type=float, default=2.0, metavar="SECONDS",
                    help="WARN on a silent gap this long inside a track that has sound (default 2)")
    ap.add_argument("--black-min", type=float, default=0.2, metavar="SECONDS", help="shortest black span reported (default 0.2)")
    ap.add_argument("--black-fail", type=float, default=1.0, metavar="SECONDS",
                    help="a black span this long away from the start/end is a FAIL (default 1)")
    ap.add_argument("--no-loudness", action="store_true", help="skip check.py's loudness measurement (faster)")
    add_common(ap)
    args = ap.parse_args()
    apply_common(args)

    if not os.path.exists(args.input):
        die(f"input not found: {args.input}")
    named = args.platform
    platform = resolve_platform(args.platform)
    src = Path(args.input).resolve()
    outdir = Path(args.frames_dir).expanduser() if args.frames_dir else PROFILE_DIR / "cache" / "qc" / src.stem
    outdir = outdir.resolve()
    if not args.no_frames and outdir == src.parent:
        die("--frames-dir is the media's own folder; review frames never go beside the media (pick another directory)")

    rows: List[Row] = []
    def row(check: str, status: str, value: Any, expected: Any = "", fix: str = "") -> None:
        rows.append({"check": check, "status": status, "value": value, "expected": expected, "fix": fix, "source": "qc.py"})

    rows += run_check(args.input, named, args.no_loudness)
    apply_common(args)   # check.py's main() set the shared flags from its own argv; restore ours

    meta = probe(args.input)
    v, a = meta.get("video") or {}, meta.get("audio") or {}
    dur = meta.get("duration") or 0.0

    d = decode_pass(args.input, meta, args.max_silence, args.black_min)

    if v:
        black = d["black"]
        if not black:
            row("black", "PASS", "none", f"no black span >= {args.black_min:g}s")
        else:
            total = sum(e - s for s, e in black)
            hole = [(s, e) for s, e in black if (e - s) >= args.black_fail and s > EDGE_S and e < dur - EDGE_S]
            allb = dur and total / dur >= BLACK_ALL
            st = "FAIL" if (hole or allb) else "WARN"
            row("black", st, f"{len(black)} span(s): {spans_text(black)}", f"no black span >= {args.black_fail:g}s inside the video",
                "look at those times (qc frames, look.py --at); a missing clip or failed overlay is a hole, a fade in/out is fine")
        frozen = d["frozen"]
        if not frozen:
            row("frozen", "PASS", "none", f"no frozen span >= {FROZEN_MIN_S:g}s")
        else:
            whole = dur and sum(e - s for s, e in frozen) / dur >= BLACK_ALL
            row("frozen", "WARN", f"{len(frozen)} span(s): {spans_text(frozen)}" + (" (the whole video)" if whole else ""),
                "holds only where intended", "intentional holds/title cards are fine; otherwise a stuck decode or missing footage: look at those times")
    else:
        row("black", "SKIP", "no video stream")
        row("frozen", "SKIP", "no video stream")

    if a:
        pk, cnt = d["peak_db"], d["peak_count"]
        silent_all = pk is not None and pk <= SILENT_PEAK_DBFS
        gaps = d["silence"]
        if silent_all:
            row("silence", "FAIL", f"track is silent (peak {pk:.1f} dBFS)", "sound in the audio track", "audio.py --replace, or re-render the audio")
        elif not gaps:
            row("silence", "PASS", "none", f"no gap >= {args.max_silence:g}s below {SILENT_PEAK_DBFS:g} dBFS")
        else:
            tagged = [f"{s:.2f}-{e:.2f}s" + (" (lead-in)" if s < EDGE_S else " (tail)" if e > dur - EDGE_S else "") for s, e in gaps[:6]]
            row("silence", "WARN", f"{len(gaps)} gap(s): " + ", ".join(tagged), f"no gap >= {args.max_silence:g}s inside the speech",
                "a pause may be intended; otherwise silence.py (cut gaps) or fill with room tone/music. 'has speech' is judged as 'the track has sound', not by a speech detector")
        if pk is None:
            row("clipping", "SKIP", "astats gave no numbers")
        elif pk >= CLIP_OVER_FAIL_DB or (cnt is not None and pk >= -0.1 and cnt >= CLIP_FAIL):
            row("clipping", "FAIL", f"peak {pk:+.2f} dBFS, {int(cnt or 0)} samples on the peak", f"peak < 0 dBFS and < {CLIP_WARN} samples at full scale",
                "audio.py --limit (or lower --gain) from the unclipped mix; clipping baked into a lossy master cannot be repaired")
        elif cnt is not None and pk >= -0.1 and cnt >= CLIP_WARN or pk > 0.0:
            row("clipping", "WARN", f"peak {pk:+.2f} dBFS, {int(cnt or 0)} samples on the peak", f"peak < 0 dBFS and < {CLIP_WARN} samples at full scale",
                "audio.py --limit --limit-ceiling -1, then loudness.py")
        else:
            row("clipping", "PASS", f"peak {pk:+.2f} dBFS" + (f", {int(cnt)} sample(s) on the peak" if cnt else ""), f"no samples at full scale")
    else:
        row("silence", "SKIP", "no audio stream")
        row("clipping", "SKIP", "no audio stream")

    if v and a:
        t = stream_times(args.input)
        if "video" in t and "audio" in t:
            frame = 1.0 / (t["video"].get("fps") or 30.0)
            end_d = t["audio"]["end"] - t["video"]["end"]
            start_d = t["audio"]["start"] - t["video"]["start"]
            drift = max(abs(end_d), abs(start_d))
            st = "FAIL" if drift > DRIFT_FAIL_S else ("WARN" if drift > DRIFT_WARN_FRAMES * frame else "PASS")
            row("A/V drift", st, f"audio ends {end_d * 1000:+.0f} ms vs video, starts {start_d * 1000:+.0f} ms",
                f"<= 1 frame ({frame * 1000:.0f} ms) WARN above, 100 ms FAIL above",
                "audio.py --replace / sync.py to re-align; re-mux with matching lengths" if st != "PASS" else "")
        else:
            row("A/V drift", "SKIP", "container reports no per-stream durations", "", "")
    else:
        row("A/V drift", "SKIP", "needs both video and audio")

    if args.captions:
        if v:
            w, h = v.get("width") or 0, v.get("height") or 0
            if v.get("rotation") in (90, -90, 270, -270):
                w, h = h, w
            st, val, fix = caption_zone(args.captions, platform, w, h)
        else:
            st, val, fix = "SKIP", "no video stream", ""
        row("caption zone", st, val, "captions inside the platform safe zone", fix)
    else:
        row("caption zone", "SKIP", "no --captions given")

    if d["errors"] or d["returncode"] != 0:
        row("decode", "FAIL", f"{len(d['errors'])} error line(s): " + " | ".join(d["errors"][:4]) if d["errors"] else f"ffmpeg exit {d['returncode']}",
            "clean full decode", "re-render; a file that errors here may stall on the platform's transcoder")
    else:
        row("decode", "PASS", "full decode, no errors", "clean full decode")

    review: Dict[str, Any] = {"frames": [], "contact_sheet": None, "dir": None}
    if v and not args.no_frames and not dry_run_input_pending(args.input):
        cuts = detect_scenes(args.input, 10.0, 1.0, dur) if dur else [0.0]
        review = export_frames(args.input, meta, outdir, cuts)
        review["dir"] = str(outdir)
        row("review frames", "PASS" if review["frames"] else "WARN", f"{len(review['frames'])} frames, {len(cuts) - 1} scene cut(s)",
            "frames exported", "" if review["frames"] else "export failed; use look.py")
    elif not v:
        row("review frames", "SKIP", "no video stream")

    failed = [r for r in rows if r["status"] == "FAIL"]
    warned = [r for r in rows if r["status"] == "WARN"]
    if not args.json and not STATE.json:
        wcol = max(len(r["check"]) for r in rows)
        print(f"{args.input} -- qc{' ' + platform if platform else ''}")
        for r in rows:
            line = f"  {r['status']:4s} {r['check']:{wcol}s}  {r['value']}"
            if r["status"] != "PASS" and r["expected"]:
                line += f"  (expected {r['expected']})"
            if r["status"] in ("WARN", "FAIL") and r["fix"]:
                line += f"  -> {r['fix']}"
            print(line)
        print(f"  {len(rows)} checks, {len(failed)} failed, {len(warned)} warnings")
        if review["frames"]:
            print(f"  review frames ({review['dir']}):")
            for f in review["frames"]:
                print(f"    {f['time']:8.2f}s  {f['label']:6s} {f['path']}")
            if review["contact_sheet"]:
                print(f"    contact sheet: {review['contact_sheet']}")
        print("  qc is mechanical: look at the frames and listen before calling it approved")
    extra = dict(platform=platform, checks=rows, failed=len(failed), warnings=len(warned), ok=not failed,
                 frames=review["frames"], contact_sheet=review["contact_sheet"], frames_dir=review["dir"])
    if failed:
        die(f"{len(failed)} of {len(rows)} qc checks failed: {', '.join(r['check'] for r in failed)}",
            kind="verification", output=None, dry_run=STATE.dry_run, **extra)
    emit(None, **extra)
    return 0


if __name__ == "__main__":
    sys.exit(main())
