#!/usr/bin/env python
"""Local CLIP footage search. Index video/image frames, query by text or reference image.

Indexes live in the configured cache, never beside the footage. Local only.
"""
import argparse, hashlib, json, os, subprocess, sys, tempfile, shutil, re, time, uuid, math

from ..config import load
from ..cache import fingerprint, Store
from ..platforms.process import run_owned
from ..platforms.locks import replace
from pathlib import Path
CACHE = str(Path(load()["cache_dir"]) / "indexes")
VIDEO = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts", ".mxf"}
HEIF = {".heic", ".heif"}
IMAGE = {".jpg", ".jpeg", ".png", ".webp", ".bmp"} | HEIF
MODELS = {"base": "openai/clip-vit-base-patch32", "large": "openai/clip-vit-large-patch14"}
MIN_FREE_MB = 2500


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def model_id(name):
    return MODELS.get(name, name)


def key_for(root):
    root = os.path.realpath(root)
    return hashlib.sha1(root.encode()).hexdigest()[:10] + "-" + re.sub(r"[^A-Za-z0-9]+", "_", os.path.basename(root))[:40], root


def collect(paths):
    """-> {root: [files]}. A dir is its own root; a loose file's root is its parent dir."""
    out = {}
    for p in paths:
        p = os.path.realpath(p)
        if os.path.isdir(p):
            out.setdefault(p, [])
            for d, dirs, files in os.walk(p):
                dirs[:] = [x for x in dirs if not x.startswith(".")]
                for f in sorted(files):
                    if os.path.splitext(f)[1].lower() in VIDEO | IMAGE and not f.startswith("."):
                        out.setdefault(p, []).append(os.path.join(d, f))
        elif os.path.isfile(p):
            out.setdefault(os.path.dirname(p), []).append(p)
        else:
            log("skip (not found):", p)
    return out


ENGINE_INFO={}


_session = None
_owned_models = []


def device():
    """Acquire before model load; the command retains authority until cleanup."""
    global _session
    from ..gpu import Session
    if _session is None:
        cfg = load()['see']
        _session = Session(cfg['min_free_vram_gb'], purpose='CLIP embeddings', model='clip', enabled=cfg['device']=='cuda')
        if _session.device == 'cuda':
            import torch
            if not torch.cuda.is_available():
                cleanup_reason = _session.close(lambda: None)
                _session.device = 'cpu'
                _session.reason = 'CUDA unavailable; CPU selected'
                if cleanup_reason and 'lease retained' in cleanup_reason:
                    _session.reason += '; ' + cleanup_reason
    ENGINE_INFO.update(engine='clip-'+_session.device, fallback_reason=_session.reason)
    return _session.device


def close_models():
    """Drop only this command's CUDA references, then validate broker completion."""
    global _session
    if _session is None:
        return
    def cleanup():
        import gc
        import torch
        torch.cuda.synchronize()
        for model in _owned_models:
            model.to('cpu')
        _owned_models.clear()
        gc.collect()
        torch.cuda.empty_cache()
    reason = _session.close(cleanup)
    _owned_models.clear()
    _session = None
    if reason and 'lease retained' in reason:
        ENGINE_INFO['cleanup_reason'] = reason
        log(reason)


def model_work(fn):
    """Bound lazy model load and every return/error to one owned lifetime."""
    from functools import wraps
    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        finally:
            close_models()
    return wrapped


def load_model(name):
    import torch
    from transformers import CLIPModel, CLIPProcessor
    from ..gpu import is_oom
    torch.set_num_threads(load()['see']['cpu_threads'])
    dev = device()
    mid = model_id(name)
    try:
        model = CLIPModel.from_pretrained(mid, local_files_only=True, torch_dtype=torch.float16 if dev == 'cuda' else torch.float32)
        if dev == 'cuda':
            _owned_models.append(model)
        model = model.to(dev).eval()
    except Exception as exc:
        if dev!='cuda' or not is_oom(exc):
            raise
        for owned in _owned_models:
            owned.to('cpu')
        _owned_models.clear()
        torch.cuda.empty_cache()
        dev='cpu'
        ENGINE_INFO.update(engine='clip-cpu',fallback_reason='CUDA out of memory at load; retry on CPU')
        model=CLIPModel.from_pretrained(mid,local_files_only=True,torch_dtype=torch.float32).eval()
    return model, CLIPProcessor.from_pretrained(mid, local_files_only=True), dev


def cpu_retry(fn):
    """Retry a failed CUDA inference once, retaining the model on CPU afterwards."""
    def wrapped(model,proc,dev,*args,**kwargs):
        from ..gpu import is_oom
        if str(getattr(model,'device',''))=='cpu':
            dev='cpu'
        try:
            return fn(model,proc,dev,*args,**kwargs)
        except Exception as exc:
            if dev!='cuda' or not is_oom(exc):
                raise
            model.to('cpu').float()
            import torch
            torch.cuda.empty_cache()
            ENGINE_INFO.update(engine='clip-cpu',fallback_reason='CUDA out of memory at inference; retry on CPU')
            return fn(model,proc,'cpu',*args,**kwargs)
    return wrapped

@cpu_retry
def embed_images(model, proc, dev, paths, bs=32):
    import torch
    from PIL import Image
    outs = []
    for i in range(0, len(paths), bs):
        ims = []
        for p in paths[i:i + bs]:
            if Path(p).suffix.lower() in HEIF:
                import pillow_heif
                pillow_heif.register_heif_opener()
            with Image.open(p) as im:
                ims.append(im.convert("RGB"))
        px = proc(images=ims, return_tensors="pt")["pixel_values"].to(dev, model.dtype)
        with torch.no_grad():
            f = model.get_image_features(pixel_values=px).float()
        outs.append(torch.nn.functional.normalize(f, dim=-1).cpu())
    import numpy as np
    return np.concatenate([o.numpy() for o in outs]) if outs else np.zeros((0, model.config.projection_dim), "float32")


@cpu_retry
def embed_text(model, proc, dev, text):
    import torch
    t = proc(text=[text], return_tensors="pt", padding=True, truncation=True, max_length=77).to(dev)
    with torch.no_grad():
        f = model.get_text_features(**t).float()
    return torch.nn.functional.normalize(f, dim=-1).cpu().numpy()[0]


def duration(path):
    r = run_owned(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def extract(path, outdir, every, cap, mode):
    """-> [(timestamp, jpg path)] for a video."""
    dur = duration(path)
    if dur <= 0:
        return []
    every = max(every, dur / cap)
    pat = os.path.join(outdir, "f_%05d.jpg")
    scale = "scale=-2:336"
    if mode == "scene":
        vf = f"select='eq(n,0)+gt(scene,0.3)',showinfo,{scale}"
        r = run_owned(["ffmpeg", "-nostdin", "-v", "info", "-i", path, "-an", "-vf", vf, "-vsync", "vfr",
                            "-q:v", "3", pat], capture_output=True, text=True)
        ts = [float(m) for m in re.findall(r"pts_time:([0-9.]+)", r.stderr)]
        files = sorted(f for f in os.listdir(outdir) if f.startswith("f_"))
        pairs = list(zip(ts, [os.path.join(outdir, f) for f in files]))
        if len(pairs) > cap:  # thin evenly
            step = len(pairs) / cap
            pairs = [pairs[int(i * step)] for i in range(cap)]
        return pairs
    vf = f"fps=1/{every:.3f},{scale}"
    run_owned(["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-an", "-vf", vf, "-q:v", "3", pat])
    files = sorted(f for f in os.listdir(outdir) if f.startswith("f_"))
    return [(round(i * every, 2), os.path.join(outdir, f)) for i, f in enumerate(files)][:cap]


def load_index(idir):
    import numpy as np
    mp = os.path.join(idir, "meta.json")
    if not os.path.exists(mp):
        return None
    with open(mp, encoding='utf-8') as f:
        meta = json.load(f)
    meta["emb"] = np.load(os.path.join(idir, meta.get("emb_file", "emb.npy")))
    return meta


def save_index(idir, meta, emb):
    import numpy as np
    os.makedirs(idir, exist_ok=True)
    # Metadata is the commit pointer; never overwrite the generation it references.
    generation = uuid.uuid4().hex
    emb_name = f"emb-{generation}.npy"
    ep = os.path.join(idir, emb_name)
    mp = os.path.join(idir, f"meta-{generation}.tmp")
    etmp = ep + ".tmp"
    try:
        with open(etmp, "wb") as f:
            np.save(f, emb.astype("float32"))
            f.flush(); os.fsync(f.fileno())
        replace(etmp, ep)
        with open(mp, "w", encoding='utf-8') as f:
            json.dump({**meta, "emb_file": emb_name}, f)
            f.flush(); os.fsync(f.fileno())
        replace(mp, os.path.join(idir, "meta.json"))
    finally:
        for p in (etmp, mp):
            if os.path.exists(p):
                os.remove(p)


@model_work
def cmd_index(a):
    import numpy as np
    if a.cap <= 0 or not math.isfinite(a.every) or a.every <= 0:
        log("--cap and --every must be positive (and --every finite)")
        return 2
    scanned_dirs = {os.path.realpath(p) for p in a.paths if os.path.isdir(p)}
    groups = collect(a.paths)
    if not groups:
        log("no videos or images found")
        return 1
    mid = model_id(a.model)
    model = proc = dev = None
    for root, files in groups.items():
        key, root = key_for(root)
        idir = os.path.join(CACHE, key)
        old = load_index(idir)
        previous = old
        if old and old.get("model") != mid:
            if root not in scanned_dirs:
                log(f"{root}: model changed; scan the full directory to rebuild without losing sibling entries")
                return 2
            log(f"{root}: model changed, rebuilding")
            old = None
        keep_rows, entries, frames = [], {}, []
        selected = set(files)
        if old:
            for f, e in old["files"].items():
                if root not in scanned_dirs and f not in selected:
                    entries[f] = e
                elif f in selected:
                    try:
                        st = os.stat(f)
                    except OSError as ex:
                        log("  cannot stat file", f, ex)
                        continue
                    if fingerprint(f) == e.get("identity") \
                            and e.get("sampling_options") == getattr(a,"sampling_options",None) \
                            and e.get("every") == a.every and e.get("mode") == a.mode and e.get("cap") == a.cap:
                        entries[f] = e
            for i, fr in enumerate(old["frames"]):
                if fr["file"] in entries:
                    keep_rows.append(i)
                    frames.append(fr)
        emb_parts = [old["emb"][keep_rows]] if old and keep_rows else []
        todo = [f for f in files if f not in entries]
        log(f"{root}: {len(files)} files, {len(entries)} unchanged, {len(todo)} to index -> {idir}")
        tdir = os.path.join(idir, "thumbs")
        os.makedirs(tdir, exist_ok=True)
        t0 = time.time()
        for n, f in enumerate(todo, 1):
            try:
                result = index_file(f, a, tdir, model, proc, dev)
                if result is None:
                    continue
                new_frames, e, entry, (model, proc, dev) = result
                frames.extend(new_frames)
                emb_parts.append(e)
                entries[f] = entry
            except OSError as ex:
                log("  skip file", f, ex)
                continue
            if n % 10 == 0:
                log(f"  {n}/{len(todo)} files ({time.time()-t0:.0f}s)")
        if emb_parts:
            emb = np.concatenate(emb_parts)
        else:
            if model is None:
                model, proc, dev = load_model(a.model)
            emb = np.zeros((0, model.config.projection_dim), "float32")
        save_index(idir, {"root": root, "model": mid, "files": entries, "frames": frames}, emb)
        # Only remove obsolete thumbnails after the new metadata is committed.
        live = {fr["thumb"] for fr in frames}
        for fr in previous["frames"] if previous else []:
            if fr["thumb"] not in live:
                try:
                    os.remove(fr["thumb"])
                except OSError as ex:
                    log("  cannot remove thumbnail", fr["thumb"], ex)
        log(f"  done: {len(frames)} frames from {len(entries)} files in {time.time()-t0:.0f}s")
    return 0


def index_file(f, a, tdir, model, proc, dev):
    st = os.stat(f)
    identity = fingerprint(f)
    # Fresh names also protect committed thumbnails during resampling/retries.
    h = uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="fs_") as tmp:
        ext = os.path.splitext(f)[1].lower()
        if ext in IMAGE:
            if ext in HEIF:
                try:
                    import pillow_heif
                except ImportError:
                    log("  skip HEIC/HEIF (pillow_heif decoder unavailable):", f)
                    return None
                pillow_heif.register_heif_opener()
            from PIL import Image
            try:
                with Image.open(f) as im:
                    im = im.convert("RGB")
                    im.thumbnail((600, 336))
                    im.save(os.path.join(tmp, "f_00000.jpg"), quality=88)
            except Exception as ex:
                log("  skip image", f, ex)
                return None
            pairs = [(0.0, os.path.join(tmp, "f_00000.jpg"))]
        else:
            if a.mode=='shot':
                from .scenes import detect_scenes, shot_frames
                cfg=load()
                pairs=shot_frames(detect_scenes(f,cfg),getattr(a,'frames_per_shot',1),cfg)
            else:
                pairs = extract(f, tmp, a.every, a.cap, a.mode)
        if not pairs:
            log("  no frames:", f)
            return None
        if model is None:
            model, proc, dev = load_model(a.model)
            log("  model", model_id(a.model), "on", dev)
        if getattr(a,"shared",False):
            import numpy as np
            if ext in IMAGE:
                e=np.asarray([image_embedding(f,model,proc,dev,a.model)],dtype='float32')
            else:
                options={"model":model_id(a.model),"frames":[p for _,p in pairs]}
                value=Store().get(f,"embeddings",options,lambda directory: {"vectors":embed_images(model,proc,dev,[p for _,p in pairs]).tolist()})
                e=np.asarray(value["vectors"],dtype="float32")
        else:
            e = embed_images(model, proc, dev, [p for _, p in pairs])
        frames = []
        for i, (t, p) in enumerate(pairs):
            dst = os.path.join(tdir, f"{h}_{i:05d}.jpg")
            shutil.copyfile(p, dst)
            frames.append({"file": f, "t": t, "thumb": dst})
        if fingerprint(f) != identity:
            raise OSError("source changed during indexing")
        entry = {"identity": identity, "mtime_ns": st.st_mtime_ns, "size": st.st_size, "every": a.every,
                 "mode": a.mode, "cap": a.cap, "sampling_options":getattr(a,"sampling_options",None), "frames": len(pairs), "thumb_hash": h}
        return frames, e, entry, (model, proc, dev)


@model_work
def cmd_query(a):
    import numpy as np
    mid = model_id(a.model)
    idxs = []
    if os.path.isdir(CACHE):
        for k in sorted(os.listdir(CACHE)):
            m = load_index(os.path.join(CACHE, k))
            if not m or m["model"] != mid or not m["frames"] or m["emb"].shape[0] == 0:
                continue
            if a.dir and not any(within(m["root"],d) or
                                 within(d,m["root"]) for d in a.dir):
                continue
            idxs.append(m)
    if not idxs:
        log("no matching index; run: crystal-ball index <dir> (model %s)" % a.model)
        return 1
    model, proc, dev = load_model(a.model)
    if a.image:
        q = image_embedding(a.image,model,proc,dev,a.model)
    elif a.text:
        q = embed_text(model, proc, dev, a.text)
    else:
        log("give text or --image"); return 2
    rows = []
    for m in idxs:
        s = m["emb"] @ q
        for i in np.argsort(-s):
            fr = m["frames"][i]
            if a.dir and not any(within(fr["file"],d) for d in a.dir):
                continue
            rows.append((float(s[i]), fr))
    rows.sort(key=lambda r: -r[0])
    out, seen = [], []
    for s, fr in rows:  # de-dupe near-adjacent hits from the same file
        if any(fr["file"] == f and abs(fr["t"] - t) < a.gap for f, t in seen):
            continue
        seen.append((fr["file"], fr["t"]))
        out.append({"file": fr["file"], "timestamp": fr["t"], "score": round(s, 4), "thumbnail": fr["thumb"]})
        if len(out) >= a.top:
            break
    if a.json:
        print(json.dumps(out, indent=1))
    else:
        for i, r in enumerate(out, 1):
            print(f"{i:2d}. {r['score']:.3f}  {r['file']} @ {r['timestamp']:.1f}s\n      thumb: {r['thumbnail']}")
    return 0


def within(path,directory):
    return Path(path).resolve().is_relative_to(Path(directory).resolve())

def odd_shot_out(embeddings,frames=None,threshold=0.4):
    """Rank interior frames by cosine distance from their two neighbours.

    Distinct shots can be intentional; this is a review hint, never a failure.
    """
    import numpy as np
    e=np.asarray(embeddings,dtype="float32")
    if len(e)<3:
        return []
    e=e/np.maximum(np.linalg.norm(e,axis=1,keepdims=True),1e-12)
    rows=[]
    for i in range(1,len(e)-1):
        distance=float(1-(e[i]@e[i-1]+e[i]@e[i+1])/2)
        if distance>=threshold:
            rows.append({"index":i,"distance":round(distance,4),"frame":frames[i] if frames else None,"status":"WARN"})
    return sorted(rows,key=lambda r:-r["distance"])


def image_embedding(file,model,processor,dev,name):
    """Share the source-image vector between indexing and reference-image searches."""
    import numpy as np
    options={'model':model_id(name),'revision':getattr(model.config,'_commit_hash',None),'version':1}
    value=Store().get(file,'clip-image',options,lambda directory: {'vector':embed_images(model,processor,dev,[file])[0].tolist()})
    return np.asarray(value['vector'],dtype='float32')
