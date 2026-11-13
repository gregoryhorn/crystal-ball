"""Full local reports, including escaped standalone HTML."""
import html
import json
import os
from urllib.parse import quote
from pathlib import Path, PureWindowsPath
import ntpath
from .cache import atomic

def asset_url(path, report_dir):
    native=PureWindowsPath(path)
    if native.is_absolute() and native.drive:
        if native.drive.startswith('\\\\'):
            return native.as_uri()
        try:
            return quote(PureWindowsPath(ntpath.relpath(str(native),str(report_dir))).as_posix())
        except ValueError:
            return native.as_uri()
    try:
        return quote(Path(os.path.relpath(path, report_dir)).as_posix())
    except ValueError:
        return Path(path).absolute().as_uri()

def write_report(doc, run_dir):
    target=Path(run_dir)/'report.md'
    lines=['# Crystal Ball report', '',f"File: {doc['file']}",f"Platform: {doc['platform']}",f"Media kind: {doc.get('media_kind') or 'not classified'}",'',
           'Sampled evidence. Check passed ≠ approved. Continuous listening and lip-sync are not judged.','',
           '| Status | Check | Evidence | Times | Fix |','|---|---|---|---|---|']
    def cell(v):
        return str(v).replace('|','\\|').replace('\n',' ')
    for r in doc['checks']:
        lines.append('| '+' | '.join(cell(r[k]) for k in ('status','id','summary','timestamps','fix'))+' |')
    lines += ['', '## Full evidence', '', '```json',json.dumps(doc.get('stages',{}),ensure_ascii=False,indent=2),'```']
    review=doc.get('stages',{}).get('review',{})
    contact=review.get('contact_sheet')
    preview=''
    if contact and Path(contact).is_file():
        relative=asset_url(contact,target.parent)
        lines += ['', '## Sampled contact sheet', '', f'![Timestamped sampled frames]({relative})']
        preview='<h2>Sampled contact sheet</h2><img style="max-width:100%;height:auto" alt="Timestamped sampled frames" src="'+html.escape(relative,quote=True)+'">'
    text='\n'.join(lines)
    atomic(target,text)
    rows=''.join('<tr>'+''.join('<td>'+html.escape(str(r[k]))+'</td>' for k in ('status','id','summary','timestamps','fix'))+'</tr>' for r in doc['checks'])
    atomic(target.with_suffix('.html'),'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Crystal Ball report</title><style>body{background:#141320;color:#eee;font:16px system-ui;padding:2rem}table{border-collapse:collapse;width:100%}td,th{border:1px solid #666;padding:.6rem;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><h1>Crystal Ball report</h1><p>File: '+html.escape(str(doc['file']))+'<br>Platform: '+html.escape(str(doc['platform']))+'<br>Media kind: '+html.escape(str(doc.get('media_kind') or 'not classified'))+'</p><p>Check passed ≠ approved. Sampled images cannot judge listening or lip-sync.</p><table><thead><tr><th>Status</th><th>Check</th><th>Evidence</th><th>Times</th><th>Fix</th></tr></thead><tbody>'+rows+'</tbody></table>'+preview+'<h2>Full evidence</h2><pre>'+html.escape(json.dumps(doc.get('stages',{}),ensure_ascii=False,indent=2))+'</pre></html>')
    return str(target)
