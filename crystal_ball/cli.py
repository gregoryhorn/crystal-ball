"""Crystal Ball command-line interface."""
import argparse
import json
import sys
from pathlib import Path
from .api import dispatch
from .cache import dumps, atomic

def parser():
    ap=argparse.ArgumentParser(prog='crystal-ball',description='Four media senses. Evidence, not creative approval.')
    ap.add_argument('--version',action='version',version='1.0.0')
    sub=ap.add_subparsers(dest='action',required=True)
    c=sub.add_parser('check'); c.add_argument('file')
    for option in ('platform','captions','script','brief'):
        c.add_argument('--'+option)
    c.add_argument('--mode',choices=['quick','full'],default='quick')
    c.add_argument('--expect-text',action='append',default=[])
    for option in ('fix','force','json'):
        c.add_argument('--'+option,action='store_true')
    t=sub.add_parser('transcribe'); t.add_argument('file'); t.add_argument('-o','--output',required=True)
    formats=t.add_mutually_exclusive_group()
    for option in ('srt','vtt','json'):
        formats.add_argument('--'+option,action='store_true')
    i=sub.add_parser('index'); i.add_argument('paths',nargs='+')
    f=sub.add_parser('find'); f.add_argument('text',nargs='?'); f.add_argument('--image'); f.add_argument('--top',type=int,default=10); f.add_argument('--dir',action='append')
    r=sub.add_parser('read-text'); r.add_argument('file'); r.add_argument('--at',type=float)
    d=sub.add_parser('doctor'); d.add_argument('--json',action='store_true')
    s=sub.add_parser('setup'); s.add_argument('engine',nargs='?',choices=['hear','see','read'])
    return ap

def main(argv=None):
    args=vars(parser().parse_args(argv)); action=args.pop('action').replace('-','_')
    try:
        if action=='setup':
            from .setup import instructions
            print(instructions(args['engine'])); return 0
        if action=='find' and bool(args['text'])==bool(args['image']):
            raise ValueError('provide text or --image')
        if action=='find' and args['top']<=0:
            raise ValueError('--top must be positive')
        if action=='check':
            for key in ('file','script','captions'):
                if args.get(key):
                    args[key]=str(Path(args[key]).expanduser().resolve())
        if action=='transcribe':
            out=args.pop('output'); kind='srt' if args.pop('srt') else 'vtt' if args.get('vtt') else 'json'
            args.pop('vtt'); args.pop('json')
            result=dispatch(action,**args)
            from .senses.hear import subtitles
            atomic(out,subtitles(result,kind) if kind!='json' else json.dumps(result,ensure_ascii=False,indent=2))
            print(dumps({'status':'written','file':out,'engine':result['engine']})); return 0
        json_output=args.pop('json',False)
        result=dispatch(action,**args)
        if action=='doctor' and not json_output:
            from .doctor import table
            print(table(result))
        elif action=='check' and not json_output:
            print(f"{result['verdict']}  {result['counts']}\nReport: {result['report']}")
            if result.get('fix'):
                fixed=result['fix']
                print(f"Fix: {fixed['status']} {fixed.get('file',fixed.get('reason',''))}")
                if fixed.get('verdict'):
                    print(f"Fixed verdict: {fixed['verdict']}; report: {fixed['report']}")
        else:
            print(dumps(result))
        return int(result.get('verdict')=='FAIL' or action=='doctor' and any(r['status']=='FAIL' for r in result['checks']) or result.get('code',0)!=0)
    except Exception as exc:
        print(dumps({'error':str(exc)[-400:]}),file=sys.stderr); return 2
if __name__=='__main__':
    sys.exit(main())
