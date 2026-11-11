import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from crystal_ball import core as q
from crystal_ball import hooks as h
PLUGIN = Path(__file__).resolve().parents[1] / 'hermes_plugin/crystal-ball'


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-threads", "1", *map(str, args)],
                   check=True, capture_output=True, timeout=40)


@pytest.fixture(scope="session")
def clips(tmp_path_factory):
    root = tmp_path_factory.mktemp("synthetic-clips")
    clips = {}
    for name, video, audio in [
        ("good", "gradients=s=1280x720:r=25:d=3:c0=0x486e92:c1=0xc1c9d2:speed=0.3:seed=1", "sine=f=440:r=48000:d=3"),
        ("black", "color=c=black:s=640x360:r=25:d=3", "sine=f=440:r=48000:d=3"),
        ("frozen", "color=c=gray:s=640x360:r=25:d=3", "sine=f=440:r=48000:d=3"),
        ("clipping", "testsrc2=s=640x360:r=25:d=3", "aevalsrc=clip(4*sin(2*PI*440*t)\\,-1\\,1):s=48000:d=3"),
        ("text", "color=c=0x173f65:s=720x1280:r=25:d=3", "sine=f=440:r=48000:d=3"),
    ]:
        path = root / f"{name}.mp4"
        args = ["-f", "lavfi", "-i", video, "-f", "lavfi", "-i", audio]
        if name == "text":
            args += ["-vf", "drawtext=font=DejaVuSans-Bold:text='NEW PLACE':fontsize=64:fontcolor=white:x=100:y=1190"]
        if name != "clipping":
            args += ["-af", "loudnorm=I=-14:TP=-1:LRA=11", "-ar", "48000"]
        ffmpeg(*args, "-c:v", "libx264", "-preset", "ultrafast", "-threads", "1", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path)
        clips[name] = path
    return clips


def request(path, run_dir, platform="youtube", **kwargs):
    run_dir.mkdir(parents=True, exist_ok=True)
    return {"file": str(path), "run_dir": str(run_dir), "platform": platform,
            "mode": "quick", "meta": q.probe(path), "rules": {"terms": [], "active": ""}, **kwargs}


@pytest.mark.parametrize("name,check,status", [("black", "black", "FAIL"), ("frozen", "frozen", "WARN"),
                                                 ("clipping", "clipping", "FAIL"), ("good", "decode", "PASS")])
def test_real_signal_clips(clips, tmp_path, name, check, status):
    result = q.run_stage("signal", request(clips[name], tmp_path / name))
    assert next(r for r in result["checks"] if r["id"] == check)["status"] == status, result


def test_real_ocr_safe_zone_and_misspelling(clips, tmp_path):
    req = request(clips["text"], tmp_path, "shorts", expect_text=["NEW PLACES"])
    review = q.run_stage("review", req)
    assert len(review["frames"]) >= 5, review
    result = q.run_stage("ocr", {**req, "review": review})
    assert any(r["id"] == "ocr_safe_zone" and r["status"] == "FAIL" for r in result["checks"]), result
    spelling = [r for r in result["checks"] if r["id"] == "ocr_spelling"]
    assert spelling and "new place" in spelling[0]["summary"], result
    assert spelling[0]["timestamps"]
    assert all(b["confidence"] >= 70 for b in result["boxes"])


def test_caption_event_frames(clips, tmp_path):
    caps = tmp_path / "captions.srt"
    caps.write_text("1\n00:00:00,300 --> 00:00:00,700\nHello\n\n2\n00:00:01,300 --> 00:00:01,700\nWorld\n")
    req = request(clips["good"], tmp_path / "run", captions=str(caps))
    review = q.run_stage("review", req)
    times = [f["time"] for f in review["frames"]]
    assert .45 in times and 1.45 in times
    ass = tmp_path / "captions.ass"
    ass.write_text("[Events]\nFormat: Layer, Start, End, Style, Text\nDialogue: 0,0:00:01.20,0:00:01.40,Default,Hi\n")
    assert q.caption_times(ass) == pytest.approx([1.3])


@pytest.fixture
def stub_aux(monkeypatch):
    actual = q.run_stage
    calls = []
    def stub(stage, req, timeout=None):
        calls.append(stage)
        if stage in {"vision", "audio"}:
            return {"checks": [q.row(stage, "PASS", "stubbed auxiliary stage")]}
        return actual(stage, req, timeout)
    monkeypatch.setattr(q, "run_stage", stub)
    return calls


def test_cache_compact_and_invalidation(clips, tmp_path, monkeypatch, stub_aux):
    monkeypatch.setattr(q, "CACHE", tmp_path / "cache")
    before = time.monotonic()
    first = q.quality_check(str(clips["good"]))
    elapsed = time.monotonic() - before
    assert not first["cached"] and first["platform"] == "youtube" and "16:9" in first["inference"]
    assert Path(first["report"]).is_file() and Path(first["review_frames"]).is_dir()
    assert len(q.dumps(first).encode()) <= 1500
    count = len(stub_aux)
    before = time.monotonic()
    hit = q.quality_check(str(clips["good"]))
    assert hit["cached"] and len(stub_aux) == count
    assert time.monotonic() - before < elapsed
    q.quality_check(str(clips["good"]), expect_text=["NEW PLACES"])
    assert len(stub_aux) > count
    count = len(stub_aux)
    q.quality_check(str(clips["good"]), force=True)
    assert len(stub_aux) > count


def test_stage_failure_isolation(clips, tmp_path, monkeypatch):
    monkeypatch.setattr(q, "CACHE", tmp_path / "cache")
    actual = q.process_json
    def broken(cmd, timeout, env=None):
        if "signal" in cmd:
            raise RuntimeError("synthetic signal failure")
        return actual(cmd, timeout, env)
    monkeypatch.setattr(q, "process_json", broken)
    result = q.quality_check(str(clips["good"]))
    assert any("synthetic signal failure" in value for value in result["not_checked"])
    doc = json.loads(Path(result["report"]).with_name("full.json").read_text())
    assert doc["stages"]["review"]["frames"]
    assert doc["stages"]["ocr"].get("lines") is not None


def test_worker_timeout_kills_descendants(tmp_path):
    pidfile = tmp_path / "pid"
    code = "import subprocess,time,pathlib; p=subprocess.Popen(['sleep','30']); pathlib.Path(" + repr(str(pidfile)) + ").write_text(str(p.pid)); time.sleep(30)"
    with pytest.raises(subprocess.TimeoutExpired):
        q.process_json([sys.executable, "-E", "-c", code], .3)
    pid = int(pidfile.read_text())
    # A reaped process or a zombie has stopped executing.
    stat = Path(f"/proc/{pid}/stat")
    assert not stat.exists() or stat.read_text().split()[2] == "Z"


def test_audio_contract_stub(clips, tmp_path, monkeypatch):
    from crystal_ball.senses import hear
    transcript={'engine':'stub','text':'Hello','segments':[{'start':0.,'end':1.,'text':'Hello','words':[]}]}
    monkeypatch.setattr(hear,'transcribe',lambda *a: transcript)
    monkeypatch.setattr(hear,'voice_balance',lambda *a: {'method':'estimate from speech windows'})
    script=tmp_path/'script.txt'; script.write_text('Hello')
    result=hear.audio_stage(request(clips['good'],tmp_path/'run',script=str(script)))
    assert {r['id'] for r in result['checks']}=={'transcript','script_match','voice_balance','speech_gaps'}
    assert result['transcript']==transcript


def test_vision_one_call_and_validation(clips, tmp_path, monkeypatch):
    from types import ModuleType
    agent=ModuleType('agent'); auxiliary_client=ModuleType('agent.auxiliary_client')
    auxiliary_client.call_llm=lambda **kw: None
    auxiliary_client.extract_content_or_reasoning=lambda x:x
    agent.auxiliary_client=auxiliary_client
    monkeypatch.setitem(sys.modules,'agent',agent)
    monkeypatch.setitem(sys.modules,'agent.auxiliary_client',auxiliary_client)
    monkeypatch.setenv('CRYSTAL_BALL_JUDGE_BACKEND','hermes-auxiliary')
    image=tmp_path/'frame.jpg'
    ffmpeg('-f','lavfi','-i','color=c=blue:s=1280x720','-frames:v','1',image)
    calls = []
    def call(**kwargs):
        calls.append(kwargs)
        return '{"checks":[{"id":"vision_artifact","status":"WARN","summary":"visible seam","items":[{"t":1,"end":1,"detail":"seam"}],"fix":"edit source"}]}'
    monkeypatch.setattr(auxiliary_client, "call_llm", call)
    monkeypatch.setattr(auxiliary_client, "extract_content_or_reasoning", lambda value: value)
    req = request(clips["good"], tmp_path / "run")
    req["review"] = {"contact_sheet": str(image), "frames": [{"time": n/2, "path": str(image)} for n in range(6)]}
    result = q.vision_stage(req)
    assert len(calls) == 1 and calls[0]["task"] == "vision"
    assert sum(p["type"] == "image_url" for p in calls[0]["messages"][0]["content"]) == 5
    assert result["checks"][0]["timestamps"] == [[1, 1]]
    calls.clear()
    monkeypatch.setattr(auxiliary_client, "call_llm", lambda **kw: '{"checks":[{"id":"bad","status":"FAIL","summary":"x","fix":"x","items":[{"t":-1}]}]}')
    with pytest.raises(ValueError):
        q.vision_stage(req)


def test_vision_spelling_ocr_overrides():
    vision = {"checks": [q.row("vision_spelling", "WARN", 'Misspelling "NEW PLACE"', [[1, 1]])]}
    assert not any(r["id"]=="vision_spelling" for r in q.crosscheck_vision(vision, {"boxes": [{"time": 1, "text": "NEW PLACES", "confidence": 95}]} )["checks"])


def test_no_overwrite_and_approved_refusal(clips, tmp_path, monkeypatch):
    from crystal_ball.config import load
    from crystal_ball.fix import apply_fix
    path=tmp_path/'copy.mp4'; path.write_bytes(clips['good'].read_bytes())
    cfg=load(); cfg['fix']['protected']=['**/copy.mp4']
    doc={'file':str(path),'platform':'youtube','checks':[q.row('loudness','FAIL','-20 LUFS')]}
    identity=q.fingerprint(path)
    assert apply_fix(doc,config=cfg)['status']=='refused'
    output=path.with_name('copy.cbfix.mp4'); output.write_text('preserve me')
    assert apply_fix(doc,force=True,config=cfg)['status']=='refused'
    assert output.read_text()=='preserve me' and q.fingerprint(path)==identity
    final=tmp_path/'final/master.mp4'; final.parent.mkdir(); final.write_bytes(path.read_bytes())
    assert apply_fix({**doc,'file':str(final)})['status']=='refused'


def test_mechanical_fix_new_file_and_recheck(clips, tmp_path, monkeypatch, stub_aux):
    monkeypatch.setattr(q, "CACHE", tmp_path / "cache")
    path = tmp_path / "quiet.mp4"
    ffmpeg("-i", clips["good"], "-c:v", "copy", "-af", "volume=0.15", "-c:a", "aac", path)
    identity = q.fingerprint(path)
    result = q.quality_check(str(path), fix=True)
    assert result["fix"]["status"] == "written", result
    assert result["verdict"] == "FAIL"
    assert result["fix"]["verdict"] in {"PASS", "WARN"}, result
    assert Path(result["fix"]["file"]).is_file() and q.fingerprint(path) == identity
    assert len(q.dumps(result).encode()) <= 1500


def wait_for(predicate, seconds=5):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if predicate():
            return
        time.sleep(.02)
    assert predicate()


def test_hooks_debounce_once_profile_and_ack(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "scoped", lambda: True)
    calls = []
    def check(**kw):
        calls.append(kw)
        return {"verdict": "FAIL", "items": [q.row("loudness", "FAIL", "-20 LUFS", fix="loudness.py")], "counts": {"WARN": 2}, "report": "/tmp/report"}
    hooks = h.Hooks(check, debounce=.05)
    try:
        hooks.state("a")
        path = tmp_path / "render.mp4"
        path.write_text("one")
        for _ in range(10):
            hooks.queue("a", path)
        wait_for(lambda: hooks.sessions["a"]["files"][str(path)]["result"])
        assert len(calls) == 1
        assert "QC render.mp4: FAIL" in hooks.pre_llm_call(session_id="a")["context"]
        assert hooks.pre_llm_call(session_id="a") is None
        assert hooks.pre_llm_call(session_id="b") is None
        assert hooks.sessions["a"]["files"][str(path)]["nudged"]
        assert hooks.pre_verify(session_id="a") is None
        path.write_text("changed length")
        hooks.queue("a", path)
        wait_for(lambda: len(calls) == 2)
        wait_for(lambda: hooks.sessions["a"]["files"][str(path)]["result"])
        hooks.acknowledge("a", path, calls and check())
        assert hooks.pre_verify(session_id="a") is None
        assert hooks.pre_verify(session_id="a", attempt=hooks.max_nudges) is None
        monkeypatch.setattr(h, "scoped", lambda: False)
        assert hooks.pre_llm_call(session_id="a") is None
    finally:
        hooks.close()


def test_hook_concurrency_and_hot_path(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "scoped", lambda: True)
    active = [0, 0]
    lock = threading.Lock()
    def check(**kw):
        with lock:
            active[0] += 1
            active[1] = max(active)
        time.sleep(.08)
        with lock:
            active[0] -= 1
        return {"verdict": "PASS", "items": [], "counts": {}}
    hooks = h.Hooks(check, debounce=.02)
    hooks.state("s")
    try:
        for i in range(6):
            path = tmp_path / f"{i}.mp4"
            path.write_text("data")
            hooks.queue("s", path)
        wait_for(lambda: all(f["result"] for f in hooks.sessions["s"]["files"].values()))
        assert active[1] <= 2
        before = time.monotonic()
        hooks.post_tool_call(tool_name="terminal", args={"command": "ffmpeg -i input.mp4 -o output.mp4", "cwd": str(tmp_path)}, session_id="other")
        hooks.pre_llm_call(session_id="s")
        hooks.pre_verify(session_id="s")
        assert time.monotonic() - before < .2
        hooks.on_session_end(session_id="s")
        assert "s" not in hooks.sessions
    finally:
        hooks.close()


def test_candidates_and_registration(monkeypatch):
    paths = h.candidate_paths({"command": 'ffmpeg -i /input.mp4 -c copy "/a path/output.mp4"'}, cwd="/x")
    assert paths == ["/a path/output.mp4"]
    assert h.Hooks.ignored("/project/cache/a.mp4")
    assert h.candidate_paths({"command": "npx remotion render Comp out/movie.mp4"}, cwd="/x") == ["/x/out/movie.mp4"]
    spec = importlib.util.spec_from_file_location("test_video_quality_plugin", PLUGIN / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    class Context:
        def __init__(self):
            self.tools, self.hooks = [], []
        def register_tool(self, **kw):
            self.tools.append(kw)
        def register_hook(self, name, handler):
            self.hooks.append(name)
    ctx = Context()
    module.register(ctx)
    assert [t["name"] for t in ctx.tools] == ["crystal_ball"]
    assert set(ctx.hooks) == {"post_tool_call", "pre_llm_call", "pre_verify", "on_session_end"}


def test_compact_many_findings_unicode(tmp_path):
    doc = {"platform": "shorts", "report": str(tmp_path / "report.md"), "frames_dir": str(tmp_path / "frames"),
           "checks": [q.row("ocr", "WARN", "خطأ إملائي " * 50, [[1, 1]], "edit source " * 30) for _ in range(100)]}
    result = q.compact(doc)
    assert len(q.dumps(result).encode()) <= 1500
    assert result["counts"]["WARN"] == 100


def test_project_rules_and_show_vocabulary(tmp_path, monkeypatch):
    from crystal_ball.config import load, rules_for
    project=tmp_path/'project'; project.mkdir()
    feedback=project/'FEEDBACK.md'; taste=project/'TASTE.md'
    feedback.write_text('Use "NEW PLACES" and spell Alexis correctly.')
    taste.write_text('Keep "Hermes" readable.')
    (tmp_path/'other.md').write_text('Unselected rule')
    config=tmp_path/'config.toml'
    config.write_text('[rules]\nfiles = ["project/*.md"]\n')
    monkeypatch.setenv('CRYSTAL_BALL_CONFIG',str(config))
    rules=rules_for(project/'movie.mp4')
    assert 'NEW PLACES' in rules['terms'] and 'Alexis' in rules['terms']
    assert 'Hermes' in rules['active'] and 'Unselected' not in rules['active']
    assert str(taste) in rules['deps']


def test_post_hook_background_integration(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "scoped", lambda: True)
    monkeypatch.setattr(h.Hooks, "ignored", staticmethod(lambda path: False))
    calls = []
    def check(**kw):
        calls.append(kw)
        return {"verdict": "PASS", "items": [], "counts": {}, "report": "/tmp/report"}
    hooks = h.Hooks(check, debounce=.1)
    video = tmp_path / "render.mp4"
    video.write_text("new render")
    try:
        before = time.monotonic()
        for _ in range(4):
            hooks.post_tool_call(tool_name="terminal", args={"command": f"ffmpeg -i input.mov '{video}'"}, session_id="s")
        assert time.monotonic() - before < .2
        wait_for(lambda: len(calls) == 1)
        wait_for(lambda: hooks.sessions["s"]["files"][str(video)]["result"])
        assert hooks.pre_llm_call(session_id="s")["context"].startswith("QC render.mp4: PASS")
        assert hooks.pre_llm_call(session_id="s") is None
    finally:
        hooks.close()


def test_pixel_fix_uses_existing_export_and_preserves_timing(clips, tmp_path, monkeypatch, stub_aux):
    # Public contract narrows automatic fixes to levels; pixel conversion is manual.
    video=tmp_path/'pixel.mp4'
    ffmpeg('-i',clips['good'],'-c:v','libx264','-threads','1','-pix_fmt','yuv444p','-c:a','copy',video)
    before=q.fingerprint(video)
    result=q.apply_fix({'file':str(video),'platform':'x','checks':[q.row('pixel format','FAIL','yuv444p')]})
    assert result['status']=='no_safe_fix'
    assert q.fingerprint(video)==before and not video.with_name('pixel.cbfix.mp4').exists()


def test_racing_output_never_overwritten(clips, tmp_path, monkeypatch):
    video = tmp_path / "race.mp4"
    video.write_bytes(clips["good"].read_bytes())
    output = tmp_path / "race.cbfix.mp4"
    from crystal_ball import fix
    actual=fix.command
    def race(cmd, timeout=60, env=None):
        value=actual(cmd,timeout,env)
        output.write_bytes(b'racing owner output')
        return value
    monkeypatch.setattr(fix,'command',race)
    result=q.apply_fix({'file':str(video),'platform':'youtube','checks':[q.row('loudness','FAIL','-20 LUFS')]})
    assert result['status']=='failed'
    assert output.read_bytes()==b'racing owner output'


def test_quick_gates_vision_full_calls_once(clips, tmp_path, monkeypatch):
    monkeypatch.setattr(q, "CACHE", tmp_path / "cache")
    stages = []
    def stub(stage, req, timeout=None):
        stages.append(stage)
        if stage == "signal":
            return {"checks": [q.row("black", "FAIL", "black video")]}
        if stage == "review":
            return {"checks": [], "frames": [], "frames_dir": str(tmp_path / "frames")}
        return {"checks": [q.row(stage, "PASS", "stub")]}
    monkeypatch.setattr(q, "run_stage", stub)
    q.quality_check(str(clips["black"]), mode="quick")
    assert "vision" not in stages
    stages.clear()
    q.quality_check(str(clips["black"]), mode="full")
    assert stages.count("vision") == 1


def test_audio_missing_is_skip(clips, tmp_path, monkeypatch):
    monkeypatch.setenv('CRYSTAL_BALL_HEAR_PYTHON',str(tmp_path/'missing-python'))
    doc=q.run_stage('audio',request(clips['good'],tmp_path/'run'))
    assert doc['checks'][0]['status']=='SKIP'
    assert doc['checks'][0]['summary'].startswith('hear: FileNotFoundError:')
    assert 'fallback not configured' in Path(doc['log']).read_text()


def test_prose_is_not_a_name_misspelling():
    lines = [{"time": 1, "text": "This keeps a reference reviewed"}]
    assert not q.spelling_checks(lines, ["Keep", "References", "Review"], proper_only=True)
    assert q.spelling_checks([{"time": 2, "text": "Alexiz"}], ["Alexis"], proper_only=True)


def test_unprobeable_file_has_skip_report(tmp_path, monkeypatch):
    monkeypatch.setattr(q, "CACHE", tmp_path / "cache")
    path = tmp_path / "broken.mp4"
    path.write_bytes(b"not an mp4")
    result = q.quality_check(str(path))
    assert result["verdict"] == "WARN" and result["counts"]["SKIP"] == 1
    assert "probe:" in result["not_checked"][0]
    assert Path(result["report"]).exists()


def test_fix_preserves_existing_ambience_rule(clips):
    result = q.apply_fix({"file": str(clips["good"]), "platform": "youtube", "checks": [q.row("loudness", "FAIL", "-45 LUFS")]})
    assert result["status"] == "no_safe_fix" and "ambience" in result["reason"]


def test_fix_refuses_stale_analysis(clips):
    doc = {"file": str(clips["good"]), "platform": "youtube", "identity": ["stale"], "checks": []}
    assert "source changed" in q.apply_fix(doc)["reason"]


def test_fix_does_not_drop_extra_audio_tracks(clips, tmp_path):
    path = tmp_path / "two_audio.mp4"
    ffmpeg("-i", clips["good"], "-map", "0:v:0", "-map", "0:a:0", "-map", "0:a:0", "-c", "copy", path)
    doc = {"file": str(path), "platform": "youtube", "checks": [q.row("loudness", "FAIL", "-20 LUFS")]}
    result = q.apply_fix(doc)
    assert result["status"] == "no_safe_fix" and "audio stream" in result["reason"]
    assert not path.with_name("two_audio.cbfix.mp4").exists()


def test_cli_check_json_is_parseable(clips):
    result=subprocess.run([sys.executable,'-E','-m','crystal_ball','check',str(clips['good']),'--platform','youtube','--json'],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    value=json.loads(result.stdout)
    assert value['verdict']=='WARN' and value['counts']['FAIL']==0
    assert len(result.stdout.encode())<=1500 and Path(value['report']).is_file()
