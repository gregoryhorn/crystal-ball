import contextlib, csv, difflib, hashlib, io, json, math, os, re, signal, subprocess, sys, tempfile, time, uuid
from pathlib import Path
from .cache import dumps, atomic, fingerprint
import traceback
import unicodedata

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

def _spelling_token(raw):
    """Return normalized text, script, case and letter count; None is a barrier."""
    text=unicodedata.normalize('NFC',raw).strip('\"\'‘’“”()[]{}.,:;?!،؛؟')
    scripts=set(); letters=0
    for i,char in enumerate(text):
        category=unicodedata.category(char)
        if category.startswith('L'):
            name=unicodedata.name(char,'')
            script='Latin' if 'LATIN' in name else 'Arabic' if 'ARABIC' in name else None
            if script is None:
                return None
            scripts.add(script); letters+=1
        elif category.startswith('M'):
            if not i or not unicodedata.category(text[i-1]).startswith(('L','M')):
                return None
        elif char in "'-’":
            previous=i-1
            while previous>=0 and unicodedata.category(text[previous]).startswith('M'):
                previous-=1
            if previous<0 or not unicodedata.category(text[previous]).startswith('L') or i+1==len(text) or not unicodedata.category(text[i+1]).startswith('L'):
                return None
        else:
            return None
    if len(scripts)!=1:
        return None
    return (unicodedata.normalize('NFC',text.casefold()),scripts.pop(),text[0].isupper(),letters)

def _spelling_tokens(text):
    tokens=[_spelling_token(w) for w in text.split()]
    return [t for t in tokens if t is not None] if all(t is not None for t in tokens) else []

def _spelling_window(wanted, candidate, proper_only):
    if any(token is None for token in candidate) or (proper_only and not any(t[2] for t in candidate)):
        return False
    for target,word in zip(wanted,candidate):
        if target[1]!=word[1]:
            return False
        if target[0]!=word[0]:
            if min(target[3],word[3])<4:
                return False
            if target[3]-word[3]>=2 and (target[0].startswith(word[0]) or target[0].endswith(word[0])):
                return False
    return True

def _spelling_evidence(value, minimum, maximum=math.inf):
    return (not isinstance(value,bool) and isinstance(value,(int,float)) and
            minimum<=value<=maximum and (isinstance(value,int) or math.isfinite(value)))

def spelling_checks(lines, expected, proper_only=False):
    targets={}
    for target in expected:
        tokens=_spelling_tokens(target)
        if tokens:
            targets.setdefault(' '.join(t[0] for t in tokens),(target,tokens))
    matches={}
    for line in lines:
        if not _spelling_evidence(line.get('confidence'),70,100) or not _spelling_evidence(line.get('time'),0):
            continue
        words=[_spelling_token(w) for w in line['text'].split()]
        for wanted,(target,tokens) in targets.items():
            size=len(tokens)
            for i in range(len(words)-size+1):
                window=words[i:i+size]
                if not _spelling_window(tokens,window,proper_only):
                    continue
                candidate=' '.join(t[0] for t in window if t is not None)
                ratio=difflib.SequenceMatcher(None,wanted,candidate).ratio()
                if min(len(wanted),len(candidate))>=4 and .79<=ratio<1:
                    matches.setdefault((wanted,candidate),set()).add(line['time'])
    checks=[]
    for (wanted,candidate),times in sorted(matches.items()):
        if len(times)>=2:
            target=targets[wanted][0]
            checks.append(row('ocr_spelling','WARN',
                              f'Possible spelling: "{candidate}" vs expected "{target}" (similarity >=79%, OCR confidence >=70, >=2 sampled frames)',
                              [[t,t] for t in sorted(times)],
                              'inspect the timestamped frames and source text; correct and re-render if confirmed'))
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
