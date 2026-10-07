# Insta360 Immich Bridge — development starting point

Created 2026-10-07 as a fork of `jagjordi/insta360-autostitcher`, baseline commit `d52ef69bdcdf09c16e25d3bf425b40e5447ed6dd`. Functional code is unchanged. This is not a working Immich integration yet.

## Current product direction

On 2026-10-07 the user selected an independent Insta360–Immich integration tool, using upstream features/code as reference rather than extending its controller architecture. Current functional code remains the upstream baseline; no integration has been implemented.

The reviewed-in-chat direction is: Immich API incremental discovery or configured recursive read-only folders → complete/stable source grouping → MediaSDK 3.1.5 → media/360 metadata validation → direct API upload and server-original hash verification → removal of the tool's local output copy, retaining Insta360 originals. Optional interval and manual triggering are both required. Parameter changes can explicitly regenerate outputs and replace the tool's previous exported assets through API upload, supported association migration and old-output soft deletion; source INSV/INSP are never deleted.

See [the design awaiting document review](superpowers/specs/2026-10-07-immich-integration-design.md). This supersedes the earlier inbox-first proposal. The existing GitHub repository remains a fork; attribution, license and history are preserved.

## Reference-code gaps (not an implementation plan)

1. Replace single-level discovery in `backend/auto-sticher.py` with recursive traversal and same-directory pairing. Skip hidden paths and symlinks; wait for incomplete/changing sources.
2. Use source identity and segment in job/output names; current timestamp-only output collides. Account for moved originals and duplicate copies.
3. Add controlled automatic scanning and queueing. `SCAN_INTERVAL` is currently unused; `serve` only starts Flask.
4. Adapt Dockerfile and CLI invocation for user-provided MediaSDK 3.1.5. GPU-enabled calls must omit `-disable_cuda`; replace old AI model argument with the new model root and resolve the SDK executable path.
5. Validate decodability, dimensions, duration/audio, capture date and spherical metadata. SDK return code 0 plus an existing output is insufficient; metadata injection errors must block publication.
6. Add a verified API delivery/replacement ledger independent of local output presence. Existing `deep_scan` resets missing output to unprocessed, so deleting local copies after upload otherwise causes repeat conversion. The existing inbox remains a separate service and is not this design's delivery path.
7. Test actual P4 conversion, video pairs, single-file video and INSP. Do not assume 8K or every camera/photo mode works.

## Local checkout

- `origin`: https://github.com/jisongkun/insta360-immich-bridge.git
- `upstream`: https://github.com/jagjordi/insta360-autostitcher.git
- Default branch inherited from upstream: `master`.
- SDK and model files are obtained separately and kept private. No SDK package or real media is included.
- No Docker build, NAS deployment or media conversion has been performed for this fork.
