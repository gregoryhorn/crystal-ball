# Windows support as-built (2026-11-13)

Status: implementation in progress on main, starting at 13c62f594f5d7fa687f8a9f1ed966bc3ac41b4e9.
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

Next checkpoint: opt-in setup/packaging and final Linux aggregate checks. W01-W17 native
acceptance, actual model inference and Windows installed-host integration remain
open until real machine execution is possible under the user's permissions.
