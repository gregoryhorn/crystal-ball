"""Private isolated stages; stdout is a single JSON object."""
import json, sys
from pathlib import Path
from . import core
from .cache import dumps

def main():
    try:
        stage, request = sys.argv[1:]
        req=json.loads(Path(request).read_text())
        fn={"signal":core.signal_stage,"review":core.review_stage,"ocr":core.ocr_stage,"vision":core.vision_stage,"audio":core.audio_stage}[stage]
        print(dumps(fn(req)))
    except Exception as exc:
        print(dumps({"error":f"{type(exc).__name__}: {exc}"[:400]}))
        return 2
    return 0
if __name__ == "__main__":
    sys.exit(main())
