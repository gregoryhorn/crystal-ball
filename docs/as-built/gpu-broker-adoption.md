# Shared GPU broker adoption

Implemented on clean primary `main` baseline `20afa63bd7bbaabc3c4ed9522414d453b6cd6c1c`; delivered by the local commit containing this record. Scope: Crystal Ball only; no deployment, service calls, push, release or other-repository edits.

Design input: app-design's canonical `design-documents/gpu-broker/DESIGN.md` r1, SHA-256 `9433b3d610788784808987b768c6dbd7fdb984b1442546698f6c1af2dab89c50`, plus `spec/integrations.md`, `spec/lease-contract.md` and `quality/acceptance.md` (the acceptance file is under `quality`, not `spec`). Acceptance scope here is A15 and affected A09/A23 boundaries, not full cross-tool adoption.

- `gpu.Session` optionally imports the separately installed machine-local `gpu_broker.acquire`, requests nonblocking authority and retains its auto-heartbeating handle. No public dependency or host paths were added. Import/admission failures select CPU with `fallback_reason`; legacy `admit()` intentionally always selects CPU because a tuple cannot own a lease. No CUDA telemetry is used.
- `see.cmd_index` and `cmd_query` retain lazy authority before CLIP load through embeddings, including early-return/error cleanup. Cleanup synchronizes, moves owned models to CPU, drops retained references, collects garbage and empties the torch allocator before broker completion/release. Direct internal `load_model()` users must call `close_models()` in `finally`, or use `model_work`; commands already do so. One-time load/inference OOM CPU retries remain.
- `hear_worker` reacquires for each CUDA request, consumes the transcription generator and unloads/destroys only its CUDA cache before completion. CPU models remain cached. OOM cleanup precedes the one-time CPU-int8 retry; failed cleanup still permits CPU retry but retains GPU occupancy. It does not import torch for CTranslate2 cleanup. API reference: https://opennmt.net/CTranslate2/python/ctranslate2.models.Whisper.html (`unload_model`, default fully unload; runtime destruction follows).
- Failed cleanup or broker completion validation never releases: the heartbeat stops and durable occupancy remains for broker reconciliation. Diagnostics go to stderr and successful result objects may include `cleanup_reason`. Persistent CUDA runtime/context memory can make completion uncertain even after tensors/models are gone. No claim of live successful release is made.

Verification: system Python/pytest; fake models, broker handles and isolated scratch artifacts. Non-live fixture substitutes an unavailable broker by default so tests cannot open production broker state. All existing behavior assertions remain except the explicitly changed legacy tuple-admission contract; OOM tests now inject a retained lease instead of bypassing admission.

Reproduce with `PYTHON` pointing to an interpreter containing the existing test requirements, `BROKER_SRC` to the optional broker source directory, and `SCRATCH` to the executing profile's scratch directory:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$BROKER_SRC" "$PYTHON" -m pytest -p no:cacheprovider --basetemp="$SCRATCH/cb-final" -m 'not live' -q
PYTHONDONTWRITEBYTECODE=1 "$PYTHON" scripts/privacy_scan.py
git diff --check
```

Observed: focused suite initially 18 passed (0.29s). Final full non-live suite after additional cleanup regressions: **207 passed, 8 deselected, 10 subtests passed in 25.51s**, exit 0. Privacy scan: PASS, 91 publishable files, zero findings, exit 0. AST measurement across changed Python files: largest function 81 lines (`cmd_index`); diff whitespace check passed. The supplied broker scratch venv lacked numpy (two collection errors, exit 2); the already provisioned system interpreter ran the suite without installing anything.

- Follow-up regression: CLIP's original CUDA-unavailable CPU decision is
  preserved after a broker grant and before model transfer. Checking availability
  before admission was rejected by the existing no-CUDA-on-denial regression;
  that guard remains unchanged. The new unavailable-CUDA test initially returned
  CUDA and failed. It now selects CPU and completes/releases the unused lease.
  Fake CUDA-lifetime fixtures explicitly advertise availability; the denied path
  still never touches torch.cuda, and no safety assertion was weakened.

Final parent verification after the CUDA-unavailable follow-up: **208 passed,
8 deselected, 10 subtests passed in 24.45s**, exit 0, using `/usr/bin/python3`
and the same non-live selection. Focused admission/session verification: 22
passed in 0.23s. The broker checkout's three fake-based integration tests also
exercise actual Crystal Ball/Breeze admission against the real broker core;
this extends the earlier repository-local boundary, not to live CUDA/services.

Original implementation limitations: no live CUDA, local model, installed plugin, production state or
live service integration was exercised. The broker's per-process-zero-memory completion rule is intentionally not weakened; persistent runtime memory can retain uncertainty until process exit/reconciliation. Other GPU callers and service capability gaps remain outside this repository's adoption claim.

## Idle-only installed candidate activation, 2026-11-13

Goal: activate the existing candidate only after its documented gates pass,
without GPU work or restarting protected/shared services. Design input remains
canonical app-design `gpu-broker/DESIGN.md` r1 (digest above) and
`spec/integrations.md` r1, Crystal Ball section. User separately authorized
idle-only activation/restart; no broker acquisition was authorized here.

- Clean primary `main`, candidate `1b7ff76`, sole worktree. Re-ran the documented
  non-live command with `/usr/bin/python3`, broker source
  `/home/gregory/Projects/gpu-broker/src`, and profile scratch basetemp:
  **208 passed, 8 deselected, 10 subtests passed in 24.09s**, exit 0.
  Privacy scan PASS (91 publishable files, zero findings); whitespace gate passed.
- Verified existing deployment at
  `/home/gregory/.hermes/profiles/video/plugins/crystal-ball`. All vendor files
  matched their installation manifest; only `gpu.py`, `senses/hear_worker.py`
  and `senses/see.py` differed from candidate. After tests, backed up those
  files and the manifest under the deployment's
  `backups/gpu-broker-20261113T040939Z/`, copied exactly these three candidate
  files, and updated only their manifest digests. Exact bytes and manifest
  entries were read back successfully. No skill, config or AGENTS edits.
- No Crystal Ball/hear user/system units were installed or loaded. Exact
  `/proc` CLI/module process matching found no active Crystal Ball worker/CLI
  immediately before writes; post-check also found none. There is no persistent
  Crystal Ball service/idle API to restart. No shared Hermes gateway restart
  was needed: tool dispatch starts fresh workers from the vendor tree. This
  establishes process absence, not a service-supported busy/idle handshake.
- From outside the checkout, installed-vendor `python -m crystal_ball --help`
  exited 0. Both configured hear and see interpreters imported that vendor
  `crystal_ball.gpu` with the new `Session` API; disabled sessions returned CPU
  with no handle, without importing torch/faster-whisper or calling acquire.
- **GPU admission is not yet operational in these engine environments:**
  `gpu_broker` was not importable in either configured interpreter. Existing
  fallback therefore remains fail-closed CPU until the optional machine-local
  helper is made importable there. Foreign-engine environment construction
  removes inherited PYTHONPATH, so a gateway-only path injection is insufficient.
  No dependency/environment changes were made here. The absence of a global
  crystal-ball executable also remains unchanged; the module entry point works
  with the installed vendor import root.

Activation is verified for newly spawned CLI/workers, not an in-memory gateway
reload or live GPU inference/release. No production acquisition, GPU model job,
unload test, stop, restart, kill or push was performed; vLLM/PRISM were untouched.
The parent owns broker initialization and the single live integration check.
