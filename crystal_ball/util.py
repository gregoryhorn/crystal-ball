import contextlib, csv, difflib, hashlib, io, json, math, os, re, signal, subprocess, sys, tempfile, time, uuid
from pathlib import Path
from .cache import dumps, atomic, fingerprint
import traceback

def _python_env(extra=None):
    """Remove inherited interpreter selectors without changing this process."""
    env = {**os.environ, **(extra or {})}
    for key in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONUSERBASE',
                'PYTHONEXECUTABLE', 'VIRTUAL_ENV', '__PYVENV_LAUNCHER__',
                'PYTHONSAFEPATH', 'CONDA_PREFIX'):
        env.pop(key, None)
    env['PYTHONNOUSERSITE'] = '1'
    return env

def foreign_python_env(extra=None):
    """Give an engine its own stdlib and only our package import root."""
    env = _python_env(extra)
    env['PYTHONPATH'] = str(Path(__file__).resolve().parent.parent)
    return env

def same_python_env(extra=None):
    """A base executable may need paths injected into its running venv parent."""
    env = _python_env(extra)
    paths = [str(Path(__file__).resolve().parent.parent),
             *(os.path.abspath(p or os.curdir) for p in sys.path)]
    env['PYTHONPATH'] = os.pathsep.join(dict.fromkeys(paths))
    return env

def engine_python_env(python, extra=None):
    # Do not resolve symlinks: a venv's bin/python and its base are distinct runtimes.
    return (same_python_env if str(python)==sys.executable else foreign_python_env)(extra)

class StageError(RuntimeError):
    def __init__(self, stage, detail, log=None, summary=None):
        super().__init__(''.join(traceback.format_exception(detail)) if isinstance(detail, BaseException) else detail)
        self.stage = stage
        self.log = log
        self.summary = summary

def error_summary(exc, stage):
    if isinstance(exc, StageError) and exc.summary:
        return exc.summary[:240]
    if isinstance(exc, StageError):
        detail = str(exc).strip().splitlines()
        exceptions = [line for line in detail if re.match(r'^[A-Za-z_][\w.]*:', line)]
        final = exceptions[-1] if exceptions else f'RuntimeError: {detail[-1] if detail else "worker failed"}'
    else:
        final = f'{type(exc).__name__}: {exc}'
    final = ' '.join(final.split())
    return f'{getattr(exc, "stage", stage)}: {final}'[:240]

def error_result(exc, stage, cache_dir=None):
    """Keep compact failures in responses and complete tracebacks on disk."""
    if cache_dir is None:
        from .config import load
        try:
            cache_dir = load()['cache_dir']
        except Exception:
            cache_dir = os.environ.get('CRYSTAL_BALL_CACHE_DIR', '~/.cache/crystal-ball')
    path = Path(cache_dir).expanduser() / 'errors.log'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as log:
        log.write(f'\nStage: {getattr(exc, "stage", stage)}\n')
        log.write(''.join(traceback.format_exception(exc)))
    return {'status': 'error', 'stage': getattr(exc, 'stage', stage),
            'error': error_summary(exc, stage), 'log': str(path)}
STATUSES = {"PASS", "WARN", "FAIL", "SKIP"}
def row(id, status, summary, timestamps=None, fix=""):
    return {"id": str(id), "status": status, "summary": str(summary),
            "timestamps": timestamps or [], "fix": str(fix)}

def skip(stage, reason):
    return {"checks": [row(stage, "SKIP", reason)]}

def has_audio_stream(file, meta=None):
    if meta is None:
        meta = json.loads(command(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', file], 15))
    return any(stream.get('codec_type') == 'audio' for stream in meta['streams'])

def command(cmd, timeout=60, env=None):
    """Kill the whole stage's descendants at the outer deadline as well."""
    proc = subprocess.run([str(x) for x in cmd], capture_output=True, text=True,
                          timeout=timeout, env=env)
    if proc.returncode:
        raise StageError(Path(str(cmd[0])).name, proc.stderr or proc.stdout or f"exit {proc.returncode}")
    return proc.stdout

def process_json(cmd, timeout, env=None):
    proc = subprocess.Popen([str(x) for x in cmd], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True, env=env)
    try:
        out, err = proc.communicate(timeout=timeout)
    except BaseException:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise
    if proc.returncode:
        try:
            failure=json.loads(out)
            detail=failure.get('error')
        except (ValueError,AttributeError):
            failure={}; detail=None
        raise StageError(failure.get('stage', str(cmd[3]) if len(cmd)>3 else str(cmd[0])),
                         err or out or f"exit {proc.returncode}", failure.get('log'), detail)
    return json.loads(out)

def norm(text):
    return " ".join(re.findall(r"\w+", text.casefold()))

def spelling_checks(lines, expected, proper_only=False):
    checks = []
    for line in lines:
        original_words = re.findall(r"\w+", line["text"])
        words = [w.casefold() for w in original_words]
        for target in expected:
            wanted = norm(target)
            size = len(wanted.split())
            if not wanted:
                continue
            candidates = [" ".join(words[i:i+size]) for i in range(max(1, len(words)-size+1))
                          if not proper_only or any(w[0].isupper() for w in original_words[i:i+size])]
            for candidate in candidates:
                ratio = difflib.SequenceMatcher(None, wanted, candidate).ratio()
                if candidate != wanted and .79 <= ratio < 1 and min(len(wanted), len(candidate)) >= 4:
                    checks.append(row("ocr_spelling", "WARN", f'"{candidate}" vs expected "{target}" (OCR >=70)',
                                      [[line["time"], line["time"]]], "edit the source text and re-render"))
                    break
    return checks

def validate_checks(checks):
    if not isinstance(checks, list) or len(checks) > 100:
        raise ValueError("checks must be a list of at most 100 items")
    result = []
    for r in checks:
        if not isinstance(r, dict) or r.get("status") not in STATUSES:
            raise ValueError("invalid check status")
        for key in ("id", "summary", "fix"):
            if not isinstance(r.get(key), str):
                raise ValueError(f"invalid {key}")
        items = r.get("items", [])
        if not isinstance(items, list):
            raise ValueError("invalid items")
        times = []
        for item in items:
            start, end = item["t"], item.get("end", item["t"])
            if (isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, (int, float)) or
                    not isinstance(end, (int, float)) or not math.isfinite(start) or not math.isfinite(end) or not 0 <= start <= end):
                raise ValueError("invalid timestamp")
            times.append([start, end])
        result.append(row(r["id"], r["status"], r["summary"], times, r["fix"]))
    return result
