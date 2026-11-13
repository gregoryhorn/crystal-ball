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

Limitations: no live CUDA, local model, installed plugin, production state or
live service integration was exercised. The broker's per-process-zero-memory completion rule is intentionally not weakened; persistent runtime memory can retain uncertainty until process exit/reconciliation. Other GPU callers and service capability gaps remain outside this repository's adoption claim.
