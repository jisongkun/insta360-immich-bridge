# Insta360 Immich Bridge

Convert Insta360 originals into exports with 360 metadata and upload them to Immich's internal library through its API. Videos become MP4; the existing INSP photo conversion remains available as JPG output. Stitching, metadata injection, and thumbnails reuse [jagjordi/insta360-autostitcher](https://github.com/jagjordi/insta360-autostitcher). New code handles discovery, scheduling, durable state, validation, and Immich delivery. GPL-3.0, upstream attribution, and Git history are preserved; the GitHub repository remains a fork.

The bridge is deployed for manual testing on fnOS, but **real GPU/camera export acceptance is blocked by a MediaSDK 3.1.5 renderer crash**. Automatic processing remains off. Simulated SDK tests and container builds do not prove real INSV/INSP compatibility. See the [validation record](docs/VALIDATION.md).

## Workflow

1. Discover `.insv` / `.insp` incrementally through Immich metadata search using `createdAt` / `updatedAt`. Advance the server-time watermark only after successful pagination, with a default 300-second overlap. Alternatively, scan multiple read-only folders recursively.
2. Wait for stable files, then pair lens roles 00/10 within each filename segment. A single file with two video streams goes directly to the original converter. Different segments produce separate exports; **recording segments are not concatenated into a timeline**. Ambiguous same-name lenses with different bytes are rejected.
3. Invoke the original conversion worker in a private workspace with its own legacy database. Use the existing settings with MediaSDK 3.1.5; debug-mode simulated success is disabled.
4. Verify unchanged sources, complete decoding, 2:1 projection, selected dimensions, video duration/audio, capture date, and 360 metadata. Failed exports are not uploaded.
5. Check Immich for identical bytes using SHA-1, then stream the upload. Stream the server's original file back and compute SHA-256. Persist the verified receipt before deleting the bridge's local export. Keep source INSV/INSP files and durable job state.

Deduplication covers original lens SHA-256 hashes and segment, effective conversion settings, SDK/model identity, and Immich address/account. Moving sources or deleting verified local MP4 copies does not trigger conversion again. Changing scan intervals does not alter deduplication. Automatic processing defaults to off. Discovery and processing are separate manual actions; **Discover and Process Now** combines them. The first discovery observes sources; scan again after the stability window to queue them.

[Immich's supported-format list](https://docs.immich.app/features/supported-formats/) includes INSV and INSP. The API can discover only indexed originals visible to the API key. Additional folder scans find files that have not been imported. Incremental discovery reuses a local asset index rather than recursively traversing the entire library each time. Known source paths still receive stat checks; content hashes are calculated initially and after changes.

## Recommended Configuration

Use Linux AMD64 with an NVIDIA GPU and NVIDIA Container Toolkit. Read-only source mappings avoid downloading large originals again. When shared mounts are unavailable, enable `download_sources`; the temporary source cache resides in `/work/sources`. Start with one stitching job and validate real samples before increasing concurrency.

| Setting | Default | Purpose |
| --- | ---: | --- |
| automatic | false | Enable scheduled discovery and processing explicitly |
| api_source_enabled | true | API source discovery, independent of the upload destination |
| automatic_photos | false | Automatic photo processing requires explicit opt-in |
| interval | 60 seconds | Immich incremental discovery |
| folder_interval | 600 seconds | Additional folder scans |
| stable_seconds | 60 seconds | Unchanged source size/timestamps across observations |
| full_interval | 86400 seconds | Full asset reconciliation and remote export checks |
| overlap | 300 seconds | Watermark overlap for indexing delays |
| stitch_parallelism | 1 | Conversion/delivery concurrency; one source is serialized |
| output_size | 5760x2880 | Existing converter's fixed 2:1 output |
| bitrate | 100000000 | 100 Mbps; original bitrate mode is also available |
| stitch_type | dynamicstitch | Existing optflow/aistitch modes are also available |

Existing H.265, FlowState, direction lock, Stitch Fusion, CUDA, automatic dimensions, original bitrate, estimated size ratio, thumbnails, sorting, pagination, multiselect, and failure retry controls are retained. Direction lock requires FlowState. The UI shows stages, elapsed time, and export bytes/estimated size; file-size ratios are not completion progress. Automatic dimensions require confirmed 2:1 equirectangular projection; unknown originals require fixed dimensions. Conversion checks estimated temporary space plus a 1 GiB reserve. Capture metadata takes priority; filenames and the configured time zone provide a fallback.

## Startup

These are general deployment instructions. The fnOS test deployment and its outstanding acceptance checks are recorded in `docs/VALIDATION.md`; private operational details belong in SJOPSWiki.

Place the private SDK package at `backend/vendor/MediaSDK-3.1.5-linux-amd64.deb`. It has been extracted locally from the supplied archive and is excluded from Git. The build verifies this SHA-256 by default:

```text
444b4b0bc22aa5335e5cc2c3dd092b16207f3a7c19bb7fe97799e94eca69325e
```

```sh
cp .env.example .env
mkdir -p bridge-config bridge-state bridge-work
cp bridge-config.example.json bridge-config/bridge-config.json
# Set IMMICH_API_KEY, BRIDGE_LOGIN_TOKEN, and SOURCE_DIR in .env.
# Set immich_url and mappings in the configuration; use a reachable server URL.
# After preparing the Linux GPU driver/runtime and validating samples:
docker compose build
docker compose up -d
```

The frontend binds to `127.0.0.1:3000` by default and proxies internal backend:8008. `BRIDGE_BIND` changes the listening address; use your existing HTTPS reverse proxy for external access. The backend API has no separate host port. `SOURCE_DIR` mounts read-only at `/sources`. Keep `/state` and `/work` separate; the configuration directory is writable so the UI can save settings. Never write directly into Immich's managed directories or database.

`mappings.from` is a prefix of `originalPath` returned by the API; `to` is the bridge's readable mount prefix. For example, server `/usr/src/app/upload` maps to bridge `/sources`. Configure the actual API path instead of guessing from host filenames. Additional folders use container paths such as `/sources/insta360`; scanning includes subfolders and skips hidden files, symlinks, and excluded patterns. Missing originals or incorrect mappings fail visibly while retaining state.

For folder-only discovery, set `api_source_enabled: false` and configure `folders`. Uploads still use the same Immich URL/key, without querying its source asset list.

For API-only original downloads, set `download_sources: true`, `mappings: []`, and `folders: []`. A real source mount is unnecessary in this mode. The cache never deletes remote originals and is not treated as an Immich export eligible for replacement.

## API Key and Login

**API keys are supported.** Read the key from `IMMICH_API_KEY` (or the variable named by `api_key_env`) or a read-only file referenced by `api_key_file`. The file takes priority. Key values do not enter JSON configuration, jobs, manifests, or logs. File-based secrets require an explicit read-only Compose mount. The UI configures reference names/paths; set actual values in the server's `.env` or secret file.

The key must belong to the target library account. Required permissions are `user.read`, `server.about`, `asset.read`, `asset.upload`, and `asset.download`. Replacement additionally needs `asset.copy`, `asset.delete`, and permissions for the selected association copy options. Discovery/upload alone does not require deletion permission. A 401 or a 403 during basic read/upload pauses automatic processing. A replacement-stage 403 for missing copy/delete permission blocks that source's version transition while ordinary new exports can continue. After fixing the key, test the connection and retry manually. The client uses Immich 3.2 structured search, based on [v3.2.4 source](https://github.com/immich-app/immich/tree/v3.2.4/server/src). Later 3.2+ releases in the same major version still require server acceptance testing. Versions below 3.2 and new major versions are rejected. The session-only sync stream is unused.

`BRIDGE_LOGIN_TOKEN` is a required, separate token for the bridge UI/API. Status, logs, settings, and thumbnails require Bearer authentication; thumbnails load through authenticated fetch. Rotating an Immich key for the same account preserves deduplication. Changing the address/account creates a new target scope and does not inherit old receipts.

## Settings Changes and Replacement

Saving settings changes defaults for new jobs. Scheduled processing does not overwrite completed results. Select current, verified exports owned by the bridge and click **Regenerate and Replace Selected Exports**: convert again, upload the new asset, verify its server hash, copy albums/favorites, move the previous export to Immich trash, and clean the local MP4.

Asset IDs change. Shared links, stacks, and sidecars are not copied by default. JSON settings `replace_shared_links` and `replace_stack` enable those association options; sidecars remain disabled. Source INSV/INSP files are never deleted. Identical bytes resolving to the same asset ID retain that asset. A duplicate owned by someone else does not authorize deleting the previous export or mutating that duplicate. Lost upload responses can recover and verify matching assets, but cannot establish ownership; later replacement may require manual inspection.

Changed predecessor bytes stop replacement. Copy/trash failures retain both assets and resume delivery without converting again. An unresolved delivery version holds the source's delivery order; newer versions show its blocking job ID and wait for it to resume. Pre-upload media validation failures allow fresh conversion or a corrected recipe. Replacement recovery rechecks the new asset's availability and bytes before retiring the old version. A permanently deleted previous export requires explicit regeneration; automatic checks only mark it missing and do not reset the source job.

## Logs and Recovery

- Global activity shows discovery, connection, scheduling, and failure summaries. Click a job timestamp for effective settings, source paths, target identity, stage events, and SDK/conversion logs. Events resume by sequence cursor after reconnecting. Pause logs, filter event levels, or download loaded logs; SDK text is limited to each file's last 64 KiB.
- `/state/logs/bridge.log` rotates by size: 10 MiB per file and five backups by default.
- `/work/jobs/<job-id>/<attempt-id>/` contains the manifest, private conversion database, result, SDK native log, and controller logs. Each SDK/conversion log is limited to 10 MiB by default; exceeding the limit stops conversion before upload.
- Successful logs default to 14-day retention; failed/unfinished logs to 30 days, with daily cleanup. Durable receipts are retained. The log API reads the last 64 KiB of up to ten files.
- Phases are pending → converting → validating → upload_intent → verifying → replacing → cleanup → done. Failures expose their reason and resume phase. Cancellation stops the conversion process group; external API operations stop at the next safe boundary, so an already-issued request may complete.
- Only one process can own a state directory. Restart clears old claims and resumes only explicitly requested manual/automatic work. Transmission failures retain exports. Network/429/5xx retries use backoff; configuration, permission, and source errors require correction and manual retry.
- Back up `/state/bridge.db` with SQLite online backup or after stopping the service, accounting for WAL, together with configuration. Back up `/work` while delivery is in progress. Losing state can lose ownership/deduplication evidence; do not blindly take ownership of existing exports.

## Development and Validation

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q
python3 -c "import ast,pathlib; ast.parse(pathlib.Path('backend/auto-sticher.py').read_text())"
cd frontend && npm ci && npm run build
```

Run the local backend with `PYTHONPATH=backend BRIDGE_CONFIG=/absolute/config.json BRIDGE_LOGIN_TOKEN=... .venv/bin/python -m bridge`; set state/work to local absolute paths. Vite proxies `127.0.0.1:8008` by default; override with `BRIDGE_DEV_API`. Actual SDK conversion acceptance requires Linux AMD64. GitHub is source control only, Actions remain disabled, and pushing source does not authorize deployment.
