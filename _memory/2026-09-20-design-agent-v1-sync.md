# Design Agent V1 remote sync — 2026-09-20

- User requested pulling Aryan's updates after `git pull` fetched but refused divergent history. The clean local branch was two commits ahead and 147 behind `origin/codex/design-agent-v1`, with common ancestor `94f91659`.
- Created local recovery branch `codex/backup-design-agent-v1-before-sync-20260920` at `aab3bced`. Fetched only the existing design-agent remote branch; its latest commit was `728a5518`.
- Rebased the two unpublished local commits onto that exact remote commit, without conflicts or a new merge. `e646707b` became `71610e5f` (discovery/ingestion fix); `aab3bced` became `1424d14f` (website baseline). `git range-diff` marked both patches identical.
- Verified the remote is an ancestor, whitespace check passed, nine compatibility tests passed, and focused Ruff lint/format passed. Root `.env` and frontend `.env.local` hashes were unchanged. No dependencies, environment settings, database state, services, or other worktrees were changed; no push.
- Incoming source includes five migration files and has one Alembic head, `5cac3234cfb3`. No live DB upgrade, restart, or end-to-end runtime verification was performed; source synchronization is not runtime rollout.
- One read-only `git show` using an exclusion pathspec was rejected; inspection succeeded when retried with explicit paths. No mutation resulted from that error.
- This note is a separate local documentation checkpoint after the two preserved commits.

## Later workspace access recovery

- User reported all four workspaces unavailable again. Their frontend manager was still running; shared APIs and fleet workers were stopped. Logs showed graceful backend shutdown, but did not identify the initiator. Existing Clerk sessions remained valid after the platform APIs were restored as detached processes.
- The freshly started API exposed the pending schema gap: project sidebar reads failed because `project.pinned` was absent. Backed up the local database to private `.local-setup/recovery/20260920_140702/before-runtime-update.dump`, verified the archive, and passed `make db-smoke` (up/down/up) on a newly created disposable database. Applied the bundled migrations from `d659c2d2b537` to `5cac3234cfb3` on `clue_sept7_dev`; project/design-document/thread/workspace counts remained 105/111/126/6. Removed only the disposable test database; retained backup and validation logs.
- Restored APIs on 8020/8030 and the design API on 8010. Existing workspace frontends on 3021–3024 returned HTTP 200 for Home and project-sidebar requests, and authenticated browser tabs were reopened. No login bypass, credential changes, environment-file edits, source implementation changes, or remote push.
- Remaining runtime prerequisite: Docker is not installed. The new launcher requires Docker and `clue-agent-sandbox:latest` before fleet startup. Fleet workers remain stopped; the recovered design API uses process-only `LUMEN_EMBEDDED_FLEET_WORKER=0`. Access and saved-data reads are restored, but new background generation is not ready. Restore the standard worker setup only after the sandbox prerequisite is satisfied; do not silently disable sandbox checks.
