# Maintainer release procedure

This is a maintainer checklist, not an automatic deployment or authorization to
install a plugin. See [CONTRIBUTING.md](CONTRIBUTING.md) for prerequisites and
commands and [CHANGELOG.md](CHANGELOG.md) for changes. Application design
belongs to app-design; application code/tests/as-built records to app-developer;
routine documentation and repository hygiene to motion-studio-maint. The current published release is v1.2.0; this document does not
create a new release or claim new inference/UI qualification.

## 1. Select and freeze the candidate

- Confirm gh api user --jq .login matches the authorized repository owner and
  origin matches the intended public Crystal Ball repository.
- Fetch origin/main, inspect status/index and divergence, and coordinate existing
  WIP. Stay on main in the primary checkout. Never stage unrelated files, use
  worktrees/side branches, rewrite history or force-push.
- Release only a reviewed, committed candidate. A dirty source archive is not
  evidence for the commit being tagged. If other owners have WIP, defer the build
  until coordinated; scripts/build_release.py reads working files.
- Have app-developer implement any version/code changes against the applicable
  app-design input and supply actual verification/as-built records. Check package,
  CLI and manifest versions agree. Update a dated Keep a Changelog entry; do not
  turn unfinished WIP into a released feature claim.

## 2. Verify without touching the live host

Use a dedicated development environment and approved scratch; set TMPDIR, TMP
and TEMP there. Install requirements/test.lock and requirements/build.lock only
in that environment, not Hermes's live environment. Provide the external tools
listed in CONTRIBUTING.md. Record the candidate SHA, interpreter/tool versions,
commands, failures, skips and evidence paths.

- Run the non-live Linux pytest suite and scripts/privacy_scan.py exactly as in
  .github/workflows/test.yml. Inspect actual Linux and Windows jobs for the same
  candidate SHA.
- On native Windows run scripts/windows/verify.ps1 with the dedicated Python and
  approved scratch. Do not equate Linux wheel resolution with native verification.
- Run python scripts/build_release.py in the dedicated environment. It stages
  selected source under approved temporary storage, writes dist/, normalizes the
  source archive and scans wheel/source members. Inspect dist/build.log and actual
  archives. Exclude credentials, private data, model weights and bytecode.
- Install the candidate wheel only in a separately authorized disposable test
  environment and exercise installed imports/CLI and the Windows wheel smoke
  described in CONTRIBUTING.md outside the checkout. Record exactly what ran.
- Optional real inference, production GPU and installed Hermes UI acceptance are
  separate tests requiring authorization. List unverified acceptance explicitly;
  neither offline CI nor a build proves them. Do not silently download models.

## 3. Publish an immutable, verified release

Review and commit only intended files; run git diff --check and inspect the
staged diff. Push main only after applicable tests pass. Read back origin/main
and the GitHub commit and require the reviewed SHA. Wait for exact-head CI;
stop on failures and delegate application fixes to app-developer.

Use a new version/tag (v plus the package version); never replace an existing tag
or release asset. Create an annotated tag at the verified candidate, push that
explicit tag and verify its peeled SHA remotely. Create the GitHub release with
an explicit tag, target SHA and reviewed notes, uploading only the inspected
wheel/source artifacts. Record SHA256 hashes of the exact uploaded bytes. Read
back release metadata/tag/asset names, then download assets to approved scratch
and compare SHA256 values. A successful upload response alone is not verification.
Do not upload build logs, private evidence or generated media as release assets.

## 4. Downstream use and rollback

Consumers use a release asset URL plus SHA256, not a local wheel path. A Crystal
Ball release does not qualify Foresight or Motion Studio on either platform.
Foresight cannot be pinned in Motion Studio until complete, working and tested
on both native Windows and Linux, including required host/UI acceptance.

For a defective release, stop promotion, document the affected version and advise
an explicit known-good version. Make a new corrective version via app-developer;
do not move tags, overwrite assets, rewrite history or self-update installed
plugins. Keep user reports/data intact. Any Nous catalog change is a separately
reviewed exact-SHA PR requiring the owner's exact payload approval before posting.
