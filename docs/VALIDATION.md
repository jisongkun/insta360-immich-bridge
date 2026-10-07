# Validation — 2026-10-07

This records development evidence, not a claim of real camera/GPU compatibility or NAS deployment.

## Evidence collected

- Persistent SQLite state, target/profile/source dedup, cross-thread claiming and newer-schema protection; config validation, secret references and SDK/model identity.
- Actual loopback HTTP request tests for API identity, search cursor/sort, streaming multipart bytes/dates, duplicate-check payload, original hash readback, copy and force-false trash; sanitized authentication failures.
- Recursive temp-filesystem discovery, stable observations, uppercase filenames, late lens pairs, hidden/symlink exclusions, identical content copies, path escape rejection and failed pagination preserving watermarks.
- Tiny FFmpeg-generated MP4: real existing spatialmedia injection/parse and complete decode. Wrong dimensions, duration, lost audio, missing 360 metadata, capture-date mismatch and changed sources are rejected.
- Existing conversion worker runs through a real private subprocess with a simulated SDK; capture timestamp and settings reach it. SDK stdout error with exit 0 is rejected. Cancellation terminates private process group. These are **not** real camera samples.
- Pipeline tests: cleanup followed by restart does not reconvert; uncertain upload is found by checksum; verification failure retains local bytes; managed replacements verify/copy/trash in order; same ID avoids trash; unrelated duplicates are untouched; edited predecessor blocks replacement; trash timeout resumes by readback; source/workspace cleanup guard; consecutive generations replace current predecessor; explicit missing-remote regeneration and transient retry state.
- Flask/service tests: auth across settings/status/logs/events/thumbnails, invalid settings/actions, one scheduler owner, manual coalescing, immutable recipes, interval due on attempted scans, log retention preserving receipts.
- Browser smoke test on localhost using temporary fake state (no real Immich/SDK): login through Vite proxy; save API interval 120 and automatic toggle; manual full-run dispatch; task detail with receipt/event; completed owned selection enables replace action. Existing table sort/pagination/multiselect remains. No production asset mutation.

## Packaging and SDK

Private downloaded archive: `Linux_CameraSDK-2.1.8_MediaSDK-3.1.5.zip`. Extracted only `MediaSDK-3.1.5-linux-amd64.deb` into ignored vendor storage. Bytes: 2,017,128,600. SHA-256:

```text
444b4b0bc22aa5335e5cc2c3dd092b16207f3a7c19bb7fe97799e94eca69325e
```

Deb control reports package `mediasdk`, version 3.1.5, architecture amd64, installed size about 11 GiB including models. Inspected vendor README/example for executable/model layout, trailing model-root slash, boolean flag semantics and native `--log_file`. Not installed on macOS.

Local Docker context verified `desktop-linux` with user's local Unix socket, not a remote/NAS daemon. Compose schema validation succeeded with example environment and `--no-env-resolution`; backend has no host port, source mount is `:ro`, frontend proxies backend:8008 through internal network, state/work are separate. Actual `compose up` has not run.

First Linux AMD64 image build failed while fetching Ubuntu packages from archive.ubuntu.com through the local fake-IP network, before SDK installation. Retry uses official HTTPS repositories and apt retry/cache, with unnecessary developer packages removed. Final build/load result is recorded below when available.

## Commands and final results

- Full suite after original-worker integration: `PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q` → **30 passed in 50.06s**. Later review fixes will be recorded separately.
- `npm ci` + `npm run build` → TypeScript and Vite success (83 modules); repeated after UI/proxy edits.
- Legacy AST-only syntax check → success.
- `ruff check backend/bridge backend/convert_job.py backend/tests --select F` → all checks passed; new Python code formatted.
- `docker compose --env-file <example-env> config --no-env-resolution -q` → exit 0.
- `git diff --check` → exit 0.
- Fresh independent review and final Docker build result pending.

## Remaining acceptance

Real Linux NVIDIA conversion and actual INSV pair/single-file/INSP camera modes; model-dependent features and output-size/codec limits; actual Immich version/permissions, API upload/server-original verification and association migration on the target deployment; panorama playback after Immich transcode. No real media, API keys or NAS system were accessed. Actions stay disabled; push is source control only.
