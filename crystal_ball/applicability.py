"""MA-r1 content classification and omission vocabulary (no engine activation)."""
from pathlib import Path
from .util import row

SHAPES = {'9:16': 9/16, '16:9': 16/9, '1:1': 1.0}


def wants_beats(req):
    import re
    return bool(req.get('beat_led') or re.search(r'\b(?:beat|music)[-\s]+led\b', req.get('brief') or '', re.I))


def omitted(identity, text, reason='not_applicable'):
    return {**row(identity, 'SKIP', 'Not checked: '+text), 'skip_reason': reason}


def normalize_skips(stages):
    for stage in stages.values():
        for check in stage.get('checks', []):
            if check['status'] == 'SKIP':
                if check['summary'].lower().startswith('not checked: '):
                    check['summary'] = 'Not checked: '+check['summary'].split(':', 1)[1].lstrip()
                else:
                    check['summary'] = 'Not checked: '+check['summary']
                check.setdefault('skip_reason', 'unavailable')
    return stages


def classify(doc):
    streams = doc.get('streams', [])
    picture = [s for s in streams if s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic')]
    audio = any(s.get('codec_type') == 'audio' for s in streams)
    fmt = doc.get('format', {}).get('format_name', '')
    # Demuxer plus decoded frame count distinguishes images, including disguised files.
    still = any(name in {'image2', 'png_pipe', 'jpeg_pipe', 'webp_pipe', 'bmp_pipe', 'tiff_pipe', 'gif', 'apng'} for name in fmt.split(','))
    if still:
        if audio or len(picture) != 1:
            return None
        count = picture[0].get('nb_read_frames', picture[0].get('nb_frames'))
        if not picture[0].get('width') or not picture[0].get('height') or str(count) == '0':
            raise ValueError('image decoder produced no usable picture')
        return 'image' if str(count) == '1' else None
    if len(picture) > 1:
        return None
    if picture:
        return 'video' if audio else 'video-without-audio'
    return 'audio-only' if audio else None


def image_review(req):
    from PIL import Image, ImageOps
    directory = Path(req['run_dir'])/'frames'
    directory.mkdir(parents=True, exist_ok=True)
    target = directory/'still.png'
    with Image.open(req['file']) as source:
        source.load()
        oriented = ImageOps.exif_transpose(source)
        oriented.convert('RGBA' if 'A' in oriented.getbands() else 'RGB').save(target)
    return {'frames': [{'time': 0.0, 'path': str(target)}], 'frames_dir': str(directory),
            'contact_sheet': str(target), 'checks': [row('review frames', 'PASS', 'one full-resolution oriented still; no temporal corroboration')]}


def shape_checks(req):
    meta = req['meta']
    if meta['media_kind'] == 'audio-only':
        return [omitted('aspect', 'audio-only media has no picture')]
    checks = [row('resolution', 'PASS' if meta['width'] > 0 and meta['height'] > 0 else 'FAIL', f"{meta['width']}x{meta['height']} oriented pixels")]
    shape = req.get('shape')
    if shape:
        error = abs(meta['width']/meta['height']/SHAPES[shape]-1)
        checks.append(row('aspect', 'PASS' if error <= .01+1e-12 else 'FAIL', f'{shape} requested; relative ratio error {error:.4%} (1% tolerance)'))
    elif req['platform'] == 'custom':
        checks.append(omitted('aspect', 'no shape requested', 'not_requested'))
    return checks


def exclusions(req):
    kind = req['meta']['media_kind']
    checks = []
    if kind == 'image':
        checks += [omitted(k, 'still image has no timeline') for k in ('duration', 'fps', 'black', 'frozen', 'flash', 'pacing', 'cut_sync', 'A/V drift', 'caption zone')]
        checks += [omitted(k, 'still image has no audio') for k in ('audio', 'silence', 'loudness', 'true peak', 'clipping', 'rhythm')]
    elif kind == 'audio-only':
        checks += [omitted(k, 'audio-only media has no picture') for k in ('resolution', 'review frames', 'ocr', 'ocr_safe_zone', 'vision', 'fps', 'black', 'frozen', 'flash', 'pacing', 'cut_sync', 'A/V drift', 'caption zone')]
    elif kind == 'video-without-audio':
        checks += [omitted(k, 'video has no audio stream') for k in ('audio', 'silence', 'loudness', 'true peak', 'clipping', 'rhythm', 'A/V drift', 'cut_sync')]
        import re
        if re.search(r'\b(?:audio\s+(?:is\s+)?required|required\s+audio|must\s+include\s+audio)\b', req.get('brief') or '', re.I):
            checks.append(row('required_output', 'FAIL', 'brief explicitly requires audio; video has no audio stream'))
    if req['platform'] == 'custom':
        checks.append(omitted('video platform', 'no video platform selected', 'not_requested'))
    if kind in {'audio-only', 'video'} and not req.get('script'):
        checks.append(omitted('script_match', 'no script supplied', 'not_requested'))
    if kind in {'audio-only', 'video'} and not wants_beats(req):
        checks.append(omitted('rhythm', 'beat analysis not requested', 'not_requested'))
        if kind == 'video':
            checks.append(omitted('cut_sync', 'beat analysis not requested', 'not_requested'))
    return checks
