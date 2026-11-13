# Crystal Ball

**Give media tools four senses. Keep the agent's context small.**

Crystal Ball is a standalone Python toolkit and Hermes Agent plugin for
checking renders, transcribing speech, searching footage and reading visible
text. A compact verdict points to full local reports and shared artifacts.

**Check passed ≠ approved.** Measurements and sampled critique support a
human decision; they do not grant creative or delivery approval.

## Four senses

| Sense | What it provides |
|---|---|
| **Hear** | Local faster-whisper ASR with word timestamps, normalized script WER, missing/changed lines and names, speech gaps and voice-balance measurements. CPU int8 admission/OOM fallback before whisper.cpp. Beat/onset detection, estimated 4/4 bars and novelty sections. |
| **See** | Incremental CLIP frame indexing; text or image search; atomic index generations; an odd-shot-out Python helper. Cached shot boundaries, thumbnails and labelled fades. |
| **Read** | Full-size sampled OCR, line grouping, spelling hints and safe-zone evidence, including optional Arabic traineddata. |
| **Judge** | One optional vision call with a contact sheet and up to four full frames, a fixed evidence prompt, brief and at most 2 KB of Markdown rules. |

Signal checks reuse the MIT ffmpeg-skill QC implementation: decode errors,
black/frozen frames, clipping/silence, stream timing, loudness/true peak,
caption margins and delivery-platform specifications.

## Quick start

Python 3.11+ and ffmpeg/ffprobe 6.1+ are required. Native Windows support targets
Windows 10/11 x64 with CPython 3.11; Linux/macOS retain their existing commands.
Core analysis needs only numpy/Pillow. Tesseract, ASR, CLIP, rhythm and GPU
engines are optional; missing senses are not checked, never a PASS.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/crystal-ball setup     # prints the pinned, user-run engine setup steps
cp crystal-ball.example.toml crystal-ball.toml
# Edit interpreter/model/data paths for your installation.
.venv/bin/crystal-ball doctor
.venv/bin/crystal-ball check ./render.mp4 --platform youtube --json
```

`python -m crystal_ball` supports the same commands. Package distribution name:
`crystal-ball-media`; import name: `crystal_ball`; executable: `crystal-ball`.
Built-in analysis model loaders never download models. Setup **prints** commands, including
explicit user-run model downloads. Run only the engines you need. GPU packages
and models are not installed into Hermes by the plugin.

### Native Windows (PowerShell, no activation)

```powershell
py -3.11 -m venv .venv
& ./.venv/Scripts/python.exe -m pip install .
& ./.venv/Scripts/python.exe -m crystal_ball doctor --json
& ./.venv/Scripts/python.exe -m crystal_ball check './media/render.mp4' --platform youtube --json
& ./.venv/Scripts/python.exe -m crystal_ball setup
# Optional: one interactive confirmation for isolated CPU engines/models/config.
& ./.venv/Scripts/python.exe -m crystal_ball setup --install
# Or select only hear or see: setup hear --install / setup see --install.
```

Provide native ffmpeg.exe and ffprobe.exe 6.1+ on trusted PATH (not the current
directory); .bat/.cmd wrappers are refused. No executable download, WSL, CUDA,
activation or execution-policy change is required. Optional Hear needs the
Microsoft Visual C++ x64 runtime; setup reports its official prerequisite link.
Print-only setup never installs; --install requires interactive stdin and one
explicit yes. It creates managed generations below
%LOCALAPPDATA%/crystal-ball/engines, verifies packages/local models offline, then
patches only selected config keys with a backup. Failed setup retains the prior
config and failed generation/downloads; correct the reported error and rerun.
No user-managed environment is overwritten or automatically removed.

Windows defaults to CPU int8 Hear and CPU float32 CLIP. Requested CUDA still
requires an independently provisioned compatible machine-local GPU broker;
seeing a GPU does not grant permission to use it. CPU work acquires no GPU lease.
Ordinary local checks/doctor with judge off stay offline and never prompt.

Use TOML literal paths, for example python = 'C:\\Media Tools\\hear\\Scripts\\python.exe',
or forward slashes. Drive-relative C:folder and root-relative \\folder are
ambiguous and rejected. Explicit local model paths start with ./ or a full
drive/UNC path; identifiers such as openai/clip-vit-large-patch14 stay identifiers.
Windows keeps an existing legacy ~/.config/crystal-ball/config.toml before
%APPDATA%/crystal-ball/config.toml; new cache default is
%LOCALAPPDATA%/crystal-ball/cache. Explicit configs/cache_dir always win.

Open the actual returned report.md, report.html and sibling full.json. Saved
reports/contact sheets persist without rerunning analysis; no assets are uploaded.
Ctrl+C cancels only the owned action tree, not other applications. UNC parsing
is supported, but initial locking/publication scope is local NTFS, not SMB.
Native Windows execution and installed Hermes UI integration still require the
checks recorded in docs/as-built/windows-support-2026-11-13.md.

The hear engine receives mono **float32 16 kHz NumPy PCM decoded by ffmpeg**,
not a filename: this bypasses incompatible PyAV decoders. Its persistent JSON
worker loads each model once and can transcribe multiple files in one run.
The launcher discovers `nvidia/cublas/lib` and `nvidia/cudnn/lib` inside the
configured interpreter's prefix and prepends them to `LD_LIBRARY_PATH`.
CPU mode uses int8; CUDA uses float16. Before loading, hear requests broker
admission (default 3.5 GiB). Missing/denied broker admission selects faster-whisper CPU
int8 before whisper.cpp. A CUDA OOM at load or during lazy inference retries
once on CPU. Results name `faster-whisper-cuda`, `faster-whisper-cpu` or
`whisper.cpp` and include `fallback_reason` (null when no fallback occurred).
CLIP uses the same admission/CPU retry policy (default 2.5 GiB); both senses
have configurable `cpu_threads`. Rhythm uses CPU only. The whisper.cpp fallback uses a private
WAV and an explicit `-of` output prefix, then parses JSON/token timestamps.

## Configuration

Resolution: `CRYSTAL_BALL_CONFIG`, then `./crystal-ball.toml`, then
`~/.config/crystal-ball/config.toml`. An explicitly selected missing config is
an error. Hermes uses `CRYSTAL_BALL_CONFIG` or `HERMES_HOME/crystal-ball.toml`.
Paths in TOML are relative to its directory; `~` and environment variables in
path fields expand. Bare interpreter/binary names resolve on `PATH`.

```toml
cache_dir = "~/.cache/crystal-ball"
# projects_root = "./media-projects" # optional background discovery root
[hear]
python = ".venv-hear/bin/python"
model = "large-v3-turbo"
device = "cuda"
[see]
python = ".venv-see/bin/python"
model = "openai/clip-vit-large-patch14"
[rhythm]
python = ".venv-rhythm/bin/python"
[scenes]
python = ".venv-scenes/bin/python"
detector = "content"
threshold = 27.0
min_shot_s = 0.3
[read]
tessdata = "./tessdata"
[judge]
backend = "off"
[rules]
files = ["rules/*.md"]
[fix]
protected = ["**/final/**"]
```

See [the complete example](crystal-ball.example.toml) for whisper.cpp,
optional demucs argv and HTTP judge configuration. Every supported key has a
`CRYSTAL_BALL_*` override: e.g. `CRYSTAL_BALL_CACHE_DIR`,
`CRYSTAL_BALL_HEAR_PYTHON`, `CRYSTAL_BALL_HEAR_DEVICE`,
`CRYSTAL_BALL_SEE_MODEL`, `CRYSTAL_BALL_JUDGE_API_KEY_ENV`. Array overrides
are TOML arrays, e.g. `CRYSTAL_BALL_RULES_FILES='["rules/*.md"]'`.
Rule files are selected explicitly; quoted phrases and proper names provide
spelling vocabulary. Prose is context, not an invented obligation.

`judge.backend` is `off` by default. `hermes-auxiliary` uses the host's
`agent.auxiliary_client`; `openai-compatible` POSTs to
`<base_url>/chat/completions`, using the model and key environment-variable
name you configure. Enabling either judge may transmit sampled images and
brief/rules to its selected provider. Local signals, ASR, OCR and CLIP do not
upload media. Optional external demucs commands are user-owned; provision their
models beforehand and review their network behavior. Text/spelling allegations require confident full-frame OCR.

Tesseract uses available `eng` and `ara` languages. Set `read.tessdata` to
select traineddata (`TESSDATA_PREFIX` is passed to the subprocess). Optional
Arabic reference: tessdata_best 4.1.0 `ara.traineddata`, SHA256
`ab9d157d8e38ca00e7e39c7d5363a5239e053f5b0dbdb3167dde9d8124335896`.
Doctor reports different versions as WARN, without replacing them.

## Media applicability (MA-r1)

`check` classifies content before dispatch: still image, audio-only, video with
sound, or video without audio. Cover art is not video. Animated/ambiguous media
is Not checked rather than guessed. Corrupt supported media fails decode;
missing engines/binaries and timeouts are incomplete evidence, not creative failure.

```sh
crystal-ball check still.png --shape 16:9 --expect-text 'HELLO WORLD' --json
crystal-ball check music.wav --platform custom --json
crystal-ball check render.mp4 --platform custom --shape 9:16 --json
```

Images ignore stale video-platform options and never run audio/temporal checks.
Their OCR uses one oriented, full-resolution still, not duplicate timestamps.
Audio runs decode, duration, silence, clipping, LUFS and true-peak measurements,
without picture checks or an invented loudness target. No-audio video omits
Hear, audio measurements, A/V and beat sync; an explicit audio-required brief
is a separate required-output mismatch. Hear keeps its existing configuration;
set `[hear] model = ""` to disable it for checks. No engine/model is downloaded.

Optional `--shape 9:16|16:9|1:1` (Python/tool `shape`) compares oriented aspect
within 1% relative error; it does not request a pixel size. With shape, the
generic safe inset is 5% per edge unless a video platform is selected. Without
shape, custom destinations omit aspect/safe-zone target compliance. These are
local conventions, not platform certification; OCR is evidence, not proof of
universal readability. Explicit video platforms retain their rules. Standalone
video inference is retained when `platform` is omitted; callers with no selected
destination should send `platform="custom"`.

Full JSON adds `media_kind` and each SKIP's `skip_reason` (`not_applicable`,
`not_requested`, `unavailable`, `dependency_failed`). Reports show `Not checked:`
omissions; the 1,500-byte compact response retains identities/counts/report paths
and omission metadata, dropping optional details as needed. Incompleteness still
aggregates to WARN, and a real FAIL takes precedence. `quick`/`full`, existing
arguments and exit meanings are unchanged. See
[the as-built/evidence record](docs/as-built/media-applicability-2026-11-13.md).

## CLI examples

```sh
crystal-ball check render.mp4 --platform shorts --mode full \
  --captions captions.srt --script script.txt --brief 'A readable title card' \
  --expect-text 'CLEAR TITLE' --json
crystal-ball transcribe render.mp4 --srt -o speech.srt
crystal-ball transcribe render.mp4 --vtt -o speech.vtt
crystal-ball transcribe render.mp4 --json -o speech.json
crystal-ball beats music.wav --export ./markers --fps 25
crystal-ball scenes render.mp4 --first 5 --export ./shots
crystal-ball cuts render.mp4 --music music.wav --within-frames 6
crystal-ball check render.mp4 --platform shorts --beat-led --json
crystal-ball index ./media ./stills --sampling shot --frames-per-shot 1
crystal-ball index ./media --sampling interval --every 2
crystal-ball find 'a blue sky' --top 5 --dir ./media
crystal-ball find --image reference.png --top 3
crystal-ball read-text render.mp4 --at 1.5
crystal-ball check render.mp4 --fix --json
crystal-ball doctor --json
crystal-ball setup hear
```

`beats` runs a JSON worker in `rhythm.python` (local librosa 1.0.0), and
returns tempo/confidence, the first 16 beats, estimated bars and artifact paths.
Full JSON also contains onset/hit times, estimated downbeats and coarse novelty
sections. The 4/4 assumption and first-beat downbeat phase are estimates;
confidence combines spacing stability and onset support, not a calibrated
probability. `--export [DIR]` writes JSON and CSV timeline markers; `--fps N`
also writes a zero-based nearest-frame list. Without DIR, exports live beside
the cached artifact. If a configured demucs command and ASR indicate speech,
rhythm may use `no_vocals.wav` or `music.wav`; otherwise it analyses the mix and
states that speech lowers beat accuracy. Separation failure falls back to mix.

`scenes` runs PySceneDetect 0.7.2 in `scenes.python`, using `content` or
`adaptive`. `threshold` is a content score (default 27), or an adaptive ratio
(use e.g. 3 for adaptive); `min_shot_s` suppresses short adjacent shots.
If the runtime is unavailable, ffmpeg `select='gt(scene,T)'` supplies cuts
with an explicit fallback reason. Its scene score approximates content threshold
as threshold/100; adaptive mode uses 0.3 because ratios are not scene scores.
A black-level threshold detector and gradual-ramp evidence label fades.
The incoming transition is `start`, `hard cut` or `fade`; dissolves are not
reliably classified. One cached thumbnail per shot is shared by review,
judge cut frames and default CLIP indexing. `--frames-per-shot 1|2|3` chooses
shot sampling; interval mode remains available. `--export [DIR]` writes CSV
and a CMX3600 non-drop EDL (straight source assembly; detected fades are comments,
not inferred transition durations). Fractional frame rates use nominal timecode.

`cuts` combines those artifacts with beat/onset offsets and beat snap suggestions
within `--within-frames N` (default 6). `--music AUDIO` uses a separate soundtrack
with the **same zero origin**; no automatic soundtrack alignment is implied.
Frame deltas are advisory: the action does not retime an edit. CLI and Hermes
return compact JSON; full shots, alignment and snap lists remain in artifacts.

Checks add three findings, with PASS omitted from compact issue lists:

- `cut_sync` runs only with `--beat-led` / Hermes `beat_led`, or a brief saying
  beat-led or music-led. It measures distance to the nearest beat **or onset**,
  reports median and worst cuts, and WARNs if more than 30% exceed 80 ms.
  Fix hints contain beat snap suggestions; full alignment remains in the report.
- `pacing` reports min/median/mean/max shot lengths as information. For vertical
  destinations it WARNs when no cut or substantial visual change occurs in the
  first 2 seconds. A static opening can still be intentional.
- `flash` inspects every decoded frame at reduced spatial resolution and FAILs
  above 3 flash cycles in any rolling 1-second window across at least 25% of
  pixels. It estimates opposing luminance changes and saturated-red changes;
  full artifacts disclose thresholds and event times. **Estimate, not a certified
  Harding test.** Small, brief or spatially complex patterns may be missed.

Quick and full both run signal, OCR and audio stages. Quick requests vision
only when the relevant signal checks all pass. Full permits a single vision
call even with signal failures. Missing engines become explicit SKIPs/WARNs;
other stages continue. CLI exit codes: 0 for a completed non-FAIL check,
1 for FAIL, 2 for an input/execution error. WARN does not mean approval.

`--fix` supports measured loudness/true-peak correction only. It preserves
video streams and writes `<stem>.cbfix<ext>` without overwriting any existing
file, including a racing writer's output. Protected globs default to
`**/final/**`; `--force` permits protected input and bypasses the check cache.
Unmeasured/near-silent ambience at or below -40 LUFS is left alone, following
the inherited signal contract. Multiple audio tracks need an explicit mix
choice, so automatic correction is refused. The output is re-checked and
both verdicts remain visible. Pixel conversion and creative edits are manual.

## Reports, cache and sample output

Content identity includes path, size, nanosecond mtime and head/tail hash.
Atomic, locked artifacts share full-size frames, transcripts, OCR and
embeddings between actions with matching sampling/model settings. Reports
live in the configured cache (`report.md`, `report.html`, `full.json`);
originals and project folders receive no analysis artifacts. Index metadata
points to an immutable embedding generation so failed commits retain the
previous readable index.

Generate the synthetic example and its actual compact JSON:

```sh
mkdir -p .test-tmp
python scripts/synthetic_example.py
```

A shortened extract from that generated test-pattern check (all full details
remain in the artifact/report paths):

```json
{"verdict":"WARN","platform":"youtube","items":[{"id":"subtitles","status":"WARN","summary":"none"}]}
```

This is an extract, not a claim that every engine ran. The accompanying
full output discloses engine availability and all SKIPs. Tool responses are
normally at most 1,500 UTF-8 bytes, never contain images, and retain report or
JSON artifact paths for longer transcripts, search hits and doctor details.

Python helper for a visual review hint:

```python
from crystal_ball.senses.see import odd_shot_out
hints = odd_shot_out(normalized_embeddings, frames, threshold=0.4)
```

Distinct shots can be intentional. The helper returns WARN hints, never FAIL.

## Hermes install

Choose your existing profile and run the copy installer from this checkout.
It vendors `crystal_ball` inside this plugin and never invokes pip or changes
the shared Hermes interpreter. Its temporary import path is restored after
loading the package; engine dependencies stay in their configured runtimes.
The host still needs the lightweight base dependencies NumPy and Pillow.

```sh
export HERMES_HOME="$HOME/.hermes/profiles/media"
python3 scripts/install_hermes.py --hermes-home "$HERMES_HOME"
# Optional initial config source (existing configs are always preserved):
# python3 scripts/install_hermes.py --hermes-home "$HERMES_HOME" --config-from ./local.toml
# Edit the profile config to point to your engine interpreters/models.
export CRYSTAL_BALL_CONFIG="$HERMES_HOME/crystal-ball.toml"
hermes plugins enable crystal-ball
# To remove this installation later:
# python3 scripts/install_hermes.py --hermes-home "$HERMES_HOME" --uninstall
```

The manifest records installed files and newly created directories. Reinstall
updates only unchanged files previously installed by this script. Uninstall
removes recorded, unchanged files and empty created directories; modified files,
pre-existing config and unrelated content are preserved and reported. Disable
the plugin before uninstalling and restart Hermes after install/uninstall.

If replacing the earlier `video-quality` plugin, first run
`hermes plugins disable video-quality` in the same profile to avoid duplicate
automatic checks. Start a new Hermes session and check `hermes plugins list`.
One tool, `crystal_ball`, exposes `check`, `transcribe`, `find`, `index`,
`read_text`, `beats`, `scenes`, `cuts`, `fix`, `doctor`. Example:

```json
{"action":"check","file":"/media/render.mp4","mode":"quick"}
```

Hooks queue debounced quick checks of newly modified videos, with at most two
concurrent background jobs. Discovery runs outside the hook hot path; it
prioritizes explicit output paths and bounds directory scans. Results inject
once per revision. Both `pre_llm_call` and `pre_verify` remind about unchecked
renders or unacknowledged FAILs: at most once per file per session and three
reminders total. A foreground check acknowledges that revision. Hooks fail
open; tested hot paths take under 200 ms. These reminders are advisory and
cannot prevent the agent from finishing. The skill caps critique at two rounds.

## Verification and development

```sh
python -m pip install -r requirements/test.lock
mkdir -p .test-tmp
TMPDIR="$PWD/.test-tmp" python -m pytest --basetemp=.test-tmp/pytest -q
python scripts/privacy_scan.py
# Uses configured local models; never downloads:
CRYSTAL_BALL_LIVE=1 TMPDIR="$PWD/.test-tmp" python -m pytest \
  --basetemp=.test-tmp/live -m live -q
# Milestone 2 engines only (set rhythm.python and scenes.python first):
CRYSTAL_BALL_LIVE=1 TMPDIR="$PWD/.test-tmp" python3 -m pytest \
  --basetemp=.test-tmp/live-detection tests/test_live.py \
  -k 'rhythm or pyscenedetect or cut_sync' -q
```

The 29 original quality tests and 18 search/fallback tests are ported to the
new layout, alongside new coverage. Contracts intentionally changed: generic
configured rule globs replace profile-specific discovery; protected globs
replace implicit approved-reference scanning; pixel fixes are now manual;
whisper.cpp arguments come from config; `pre_llm_call` also sends capped finish
reminders. Direct synthetic-media tests still verify signal/OCR behavior,
new-file fixes/rechecks, cache invalidation and index atomicity. Tests isolate
auxiliary providers when checking unrelated orchestration; those stubs are
not evidence of real ASR or provider inference. Live tests are opt-in.

Build distributable archives offline, with account ownership removed from tar
metadata and all archive members privacy-scanned:

```sh
python -m pip install -r requirements/build.lock  # user-run, if needed
python scripts/build_release.py
```

The wheel also carries pinned setup recipes, example config, plugin and skill
under the interpreter's `share/crystal-ball/` directory, including the copy installer. The source archive
includes tests, docs, CI and scripts. A plain unnormalized source-archive build
can inherit account names; use the release script before publishing.

The privacy scanner examines tracked and non-ignored untracked publishable
files. It excludes git internals and ignored runtime/test/build caches; it
rejects unexpected binaries, private paths, personal identifiers, non-placeholder
emails and common secret patterns. Add private denylist terms using
`CRYSTAL_BALL_PRIVACY_DENYLIST=/path/to/private-denylist.txt` (one per line;
never committed). This heuristic is not a secret-management guarantee.

## Limits and licence

Sparse frames cannot establish continuous motion or lip-sync. ASR and mix
measurements cannot constitute listening. OCR may miss stylized, brief or
small text, and fuzzy spelling is a hint. Safe-zone FAIL requires a line with
at least three alphanumeric characters, confidence at least 70 and presence
near the border in two sampled frames, or an OCR-corroborated safe-zone confirmation by the
judge; otherwise it is WARN. Findings are deduplicated and capped in the
compact presentation. An unprobeable file gets a WARN report with a SKIP,
not a fabricated clean decode. No performance guarantee is made for a
particular GPU, model, machine or clip.

MIT; see [LICENSE](LICENSE) and [third-party notices](THIRD_PARTY_NOTICES.md).
Models and external binaries are user-installed, not bundled.
