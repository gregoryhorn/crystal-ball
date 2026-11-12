"""OCR lines with confidence, persistence, bounded findings and spelling evidence."""
import csv
import io
import os
from pathlib import Path
from ..util import command, row, skip, norm, spelling_checks, _spelling_tokens
from ..config import load
from ..cache import Store
from ..checks import platforms

def lines_from_tsv(text, frame):
    if not text.startswith('level\tpage_num\t'):
        raise ValueError('tesseract returned no TSV')
    groups={}
    for b in csv.DictReader(io.StringIO(text),delimiter='\t'):
        word=b.get('text','').strip()
        if not word or float(b.get('conf',-1))<70:
            continue
        key=tuple(b[k] for k in ('page_num','block_num','par_num','line_num'))
        groups.setdefault(key,[]).append(b)
    lines=[]
    for group in groups.values():
        text=' '.join(b['text'].strip() for b in group)
        x=min(int(b['left']) for b in group); y=min(int(b['top']) for b in group)
        right=max(int(b['left'])+int(b['width']) for b in group)
        bottom=max(int(b['top'])+int(b['height']) for b in group)
        lines.append({'time':frame['time'],'text':text,'confidence':min(float(b['conf']) for b in group),'box':[x,y,right-x,bottom-y]})
    return lines

def filter_lines(lines, sizes, safe, platform, confirmed=(), cap=20):
    grouped={}
    for line in lines:
        key=norm(line['text'])
        grouped.setdefault(key,[]).append(line)
    checks=[]
    for key,group in grouped.items():
        edge=[]
        for line in group:
            w,h=sizes[line['time']]; x,y,bw,bh=line['box']
            if x<safe['left']*w or y<safe['top']*h or x+bw>(1-safe['right'])*w or y+bh>(1-safe['bottom'])*h:
                edge.append(line)
        if not edge:
            continue
        # Judge confirmation never promotes short or low-confidence noise.
        credible=sum(c.isalnum() for c in key)>=3 and min(l['confidence'] for l in edge)>=70
        persistent=len({l['time'] for l in edge})>=2
        status='FAIL' if credible and (persistent or key in {norm(t) for t in confirmed}) else 'WARN'
        checks.append(row('ocr_safe_zone',status,f'"{group[0]["text"]}" overlaps {platform} UI safe border'+(' (unconfirmed OCR)' if status=='WARN' else ''),[[l['time'],l['time']] for l in edge][:6],'move source text inside the safe zone; re-render'))
    return checks[:cap]

def ocr_frames(file, frames, config=None):
    from PIL import Image
    cfg=config or load(); tess=cfg['read']['tessdata']
    env=os.environ.copy()
    if tess:
        env['TESSDATA_PREFIX']=tess
    available=command(['tesseract','--list-langs'],15,env).splitlines()
    langs=[x for x in ('eng','ara') if x in available]
    if not langs:
        raise RuntimeError('no English or Arabic tesseract traineddata available')
    options={'frames':[(f['time'],f['path']) for f in frames],'tessdata':tess,'languages':langs,
             'models':[(p.name,p.stat().st_size,p.stat().st_mtime_ns) for p in Path(tess).glob('*.traineddata')] if tess else []}
    def produce(directory):
        lines=[]; sizes={}
        for frame in frames:
            with Image.open(frame['path']) as im:
                sizes[str(frame['time'])]=list(im.size)
            text=command(['tesseract',frame['path'],'stdout','-l','+'.join(langs),'--psm','11','-c','tessedit_create_tsv=1'],20,env)
            lines+=lines_from_tsv(text,frame)
        return {'lines':lines,'sizes':sizes,'languages':langs,'artifact_paths':[f['path'] for f in frames]}
    return Store(cfg['cache_dir']).get(file,'ocr',options,produce)

def ocr_stage(req):
    frames=req['review'].get('frames',[])
    if not frames:
        return skip('ocr','review frames unavailable')
    data=ocr_frames(req['file'],frames,req.get('config'))
    sizes={float(k):v for k,v in data['sizes'].items()}
    checks=filter_lines(data['lines'],sizes,platforms().PLATFORMS[req['platform']]['safe'],req['platform'])
    expected=req.get('expect_text',[])
    # Deduplicate vocabulary by the same spelling-local normalization, not display copy.
    expected_keys={tuple(t[0] for t in _spelling_tokens(term)) for term in expected}
    rule_terms=[term for term in req['rules']['terms']
                if tuple(t[0] for t in _spelling_tokens(term)) not in expected_keys]
    checks+=spelling_checks(data['lines'],expected)
    checks+=spelling_checks(data['lines'],rule_terms,proper_only=True)
    for expected in req.get('expect_text',[]):
        if not any(norm(expected) in norm(l['text']) for l in data['lines']):
            checks.append(row('expected_text','WARN',f'"{expected}" not confirmed in sampled OCR'))
    if not checks:
        checks=[row('ocr','PASS',f"{len(data['lines'])} confident lines checked")]
    if 'ara' not in data['languages']:
        checks.append(row('ocr_arabic','SKIP','Arabic traineddata unavailable'))
    return {**data,'checks':checks[:40],'boxes':data['lines'],'sampling':'full-size sampled frames; confidence >=70, >=3 alphanumeric characters and persistence required for FAIL'}

def read_text(file, at=None, config=None):
    from ..workers import see_request
    return see_request('read_text',{'file':str(file),'at':at},config,300)

def _read_text(file, at=None, config=None):
    from ..core import review_stage
    from ..frames import probe
    cfg=config or load(); file=str(Path(file).resolve()); meta=probe(file)
    if at is None:
        review=review_stage({'file':file,'meta':meta,'cache_dir':cfg['cache_dir']})
    else:
        if not 0<=at<meta['duration']:
            raise ValueError('timestamp outside media')
        def produce(directory):
            p=directory/'frame.jpg'
            command(['ffmpeg','-nostdin','-v','error','-ss',str(at),'-i',file,'-frames:v','1','-threads','1','-q:v','2',str(p)],20)
            return {'frames':[{'time':at,'path':str(p)}],'artifact_paths':[str(p)]}
        review=Store(cfg['cache_dir']).get(file,'frame',{'at':at},produce)
    return ocr_frames(file,review['frames'],cfg)


def confirm_safe_zones(ocr,vision):
    """Promote a credible single-frame border finding only with timed judge corroboration."""
    import re
    confirmations=[]
    for check in vision.get('checks',[]):
        if check['id']=='vision_safe_zone':
            for text in re.findall(r'["“]([^"”]+)["”]',check['summary']):
                confirmations.append((norm(text),check['timestamps']))
    checks=[]
    for check in ocr.get('checks',[]):
        item=check.copy()
        if item['id']=='ocr_safe_zone' and item['status']=='WARN':
            texts=re.findall(r'["“]([^"”]+)["”]',item['summary'])
            text=norm(texts[0]) if texts else ''
            credible=sum(c.isalnum() for c in text)>=3 and any(norm(l['text'])==text and l['confidence']>=70 for l in ocr.get('lines',[]))
            if credible and any(text==confirmed and any(abs(t[0]-v[0])<=.2 for t in item['timestamps'] for v in times) for confirmed,times in confirmations):
                item['status']='FAIL'
                item['summary']=item['summary'].replace(' (unconfirmed OCR)',' (judge corroborated)')
        checks.append(item)
    return {**ocr,'checks':checks}
