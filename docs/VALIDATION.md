# Validation — 2026-10-07

This records development evidence and dated fnOS diagnostic results. Successful real-camera export and end-to-end delivery have not been demonstrated.

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

First Linux AMD64 image build failed while fetching Ubuntu packages from archive.ubuntu.com through the local fake-IP network, before SDK installation. Retry uses official HTTPS repositories and apt retry/cache, with unnecessary developer packages removed. Retry built the image, then explicit SDK startup exposed TIFF ABI5 and GTK3 omissions in vendor dependencies. Added pinned official Ubuntu compatibility package and loader/help checks; final result below.

## Commands and final results

- Full suite after original-worker integration: `PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q` → **30 passed in 50.06s**. Later review fixes will be recorded separately.
- `npm ci` + `npm run build` → TypeScript and Vite success (83 modules); repeated after UI/proxy edits.
- Legacy AST-only syntax check → success.
- `ruff check backend/bridge backend/convert_job.py backend/tests --select F` → all checks passed; new Python code formatted.
- `docker compose --env-file <example-env> config --no-env-resolution -q` → exit 0.
- `git diff --check` → exit 0.
- Fresh whole-branch review found seven important gaps; failing regressions reproduced cancellation after verify, unfinished replacement lineage, restart scope, folder-only API coupling, stream truncation retryability, replacement permission isolation and default automatic photo exclusion. Fixes implemented and targeted tests passed. Metadata priority/regeneration, projection blocking and workspace-space tests also added.
- Updated full suite: **39 passed in 50.66s**; frontend build **84 modules, 328 ms**; AST, ruff F and diff checks passed.
- Linux AMD64 Docker image built successfully after loader corrections. `ldd` has no missing libraries; actual `MediaSDKTest -help` prints **SDK version 3.1.5**, model-root and native CLI flags, exits **255** as expected from vendor input validation. This proves loader/help startup on local emulation, not GPU/media conversion.
- GitHub Actions permissions readback: **enabled=false**. No Actions run or deployment performed.
- Second fresh independent whole-branch review re-ran 39 tests and found validation retry stuck on invalid bytes and resumed replacement trusting stale new-asset verification. Both reproduced with failing regression tests and fixed: pre-upload validation restarts conversion, unresolved remote intent retains lineage, replacement resume verifies new remote content and availability before old mutation.
- Final code suite: **41 passed in 50.69s**; frontend **84 modules, 339 ms**; ruff F, AST and diff checks passed. Backend image rebuilt with final source, exit 0.
- Latest browser fixture smoke: API-source switch persists independently; automatic-photo toggle defaults off; per-job pause/resume and error filter work; size percentage/ETA removed. Blob-download click had no browser console error but IAB download event was not observable (two timeouts), so saved-file behavior remains a browser acceptance item; no claim that download was verified.
- Follow-up review **approved code commit 39ba803**, independently running **23 targeted tests**, with no unresolved Important findings. Declined real GPU/camera/server and browser download completion as lacking evidence.
- Original checkout master fast-forwarded to 39ba803 and pushed to origin; immediate ahead/behind readback **0/0**. Final source remains in the user checkout. No NAS deployment.
- Final container smoke: actual image Python bridge imports and Flask authenticated status passed (unauthenticated401/authenticated200); private SDK vendor copy in user checkout rehashed to the expected SHA-256. Compose validation repeated successfully.
- Original-checkout clean frontend `npm ci && npm run build`: **84 modules, 359 ms**; merged-checkout backend: **41 passed in 50.72s**, legacy AST success.

## Remaining acceptance

Real Linux NVIDIA conversion and actual INSV pair/single-file/INSP camera modes; model-dependent features and output-size/codec limits; actual Immich version/permissions, API upload/server-original verification and association migration on the target deployment; panorama playback after Immich transcode. The earlier development suite used no real media, API keys or NAS system. Subsequent authorized runtime checks are recorded below. Actions stay disabled; push is source control only.

## English interface and documentation

- Translated the bridge settings, job details, table labels, application help, README and approved design specification into English. Displayed dates/times use `en-US`; conversion and delivery behavior are unchanged.
- Clean `npm ci && npm run build` passed. After formatting, repeated build passed with **84 modules, 323 ms**. `git diff --check` passed.
- Scanned all Git-tracked UTF-8 text files for Chinese ideographs: no matches. The HTML document already declares `lang="en"`.
- Rendered production build in the in-app browser against a temporary localhost fixture. Verified English dashboard, expanded integration settings, job receipt/event labels and date/time display. Saved an English settings screenshot outside the repository. Fixture state did not invoke Immich, SDK conversion or production actions; temporary preview was stopped after inspection.
- Backend tests were not repeated for this text/locale-only change. The prior backend acceptance limits above still apply.

## Authorized fnOS manual deployment and real SDK diagnostics

On 2026-10-07 the user authorized NAS deployment, its NVIDIA GPU, highest-quality H.265 and end-to-end debugging. Deployed backend/frontend images from source `77ae26a` as Linux AMD64 on fnOS. Frontend HTTP 200, unauthenticated status 401 and authenticated status 200; automatic processing off, zero jobs. Verified source/key mounts read-only and separate SSD config/state volumes and HDD workspace. Private deployment paths and credential references are recorded in SJOPSWiki.

Read-only Immich API checks verified version 3.2.4, the requested account, and 90 indexed INSV assets. The live server uses `/data`, requiring `/data` -> `/sources`. Three short X6 sources contain two HEVC Main10 3840x3840 tracks at 50 fps, AAC stereo, BT.2020/HLG. No source files were modified or downloaded to the development machine. Existing inbox credentials were used in process memory for initial identity/search diagnostics only. The user subsequently approved the dedicated bridge key's exact scope in local Chrome; it was created, backed up to Bitwarden and installed read-only on fnOS. No credentials enter Git.

Requested profile is fixed 7680x3840, 200 Mbps, H.265, AI stitching, FlowState, direction lock, Stitch Fusion and CUDA enabled. This is **not a validated highest-quality export**. The current bridge has no 10-bit/software-codec profile flags; standalone diagnostic SDK commands tested them without modifying the conversion algorithm or production configuration.

Actual SDK 3.1.5 tests on the Tesla P4 (driver 580.142) failed:

| Controlled diagnostic | Result |
| --- | --- |
| Requested 8K AI/H.265, explicit 10-bit, hardware codecs | Exit 139; CUDA decoder OOM and renderer errors; invalid MP4 |
| Same with software decoding, GPU stitching/encoding retained | Exit 139; OpenGL invalid-value/operation/framebuffer errors |
| Software decode with Immich ML temporarily stopped; 0 MiB GPU used before run | Same renderer failure; ML restarted and health verified |
| Omit explicit 10-bit export flag | Same failure; SDK still selects its SDR10 path for these sources |
| Simplified 4K optflow/software decode; omit stabilization/fusion | Same failure |
| Same simplified profile with a second source | Same failure |
| Same SDK/source/profile under vendor-supported Ubuntu 22.04 dependencies | Same failure; production Ubuntu 24.04 alone does not explain it |

NVIDIA GL context logs identify Tesla P4 and OpenGL 4.3; real driver EGL/GLX libraries are mounted. `GLEW initialization failed` precedes invalid GL operations and segmentation fault. Outputs are 44-byte MP4 headers with no `moov` atom; ffprobe rejects them. Reducing resolution and freeing VRAM did not resolve the renderer failure, so it is not established as a simple VRAM-capacity problem. The corresponding [vendor issue #50](https://github.com/Insta360Develop/Desktop-MediaSDK-Cpp/issues/50) contains a 3.1.5 headless regression report with matching errors. That report is a lead; exact binary root cause and a working fix remain unverified.

The Ubuntu 22.04 diagnostic image and copied private SDK live outside Git. No NAS driver/daemon change, Immich database write, original mutation or failed-output upload occurred. Native success, 10-bit/color fidelity, panorama playback, actual upload/hash verification/cleanup and real dedup/replacement remain outstanding. Automatic processing must stay off until those checks pass.

## Dedicated-key integration and original-worker failure test

- The actual server returns `v3.2.4` from `/server/about`. Identity succeeded directly but the bridge rejected that release prefix. A real loopback HTTP regression failed before the minimal optional-`v` parsing fix; both bare/prefixed versions now pass, while unsupported 2.x, 3.1 and unknown versions still reject. Conversion code is unchanged.
- Fresh backend validation after this fix: `PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q` → **46 passed in 21.05s**; ruff F, legacy AST and diff checks passed. The deployed module's SHA-256 matches the checkout. No frontend source changed in this fix.
- Dedicated-key `/users/me`, `/server/about` and authenticated bridge status returned 200 for the expected account. The bridge reports connected to `v3.2.4`.
- A controlled folder scan selected one 15.4 MB, approximately 0.6-second X6 source. The bridge dispatched it through the original worker with the requested fixed 7680x3840, 200 Mbps, AI/H.265 profile. The native process aborted (worker return **-6**) after CUDA/OpenGL errors. The job persisted `failed` / `converting`, with no asset ID, ownership or verification proof. Controller/native logs are visible in local Chrome. This pipeline test did not produce an accepted export or upload.
- Source SHA-256 before and after the job was identical. Restored API discovery settings afterward; automatic processing remains off, with no active tasks.
- A subsequent real bridge API discovery persisted **123 source records** and an upper-bound watermark. The already stable test source reused the existing job; job count remained one. This verifies index/watermark persistence and rediscovery reuse for that failed source, **not completed-export deduplication**. No broad library conversion was triggered.
- All four Immich core containers remained healthy. Runtime state/config were snapshotted separately from Git; recovery references and image identities belong in SJOPSWiki.

End-to-end acceptance is still blocked at native SDK conversion. Upload/server-original hash verification, local cleanup, completed/restart deduplication, replacement and panorama playback cannot be claimed from this failed run or the simulated tests.

## Setup/control usability repair — 2026-10-07

Review scope and reproduced defects are recorded in `docs/UI_REVIEW.md`. Superpowers debugging, regression-first changes and a separate read-only follow-up review were used; the final reviewed patch had no remaining verified Important issue in this scope.

- Full backend: **61 passed in 18.42s**. Fifteen new setup/control regressions cover private key storage/readback, blank-key preservation, invalid/form-wide Save, persistence failure, draft-only ratio calculation, target invalidation/reverification, busy selected work, unreadable secrets and discovery/thumbnail cancellation.
- Frontend: clean `npm ci`, **10 React tests passed**, TypeScript and Vite production build passed. API responses are the external test seam; actual App/BridgePanel/query cache are exercised. Verified red/green for polling overwrite, partial Save, cancelled/reopened ratio callback, numeric clearing and slow-status Save/reopen. Final assets: `index-CDq7Oc6c.js`, `index-CnEwtNUs.css`.
- Python ruff F, original-worker AST syntax and `git diff --check` passed. The original conversion worker is unchanged.
- Local Chrome with isolated Flask/SQLite fixture: Cancel clears entered dummy key and URL edits; interval 120 survives Save/reload; resolution 3840x1920 and ratio 3 survive immediate Save/reopen. Fixture receipts are synthetic UI evidence, not media or upload acceptance. Real credentials were not entered into the fixture.
- Native SDK GPU export/upload acceptance remains blocked as described above. These repairs do not establish successful real export, delivery, deletion or replacement. fnOS deployment continues with automatic processing off and the requested fixed H.265 recipe.

Runtime follow-up: code release `8636b8193f5bf61d69f2cf434aab8aee244c95b1` is deployed on fnOS. All 15 bridge/converter source hashes and both frontend asset hashes match the checkout/build. Authenticated settings/status and a read-only Immich connection check passed; unauthenticated status returned 401. Installed key reference and complete configuration hash are unchanged, with the requested H.265 profile and automatic processing off. Live Chrome confirms the key field/configured indicator and Cancel restoring the saved URL. One prior failed native job remains unverified with no asset; no conversion/upload was requested. Both bridge services run and four Immich core containers were healthy. Image IDs, protected pre-update backup and rollback details are recorded in the SJOPSWiki project/runbook.

## Bridge authentication repair — 2026-10-07

A new browser could click Test Connection while status authentication was pending. Only a final `/status` query error opened Login; a rejected action just displayed `Login required`. The frontend now shows Bridge Login immediately without a browser token, gates controls until status is available, and routes protected JSON API 401 responses to Login immediately without retrying status 401. Invalid `/login` responses retain the form/error; late responses using an old token cannot clear a newer login. The required backend authentication and server-held Immich key are unchanged.

Two UI regressions failed before implementation (fresh browser and rejected Test Connection); both passed after the fix. A deferred old-token 401 test failed when the token comparison guard was removed, then passed after restoring it. An independent reviewer found open settings/Stop controls remained enabled behind Login after expiry. A failing regression reproduced it; protected controls now disable while Login is open, including the connection fieldset. Fresh validation: 14 React tests, clean `npm ci`, TypeScript/Vite production build, 61 backend tests. npm reported the existing esbuild/fsevents install-script allowlist notices; test/build commands succeeded. fnOS browser/native acceptance is recorded separately after deployment.

Independent final source review found no remaining Critical/Important authentication issue; the reviewer independently reran all 14 React tests. Original-worker AST and `git diff --check` passed. GitHub Actions remained disabled. No backend/converter implementation changed in this repair.
