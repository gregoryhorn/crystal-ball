import contextlib, csv, difflib, hashlib, io, json, math, os, re, signal, subprocess, sys, tempfile, time, uuid
from pathlib import Path
from .cache import dumps, atomic, fingerprint
STATUSES = {"PASS", "WARN", "FAIL", "SKIP"}
def row(id, status, summary, timestamps=None, fix=""):
    return {"id": str(id), "status": status, "summary": str(summary),
            "timestamps": timestamps or [], "fix": str(fix)}

def skip(stage, reason):
    return {"checks": [row(stage, "SKIP", reason)]}

def command(cmd, timeout=60, env=None):
    """Kill the whole stage's descendants at the outer deadline as well."""
    proc = subprocess.run([str(x) for x in cmd], capture_output=True, text=True,
                          timeout=timeout, env=env)
    if proc.returncode:
        raise RuntimeError((proc.stderr or proc.stdout or f"exit {proc.returncode}")[-500:])
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
            detail=json.loads(out).get('error')
        except (ValueError,AttributeError):
            detail=None
        raise RuntimeError((detail or err or out or f"exit {proc.returncode}")[-400:])
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
