"""Private isolated stages; stdout is a single JSON object."""
import json, os, sys
from pathlib import Path
from . import core
from .cache import dumps
from .util import error_result

def main():
    stage='stage'; req={}
    try:
        if len(sys.argv)==1:
            # Nested engines share this worker's process group and outer deadline.
            os.environ['CRYSTAL_BALL_STAGE']='1'
            payload=json.load(sys.stdin)
            stage=payload['operation']; req=payload['request']
            if stage=='visual':
                from .visual import _scan
                value=_scan(req['file'],req['config'])
            elif stage=='voice_balance':
                from .senses.hear import _voice_balance
                value=_voice_balance(req['file'],req['transcript'],req['config'])
            elif stage=='read_text':
                from .senses.read import _read_text
                value=_read_text(req['file'],req.get('at'),req['config'])
            else:
                raise ValueError('unknown media operation')
            print(dumps(value))
            return 0
        stage, request = sys.argv[1:]
        req=json.loads(Path(request).read_text())
        from .editing import edit_stage
        fn={"signal":core.signal_stage,"review":core.review_stage,"ocr":core.ocr_stage,"vision":core.vision_stage,"audio":core.audio_stage,"editing":edit_stage}[stage]
        print(dumps(fn(req)))
    except Exception as exc:
        print(dumps(error_result(exc,stage,req.get('cache_dir'))))
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 2
    return 0
if __name__ == "__main__":
    sys.exit(main())
