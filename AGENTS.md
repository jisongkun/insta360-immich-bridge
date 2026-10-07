# Insta360 Immich Bridge

Fork of https://github.com/jagjordi/insta360-autostitcher. This checkout is development source only; no NAS deployment has occurred.

## Authority and scope

- `AGENTS.md` is the authoritative instruction file for every coding agent. `CLAUDE.md` only imports it.
- Read `docs/DEVELOPMENT.md`, current source and tests before changes. Keep durable design and validation findings in tracked `docs/`.
- Deployment facts belong in `/Users/shinji/Developer/sjopswiki/projects/insta360-immich-bridge.md` and its linked runbook. Read the target host and credential policies there before accessing NAS systems.
- Never modify, move or delete Immich-managed originals or write directly to its database. Mount source media read-only. Deliver validated outputs through the existing inbox/API workflow.
- SDK packages, model files, credentials, real media and runtime databases must not enter Git. Preserve upstream GPL-3.0 attribution and licensing.
- GitHub is source control only. Keep Actions disabled; pushes and merges do not authorize deployment.

## Validation

- Backend syntax check without executing it: `python3 -c "import ast,pathlib; ast.parse(pathlib.Path('backend/auto-sticher.py').read_text())"`.
- Frontend validation: `cd frontend && npm ci && npm run build` when frontend changes.
- Add meaningful tests for recursive discovery, pairing, source stability, collisions, restarts and delivery state when implementing those behaviors.
- Actual SDK/NVIDIA conversion requires Linux AMD64 and real INSV/INSP samples. Do not claim media compatibility from mock tests or syntax checks.
- Commit and push intended changes and record validation. Do not commit unrelated user edits.

## Multi-Agent Collaboration (Codex + Claude Code)

All agents share these instructions and tracked docs. Keep work scoped, preserve others' changes and report evidence and pending items clearly. Delegate only when explicitly requested or required by applicable instructions.

## Agent Memory (Hindsight only)

Use the repository-scoped `coding-agent::{gitProject}` bank for continuity. Search relevant knowledge when starting a new task or revisiting decisions; verify recalled facts against code, tests and tracked docs. Do not create file-based agent memory, enable git seeding, surveys or automatic knowledge-page indexing.
