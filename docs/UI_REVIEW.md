# Setup and task usability review — 2026-10-07

The review used Superpowers systematic debugging, regression tests, a separate read-only reviewer and local Chrome. The original conversion worker is unchanged.

| Reproduced problem | Repair | Evidence |
| --- | --- | --- |
| No direct API-key field; connection editor had no Cancel | Write-only password input; server-owned private key file; Cancel restores saved values and clears key | Flask secret/readback/error tests; React Cancel/key tests; Chrome discard check |
| Converter Save could partially commit parallelism/ratio before an invalid profile failed | One settings request validates all fields before writes | Flask invalid request and persistence-failure tests; React rejected Save; old App failed the same regression |
| Polling overwrote converter draft | Initialize draft on open; leave it untouched by polls | React regression failed with original App, passed after fix |
| Compute Ratio persisted before Save; a late response crossed Cancel/reopen | Draft-only calculation and dialog-generation guard | Flask compute test; deferred React response regression |
| Reopening immediately after Save showed previous settings while status refreshed | Cache accepted config/ratio/concurrency before closing | Delayed-status React regression; Chrome immediate reopen |
| Numeric fields could not be cleared (typing 3 produced 13 or 0.013) | Preserve editing strings and validate on Save | React clear/replace regression for all five fields |
| New URL/key retained previous connection/target | Clear verification/target; verify current account before folder enqueue; reject connection changes during tasks | Flask target/config tests |
| Different selected work silently reused a running task | Coalesce only equivalent requests; otherwise report busy | Real blocking task/selected regeneration tests |
| Stop did not reach discovery/thumbnails; Stop errors were unhandled | Safe-boundary cancellation throughout discovery, chunks and queued thumbnails; visible Stop errors | Blocking thumbnail/discovery tests, metadata watermark and partial download tests, React Stop error |
| Details displayed the receipt captured at click time | Read current polled job by ID | React receipt changes to verified/uploaded/deleted while open |
| Missing secret file broke status/logging | Treat unreadable secret as unconfigured | Authenticated status/logging regression |
| New browser could click Test Connection before login; action 401 did not immediately open Login | Immediate Bridge Login when browser token is absent; controls wait for status; protected API 401 opens login without retry delay | React fresh-browser and Test Connection rejection/login/retry tests; late 401 cannot clear a newer login |

Managed key files are not in Git. Blank Save retains external read-only secrets. Previous managed files remain for rollback and require the protected config-volume backup; this does not update Bitwarden or revoke Immich keys. Cancellation waits for in-flight HTTP/probe/thumbnail operations. The JSON and SQLite settings stores are validated together but are not crash-atomic across both files.

Native MediaSDK 3.1.5 GPU rendering on fnOS remains blocked by the previously recorded CUDA/OpenGL crash. UI/bridge regressions do not establish successful real export, upload, cleanup or replacement. Automatic processing remains off. Fresh test/build and deployment evidence is recorded in `docs/VALIDATION.md` and SJOPSWiki.
