# Insta360–Immich Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task in the current session. Steps use checkbox syntax for tracking. Conversion references/reuses the existing project; new code is restricted to bridge responsibilities and required compatibility fixes.

**Goal:** Build a restart-safe bridge that discovers Insta360 originals, invokes the existing converter, verifies direct Immich uploads, cleans local copies and optionally replaces managed prior exports.

**Architecture:** New `backend/bridge/` modules own discovery, configuration, state, scheduling and Immich delivery. A subprocess gateway invokes the current `backend/auto-sticher.py` worker for one source group with a private legacy database/workspace; it does not run its scanner/server. Existing React controls are extended around the bridge API.

**Tech Stack:** Python 3.11+ / Flask / requests / SQLite, React / TypeScript / Vite, FFmpeg/ffprobe, user-provided Linux AMD64 MediaSDK 3.1.5 and pinned existing spatialmedia dependency.

**Spec:** [Approved design with latest conversion-reuse boundary](../specs/2026-10-07-immich-integration-design.md).

## Global Constraints

- Retain source INSV/INSP and companion files; source mounts are read-only.
- Only official API writes to Immich; never manipulate its database or originals directory directly.
- Replace only previous outputs proven to be managed by the bridge, using a new asset then old-asset soft deletion; never delete a source asset or blindly adopt ownership of a duplicate.
- Keep upstream GPL-3.0 attribution and current Git history; no GitHub Actions or NAS deployment.
- SDK packages/models, real media, secrets and runtime state remain outside Git.
- Default automatic processing is off; optional Immich interval 60 seconds, folder interval 600 seconds, stable window 60 seconds, conversion/upload concurrency initially 1.
- Default video profile uses the existing fixed 5760x2880 output, existing parameter controls and explicit codec choices; auto sizing remains an explicitly selected legacy option subject to verification, not a new algorithm.
- Duration tolerance `max(0.5 seconds, 2 source-frame durations)`; present source audio must be retained with output audio/video duration difference at most 0.5 seconds.
- Immich discovery uses metadata search via API Key, not session-only sync stream; capability-check the actual server version against the v3.2.4 reference.
- Tests with simulated SDK/API do not establish camera/GPU compatibility. Actual Linux/real media acceptance remains reported separately.

## Review Focus

1. Key rotation/target account changes must not reuse old receipts or expose credentials: Task 1/2 tests.
2. Older footage newly uploaded, case variants and a late second lens must be discovered: Task 3 tests.
3. Process restart after successful upload but before receipt or cleanup must not reconvert or reupload: Task 5/6 tests.
4. Identical new bytes or duplicate assets owned outside this bridge must not cause deletion of the current output or mutation of unrelated assets: Task 5 tests.
5. A missing mount, source changing during conversion or cancelling a child process must not publish incomplete output or affect originals: Task 3/4/6 tests.

## File and interface map

- `backend/bridge/config.py`: `BridgeConfig`/`StitchProfile`, validated settings and redacted public representation.
- `backend/bridge/store.py`: `Store`, schema migrations, atomic job claiming, receipts/replacement steps and events.
- `backend/bridge/immich.py`: `ImmichClient`, bounded metadata pagination, upload/check/download/copy/trash operations.
- `backend/bridge/discovery.py`: `SourceFile`/`SourceGroup`, folder discovery, mapped/API inputs, stable pairing and identity.
- `backend/bridge/converter.py`: `ConversionRequest`/`ConversionResult` and `Converter.convert(request, cancel_event, on_event)`.
- `backend/convert_job.py`: private manifest entry point importing the existing controller, explicit sources/settings, one synchronous worker invocation.
- `backend/bridge/validation.py`: upload eligibility from media probe/decode and source snapshots; no new conversion code.
- `backend/bridge/pipeline.py`: `Pipeline.process(job_id, cancel_event)` and resumable delivery/replacement.
- `backend/bridge/service.py`: scheduling, worker ownership and manual actions.
- `backend/bridge/app.py`, `backend/bridge/__main__.py`: authenticated API and service startup.
- `backend/tests/`: tests against real temp filesystem/SQLite and loopback mock Immich HTTP boundaries; test-only fixtures stay here.
- `frontend/src/components/BridgePanel.tsx`, `BridgeJobDetails.tsx`: bridge settings/actions and event details, retaining existing table/thumbnail helpers.
- `backend/requirements.txt`, `requirements-dev.txt`, Docker/Compose/env files: pinned runtime/test dependencies and new bridge entry point.

Data interfaces are dataclasses with explicit serializable fields. `SourceFile` contains location ID, original filename, lens role, resolved path, source asset ID if any, stat snapshot and SHA-256. `SourceGroup` contains identity, ordered files, segment, capture time and media kind. `StitchProfile` contains effective converter settings plus SDK/model identity; `fingerprint()` excludes scheduling/logging settings. `ConversionRequest` contains job/attempt ID, group, profile, capture time and a bridge-owned work directory; `ConversionResult` contains output path, process exit, SDK error summary, logs and effective settings.

## Task 1: Configuration and durable bridge state

**Files:** Create `backend/bridge/__init__.py`, `config.py`, `store.py`, `backend/tests/test_store.py`, `test_config.py`, requirements files.

**Interfaces:** `BridgeConfig.load(path: Path) -> BridgeConfig`, `public_dict() -> dict`, `StitchProfile.fingerprint() -> str`; `Store(path: Path)`, `enqueue(group: dict, profile: dict, target: str, force: bool = False) -> str`, `claim(stage: str, owner: str) -> dict | None`, `checkpoint(job_id: str, fields: dict)`, `event(job_id: str | None, stage: str, message: str)`. Config credentials are env/file references, never persisted raw in jobs/events.

- [x] RED: Test temp SQLite survives reopen; two claimers cannot own the same job; source/profile/target equality reuses a completed job, changed profile creates a new version, force creates a new attempt; changing target never matches prior receipts. Test interval/stability/paths reject invalid values and `public_dict` omits secrets.
- [x] Run `python -m pytest backend/tests/test_store.py backend/tests/test_config.py -q`; confirm missing behavior fails.
- [x] Implement versioned schema for source locations/groups, profiles, jobs, deliveries, targets, sync state and events; transactions and unique constraints enforce identity/ownership. Add pinned Flask/requests and test dependencies in a Git-ignored virtualenv.
- [x] Run the new tests and whole available suite; expect all pass. Commit `feat: add durable bridge state and configuration`.

## Task 2: Immich API client and target capabilities

**Files:** Create `backend/bridge/immich.py`, `backend/tests/http_fixture.py`, `test_immich.py`.

**Interfaces:** `ImmichClient(base_url: str, api_key: str, timeout: float)`, `identify() -> dict`, `search(filter: dict, cursor: str | None = None) -> dict`, `find_checksum(sha1: str) -> dict | None`, `upload(path: Path, capture_time: str, sha1: str) -> dict`, `asset(asset_id: str) -> dict`, `download(asset_id: str, destination: BinaryIO) -> str` returning streamed SHA-256, `copy(source_id: str, target_id: str, options: dict)`, `trash(asset_id: str)` with force false. Errors carry sanitized reason/status and retry classification.

- [x] RED: Use a real loopback HTTP fixture to test API base normalization, x-api-key headers, structured search/cursor pages, multipart streaming file bytes and dates, SHA-1 duplicate responses, downloaded SHA-256, 401 versus retryable 503, copy options and non-force deletion.
- [x] Run `python -m pytest backend/tests/test_immich.py -q`; confirm failures before implementation.
- [x] Implement timeouts/TLS validation, bounded downloads and sanitized failures; identity/version check records server and account, and permission failures disable the corresponding action without disabling plain discovery/upload.
- [x] Run client tests and whole suite; commit `feat: add verified Immich API client`.

## Task 3: Incremental and recursive discovery

**Files:** Create `backend/bridge/discovery.py`, `backend/tests/test_discovery.py`.

**Interfaces:** `discover_folders(config: BridgeConfig, store: Store, now: float) -> list[SourceGroup]`, `discover_immich(client: ImmichClient, config: BridgeConfig, store: Store, full: bool = False) -> list[SourceGroup]`, `resolve_original(original_path: str, mappings: list[dict]) -> Path`, `source_identity(files: list[SourceFile], segment: str) -> str`. Reuse legacy media probes through the converter boundary instead of inventing camera format parsing.

- [x] RED: Test nested discovery, exclusions/hidden/symlink rejection, missing read-only root, extension case, source change during hashing, same-second different segments, late lens pairs, duplicate copies and moved files. Test path mappings refuse traversal/escape and use longest prefix.
- [x] RED: Test first full API discovery, old capture date with recent createdAt, updated source locations, overlapped time boundary, late metadata, pagination failure leaving watermarks unchanged and incomplete full scan not marking assets missing.
- [x] Run `python -m pytest backend/tests/test_discovery.py -q`; inspect expected failures.
- [x] Implement persisted observation times/stat, source SHA-256 and canonical lens/segment groups. API watermark upper bound comes from server reference time; default overlap 300 seconds, advance only after full successful persistence. Daily full API reconciliation is separately scheduled. Downloads are temporary source caches and never mixed with managed originals.
- [x] Run discovery and whole suite; commit `feat: discover stable Insta360 sources incrementally`.

## Task 4: Gateway to existing conversion and SDK 3.1.5

**Files:** Modify only necessary conversion compatibility points in `backend/auto-sticher.py`; create `backend/convert_job.py`, `backend/bridge/converter.py`, `validation.py`, `backend/tests/test_converter.py`, `test_validation.py`.

**Interfaces:** `Converter.convert(request: ConversionRequest, cancel_event: Event, on_event: Callable) -> ConversionResult`; `validate(result: ConversionResult, group: SourceGroup, profile: StitchProfile) -> dict`. Manifest contains no secrets; gateway returns JSON result/exit and separate captured logs.

- [x] RED: Test fixed SDK executable, GPU mode omitting `-disable_cuda`, explicit disable mode, model root ending `/`, AI model checks, metadata injection failure preventing success and manifest sources/settings reaching the legacy worker. Test unique task workspaces prevent legacy timestamp collisions.
- [x] RED: Test SDK error with exit 0 fails upload eligibility; decode/probe failure, duration beyond tolerance, audio loss, missing spherical metadata and changed source snapshots are rejected. Use tiny FFmpeg-generated fixtures for real validation, SDK fixtures only at subprocess boundary.
- [x] Run `python -m pytest backend/tests/test_converter.py backend/tests/test_validation.py -q`; confirm missing behavior fails.
- [x] Keep legacy `_run_job`, image/video metadata and thumbnail routines. Add only executable/model/log configuration and boolean failure propagation. Gateway loads the module in a separate process, initializes a private legacy DB, inserts one explicit source group and invokes one worker synchronously; it never calls legacy scan/server or debug-success mode. Bridge owns process group cancellation and stage/progress reporting; output size ratios remain estimates.
- [x] Pin the existing spatialmedia source to an immutable revision and preserve its provenance. Do not implement a new injector. Run tests, backend AST check and suite; commit `feat: invoke existing converter through isolated bridge gateway`.

## Task 5: Resumable delivery, deduplication and replacement

**Files:** Create `backend/bridge/pipeline.py`, `backend/tests/test_pipeline.py`.

**Interfaces:** `Pipeline(store: Store, client: ImmichClient, converter: Converter, config: BridgeConfig)`, `process(job_id: str, cancel_event: Event)`, `resume_delivery(job_id: str)`. Each external operation has persisted intent and a readback path; target account scopes all receipts.

- [x] RED: Test completed receipts skip conversion after local cleanup; network failure retains local output; upload timeout with an existing server result resumes verification; SHA-256 mismatch blocks cleanup; source paths can never be cleanup targets.
- [x] RED: Test parameter changes produce a new generation; old asset remains until new verification/association migration; new/old equal ID does not trash; a duplicate outside bridge ownership is not mutated; old checksum change stops cleanup; trash timeout is resolved by readback; crashes around every receipt/cleanup boundary resume the correct stage.
- [x] Run `python -m pytest backend/tests/test_pipeline.py -q`; verify behavioral failures.
- [x] Implement stage-specific processing, immutable profiles, streamed server verification, ownership proof and guarded local deletion. Default association copy albums/favorite only; optional shared links/stack explicit, sidecar false. Failed old-asset cleanup retries only cleanup; remotely missing outputs require user action.
- [x] Run pipeline tests and whole suite; commit `feat: deliver and replace verified Immich exports safely`.

## Task 6: Optional scheduler, manual controls and logs

**Files:** Create `backend/bridge/service.py`, `app.py`, `__main__.py`, `backend/tests/test_service.py`, `test_app.py`.

**Interfaces:** `BridgeService.tick(now: float)`, `trigger(action: str, job_ids: list[str] | None, options: dict) -> str`, `cancel(task_id: str)`; `create_app(service: BridgeService) -> Flask`. API exposes `/status`, `/tasks`, `/tasks/terminate`, `/settings/bridge`, `/settings/stitch`, `/settings/parallelism`, `/login`, `/jobs/<id>/events?after=<seq>`, `/jobs/<id>/logs`, `/thumbnails/<id>.jpg` with authentication.

- [x] RED: Test automatic off, editable interval, manual discover versus full run, non-overlapping manual/timed scans, restart recovery, cancellation process ownership, authentication on all endpoints including logs/thumbnails/settings, secret redaction and invalid action/config rejection.
- [x] Run `python -m pytest backend/tests/test_service.py backend/tests/test_app.py -q`; inspect failures.
- [x] Implement one bridge scheduler owner, persisted claims and events, bounded retry/backoff, paused target on auth failure, progress/stage status and next run times. Logs are task/attempt-specific with size/age limits; receipts survive log cleanup. Reject deletion/replacement actions outside managed outputs.
- [x] Run API/service tests and suite; commit `feat: add bridge scheduling controls and task logs`.

## Task 7: Extend the existing dashboard for bridging

**Files:** Modify `frontend/src/api.ts`, `types.ts`, `App.tsx`, `components/JobTable.tsx`, CSS and proxy configuration; create `components/BridgePanel.tsx`, `BridgeJobDetails.tsx`.

**Interfaces:** Existing polling/status/table remains; new API calls align with Task 6 routes. Public settings contain secret references/connection status, never actual Immich Key values. Settings distinguish new-task defaults from selected-task regeneration/replacement.

- [x] Add meaningful API/browser checks for secret-free settings, interval toggle/manual action payloads, selection-based replacement, resumed event polling and failure-stage visibility; reuse mature frontend tooling rather than recreate routing/table libraries.
- [x] Add source mapping/folder settings, target connection status, stitch settings, optional scheduling, scan summary, effective profile and per-job event/log details. Preserve sorting/pagination/multiselect/thumbnails and manual retry actions.
- [x] Run `cd frontend && npm ci && npm run build`; expect TypeScript and Vite exit 0. Verify in local browser with fake HTTP/SDK only; do not upload real assets. Commit `feat: expose Immich bridge controls in dashboard`.

## Task 8: Package SDK and document the completed bridge

**Files:** Modify `backend/Dockerfile`, root `docker-compose.yml`, `.env.example`, `.gitignore`, `README.md`, `docs/DEVELOPMENT.md`; create `docs/VALIDATION.md`, `backend/.dockerignore` as needed.

**Interfaces:** Compose starts the new bridge entry point and existing frontend over an internal network; backend API is not exposed independently by default. SDK deb lives in private `backend/vendor/`, supplied by user; build arg is relative to the backend context. Source mounts use `:ro`; state and work mounts are distinct.

- [x] RED/check: Validate Compose resolves ports/proxy consistently, source volumes are read-only and no SDK/media/secrets are tracked; SDK/models excluded from general context except explicitly supplied build artifact. Verify gateway dependencies are included and legacy default serve is not started.
- [x] Extract only the MediaSDK deb from the downloaded archive into Git-ignored vendor storage, recording SHA-256/version; do not install Linux SDK on macOS. Adjust Docker executable/model paths and pin conversion/runtime dependencies. Preserve NVIDIA driver/runtime boundary; no NAS driver changes or deployment.
- [x] Document startup, Key permissions, path mapping versus downloads, folder mode, manual/automatic actions, replacement semantics, logs, backups, recovery and remaining real-media acceptance. State that GitHub remains a fork and conversion code is reused under GPL-3.0.
- [x] Run backend AST check, `python -m pytest backend/tests -q`, frontend clean build, Compose validation if Docker is available and `git diff --check`. Record exact results/limitations. No claim of SDK conversion without actual Linux/sample evidence.
- [x] Review complete diff against source retention, resumability, ownership and UI requirements; fix substantive findings with regression tests. Commit intended changes and push, verify remote ahead/behind 0/0. Actual NAS deployment/real-media validation is a separate authorized operation.

## Execution and acceptance boundary

The user approved this plan and implementation in this session. Tasks 1–8 are implemented, with focused RED/GREEN tests, packaging validation and commits. Fresh full-branch reviews found substantive recovery issues; regression tests reproduced them, fixes passed follow-up review at 39ba803. Code was fast-forwarded into the user checkout and pushed with remote ahead/behind 0/0. Native inline execution is used without per-task implementer agents; the fresh whole-change review and targeted follow-up completed before final integration. Rulings and durable findings are recorded in DEVELOPMENT.md and VALIDATION.md as required by the repository memory policy.

Local success means bridge tests/builds and controlled boundary checks pass. Production readiness additionally requires the actual Linux GPU, SDK and real camera samples plus API verification on the deployed server; absent those, report that acceptance as outstanding rather than claiming compatibility.
