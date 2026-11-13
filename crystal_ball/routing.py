"""Applicability-before-dispatch: excluded stages are never executed."""
from .applicability import omitted, wants_beats
from .util import row, skip
from .senses.judge import crosscheck_vision
from .senses.read import confirm_safe_zones


def dispatch_stages(request, runner):
    kind = request['meta'].get('media_kind', 'video')
    if kind is None:
        return {'probe': {'checks': [omitted('probe', 'unsupported media kind')]}}
    stages = {'signal': runner('signal', request)}
    decoded = any(r['id'] == 'decode' and r['status'] == 'PASS' for r in stages['signal'].get('checks', []))
    if not decoded:
        stages['dependencies'] = {'checks': [omitted('dependent analysis', 'decode failed; dependent analysis unavailable', 'dependency_failed')]}
        return stages
    picture = kind != 'audio-only'
    audio = kind in {'audio-only', 'video'}
    if audio:
        if request['config']['hear']['model']:
            stages['audio'] = runner('audio', request)
        else:
            stages['audio'] = {'checks': [omitted('audio', 'Hear is disabled', 'not_requested')]}
    else:
        stages['audio'] = {'checks': [omitted('audio', 'still image has no audio' if kind == 'image' else 'video has no audio stream')]}
    if picture:
        stages['review'] = runner('review', request)
        dependent = {**request, 'review': stages['review']}
        stages['ocr'] = runner('ocr', dependent)
        if request['mode'] == 'quick' and any(r['status'] in {'FAIL', 'WARN'} for r in stages['signal'].get('checks', [])):
            stages['vision'] = {'checks': [omitted('vision', 'quick mode: signal checks did not all pass', 'not_requested')]}
        else:
            stages['vision'] = runner('vision', dependent)
        stages['vision'] = crosscheck_vision(stages['vision'], stages['ocr'])
        stages['ocr'] = confirm_safe_zones(stages['ocr'], stages['vision'])
    if kind in {'video', 'video-without-audio'}:
        stages['editing'] = runner('editing', request)
    elif kind == 'audio-only' and wants_beats(request):
        from .senses.rhythm import beats
        try:
            stages['rhythm'] = {'checks': [row('rhythm', 'PASS', 'requested beat evidence measured')], 'evidence': beats(request['file'], request['config'])}
        except Exception as exc:
            stages['rhythm'] = skip('rhythm', str(exc))
    return stages
