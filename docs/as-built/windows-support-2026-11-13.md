# Windows support as-built (2026-11-13)

Status: implemented on main and exercised on Linux; native Windows NOT CHECKED.
Starting candidate: 13c62f594f5d7fa687f8a9f1ed966bc3ac41b4e9.
Goal: native Windows support with unchanged media CLI/tool/report contracts and
honest unavailable senses. No push, tag, release, version bump, live profile
installation or profile/config changes are authorized or performed. No UI changes;
the existing Python stack is retained (NSH/GPUI Kit are not applicable).

Authoritative app-design inputs, both r1, in that profile's canonical
workspace/design-documents/crystal-ball directory:
- windows-support-2026-11-13-design.md
  SHA256 18c097aa7e121352fdba448826c803499f5f798322348d9903179955f76df3d6
- windows-support-2026-11-13-acceptance.md
  SHA256 7f21bd6b3e72a6cc223f369bce20147c70aba2f5937003a096b1e194ebd404f7

Implemented paths/storage checkpoint: platforms/paths.py, executables.py and
locks.py provide native config/model path handling, explicit trusted executable
search and bounded advisory locks/publication retry. Config accepts UTF-8 BOM,
platform CPU defaults and see.device. Reports serialize relative/drive/UNC assets;
hooks retain structured paths and native identity matching without changing
notification display paths. The fake-home Hermes installer uses confined portable
manifest keys, historical backslash validation and reparse-point rejection.

Observed Linux checkpoint command: python -m pytest tests/platforms/test_paths.py
tests/platforms/test_executables.py tests/platforms/test_locks.py tests/test_plugin.py
tests/test_privacy_and_cache.py -q -p no:cacheprovider --basetemp $Scratch/pytest.
Result: 24 passed (0.55s), exit 0. All temporary test data is in the developer
profile's cache/scratch; no models or production GPU broker were contacted.

Native Windows is NOT CHECKED. The supplied Motion Studio Windows-test-result
handoff contains no address, transport, machine path or reusable credential route;
it records only an existing UI observation. It cannot be used to execute native
acceptance. No Motion Studio requests/takes were touched. A Linux test is not
native Windows or installed Hermes UI evidence.

Privacy scan currently FAILS on 10 pre-existing private-path/name findings in
gpu-broker-adoption.md, at lines 52, 56, 95, 96 and 99. That historical record and
privacy assertions are unchanged. Archive scans are separate from repository scans.

Owned-runtime checkpoint: platforms/process.py, posix.py, windows/jobs.py and
windows/launcher.py contain process ownership; Windows target launch follows
checked self-assignment to a KILL_ON_JOB_CLOSE Job Object. POSIX nested work
inherits the outer owned stage session. util/workers/hermes/api and direct media
launches now use that boundary. Hear retains one worker and reads complete lines
through a queue/thread, not selectors. Cleanup/drains have bounded waits. Native
Win32 API declarations/assignment and host-job nesting remain unexecuted.

platforms/runtime.py chooses numpy/Pillow core work before the configured See
fallback and probes actual sysconfig sites for cache invalidation. Doctor probes
optional packages in their engine, reports executable paths/releases and CPU
configuration; See now disables broker admission for configured CPU. Engine-only
Windows DLL paths use lifetime-held os.add_dll_directory handles. No vendor source
was changed; checks.py sanitizes PATH and checks the vendor's observed selections.

Linux checkpoint: python -m pytest tests/platforms/test_processes.py
tests/platforms/test_runtime.py tests/test_second_trial.py tests/test_trial_regressions.py
tests/test_admission_install.py tests/test_gpu_sessions.py tests/test_quality.py
-q -p no:cacheprovider --basetemp $Scratch/pytest: 102 passed in 19.80s, exit 0.
This includes real child/grandchild deadline cleanup, persistent stub transport,
core/thin-host workers, actual signal/OCR fixtures and broker fakes, not models.
The unavailable-See tests now explicitly cover thin hosts because core-first
routing is the intentional design change. Inference-only mocks moved from
subprocess.run to run_owned; assertions about GPU cleanup were preserved.

## Setup and packaging checkpoint

`engines/setup/{plan,install,recipes}.py` implements the additive CLI
`setup [hear|see] --install`: one interactive confirmation, isolated managed
Windows CPython 3.11 x64 CPU generations, native VC++ prerequisite check, explicit
package/model downloads, offline probes, failed-generation records, validated
reuse, backed-up selected-key-only TOML publication and config-race refusal.
Default setup remains print-only; read --install refuses external installation.
Existing media action enum/schema and package/plugin version 1.1.1 are unchanged.

`requirements/windows/` contains complete hashed wheel-only Hear/See recipes and
separate official-index Torch CPU recipe. `scripts/windows/freeze_recipes.py`
checks target dependency markers/closure before freezing. Windows wheel downloads
and all three offline --require-hashes checks exited 0 on Linux; they do not prove
native imports. Metadata records external FFmpeg/VC++ prerequisites. Models stay
out of the core/Hermes venv; judge stays off. No live inference was attempted.

Nested locks/metadata are in wheel/sdist; README, CONTRIBUTING and example TOML
have native path, PowerShell, CPU setup and recovery instructions. Installer keys
also reject alternate-stream colon and NUL escapes. Fake-home installer checks
cover safety without modifying any actual profile. Setup/installer focused tests:
22 passed in 0.12s, exit 0 (before the final workflow harness checkpoint).

## Final Linux evidence

Commands used the dedicated scratch CPython 3.11 venv, with
PYTHONDONTWRITEBYTECODE=1, HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1.
`$Python` below is that venv interpreter and `$Scratch` the approved temporary root.
Results were observed, not supplied by fixtures as claimed external execution.

- `$Python -m pytest -q -rs -p no:cacheprovider --basetemp $Scratch/cb-final`:
  257 passed, 8 skipped, 10 subtests passed in 29.32s; exit 0. All eight skips are
  the opt-in tests/test_live.py model tests (lines 15, 37, 56, 65, 75, twice 91,
  108). No core Windows tests were broadly skipped. This is Linux evidence only.
- `$Python -m pytest tests/engines tests/windows -q -rs -p no:cacheprovider
  --basetemp $Scratch/cb-handoff-tests`: 23 passed in 1.21s, exit 0.
- `$Python scripts/build_release.py`: exit 0; wheel 87 privacy-scanned members,
  sdist 128. Build intermediates are staged under TMPDIR, not the checkout.
- Isolated wheel installed into a separate scratch venv and exercised outside
  the checkout using `python -I scripts/windows/wheel_smoke.py --scratch $Scratch`
  (script argument is its absolute source path). Exit 0: packaged resources 4;
  doctor exit 0; completed check exit 1; 5 sampled frames; contact sheet reopens;
  persisted Markdown/HTML/full.json reopen; CLI/real tool-worker counts agree:
  PASS 19, WARN 2, FAIL 1, SKIP 5. Check exit 1 is the synthetic media verdict,
  not a smoke-harness error. Optional audio is explicitly SKIP. Installed-wheel
  model inference and actual Hermes UI are NOT CHECKED. Tesseract is present on
  this Linux host; this smoke does not claim a fresh OCR-free machine.
- Changed Python source measured by AST (complete decorated/nested spans):
  405 functions, largest 100 lines, core._base_check; all <=300.
- `git diff --check`: exit 0.
- `$Python scripts/privacy_scan.py`: exit 1, 124 publishable files, 10 findings,
  all in the unchanged historical gpu-broker-adoption.md lines listed above.
  This gate remains FAIL; no scanner suppression/weakening or unrelated document
  rewrite was performed. Archive privacy passing is not repository privacy passing.

The Windows CI job and `scripts/windows/verify.ps1` are implemented, not executed
here. Wrapper requires explicit interpreter/scratch, sets offline/temp variables,
runs pytest/privacy/build, and stops at the first failure. The known repository
privacy failure will stop that wrapper/CI until separately resolved. The wheel
smoke is a separate explicit installed-wheel command documented in CONTRIBUTING;
no wrapper downloads models or installs into a profile.

Artifact SHA256 from the final local build (not a publication):

    wheel 4a9cc49fb407b9056fefc03376a148ac2f005932223180d1085f5024bc59e60c
    sdist e2dcdfe1472394982a8b4e8311e4c379388c2fb8af1d36212486a0b05b3b16e9
    hear-cpu.lock 130f086b180b22a1ec7d3b20ebb883222a438020b011347c4ae05fa77c2bb403
    see-cpu.lock d97bebfdde75fc76d8d2f6cba96a3a385998905b0b2f1c2405ded1fcde4e7d3b
    torch-cpu.lock 769da432d1658b625dc15d30c8955dc57c942880cb7f2b75a55d610d24012287

## Native acceptance still to run

All rows below are native Windows NOT CHECKED: no reusable access route is given
in the supplied machine handoff. Linux substitutes are explicitly distinguished.
Use the companion r1 acceptance commands and discovered approved Windows paths;
record edition/build, Python/tool versions, candidate and actual host backend.
This as-built is the durable execution summary/evidence; no ephemeral scratch
logs are cited as lasting evidence. W15 profile installation needs separate
permission because the present task expressly forbids profile installation.

| ID | Command/action still required on native Windows | Existing narrower evidence / limitation |
| --- | --- | --- |
| W01 | check Unicode/space/backslash/drive paths; reopen reports; BOM/model grammar and UNC parsing | Linux path units and real Unicode smoke pass; no SMB execution claim |
| W02 | fresh core-only venv check, without optional engines/OCR/broker | Linux core-first/thin-host fixtures and wheel frames/signal pass |
| W03 | doctor plus actual signal selection, old/missing tools, cwd hijack and wrapper refusal | Linux resolver/runtime units pass |
| W04 | native child/grandchild deadline, Ctrl+C, parent death, host-job nesting, denied assignment, unrelated sentinel | Linux deadline tree cleanup passes; Win32 APIs not executed |
| W05 | persistent stub worker twice on one PID, Unicode/stderr, EOF/partial/mismatched ID/timeout and handle cleanup | Linux transport fixtures pass; real Hear is separate |
| W06 | two-process NTFS Store contention, kill holder, timeout/permissions and corrupt artifacts | Linux locking/storage tests pass |
| W07 | Windows sharing violation/replacement retries, old embedding generation preserved, fix no-overwrite race/input unchanged | Linux publication/fix regressions pass |
| W08 | native consent/decline/EOF, one-confirm setup, injected pip/download/probe/config failures, reuse | Linux setup mocks/failure-injection pass, not provisioning |
| W09 | native hash-locked install/import, wheel smoke, fake-home portable manifest/reinstall/uninstall and junction escapes | Linux Windows-wheel resolution/hash verification, build, installed-wheel smoke and fake-home tests pass |
| W10 | actual CPU int8 speech transcription, word timestamps, persistent worker and Store reuse offline | NOT CHECKED on any OS in this task; no model downloads |
| W11 | actual CPU CLIP image/video index, text/image search and reopened generation offline | NOT CHECKED on any OS in this task |
| W12 | native Tesseract CLEAR TITLE/two-frame typo and absent-Arabic SKIP | Linux real signal/OCR fixtures pass, not native OCR |
| W13 | native CLI vs tool-worker check/fix semantic parity, registrations and UTF-8 budget/mandatory envelope failures | Linux contract suites and installed-wheel check parity pass |
| W14 | open cached HTML in native browser; Unicode/contact-sheet assets and saved reopen | Linux persisted files/image reopen and URI units pass; native browser not seen |
| W15 | authorized installed candidate in actual native Hermes UI; discovery/ack once per revision, reopen/session cleanup | NOT CHECKED; prohibited live profile install not performed |
| W16 | Windows non-live suite/build/privacy and measure function spans | Linux tests/build/function spans pass; repository privacy FAIL as above; Windows CI not run |
| W17 | only with separate GPU authorization: real broker/DLL tuple, leases, OOM retry and cleanup | NOT CHECKED; broker mocks only, no production GPU calls |

Alignment at handoff: changes implement the supplied Windows design without a UI
rewrite or altered media contracts. Native core/inference/host sign-off is not
claimed. Next observable outcome is running the existing native harness and the
above acceptance actions on an accessible authorized Windows machine, not a
release, version bump or deployment.

Local checkpoints: 4403a5c paths/storage; 6655a65 owned processes/core runtime;
dc78c8f consent-based setup/packaged recipes. The subsequent harness commit
contains Windows CI, verify.ps1, wheel_smoke.py, freeze_recipes.py, real Unicode
workflow tests, staged-build isolation and contributor instructions. No live
installation or remote write occurred. The final rebuilt wheel was force-reinstalled
only into the scratch test venv and reran the isolated smoke: exit 0, identical
counts and five frames. The candidate is the local main commit containing this
record (inspect `git log -1`); no release is implied.

## Debian runtime regression correction

Scope/alignment: Claude's review of 42bb427 requested both host suites green;
this correction uses the same canonical r1 design/acceptance digests above,
particularly D4's actual-site discovery and preserved core-first/thin-host routing.
`platforms/runtime.py` now combines sysconfig, site.getsitepackages() and user
site paths, normalizes/deduplicates them and excludes nonexistent/non-directories.
A deterministic regression covers duplicate/missing/file paths and system numpy
metadata. API reference: https://docs.python.org/3.14/library/site.html .

Both reported failures reproduced on /usr/bin/python3 (3.14.4). The thin-host
selection assertion actually chose the configured engine correctly: Debian's
stdlib sitecustomize.py shadowed the fixture's launch logger. `tests/conftest.py`
now uses a uniquely named .pth-loaded module for logging/module hiding.
`test_second_trial.py` uses a real no-system-packages host venv instead of -S,
asserts engine selection and preserves every stage/result/launch assertion.
Production core selection, dependencies, versions and media contracts are unchanged.

Full suites ran with PYTHONDONTWRITEBYTECODE=1, HF_HUB_OFFLINE=1 and
TRANSFORMERS_OFFLINE=1; command for each was `$Python -m pytest -q -rs
-p no:cacheprovider --basetemp $Scratch/cb-review-full314` (full311 for 3.11).
$Scratch is this developer profile's cache/scratch. Observed exit 0 for both:
- /usr/bin/python3 (3.14.4): 258 passed, 8 skipped, 10 subtests passed in 29.89s;
  two existing PurePath.as_uri deprecation warnings in report.py.
- /home/gregory/.hermes/profiles/app-developer/cache/scratch/crystal-windows-venv/bin/python
  (3.11.15): 258 passed, 8 skipped, 10 subtests passed in 28.30s.
Both skip only the opt-in live-model tests. Focused runtime/second-trial suites:
33 passed on each interpreter. Candidate: local main commit containing this
appendix, parent 42bb427; changed runtime.py and the three test files named above.
No push/tag/release/version bump/profile install. Native Windows remains untested;
this correction does not change the earlier privacy-gate limitation.
