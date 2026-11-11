"""Isolated tool dispatcher: one compact JSON response."""
import json
import sys
from .api import dispatch, compact_action
from .cache import dumps
from .util import error_result

def main():
    action='tool'
    try:
        req=json.load(sys.stdin); action=req.pop('action')
        value=dispatch(action,**req)
        print(dumps(compact_action(action,value)))
    except Exception as exc:
        print(dumps(error_result(exc,action)))
    return 0
if __name__=='__main__':
    sys.exit(main())
