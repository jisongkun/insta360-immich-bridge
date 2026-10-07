# Insta360 Immich Bridge — development starting point

Created 2026-10-07 as a fork of `jagjordi/insta360-autostitcher`, baseline commit `d52ef69bdcdf09c16e25d3bf425b40e5447ed6dd`. Functional code is unchanged. This is not a working Immich integration yet.

## Intended workflow

Read-only recursive discovery of Insta360 originals already managed in Immich date directories → pair complete, stable sources → NVIDIA MediaSDK conversion → validate media and panorama metadata → atomically deliver completed MP4/JPG to the existing Immich inbox. Directory/filename compatibility must be checked against real Immich-ingested samples.

## Work to implement

1. Replace single-level discovery in `backend/auto-sticher.py` with recursive traversal and same-directory pairing. Skip hidden paths and symlinks; wait for incomplete/changing sources.
2. Use source identity and segment in job/output names; current timestamp-only output collides. Account for moved originals and duplicate copies.
3. Add controlled automatic scanning and queueing. `SCAN_INTERVAL` is currently unused; `serve` only starts Flask.
4. Adapt Dockerfile and CLI invocation for user-provided MediaSDK 3.1.5. GPU-enabled calls must omit `-disable_cuda`; replace old AI model argument with the new model root and resolve the SDK executable path.
5. Validate decodability, dimensions, duration/audio, capture date and spherical metadata. SDK return code 0 plus an existing output is insufficient; metadata injection errors must block publication.
6. Separate output persistence and inbox delivery, or add a verified delivery ledger. Existing `deep_scan` resets missing output to unprocessed, so pointing output directly at a deleting inbox causes repeat conversion.
7. Test actual P4 conversion, video pairs, single-file video and INSP. Do not assume 8K or every camera/photo mode works.

## Local checkout

- `origin`: https://github.com/jisongkun/insta360-immich-bridge.git
- `upstream`: https://github.com/jagjordi/insta360-autostitcher.git
- Default branch inherited from upstream: `master`.
- SDK and model files are obtained separately and kept private. No SDK package or real media is included.
- No Docker build, NAS deployment or media conversion has been performed for this fork.
