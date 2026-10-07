# Independent Insta360–Immich Integration Design

Date: 2026-10-07. Status: reviewed by the user, who authorized implementation. The latest scope reuses the existing media conversion implementation and adds only bridging and necessary compatibility adaptations. Bridge implementation and local validation are complete; evidence and the remaining real GPU/Immich acceptance boundary are in `docs/VALIDATION.md`. No deployment has occurred.

## 1. Product Purpose and Confirmed Requirements

The project orchestrates media discovery, stitching, validation, import, export replacement, and recovery between Insta360 MediaSDK and Immich. The SDK supplies stitching algorithms; FFmpeg/ffprobe handle probing and decoding; SQLite supplies persistence. These general capabilities are reused.

The existing autostitcher's conversion flow is referenced and reused directly: SDK invocation, video/photo handling, date/360 metadata injection, and thumbnails remain. Changes are limited to compatibility fixes required by SDK 3.1.5 and bridge invocation. There is no new stitching algorithm or transcoding framework. A separate process and job workspace invoke the existing converter; the old controller's discovery, scheduling, and database are not the authority for bridge state.

New code is organized around bridging responsibilities. Existing job tables, settings, thumbnails, selected-job processing, retries, and manual controls inform the UI, preserving reusable capabilities. Reused code records its origin and follows GPL-3.0. Existing licenses, attribution, and history remain. This design does not change the GitHub repository's fork identity or rewrite Git history.

The user confirmed:

- Use the locally downloaded Linux MediaSDK 3.1.5.
- Discover Insta360 originals through the Immich API or one or more folders, including subfolders.
- Stitch with configurable parameters into 360 MP4 files containing spherical metadata.
- Upload directly through the API to Immich's internal library, letting Immich control storage paths.
- Delete the bridge's local export after verifying import; retain original INSV/INSP files.
- Support deduplication, restart recovery, logs, optional intervals, and manual triggers.
- Allow changed settings to regenerate and replace previous MP4 exports.

Video is the primary acceptance target. Existing photo stitching remains as a separate INSP/JPG path. Automatic jobs default to video only; photo mode requires separate sample acceptance. Thumbnails, sorting, pagination, multiselect, concurrency settings, and batch retries remain. The old file-size ratio may estimate storage capacity; it must not determine success or impersonate real progress.

## 2. Scope and Boundaries

The design targets a single service instance, one configured Immich destination account, and multiple sources. The database records target server/account identity. Switching targets must not reuse another account's delivery receipts.

Sources are read-only. Never modify, move, or delete original INSV/INSP or camera companion files, and never write directly to Immich's database or managed directories. Remote replacement uses official APIs only for previous exports whose bridge ownership can be proven. An existing duplicate discovered during ordinary upload does not automatically grant replacement/deletion rights.

Output to the Immich library means API import, not direct writes to `/data/library`. Use a dedicated runtime key reference rather than borrowing another application's key; values must stay out of Git, web responses, and logs.

The local Mac is for development and SDK package inspection. Actual SDK/GPU execution requires Linux AMD64. Target capabilities require measurements rather than inference from option names. Installation, NAS deployment, real media conversion, and acceptance are later operations. Source pushes do not authorize deployment.

## 3. Architecture

Retain Python, React/TypeScript, and SQLite, separating these responsibilities:

| Module | Responsibility |
| --- | --- |
| Source adapters | Incremental Immich queries, recursive folder discovery, original-path resolution or downloads |
| Media recognition/pairing | Media information, lens roles, segments, completeness, and stability |
| Jobs and scheduling | Durable jobs, settings snapshots, scheduled/manual triggers, leases, and recovery |
| Converter gateway | Isolated existing-converter invocation, SDK 3.1.5 adaptations, capability preflight, subprocesses, and logs |
| Media validation | Decodability, dimensions, duration, audio, dates, and 360 metadata |
| Immich client | Upload, duplicate checks, asset readback, original-download verification, association migration, and soft deletion |
| Logs and control API | Job events, SDK logs, configuration, status, and web interaction |

One process owns bridge scheduling. Prevent multiple instances from claiming the same jobs. Conversion and delivery claim durable work. The existing worker executes one explicit job in an isolated process without its legacy scanner or REST service. Pin dependencies; do not install code from an unpinned GitHub branch during builds. Retain and pin the existing 360 metadata module.

## 4. Media Discovery

### 4.1 Immich API Source

Initially, query all relevant originals through `POST /api/search/metadata` and build an index. Recognition uses original filenames/extensions and media information. Do not require extracted camera branding or filter exclusively by capture date. Support extension case variations and exclude trashed/offline assets.

Regular queries use creation/update times incrementally. Creation time means the server asset-record time, not capture time. Use structured filters and cursor pagination. A pagination cursor belongs to one query, not a durable change-stream checkpoint.

Fix an upper bound per scan and use a time-overlap window. Persist asset IDs for deduplication. Advance the watermark only after reading and storing all results; failures retain the old watermark. Use a server reference clock to account for clock skew. Include new assets, asynchronous metadata updates, and known unpaired sources in matching checks.

Initial full discovery, routine incremental discovery, and periodic full reconciliation are independent. Full reconciliation defaults to daily and may be disabled or triggered manually; it addresses changes and missing assets outside time windows. Incomplete pagination cannot establish that an asset disappeared. Time windows do not provide strict change-stream completeness, so full reconciliation remains necessary.

Explicitly choose original access:

1. **Read-only mounts:** map Immich `originalPath` prefixes to bridge container paths. Use the longest matching prefix; reject paths outside mappings and path escapes. Use the current path returned by the API, not hardcoded Storage Template dates.
2. **API downloads:** when local access is unavailable, download into the bridge's temporary cache and verify server content fingerprints/completeness. On API failure, do not guess paths or silently switch to an unconfigured source.

The API finds only imported media accessible to the key. Folder mode discovers files that have not been imported.

`/api/sync/stream` is not a dependency: the inspected v3.2.4 source requires a login session and explicitly rejects API keys. Key-authenticated metadata search supports this design without account passwords or browser sessions.

### 4.2 Folder Sources

Support multiple read-only roots, recursive selection, and exclusion rules. Skip hidden paths, symlinks, and the bridge's own workspace. Report absent/unmounted roots rather than creating directories and silently scanning an empty location.

Observe new files at least twice. Recognition starts after size and mtime/ctime remain unchanged beyond the stability window, defaulting to 60 seconds. Verify stat/content identity before and after conversion; do not publish changed sources. For strict copy submission, use a hidden `.copying` directory and rename after copying completes. A stability timeout alone cannot prove that an arbitrarily paused copy has finished.

### 4.3 Pairing and Identity

Folder mode prioritizes a shared directory, capture identifier, segment, and lens role. Immich mode combines original filenames, media information, and original-asset identity, accommodating renamed storage directories and separately stored lenses. Do not pair solely by the same second or adjacent directories.

Recognize single-file multi-lens and dual-file video independently. INSP recognition must not rely solely on video stream counts. Unsupported or ambiguous modes show a specific reason and wait for user input rather than guessing.

Source identity uses normalized lens roles and each original's SHA-256 bytes, including segment semantics. Paths, asset IDs, and stat snapshots remain location/cache information. Hash initially and reuse unchanged-source hashes instead of reading all bytes on every poll. Identical sources across adapters share location records; changed content creates a new source version.

## 5. Stitching Settings and SDK

Each job retains an immutable settings snapshot so changes made while it is queued do not undermine traceability. Recipe fingerprints cover effective parameters, SDK version, relevant model versions/hashes, and projection/metadata processing version. Log-level or interval changes do not trigger regeneration.

Settings cover resolution, bitrate, H.264/H.265, stitching algorithm, FlowState, direction lock, StitchFusion, and accessory correction. Advanced 3.1.5 features such as 10-bit processing and denoising require capability checks. Direction lock depends on FlowState. Missing models or feature downgrades must be visible rather than silently reported as successful application of all requested settings.

Automatic resolution considers camera, projection, and track information. A single lens track's dimensions are not automatically panorama dimensions. Unknown media requires fixed parameters. Do not upsample low-resolution sources by default. Persist actual selected dimensions in the job snapshot. High-load modes such as 8K require real samples.

User archive: `/Users/shinji/Downloads/Linux_CameraSDK-2.1.8_MediaSDK-3.1.5.zip`. The package README specifies `/opt/MediaSDK-3.1.5-linux/`, executable `bin/MediaSDKTest`, and default models `bin/models/`. The adapter permits explicit executable and model-root configuration.

Omit `-disable_cuda` when GPU processing is enabled; include it only to disable CUDA. Use the new `-model_root_dir` with a trailing `/`. Do not reuse `-disable_cuda false` or obsolete AI-model arguments.

Pass SDK arguments as an array, not a shell command. Capture stdout/stderr and native logs. Parse recognized progress where available; without a reliable percentage, show stage and elapsed time only. Cancellation terminates the process group started by the bridge, waits for exit, then handles its own temporary files. Recovery after cancellation reconfirms source/output state.

The packaged example's error callback can still exit with status 0. Success requires checks of execution errors, feature status, and actual media. Use INFO service logging with a separate SDK level. SDK `--log_file` points to a managed log path created by the bridge.

## 6. Export Validation and Import

Convert into unique temporary paths in the bridge workspace, with source identity, segment, and attempt information. Jobs do not share files or overwrite unknown outputs. Insufficient space stops conversion dispatch.

Inject 360 metadata before upload. Video checks include complete decoding, selected dimensions and 2:1 projection, source-consistent duration/audio and decodability, capture date, readable spherical metadata, and unchanged original identity. The initial duration tolerance is `max(0.5 seconds, 2 source-video frames)`. Dual-file lens durations must agree; source audio must survive, with audio/video duration differences no greater than 0.5 seconds. Missing required probe information needs resolution, not a validation bypass. Record real SDK sample evidence before adjusting tolerances. File-size ratios do not prove success. Photos have separate image/panorama metadata checks.

Capture dates prioritize available original metadata. Filenames are a fallback using the configured capture time zone. Do not substitute container time zones or export times.

Persist export SHA-256 and Immich's SHA-1 duplicate-check checksum before upload. Successful upload returns a new asset ID, or duplicate detection returns an existing one. Read back the asset to confirm account and non-trash state, then stream the server original and compare SHA-256. An upload timeout does not trigger stitching again: check by checksum first, then retry upload if needed.

Delete local exports and eligible source-download caches only after server-original verification and a durable receipt. Cleanup operates only on ledger-linked files inside managed workspaces whose identities still match. The committed receipt ensures that local absence after restart still means completion. Interrupted deletion resumes cleanup alone.

Server receipt and web playability are separate stages. Metadata extraction, thumbnails, and transcoding can finish asynchronously and should be represented separately. Actual 360-view playback belongs to real-media acceptance.

## 7. Settings Changes and Previous Export Replacement

Skip a source when identity/recipe match and its completed receipt remains valid. Changed recipes are eligible for regeneration through single selection, multiselect, or source-based batch application. Saved defaults affect new jobs rather than automatically reprocessing the whole library. Optional automatic outdated-recipe processing requires an explicit scope. Forced regeneration with the same recipe creates another attempt/version without destroying existing receipts.

The inspected v3.2.4 public API does not offer media replacement while preserving asset IDs. A new asset takes over:

1. Keep the old version while generating and validating a new export.
2. Upload and download-verify the new asset; persist old/new IDs, settings, and fingerprints.
3. Migrate configured associations supported by available permissions and verify the result.
4. Reconfirm the previous asset is a managed export for the same target account and its bytes have not changed externally.
5. Move it to trash through the API without forced permanent deletion.
6. Complete the version transition and local cleanup.

Equal old/new IDs mean identical effective output bytes. Keep the asset and update the verified recipe-version record. A duplicate belonging to another existing asset does not establish bridge creation or authorize association mutation. Report reuse/conflict, retain the old version, and request user intervention if necessary.

Official `copy` supports albums, favorites, shared links, stacks, and sidecars. Default migration includes albums/favorites; shared links/stacks are explicit choices. Do not blindly copy sidecars over newly validated metadata. Descriptions, ratings, and tags need separately verified interfaces. Do not claim preservation of every face association, comment, edit, or reference. Asset IDs and direct links change.

Generation, upload verification, or association-copy failures retain the previous version and do not start old-asset cleanup. If a trash response is lost, read back the old asset before deciding whether it failed; avoid unnecessary regeneration/upload. A genuine failure resumes that phase only. Replacement is not a single transaction across Immich and SQLite, so temporary coexistence is acceptable and appears as an incomplete replacement. Commit every confirmed phase separately.

Use a dedicated key. Basic operations require asset read/upload/download and identity/server inspection permissions. Replacement additionally requires copy/delete and selected metadata-update permissions. Missing replacement permissions must not stop ordinary new exports; show the failed phase.

## 8. Persistence and Recovery

| Record | Main Contents |
| --- | --- |
| Target | Server identity, account ID, configuration version, and capabilities |
| Source/location | Adapter, root/API scope, asset ID, current path, stat snapshot, and synchronization watermark |
| Source group | Lens roles, segment, content fingerprints, pairing/stability state |
| Recipe | Requested/effective settings, SDK/model versions, normalized fingerprint |
| Conversion | Source group, recipe snapshot, attempt, lease, progress, output path/hash, validation report |
| Delivery/replacement | Old/new assets, creation/reuse identity, confirmations, association migration, cleanup phase |
| Event | Timestamp, job, stage, reason code, summary, log location |

Conversion states include waiting for a pair, waiting for stability, pending, running, validating, export ready, failed, and cancelled.

Delivery states include pending upload, uploading, pending verification, verified, migrating associations, retiring the old version, complete, retry pending, and manual intervention. Local absence alone does not imply failure or a need to stitch again.

On startup, reconcile leases, bridge-owned processes, temporary files, and receipts, then recover by phase. Do not kill a process solely by a saved PID, which may have been reused. Authentication failures pause target delivery; network failures use backoff. Invalid configurations and unsupported sources show correctable reasons rather than retrying forever. Mark externally deleted remote exports as missing; do not automatically recreate user-deleted content.

The legacy SQLite database is a reference format. The new schema uses explicit migration versions. Historical `processed` records do not prove verified delivery or ownership. Preserve the original database and use explicit import/reconfirmation; never perform remote cleanup solely from its status field.

## 9. Scheduling and Web UI

Automatic mode can be disabled and intervals edited. It starts off and is enabled by the user after sources/target are configured and verified. Recommended intervals are 60 seconds for incremental API checks and 600 seconds for folder scans, initially with one conversion and one upload. Do not start another scan of a source while its previous scan is running. Manual and scheduled work share deduplication/claim rules.

Manual actions include new-source checks, folder scans, full API reconciliation, selected/pending stitching, failed-job retries, delivery retries, regeneration/replacement, thumbnail generation, and cancellation. A full manual run may queue work after discovery but is distinct from discovery alone. New media may enter processing automatically once automatic mode is enabled.

Settings show sources, Immich connection/account/capabilities, read-only mappings or download mode, SDK capabilities, recipes, scheduling, and logs. Jobs retain pagination, sorting, multiselect, and thumbnails, adding source, stage, recipe version, skip/failure reason, elapsed time, import link, and replacement state.

Show last/next checks and scan summaries. Distinguish no new sources from inaccessible sources. Job logs append in real time, support pause, level filtering, and downloads, and resume by sequence number after reconnecting. Ordinary state retains existing query polling. Real-time logs can use authenticated streams or incremental requests, without an unauthenticated log endpoint.

## 10. Logging, Storage, and Runtime Dependencies

Write service logs to stdout and rotating files, events to SQLite, and SDK logs to separate attempt files. Events contain time, job/attempt, stage, reason code, and summary. Redact tokens, Authorization, sensitive configuration, and transfer credentials. Paths/media details are available only through authenticated views.

Retention is configurable: recommend 14 days for service/successful-job logs and 30 days for failures, with capacity limits. Source/recipe/receipt ledgers survive log rotation to preserve deduplication and replacement evidence. Full disks and unwritable logs must be reported rather than silently losing recovery records.

SQLite, logs, and thumbnails use a persistent state volume; media workspaces use separate capacity. SDK packages/models, secrets, real media, and runtime databases stay out of Git. Builds use pinned dependencies. Users supply SDK packages with recorded versions/hashes. SDK/model changes require capability and short-sample retesting.

## 11. Validation and Acceptance

Automated tests use temporary directories and simulated API/SDK boundaries, covering:

- Recursion, exclusions, symlinks, missing mounts, and uppercase extensions.
- Single-file/lens pairing, late lenses, colliding segment names, moves, and duplicate copies.
- Source changes, hidden copy submission, changes during conversion, and temporary-output collisions.
- Incremental time boundaries, newly imported old recordings, pagination failure, stationary watermarks, and full reconciliation.
- Recipe fingerprints, same-recipe deduplication, forced regeneration, and changed settings.
- SDK exit 0 with errors, model downgrades, and media/metadata validation failures.
- Successful uploads with lost responses, duplicate uploads, server hash mismatches, and account changes.
- Crashes around cleanup/receipts, restart recovery, cancellation, and competing schedulers.
- Equal old/new IDs, unrelated duplicate conflicts, copy/trash failures, and original-source deletion protection.

Real Linux/GPU acceptance separately checks SDK startup, short INSV, dual-lens samples when available, INSP, audio/date/projection, GPU utilization, and Immich 360 playback. Unsupported-by-evidence camera modes remain unverified. Inspect actual server capabilities read-only first, then validate upload, deduplication, copy, trash, and original downloads with controlled test assets.

The design phase established document consistency and inspected-source behavior only; it did not claim measured SDK/GPU/server compatibility.

## 12. Evidence and Next Steps

Local evidence includes repository `AGENTS.md`, current source, `docs/DEVELOPMENT.md`, downloaded archive contents, previously extracted `/tmp/insta360-sdk-inspect/MediaSDK-3.1.5-20260819-linux64/README.txt` and `example/main.cc`, and sjopswiki project/inbox/SDK/integration records. Operations notes are not live-health verification for this development task.

Official API inspection is pinned to v3.2.4. Connection preflight must confirm the actual server version:

- [Search filters, sorting, and cursors](https://github.com/immich-app/immich/blob/v3.2.4/server/src/dtos/search.dto.ts)
- [Metadata search permissions](https://github.com/immich-app/immich/blob/v3.2.4/server/src/controllers/search.controller.ts)
- [Upload, original download, and SHA-1 duplicate checks](https://github.com/immich-app/immich/blob/v3.2.4/server/src/controllers/asset-media.controller.ts)
- [Sync stream requires a session and rejects API keys](https://github.com/immich-app/immich/blob/v3.2.4/server/src/services/sync.service.ts)
- [Copy and delete APIs](https://github.com/immich-app/immich/blob/v3.2.4/server/src/controllers/asset.controller.ts)
- [Copy scope and trash semantics](https://github.com/immich-app/immich/blob/v3.2.4/server/src/services/asset.service.ts)
- [Internal upload example](https://docs.immich.app/guides/python-file-upload/)

The design specified proceeding to Superpowers writing-plans after review, defining modules/interfaces, schema, assertions, testing, and migration order. The user selects execution mode; the design phase does not automatically create agents or chats. NAS deployment is recorded separately and follows the relevant operations rules. Implementation progress and verified results are recorded in the tracked plan and validation document.
