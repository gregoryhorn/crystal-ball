import contextlib, csv, difflib, hashlib, io, json, math, os, re, signal, subprocess, sys, tempfile, time, uuid
from pathlib import Path
from .util import command, row
from .checks import load_qc
def probe(path):
    doc = json.loads(command(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", path], 15))
    video = next((s for s in doc["streams"] if s["codec_type"] == "video" and
                  not s.get("disposition", {}).get("attached_pic")), None)
    if not video:
        raise ValueError("file has no video stream")
    width, height = video["width"], video["height"]
    rotation = next((s.get("rotation", 0) for s in video.get("side_data_list", []) if "rotation" in s), 0)
    if abs(int(rotation)) % 180 == 90:
        width, height = height, width
    return {"width": width, "height": height, "duration": float(doc["format"].get("duration", 0)),
            "streams": doc["streams"]}

def caption_times(path):
    if not path:
        return []
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    if Path(path).suffix.lower() == ".srt":
        pairs = re.findall(r"(\d+:\d+:\d+[,.]\d+)\s*-->\s*(\d+:\d+:\d+[,.]\d+)", text)
    else:
        pairs = []
        fmt = ["layer", "start", "end"]
        in_events = False
        for line in text.splitlines():
            if line.startswith("["):
                in_events = line.strip().lower() == "[events]"
            elif in_events and line.lower().startswith("format:"):
                fmt = [s.strip().lower() for s in line.split(":", 1)[1].split(",")]
            elif in_events and line.lower().startswith("dialogue:"):
                fields = line.split(":", 1)[1].split(",", len(fmt) - 1)
                event = dict(zip(fmt, fields))
                pairs.append((event["start"], event["end"]))
    def seconds(value):
        h, m, s = value.replace(",", ".").split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    return [min(seconds(e), seconds(s) + min(0.15, (seconds(e) - seconds(s)) / 2)) for s, e in pairs]

def review_stage(req):
    from PIL import Image, ImageDraw, ImageOps
    qc = load_qc()
    meta = req["meta"]
    dur = meta["duration"]
    last = max(0, dur - 0.08)
    from .senses.scenes import detect_scenes
    shots=detect_scenes(req['file'],req.get('config'))
    cuts=[s['start'] for s in shots['shots'][1:]]
    if len(cuts) > 12:
        cuts = [cuts[int(i * len(cuts) / 12)] for i in range(12)]
    cap_times = caption_times(req.get("captions"))
    times = sorted(set(round(max(0, min(t, last)), 3) for t in
                       [0, dur * .25, dur * .5, dur * .75, last] + [t + .1 for t in cuts] + cap_times))
    frame_dir = Path(req["run_dir"]) / "frames"
    frame_dir.mkdir(exist_ok=True)
    frames = []
    for i, t in enumerate(times):
        target = frame_dir / f"{i:04d}_{t:.3f}s.jpg"
        command(["ffmpeg", "-v", "error", "-nostdin", "-threads", "1", "-ss", str(t), "-i", req["file"],
                 "-map", "0:V:0", "-frames:v", "1", "-threads", "1", "-q:v", "2", "-n", target], 15)
        frames.append({"time": t, "path": str(target), "at_cut":any(abs(t-(cut+.1))<.002 for cut in cuts)})
    cols = min(4, len(frames))
    tw, th = 320, round(320 * meta["height"] / meta["width"])
    sheet = Image.new("RGB", (cols * tw, math.ceil(len(frames) / cols) * (th + 24)), "#202020")
    draw = ImageDraw.Draw(sheet)
    for i, frame in enumerate(frames):
        x, y = (i % cols) * tw, (i // cols) * (th + 24)
        with Image.open(frame["path"]) as im:
            sheet.paste(ImageOps.contain(im, (tw, th)), (x, y + 24))
        draw.text((x + 4, y + 4), f"{frame['time']:.3f}s", fill="white")
    contact = frame_dir / "contact.jpg"
    sheet.save(contact, quality=85)
    return {"frames": frames, "contact_sheet": str(contact), "frames_dir": str(frame_dir),
            "scenes":shots["paths"], "checks": [row("review frames", "PASS", f"{len(frames)} review/caption frames exported")]}
