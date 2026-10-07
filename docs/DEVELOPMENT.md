# Insta360 Immich Bridge — development

The checkout began at upstream `jagjordi/insta360-autostitcher` commit `d52ef69bdcdf09c16e25d3bf425b40e5447ed6dd` on 2026-10-07. The GitHub repository remains a fork, with GPL-3.0 and upstream attribution preserved. GitHub is source control only; Actions stay disabled. The 2026-10-07 fnOS deployment is for manual testing with automatic processing off; real export acceptance is incomplete.

## Implemented boundary

New `backend/bridge/` modules own validated configuration, recursive/incremental discovery, durable SQLite claims/receipts, scheduling, authenticated API and Immich upload/replacement. The original `backend/auto-sticher.py` owns conversion, metadata injection, probes and thumbnail extraction. `convert_job.py` loads that module in an isolated subprocess, uses a private legacy DB/workspace, inserts one explicit job and calls its `_run_job`; it never starts the legacy scanner, HTTP server or debug-success mode.

Compatibility changes to legacy code are limited to SDK executable/model/log paths and flags, correctly configured thumbnail paths, explicit timezone-aware capture metadata and propagation of metadata injection failures. No new stitching algorithm or segment concatenation has been added. INSP remains JPG output, as upstream did. Distinct filename segments remain distinct jobs.

## Durable state

`/state/bridge.db` is the authority, not the legacy DB or presence of local MP4. Jobs carry immutable effective recipes, source content identities, target address/account, delivery phase and verification/ownership proofs. Claims are atomic, scoped by source+target. One process holds an OS lock for the state directory. The SQL schema is version 1; a newer schema refuses downgrade. Payload evolution currently remains in JSON.

Discovery groups by lens role, timestamp, segment and directory for folders, or target-scoped API names for Immich. It rejects ambiguous same-name/different-content roles. Stability uses persisted stat observations, then SHA-256/SHA-1 read with before/after checks. Source-content and media-probe caches avoid unnecessary rereads; API discovery still observes known paths without recursively walking the entire library.

Incremental API discovery uses the server Date as upper bound and a 300-second overlap over `createdAt`/`updatedAt`, not capture date. The full paginated result is indexed before the watermark advances; network/pagination failure does not advance it. Daily full reconciliation checks sources and completed remote receipt presence without resetting completed jobs. Filename patterns remain the upstream VID/IMG timestamp/lens/segment forms; do not infer unsupported formats.

Upload has a persisted intent and uses Immich SHA-1 duplicate checking, then validates server-original size and streamed SHA-256. Receipt is committed before local cleanup. Replacement is explicit; upload/verify → verify old bytes → copy albums/favorite (optional shared links/stack; sidecar false) → soft trash old asset. Only bridge-owned outputs can be mutated. A lost upload response can resume verification of a duplicate, but cannot invent ownership. Original asset IDs are protected from replacement; source mounts are read-only.

## API basis and SDK

The reference API is Immich v3.2.4. Verified against official source: structured search sort permits fileCreatedAt, not createdAt; pattern `.like` uses case-insensitive SQL; upload checksum is SHA-1; copying associations does not replace binary content or preserve an ID; DELETE force false is soft deletion. The sync stream rejects API keys and is not used. The client checks 3.x minor >=2; the deployed server version and read-only metadata search have been verified; upload/replacement acceptance is still required.

MediaSDK 3.1.5 was supplied privately by the user. SDK deb SHA-256 is recorded in `VALIDATION.md`. Executable `/opt/MediaSDK-3.1.5-linux/bin/MediaSDKTest`, models sibling `bin/models/`. GPU mode omits `-disable_cuda`; CLI checks its presence, so passing false would still disable it. Model root ends with `/`. The SDK sample may return 0 on error or skip missing-model features; task-specific native/stdout logs and actual media validation are both required.

SDK/model bytes are included in effective recipe identity and checked again before executing queued work. Spatialmedia reuses the existing upstream dependency pinned to `37ec4220a7b3101864480c6c860b469204fd2a0a`; validation uses its real `parse_metadata` track map, not guessed interfaces.

## Local validation

Use English for interface labels, help text, repository documentation and project communication. UI date/time formatting explicitly uses `en-US`; capture-date timezone configuration remains independent.

Use Python 3.11+ and ignored `.venv` with `backend/requirements-dev.txt`. Run `PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q`. Legacy syntax without execution: `python3 -c "import ast,pathlib; ast.parse(pathlib.Path('backend/auto-sticher.py').read_text())"`. Frontend: `cd frontend && npm ci && npm run build`. Build/config evidence and outstanding Linux/real-camera acceptance belong in `docs/VALIDATION.md`.

Tests use real temporary files/SQLite, loopback HTTP, tiny FFmpeg media and a simulated SDK subprocess through the original worker. Simulated SDK tests prove gateway behavior, not Insta360 media/GPU compatibility. Production acceptance must include actual single-file video, lens pairs, INSP, selected codec/FlowState/model modes, reconnect/restart and API replacement on the user's server.

## Execution rulings

- Ruling: tracked plan checkboxes and `docs/VALIDATION.md` hold implementation progress/findings — repository instructions prohibit file-based agent memory, so no Superpowers scratch memory ledger is created — cost is less granular transient journaling.
- Ruling: one worker uses serial phases in a JSON job payload backed by transactional SQLite rather than many delivery tables/dataclasses — fewer dependencies and migrations for this initial bridge — cost is application-level payload typing and future migrations.
- Ruling: parameter changes do not automatically overwrite completed exports; a replacement requires explicit selected-job action — matches approved design and protects original receipts — cost is a manual action when changing existing outputs.
- Ruling: copy shared links/stack is opt-in JSON configuration; sidecar stays off — binary replacement changes asset ID and copying old sidecars can overwrite new capture metadata — cost is intentionally limited default association migration.
- Ruling: upload-response loss preserves bytes and allows verification, but records conservative non-ownership — no reliable creation proof exists — cost is manual inspection before replacing that recovered asset.
- Historical development boundary: the original unit/fixture tests used no NAS, real media or Immich credentials. The user subsequently authorized fnOS GPU deployment and end-to-end debugging; dated runtime results are tracked separately in `docs/VALIDATION.md` and SJOPSWiki.

Deployment facts/policies live in `/Users/shinji/Developer/sjopswiki/projects/insta360-immich-bridge.md` and linked runbook. Read them and the target host policies before any NAS operations. SDKs/models, credentials, real media and state stay outside Git.

## Final-review corrections

- Cancel checks separate external delivery operations. A verified receipt may be committed after an in-flight download completes, but cancellation blocks association copy, trash and local cleanup at the next boundary.
- Any unresolved remote delivery phase retains source+target lineage beyond a live claim, including failure, cancellation and restart. Later generations display the blocking job and resume only after it completes. Startup dispatch is limited to persisted requested IDs.
- `api_source_enabled` is independent of destination URL; folder-only input can still upload. `automatic_photos` defaults false. Replacement-only 403 does not pause ordinary new-video processing; streaming response exceptions retain retryability.
- Capture metadata precedes filename timezone fallback and survives regeneration. Effective auto dimensions require positive projection evidence, are snapshotted, and are passed to the original worker as fixed dimensions; unknown projection requires explicit fixed parameters. Space preflight reserves estimated temporary output plus 1 GiB.
- UI removed size-based percentage/ETA; size ratio remains capacity information. Event cursors support reconnection, task log pause/filter and loaded-log download.
- SDK loader verification exposed missing GTK3/TIFF ABI5 dependencies absent from the vendor deb. Ubuntu 24.04 supplies GTK3; ABI5 uses the pinned official [Jammy security package](https://packages.ubuntu.com/jammy/amd64/libtiff5/download), SHA-256 `298a778a6a579a556f6bb4e32512cd76e0483b57b4a379ee85397f62fe21f225`. Never symlink TIFF ABI6 to ABI5. Vendor `-help` prints help then returns 255 because it also requires input; the build explicitly checks both expected return and required help flag.

- Follow-up review: pre-upload media-validation failures reset conversion phase and allow a corrected recipe, while upload intent/verification/replacement/cleanup retain lineage. Resumed replacements revalidate new remote bytes/presence before any old mutation, and check new presence again immediately before old trash, including copied=True recovery.

- Integration ruling: the user already authorized development and repository instructions require commit/push, so finishing the branch uses a fast-forward into current master and source push rather than asking for another workflow choice. Fresh full-change review and follow-up approval preceded integration; no PR, force push, history rewrite, Actions enablement or deployment.

## Setup and control repair — 2026-10-07

The authenticated settings endpoint accepts transient `immich_api_key` and `expected_size_ratio` fields. Entered keys use unique 0600 files in the protected config credential directory; persistent JSON contains only the reference. Blank key means keep existing credentials. Validate the complete merged profile/config and ratio before writing. SQLite changes use one transaction, with config rollback on a reported commit failure; this is not a crash-atomic transaction spanning JSON and SQLite. Config/ratio persistence failure leaves old credentials usable and removes the newly created key. Old managed key versions remain for rollback; no automatic Bitwarden sync or remote revocation is implied.

Connection changes clear the persisted target/verification and require a new account check before folder jobs are queued. They are rejected while tasks run. Identical manual requests may coalesce, but a different action or selected-ID list receives an explicit busy error. Cancellation propagates through discovery pages, chunk reads/downloads, grouping, reconciliation and queued thumbnails; in-flight HTTP/probe/thumbnail work can finish at a safe boundary. Only a fully fetched API index advances its watermark.

UI drafts are initialized on opening and preserved during polling; Cancel clears connection/key edits. Converter Save submits all fields in one validated request. Numeric drafts permit clearing before replacement. Compute Ratio is preview-only until Save, and abandoned-dialog responses cannot update a later draft. Job details use the current status receipt and Stop errors are visible. See `docs/UI_REVIEW.md` for reproduced defects, test coverage and acceptance limits.
