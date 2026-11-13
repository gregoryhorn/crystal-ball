import contextlib, csv, difflib, hashlib, io, json, math, os, re, signal, subprocess, sys, tempfile, time, uuid
from pathlib import Path
import concurrent.futures as futures
from .config import load, rules_for
from .cache import dumps, atomic, fingerprint, Store, runtime_stamp
from .checks import SCRIPTS, load_qc, platforms
from .util import row, skip, command, process_json, norm, spelling_checks, validate_checks, engine_python_env, error_result
from .frames import probe, caption_times, review_stage as _review_stage
from .report import write_report
from .senses.read import ocr_stage, confirm_safe_zones
from .senses.judge import vision_stage, crosscheck_vision
from .senses.hear import audio_stage
from .fix import apply_fix
from .platforms.runtime import core_media_python
VERSION = "1.2.0"
MAX_BYTES = 1500
TIMEOUTS = {"signal":180,"review":120,"ocr":120,"audio":300,"vision":100,"editing":600}
CACHE = None

def review_stage(req):
    if req.get('meta', {}).get('media_kind') == 'image':
        from .applicability import image_review
        return image_review(req)
    cfg=req.get("config") or load()
    options={"captions":fingerprint(req["captions"]) if req.get("captions") else None,"version":VERSION,
             "scenes":cfg["scenes"],"runtime":runtime_stamp(cfg)}
    def produce(directory):
        value=_review_stage({**req,"run_dir":str(directory)})
        value["artifact_paths"]=[f["path"] for f in value["frames"]]+[value["contact_sheet"]]
        return value
    return Store(req.get("cache_dir")).get(req["file"],"frames",options,produce)

def run_stage(stage, request, timeout=None):
    try:
        request_path=Path(request["run_dir"])/f"{stage}-request.json"
        atomic(request_path,dumps(request))
        cfg=request.get('config') or load()
        python=core_media_python(cfg) if stage in {'review','ocr','editing'} or stage == 'signal' and request.get('meta',{}).get('media_kind') == 'image' else sys.executable
        env=engine_python_env(python,{"OMP_THREAD_LIMIT":"1","OPENBLAS_NUM_THREADS":"1","HF_HUB_OFFLINE":"1","CRYSTAL_BALL_STAGE":"1"})
        value=process_json([python,"-m","crystal_ball.stage_worker",stage,request_path],timeout or TIMEOUTS[stage],env)
        if not isinstance(value,dict) or "error" in value:
            raise ValueError(str(value.get("error","invalid stage object")))
        return value
    except Exception as exc:
        failure=error_result(exc,stage,request.get('cache_dir'))
        return {**skip(stage,failure['error']), 'log':failure['log']}

def signal_stage(req):
    from .media_signal import signal
    return signal(req)

def compact(doc, cached=False):
    checks = doc["checks"]
    counts = {status: sum(r["status"] == status for r in checks) for status in ("PASS", "WARN", "FAIL", "SKIP")}
    incomplete = any(r["status"] == "SKIP" and r["id"] not in {"caption zone", "continuous_review"} for r in checks)
    verdict = "FAIL" if counts["FAIL"] else "WARN" if counts["WARN"] or incomplete else "PASS"
    issues = [{**r,"timestamps":list(r["timestamps"])} for r in checks if r["status"] != "PASS"]
    issues.sort(key=lambda r: (r["status"] != "FAIL", r["id"]))
    # Merge repeating frame findings while retaining every finding in the full report.
    grouped = {}
    for r in issues:
        key = (r["id"], r["status"], r["summary"])
        if key in grouped:
            grouped[key]["timestamps"] += r["timestamps"]
        else:
            grouped[key] = r
    issues = list(grouped.values())
    for r in issues:
        r["summary"] = r["summary"][:140]
        r["fix"] = r["fix"][:160]
        r["timestamps"] = r["timestamps"][:6]
    result = {"verdict": verdict, "cached": cached, "platform": doc["platform"],
              "inference": doc.get("inference"), "counts": counts, "items": issues,
              "not_checked": [f"{r['id']}: {r['summary']}"[:140] for r in checks if r["status"] == "SKIP"],
              "not_checked_omitted_count": 0,
              "report": doc["report"], "review_frames": doc["frames_dir"]}
    logs = sorted({stage['log'] for stage in doc.get('stages', {}).values() if stage.get('log')})
    if logs:
        result['log'] = logs[0]
    return fit_compact(result)

def fit_compact(result):
    """Spend the budget on every non-PASS identity before optional details."""

    result['omitted_details']=result.get('omitted_details',0)
    result['not_checked_omitted_count']=result.get('not_checked_omitted_count',0)
    if result['not_checked_omitted_count']>0:
        result['more_not_checked_in_report']=True
    else:
        result.pop('more_not_checked_in_report',None)
    for limit in (80,40):
        if len(dumps(result).encode())<=MAX_BYTES:
            return result
        for item in result['items']:
            if 'summary' in item:
                item['summary']=item['summary'][:limit]
                item['fix']=item.get('fix','')[:limit]
                item['timestamps']=item.get('timestamps',[])[:2]
    # not_checked is a compatibility detail list; SKIP identities also live in items.
    while len(dumps(result).encode())>MAX_BYTES and result['not_checked']:
        result['not_checked'].pop()
        result['not_checked_omitted_count']+=1
        result['more_not_checked_in_report']=True
    for index in range(len(result['items'])-1,-1,-1):
        if len(dumps(result).encode())<=MAX_BYTES:
            return result
        item=result['items'][index]
        if 'summary' in item:
            result['items'][index]={k:item[k] for k in ('id','status')}
            result['omitted_details']+=1
    # Multiple findings may share an identity; keep that identity once when details go.
    unique=[]
    for item in result['items']:
        if item not in unique:
            unique.append(item)
    result['items']=unique
    for key in ('inference','review_frames','log','platform','cached'):
        if len(dumps(result).encode())<=MAX_BYTES:
            break
        result.pop(key,None)
    if len(dumps(result).encode())>MAX_BYTES:
        raise ValueError('compact result exceeds byte budget: mandatory identities, paths and metadata retained')
    return result

def _base_check(file, platform=None, captions=None, script=None, brief=None, expect_text=None, mode="quick", force=False, beat_led=False, shape=None):
    from .applicability import SHAPES, omitted, normalize_skips
    if shape is not None and shape not in SHAPES:
        raise ValueError('shape must be 9:16, 16:9 or 1:1')
    cfg = load()
    path = Path(file).expanduser().resolve()
    if not path.is_absolute() or not path.is_file():
        raise ValueError("file must be an existing absolute path")
    path = path.resolve()
    if mode not in {"quick", "full"}:
        raise ValueError("mode must be quick or full")
    if expect_text is not None and (not isinstance(expect_text, list) or any(not isinstance(t, str) for t in expect_text)):
        raise ValueError("expect_text must be a list of strings")
    if brief is not None and not isinstance(brief, str):
        raise ValueError("brief must be text")
    deps = {}
    for key, value in (("captions", captions), ("script", script)):
        if value:
            if not Path(value).is_absolute() or not Path(value).is_file():
                raise ValueError(f"{key} must be an existing absolute path")
            deps[key] = fingerprint(value)
    if captions and Path(captions).suffix.lower() not in {".ass", ".srt"}:
        raise ValueError("captions must be .ass or .srt")
    rules = rules_for(path, cfg)
    identity = fingerprint(path)
    params = dict(platform=platform, captions=captions, script=script, brief=brief, expect_text=expect_text or [], mode=mode, beat_led=beat_led, shape=shape)
    # Include relevant code/data dependencies so installing audio/Arabic cannot leave stale SKIPs.
    dependencies = {"config":cfg, "engines":runtime_stamp(cfg), "code":[fingerprint(p) for p in Path(__file__).parent.rglob("*.py")]}
    key = hashlib.sha1(dumps([identity, params, VERSION, deps, rules["deps"], dependencies]).encode()).hexdigest()
    entry = Path(CACHE or cfg["cache_dir"]) / "results" / key
    cached_path = entry / "result.json"
    if not force and cached_path.exists():
        try:
            doc = json.loads(cached_path.read_text(encoding='utf-8'))
            if Path(doc["report"]).is_file():
                return compact(doc, True), doc
        except (OSError, ValueError, KeyError):
            pass
    try:
        meta = probe(path)
    except Exception as exc:
        # A corrupt/unprobeable file still gets a human report and a SKIP reason.
        run_dir = entry / uuid.uuid4().hex[:10]
        frames_dir = run_dir / "frames"
        frames_dir.mkdir(parents=True)
        failure=error_result(exc,'probe',cfg['cache_dir'])
        supported = path.suffix.lower() in {'.png','.jpg','.jpeg','.webp','.bmp','.tif','.tiff','.wav','.mp3','.flac','.ogg','.m4a','.mp4','.mov','.mkv','.webm','.avi'}
        unavailable = isinstance(exc, (FileNotFoundError, ModuleNotFoundError, subprocess.TimeoutExpired))
        if supported and not unavailable:
            stage = {'checks': [row('decode','FAIL',failure['error']), omitted('dependent analysis','decode failed; dependent analysis unavailable','dependency_failed')], 'log':failure['log']}
        else:
            stage = {'checks': [omitted('probe',failure['error'] if unavailable else 'unsupported media kind','unavailable' if unavailable else 'not_applicable')], 'log':failure['log']}
            stage['checks'].append(omitted('decode', 'no completed applicable decode check', 'dependency_failed'))
        doc = {"version": VERSION, "file": str(path), "identity": identity, "platform": platform or "unknown",
               "inference": "unavailable: could not probe media", "checks": stage["checks"],
               "stages": {"probe": stage}, "frames_dir": str(frames_dir)}
        doc["report"] = write_report(doc, run_dir)
        atomic(run_dir / "full.json", dumps(doc))
        atomic(cached_path, dumps(doc))
        return compact(doc), doc
    platform_defs = platforms()
    inference = None
    kind = meta.get('media_kind', 'video')
    if kind not in {'video', 'video-without-audio'}:
        platform = 'custom'
    if not platform:
        aspect = meta["width"] / meta["height"]
        if abs(aspect - 9/16) < .06:
            platform, inference = "shorts", "9:16 -> shorts (reels also possible)"
        elif abs(aspect - 16/9) < .1:
            platform, inference = "youtube", "16:9 -> youtube"
        else:
            platform, inference = "custom", f"{meta['width']}:{meta['height']} -> custom; destination unknown"
    platform = platform_defs.resolve(platform)
    if platform not in platform_defs.PLATFORMS:
        raise ValueError(f"unknown platform: {platform}")
    run_dir = entry / uuid.uuid4().hex[:10]
    run_dir.mkdir(parents=True)
    request = {**params, "file": str(path), "platform": platform, "meta": meta,
               "rules": rules, "run_dir": str(run_dir), "cache_dir": cfg["cache_dir"], "config":cfg}
    stages = applicable_stages(request, run_stage)
    normalize_skips(stages)
    checks = [r for stage in stages.values() for r in stage.get("checks", [])]
    if not any(r['id'] == 'decode' and r['status'] == 'PASS' for r in checks) and not any(r['status'] == 'FAIL' for r in checks):
        checks.append(omitted('decode', 'no completed applicable decode check', 'dependency_failed'))
    if fingerprint(path) != identity:
        checks.append(omitted('source_changed', 'media changed during QC; retry', 'dependency_failed'))
    if kind in {'video', 'video-without-audio'}:
        checks.append(omitted('continuous_review', 'vision/OCR sample frames; continuous motion and listening not checked', 'unavailable'))
    doc = {"version": VERSION, "file": str(path), "identity": identity, "platform": platform,
           "media_kind": kind, "inference": inference, "checks": checks, "stages": stages,
           "frames_dir": stages.get('review', {}).get('frames_dir', str(run_dir/'frames'))}
    doc['report'] = write_report(doc, run_dir)
    atomic(run_dir/'full.json', dumps(doc))
    if not any(r['id'] == 'source_changed' for r in checks):
        atomic(cached_path, dumps(doc))
    return compact(doc), doc

def applicable_stages(request, runner):
    from .routing import dispatch_stages
    return dispatch_stages(request, runner)


def quality_check(file, platform=None, captions=None, script=None, brief=None, expect_text=None, mode="quick", fix=False, force=False, beat_led=False, shape=None):
    result, doc = _base_check(file, platform, captions, script, brief, expect_text, mode, force, beat_led, shape)
    if fix:
        fixed = apply_fix(doc, force, config=load())
        # Full commands belong in the human report, not in the model's context.
        atomic(Path(doc["report"]).with_name("fix.json"), dumps(fixed))
        result["fix"] = {k: v for k, v in fixed.items() if k != "commands"}
        if fixed["status"] == "written":
            checked, _ = _base_check(fixed["file"], platform, captions, script, brief, expect_text, mode, False, beat_led, shape)
            result["fix"].update(verdict=checked["verdict"], counts=checked["counts"], report=checked["report"])
        # Refit details around the fix result while preserving all finding identities.
        fit_compact(result)
    return result
