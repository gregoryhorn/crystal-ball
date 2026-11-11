import contextlib, csv, difflib, hashlib, io, json, math, os, re, signal, subprocess, sys, tempfile, time, uuid
from pathlib import Path
import shlex
import itertools
import threading
import concurrent.futures as futures
from .core import quality_check
from .frames import probe
from .config import load
HOME=Path(os.environ.get("HERMES_HOME","~/.hermes")).expanduser()
VIDEO={".mp4",".mov",".webm",".mkv",".m4v",".avi",".mxf"}
def scoped():
    return True
def candidate_paths(args, result="", cwd=None):
    """Cheap extraction only. Stat, project scans and probing are background work."""
    cwd = Path(cwd or HOME)
    texts = []
    budget=[32768,128]
    def collect(obj,depth=0):
        if depth>5 or budget[0]<=0 or budget[1]<=0:
            return
        budget[1]-=1
        if isinstance(obj,str):
            value=obj[:budget[0]]
            budget[0]-=len(value)
            texts.append(value)
        elif isinstance(obj,dict):
            for value in itertools.islice(obj.values(),64):
                collect(value,depth+1)
        elif isinstance(obj,list):
            for value in obj[:64]:
                collect(value,depth+1)
    collect(args)
    collect(result)
    found = set()
    for text in texts[:64]:
        try:
            tokens = shlex.split(text)
        except ValueError:
            tokens = text.split()
        for i, token in enumerate(tokens):
            token = token.rstrip(";,)}]")
            if i and tokens[i-1] in {"-i", "--input"}:
                continue
            if Path(token).suffix.lower() in VIDEO:
                p = Path(token)
                found.add(os.path.abspath(str(cwd / p) if not p.is_absolute() else str(p)))
    return sorted(found)[:64]

class Hooks:
    """Session-local, once-per-file-revision notifications and bounded async work.

    A foreground quality_check acknowledges that revision's FAIL. Injecting a
    background result alone does not acknowledge it. Nudge each revision once.
    """
    def __init__(self, check=None, debounce=1.0, config_loader=None):
        self.config_loader = config_loader or load
        self.check = check or quality_check
        self.debounce = debounce
        self.lock = threading.Condition(threading.RLock())
        self.sessions = {}
        self.pending = {}
        self.discoveries = []
        self.running = 0
        self.executor = None
        self.thread = None
        self.closed = False
        self.max_nudges = 3

    def state(self, sid):
        if sid not in self.sessions and len(self.sessions) >= 256:
            return None
        return self.sessions.setdefault(sid, {"files": {}, "started": time.time(), "reminded": set(), "reminders": 0})

    def start(self):
        if self.thread is None:
            self.executor = futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="video-qc-auto")
            self.thread = threading.Thread(target=self._loop, daemon=True, name="video-qc-dispatch")
            self.thread.start()

    @staticmethod
    def signature(path):
        st = Path(path).stat()
        return (st.st_size, st.st_mtime_ns)

    @staticmethod
    def ignored(path):
        p = Path(path)
        parts = {part.casefold() for part in p.parts}
        return bool(parts & {"cache", ".git"}) or ".cbfix-" in str(p)

    def queue(self, sid, path):
        """Called off the hook hot path (also convenient for focused tests)."""
        try:
            path = str(Path(path).resolve())
            sig = self.signature(path)
            if re.search(r"proxy|draft", path, re.I) and probe(path)["duration"] < 1:
                return
            with self.lock:
                state = self.sessions.get(sid)
                if state is None:
                    return
                previous = state["files"].get(path)
                if previous and previous["sig"] == sig:
                    return
                if len(state["files"]) >= 128 and not previous:
                    return
                state["files"][path] = {"sig": sig, "result": None, "injected": False, "ack": False, "nudged": False}
                self.pending[(sid, path)] = time.monotonic() + self.debounce
                self.start()
                self.lock.notify_all()
        except Exception:
            pass

    def _discover(self, sid, paths, cwd, since):
        candidates = set(paths)
        # Handle explicit render paths before any bounded directory discovery.
        for path in paths:
            try:
                if not self.ignored(path) and Path(path).stat().st_mtime >= since:
                    self.queue(sid,path)
            except OSError:
                pass
        # Discovery is background-only and bounded to a configured root or tool cwd.
        cfg=self.config_loader()
        root=Path(cfg.get('projects_root') or (Path(paths[0]).parent if paths else cwd)).expanduser().resolve()
        project=root if root.is_dir() else None
        if project:
            seen = 0
            for root, dirs, files in os.walk(project):
                dirs[:] = [d for d in dirs if d.casefold() not in {"cache", "tmp", "temp", ".git", "node_modules", ".venv"}]
                for name in files:
                    seen += 1
                    if Path(name).suffix.lower() in VIDEO:
                        candidates.add(str(Path(root) / name))
                    if seen >= 5000:
                        break
                if seen >= 5000:
                    break
        for path in list(candidates)[:256]:
            try:
                if not self.ignored(path) and Path(path).stat().st_mtime >= since:
                    self.queue(sid, path)
            except OSError:
                pass

    def _check(self, sid, path):
        with self.lock:
            state = self.sessions.get(sid)
            snapshot = state and state["files"].get(path)
            sig = snapshot and snapshot["sig"]
        if not sig:
            return
        result = self.check(file=path, mode="quick")
        with self.lock:
            state = self.sessions.get(sid)
            current = state and state["files"].get(path)
            if current and current["sig"] == sig and self.signature(path) == sig:
                current["result"] = result

    def _run_job(self, kind, args):
        try:
            (self._discover if kind == "discover" else self._check)(*args)
        except Exception:
            pass
        finally:
            with self.lock:
                self.running -= 1
                self.lock.notify_all()

    def _loop(self):
        with self.lock:
            while not self.closed:
                now = time.monotonic()
                ready = next((key for key, due in self.pending.items() if due <= now), None)
                if self.running < 2 and (ready or self.discoveries):
                    if ready:
                        del self.pending[ready]
                        kind, args = "check", ready
                    else:
                        kind, args = "discover", self.discoveries.pop(0)
                    self.running += 1
                    self.executor.submit(self._run_job, kind, args)
                else:
                    self.lock.wait(timeout=.1)

    def post_tool_call(self, tool_name="", args=None, result="", session_id="", duration_ms=0, **kwargs):
        if not scoped() or not session_id or tool_name == "crystal_ball":
            return
        try:
            module=sys.modules.get('agent.runtime_cwd')
            cwd=str(module.resolve_agent_cwd()) if module else os.getcwd()
        except Exception:
            cwd=os.getcwd()
        try:
            if isinstance(args, dict):
                cwd = args.get("cwd") or args.get("workdir") or cwd
            paths = candidate_paths(args, result, cwd)
            since = time.time() - max(0, float(duration_ms or 0)) / 1000 - 1
            with self.lock:
                if self.state(session_id) is None or len(self.discoveries) >= 128:
                    return
                self.start()
                self.discoveries.append((session_id, paths, cwd, since))
                self.lock.notify_all()
        except Exception:
            pass

    def acknowledge(self, sid, path, result):
        if not sid:
            return
        try:
            path = str(Path(path).resolve())
            sig = self.signature(path)
            with self.lock:
                state = self.state(sid)
                if state is None:
                    return
                previous = state["files"].get(path, {})
                state["files"][path] = {"sig": sig, "result": result, "injected": True, "ack": True,
                                        "nudged": previous.get("nudged", False) if previous.get("sig") == sig else False}
        except Exception:
            pass

    def pre_llm_call(self, session_id="", **kwargs):
        if not scoped():
            return
        try:
            lines = []
            with self.lock:
                state = self.sessions.get(session_id, {})
                for path, file in state.get("files", {}).items():
                    result = file["result"]
                    if result is None or file["injected"]:
                        continue
                    issue = next(iter(result.get("items", [])), {})
                    line = f"QC {Path(path).name}: {result['verdict']}"
                    if issue:
                        line += f" {issue['id']} {issue['summary'][:90]} (fix: {issue.get('fix', '')[:100]})"
                    line += f"; {result.get('counts', {}).get('WARN', 0)} WARN; report: {result.get('report', '')}"
                    lines.append(line.replace("\n", " "))
                    file["injected"] = True
                    if len(lines) >= 8:
                        break
            reminder=self._reminders(session_id)
            lines.extend(reminder)
            return {"context": "\n".join(lines)} if lines else None
        except Exception:
            return None

    def _reminders(self, sid):
        lines=[]
        with self.lock:
            state=self.sessions.get(sid)
            if not state:
                return lines
            for path,file in state['files'].items():
                result=file['result']
                if state['reminders']>=3:
                    break
                if path not in state['reminded'] and (result is None or result.get('verdict')=='FAIL' and not file['ack']):
                    lines.append(f'Run crystal_ball check on {path} before reporting it done; check passed ≠ approved.')
                    state['reminded'].add(path)
                    state['reminders']+=1
                    file['nudged']=True
        return lines

    def pre_verify(self, session_id='', attempt=0, **kwargs):
        if not scoped() or attempt>=self.max_nudges:
            return
        try:
            lines=self._reminders(session_id)
            return {'action':'continue','message':'\n'.join(lines)} if lines else None
        except Exception:
            return None

    def on_session_end(self, session_id="", **kwargs):
        if not scoped():
            return
        with self.lock:
            self.sessions.pop(session_id, None)
            self.pending = {key: due for key, due in self.pending.items() if key[0] != session_id}
            self.discoveries = [job for job in self.discoveries if job[0] != session_id]

    def close(self):
        """For tests/host disposal; does not cancel unrelated processes."""
        with self.lock:
            self.closed = True
            self.lock.notify_all()
        if self.thread:
            self.thread.join(timeout=1)
        if self.executor:
            self.executor.shutdown(wait=True, cancel_futures=True)
