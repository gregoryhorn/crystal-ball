"""Private isolated stages; stdout is a single JSON object."""
import json, sys
from pathlib import Path
from . import core
from .cache import dumps
from .util import error_result

def main():
    stage='stage'; req={}
    try:
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
