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
| **Hear** | Local faster-whisper ASR with word timestamps, normalized script WER, missing/changed lines and names, speech gaps and voice-balance measurements. Optional whisper.cpp fallback. |
| **See** | Incremental CLIP frame indexing; text or image search; atomic index generations; an odd-shot-out Python helper. |
| **Read** | Full-size sampled OCR, line grouping, spelling hints and safe-zone evidence, including optional Arabic traineddata. |
| **Judge** | One optional vision call with a contact sheet and up to four full frames, a fixed evidence prompt, brief and at most 2 KB of Markdown rules. |

Signal checks reuse the MIT ffmpeg-skill QC implementation: decode errors,
black/frozen frames, clipping/silence, stream timing, loudness/true peak,
caption margins and delivery-platform specifications.

## Quick start

Python 3.11+, Linux or macOS, ffmpeg/ffprobe 6.1+ and Tesseract are required.
The shared artifact lock uses POSIX file locking. GPU engines are optional.

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
Built-in model loaders never download models. Setup **prints** commands, including
explicit user-run model downloads. Run only the engines you need. GPU packages
and models are not installed into Hermes by the plugin.

The hear engine receives mono **float32 16 kHz NumPy PCM decoded by ffmpeg**,
not a filename: this bypasses incompatible PyAV decoders. Its persistent JSON
worker loads each model once and can transcribe multiple files in one run.
The launcher discovers `nvidia/cublas/lib` and `nvidia/cudnn/lib` inside the
configured interpreter's prefix and prepends them to `LD_LIBRARY_PATH`.
CPU mode uses int8; CUDA uses float16. The whisper.cpp fallback uses a private
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

## CLI examples

```sh
crystal-ball check render.mp4 --platform shorts --mode full \
  --captions captions.srt --script script.txt --brief 'A readable title card' \
  --expect-text 'CLEAR TITLE' --json
crystal-ball transcribe render.mp4 --srt -o speech.srt
crystal-ball transcribe render.mp4 --vtt -o speech.vtt
crystal-ball transcribe render.mp4 --json -o speech.json
crystal-ball index ./media ./stills
crystal-ball find 'a blue sky' --top 5 --dir ./media
crystal-ball find --image reference.png --top 3
crystal-ball read-text render.mp4 --at 1.5
crystal-ball check render.mp4 --fix --json
crystal-ball doctor --json
crystal-ball setup hear
```

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

Choose your existing profile and its Hermes Python; then run these yourself
from this checkout. The build never installs into a profile automatically.

```sh
export HERMES_HOME="$HOME/.hermes/profiles/media"
export HERMES_PYTHON="/path/to/hermes/venv/bin/python"
"$HERMES_PYTHON" -m pip install .
mkdir -p "$HERMES_HOME/plugins" "$HERMES_HOME/skills"
cp -R hermes_plugin/crystal-ball "$HERMES_HOME/plugins/"
cp -R hermes_plugin/skill/crystal-ball "$HERMES_HOME/skills/"
cp crystal-ball.example.toml "$HERMES_HOME/crystal-ball.toml"
# Edit the copied config to point to your engine interpreters/models.
export CRYSTAL_BALL_CONFIG="$HERMES_HOME/crystal-ball.toml"
hermes plugins enable crystal-ball
```

If replacing the earlier `video-quality` plugin, first run
`hermes plugins disable video-quality` in the same profile to avoid duplicate
automatic checks. Start a new Hermes session and check `hermes plugins list`.
One tool, `crystal_ball`, exposes `check`, `transcribe`, `find`, `index`,
`read_text`, `fix`, `doctor`. Example:

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
under the interpreter's `share/crystal-ball/` directory. The source archive
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
