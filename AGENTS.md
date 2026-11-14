# Agent instructions for Crystal Ball

## Scope and ownership

Read README.md, CONTRIBUTING.md and RELEASING.md before changing this repository.
Use CHANGELOG.md for user-visible changes; keep it in Keep a Changelog format.
Consult the relevant docs/as-built record for observed implementation and limits.
Do not treat historical verification as qualification of a new candidate.

app-design owns application design, contracts and acceptance plans. app-developer
owns application code, tests and factual as-built documentation. Implementation
requires the applicable app-design document and revision first; request missing
coverage rather than inventing behavior. Maintenance may update routine docs and
repository hygiene, but must not take over code or specialist-owned records.

## Git and coordination

Work only on main in the primary checkout. Inspect status and the index and
coordinate per-path writers before editing. Preserve existing WIP, including
site changes. Stage explicit paths only; do not absorb unrelated staged work.
No side branches, worktrees, force pushes or history rewriting. Confirm the
intended origin and authorized GitHub identity before publication.

## Verification

Use Python 3.11+ in a dedicated development environment with the prerequisites
and locked dependencies described in CONTRIBUTING.md. Never install dependencies
into the live Hermes environment. Use approved disposable storage and set
TMPDIR, TMP and TEMP there; keep durable evidence outside temporary storage.

With that environment prepared, run the offline tests and privacy scanner:

```sh
python -m pytest --basetemp="$TMPDIR/crystal-ball-pytest" -q
python scripts/privacy_scan.py
```

Use a fresh basetemp directory for each run: pytest may clear its contents.
For native Windows, follow the dedicated-interpreter verify.ps1 and installed
wheel smoke procedures in CONTRIBUTING.md; do not substitute Linux wheel
resolution for native execution. Release builds follow RELEASING.md.

Record the exact candidate, commands, failures, skips and missing prerequisites.
Live inference requires explicit authorization, CRYSTAL_BALL_LIVE=1 and an
explicit local engine config. Ordinary tests must not download models or contact
the production broker. Component/offline tests are not live inference or native
Hermes host/UI acceptance. Missing engines mean Not checked, never PASS.
A technical check passing does not grant creative or delivery approval.

## Safety and publication

Use generated fixtures only. Never commit real footage, transcripts, private
configs/evidence, credentials, model weights, bytecode or dependency binaries.
Preserve third-party notices, licence distinctions, atomic publication,
non-overwrite behavior and real signal/OCR checks; do not weaken tests to pass.
Do not change production profiles, runtime plugins, shared OAuth routing or
unrelated services. Maintenance must not create media or automate the live UI.
Obtain secrets only through configured authorized routes; never inspect or copy
OAuth tokens or commit secret values.

Review the explicit diff and applicable checks before pushing. Read back the
exact remote commit and changed files after publication. Tags and releases
follow RELEASING.md; never move tags or replace published assets. Every PR,
issue or comment on NousResearch repositories requires the owner's explicit
approval of the exact payload, even when own-repository publication is allowed.
