"""Cut/beat alignment and compact quality findings; all retiming is advisory."""
import bisect
import math
import statistics
from .util import row


def nearest(values, time):
    if not values:
        return None
    i=bisect.bisect_left(values,time)
    return min(values[max(0,i-1):min(len(values),i+1)],key=lambda t:abs(t-time))


def alignment(shots, rhythm, fps, within_frames=6):
    fps=float(fps)
    if not math.isfinite(fps) or fps<=0 or int(within_frames)<0:
        raise ValueError('fps must be positive and within_frames non-negative')
    beats=sorted(rhythm.get('beats',[])); onsets=sorted(rhythm.get('onsets',[]))
    rows=[]; snaps=[]
    for shot in shots[1:]:
        cut=shot['start']; beat=nearest(beats,cut); onset=nearest(onsets,cut)
        candidates=[(abs(t-cut),t,kind) for t,kind in [(beat,'beat'),(onset,'onset')] if t is not None]
        if not candidates:
            continue
        offset,target,kind=min(candidates)
        rows.append({'cut':cut,'nearest':target,'kind':kind,'offset_ms':round(offset*1000,3),'beat':beat,'onset':onset})
        if beat is not None and abs(beat-cut)*fps<=int(within_frames)+1e-6:
            snaps.append({'cut':cut,'beat':beat,'cut_frame':round(cut*fps),'beat_frame':round(beat*fps),'frame_delta':round(beat*fps)-round(cut*fps),'offset_frames':round((beat-cut)*fps,3)})
    offsets=[r['offset_ms'] for r in rows]
    off=sum(v>80+1e-6 for v in offsets)
    return {'cut_count':max(0,len(shots)-1),'measured_cuts':len(rows),'median_offset_ms':round(statistics.median(offsets),3) if offsets else None,'offbeat_fraction':off/len(rows) if rows else None,
            'worst_cuts':sorted(rows,key=lambda r:r['offset_ms'],reverse=True)[:10],'alignment':rows,'snaps':snaps,'fps':fps,'within_frames':int(within_frames),
            'method':'nearest beat OR onset; >30% of measured cuts more than 80ms away warns; snap targets use beats only'}


def cut_sync(doc):
    if not doc['measured_cuts']:
        return row('cut_sync','SKIP','no measurable cuts or rhythm anchors')
    warn=doc['offbeat_fraction']>.30
    worst=doc['worst_cuts'][:3]
    suggestions='; '.join(f"{s['cut']:.3f}s -> {s['nearest']:.3f}s ({round(s['nearest']*doc['fps'])-round(s['cut']*doc['fps']):+d}f, {s['kind']})" for s in worst if s['offset_ms']>80)
    return row('cut_sync','WARN' if warn else 'PASS',f"median {doc['median_offset_ms']:.1f}ms; {doc['offbeat_fraction']:.0%} of cuts >80ms; nearest beat/onset",[[r['cut'],r['cut']] for r in worst],f'Snap suggestions: {suggestions}' if suggestions else '')


def pacing(shots, platform, visual_changes=()):
    lengths=[s['duration'] for s in shots]
    if not lengths:
        return row('pacing','SKIP','no shots available')
    first=min([s['start'] for s in shots[1:]]+list(visual_changes),default=None)
    vertical=platform in {'shorts','reels','tiktok','instagram','instagram-reels','youtube-shorts'}
    warn=vertical and (first is None or first>2)
    summary=f'{len(lengths)} shots; min/median/mean/max {min(lengths):.2f}/{statistics.median(lengths):.2f}/{statistics.mean(lengths):.2f}/{max(lengths):.2f}s (informational)'
    if vertical:
        summary+='; '+('no cut/visual change in first 2s' if warn else f'first cut/visual change {first:.3f}s')
    return row('pacing','WARN' if warn else 'PASS',summary,[[0,min(2,shots[-1]['end'])]] if warn else [],'review the opening hook in the source edit' if warn else '')


def flash(visual):
    # Count cycles, not both edges. Merge red/luminance events on the same frame.
    times=sorted(set(e['time'] for e in visual['flashes']))
    windows=[]; left=0; maximum=0
    for right,time in enumerate(times):
        while time-times[left]>=1-1e-9:
            left+=1
        count=right-left+1; maximum=max(maximum,count)
        if count>3:
            windows.append([times[left],time])
    check=row('flash','FAIL' if windows else 'PASS',f'{maximum} flashes in a 1s window; estimate, not a certified Harding test',windows[:10],
              'reduce rapid luminance/red flashing in the source and obtain specialist safety review' if windows else '')
    return {'checks':[check],'max_flashes_per_second':maximum,'windows':windows,'events':visual['flashes'],'method':visual['method'],'label':visual['label']}


def edit_stage(req):
    from .config import load
    from .senses.scenes import detect_scenes
    from .senses.rhythm import beats
    from .visual import scan
    cfg=req.get('config') or load(); checks=[]; details={}
    try:
        shots=detect_scenes(req['file'],cfg); details['scenes']=shots
    except Exception as exc:
        shots=None; checks.append(row('pacing','SKIP',str(exc)[-200:]))
    try:
        visual=scan(req['file'],cfg)
        safety=flash(visual); checks+=safety['checks']; details['flash']=safety
    except Exception as exc:
        visual={}; checks.append(row('flash','SKIP',str(exc)[-200:]))
    if shots:
        checks.append(pacing(shots['shots'],req['platform'],visual.get('visual_changes',[])))
    import re
    if req.get('beat_led') or re.search(r'\b(?:beat|music)[-\s]+led\b',req.get('brief') or '',re.I):
        try:
            if not shots:
                raise RuntimeError('shots unavailable')
            rhythm=beats(req['file'],cfg)
            aligned=alignment(shots['shots'],rhythm,shots['fps'])
            checks.append(cut_sync(aligned)); details['rhythm']=rhythm; details['cut_sync']=aligned
        except Exception as exc:
            checks.append(row('cut_sync','SKIP',str(exc)[-200:]))
    return {'checks':checks,**details}
