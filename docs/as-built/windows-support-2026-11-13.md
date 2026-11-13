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

Next implementation checkpoint: owned subprocess/pipe transport and core runtime,
then opt-in setup/packaging and final Linux aggregate checks. W01-W17 native
acceptance, actual model inference and Windows installed-host integration remain
open until real machine execution is possible under the user's permissions.
