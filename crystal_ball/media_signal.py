"""Applicable signal measurements; platform rules only for selected video targets."""
import math
from .checks import load_qc
from .util import row, command
from .applicability import omitted, shape_checks, exclusions


def signal(req):
    kind = req['meta']['media_kind']
    checks = shape_checks(req)+exclusions(req)
    if kind == 'image':
        from PIL import Image
        try:
            with Image.open(req['file']) as image:
                image.load()
                checks += [row('format', 'PASS', image.format), row('decode', 'PASS', 'full still decode, no errors')]
        except Exception as exc:
            checks.append(row('decode', 'FAIL', f'image decode failed: {exc}'))
        return {'checks': checks}
    qc = load_qc()
    meta = qc.probe(req['file'])
    video, audio = meta.get('video'), meta.get('audio')
    measured = qc.decode_pass(req['file'], meta, 2.0, .2)
    if measured['returncode'] or measured['errors']:
        checks.append(row('decode', 'FAIL', 'full decode failed: '+str(measured['errors'] or measured['returncode'])))
        checks.append(omitted('signal dependencies', 'decode failed; dependent analysis unavailable', 'dependency_failed'))
        return {'checks': checks}
    checks.append(row('decode', 'PASS', 'full decode, no errors'))
    # The vendored platform gate is never called for audio or custom destinations.
    if video and req['platform'] != 'custom':
        for item in qc.run_check(req['file'], req['platform'], False):
            if item['check'] in {'audio', 'loudness', 'true peak'} and not audio:
                continue

            checks.append(row(item['check'], item['status'], str(item['value']), fix=fix_hint(item.get('fix', ''))))
    else:
        codecs = [s.get('codec_name', 'unknown') for s in req['meta']['streams'] if s.get('codec_type') in {'video', 'audio'} and not s.get('disposition', {}).get('attached_pic')]
        checks.append(row('format', 'PASS', ', '.join(codecs)))
        checks.append(row('duration', 'PASS' if meta.get('duration', 0) > 0 else 'FAIL', f"{meta.get('duration', 0):.3f}s measured; no duration target requested"))
        if video:
            checks.append(row('fps', 'PASS' if video.get('fps', 0) > 0 else 'FAIL', f"{video.get('fps', 0):g} fps measured"))

    if video:
        duration = meta.get('duration') or 0
        black = measured['black']
        hole = any(e-s >= 1 and s > qc.EDGE_S and e < duration-qc.EDGE_S for s,e in black)
        all_black = duration > 0 and sum(e-s for s,e in black)/duration >= qc.BLACK_ALL
        checks.append(row('black', 'FAIL' if hole or all_black else 'WARN' if black else 'PASS', qc.spans_text(black) or 'none', black))
        checks.append(row('frozen', 'WARN' if measured['frozen'] else 'PASS', qc.spans_text(measured['frozen']) or 'none', measured['frozen']))
        if req.get('captions'):
            if req['platform'] != 'custom' or req.get('shape'):
                checks.append(caption_check(qc, req))
            else:
                checks.append(omitted('caption zone', 'no video platform selected', 'not_requested'))
        else:
            checks.append(omitted('caption zone', 'no captions supplied', 'not_requested'))
    if audio:
        peak, count = measured['peak_db'], measured['peak_count']
        if peak is None:
            checks += [omitted(k, 'audio measurement unavailable', 'unavailable') for k in ('silence', 'clipping')]
        else:
            gaps = measured['silence']
            checks.append(row('silence', 'FAIL' if peak <= qc.SILENT_PEAK_DBFS else 'WARN' if gaps else 'PASS', f'peak {peak:g} dBFS; '+(qc.spans_text(gaps) or 'no gaps'), gaps))
            clipping = peak >= qc.CLIP_OVER_FAIL_DB or (peak >= -.1 and (count or 0) >= qc.CLIP_FAIL)
            warn = peak > 0 or (peak >= -.1 and (count or 0) >= qc.CLIP_WARN)
            checks.append(row('clipping', 'FAIL' if clipping else 'WARN' if warn else 'PASS', f'peak {peak:g} dBFS; {count} samples on peak'))
        if req['platform'] == 'custom':
            import check as check_module
            level = check_module.measure_loudness(req['file'])
            if level:
                checks.append(row('loudness measurement', 'PASS', f"{level['lufs']:g} LUFS measured; no target comparison"))
                checks.append(row('true peak', 'PASS' if level['tp'] <= -1+check_module.TP_TOLERANCE_DB else 'FAIL', f"{level['tp']:g} dBTP; generic -1 dBTP ceiling"))
            else:
                checks += [omitted(k, 'audio measurement unavailable', 'unavailable') for k in ('loudness measurement', 'true peak')]
            checks.append(omitted('loudness', 'no loudness target requested', 'not_requested'))
        if video:
            timing = qc.stream_times(req['file'])
            if 'audio' in timing and 'video' in timing:
                drift = max(abs(timing['audio'][k]-timing['video'][k]) for k in ('start', 'end'))
                frame = 1/(timing['video'].get('fps') or 30)
                checks.append(row('A/V drift', 'FAIL' if drift > .1 else 'WARN' if drift > frame else 'PASS', f'{drift*1000:g} ms maximum stream drift'))
            else:
                checks.append(omitted('A/V drift', 'per-stream timing unavailable', 'unavailable'))
    # JSON has no infinities; retain explicit silence evidence instead of losing the stage.
    for key, value in measured.items():
        if isinstance(value, float) and not math.isfinite(value):
            measured[key] = str(value)
    return {'checks': checks, 'measurements': measured}


def caption_check(qc, req):
    """Reuse ASS evidence gates with the requested generic inset, not platform overlays."""
    platform = req['platform']
    original = qc.PLATFORMS[platform]
    if platform == 'custom':
        qc.PLATFORMS[platform] = {**original, 'frame': (req['meta']['width'], req['meta']['height']),
                                  'safe': dict.fromkeys(('left','right','top','bottom'), .05)}
    try:
        status, text, fix = qc.caption_zone(req['captions'], platform, req['meta']['width'], req['meta']['height'])
    finally:
        qc.PLATFORMS[platform] = original
    if platform == 'custom':
        text = text.replace('custom', 'generic 5% inset').replace('UI', 'border')
        fix = 'move caption source inside the generic 5% inset; re-render' if status in {'WARN','FAIL'} else ''
    return row('caption zone', status, text, fix=fix)


def fix_hint(hint):
    """Keep the existing public hints instead of exposing private vendored scripts."""
    for names, replacement in [
        (('loudness.py',), 'crystal-ball check FILE --fix; measured levels only, always to a new file'),
        (('caption.py',), 'review caption delivery needs and edit the caption source; re-render if needed'),
        (('sync.py',), 'align the source audio and video, then re-render and re-check'),
        (('audio.py','silence.py'), 'inspect these audio times, adjust the source mix if needed, and re-render'),
        (('look.py','qc frames'), 'inspect the timestamped report frames and source timeline; re-render if unintended'),
        (('export.py',), 're-export the source to the stated platform format, then re-check'),
    ]:
        if any(name in hint for name in names):
            return replacement
    return hint
