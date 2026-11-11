"""Isolated tool dispatcher: one compact JSON response."""
import json
import sys
from .api import dispatch, compact_action
from .cache import dumps

def main():
    try:
        req=json.load(sys.stdin); action=req.pop('action')
        value=dispatch(action,**req)
        print(dumps(compact_action(action,value)))
    except Exception as exc:
        print(dumps({'status':'error','error':str(exc)[:220]}))
    return 0
if __name__=='__main__':
    sys.exit(main())
