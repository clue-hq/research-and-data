# San Diego stack startup

- User requested frontend, platform API, design API and fleet workers, and asked for
  conflicts with other running workspaces. Root ports 3028/8018/8028/8038 belonged to
  Jerusalem; frontend env targeted Damascus 3027/8017/8027. Verified process cwd.
- Aligned local env and example origins/ports to frontend 3033, design 8013, platform
  8023/8033. Preserved isolated Postgres 55170 (`clue_san_diego`, head 403bce58bdcf)
  and Redis 65170. DEV_STACK_DB_URL now matches CLUE_DATABASE_URL. Four workers,
  three slots each; legacy entity-research runtime remains disabled.
- Copied San Salvador's matching .artifacts into San Diego using rsync --ignore-existing;
  source unchanged. Made raw-artifact and trial roots absolute to avoid cwd divergence.
- Added scripts/dev_stack_san_diego.sh with config and occupied-port/worker guards.
  Common launcher now honors the existing LUMEN_CORE_HELPER setting. Debug helper
  and editor WASM match engine bb1aaeea610a. Docker sandbox image exists.
- Initial attached background launch was cleaned up when the command exited. Relaunched
  with subprocess.Popen(start_new_session=True), file logs and disconnected stdin.
- Real worker boot exposed missing asset @2 profile pins: name-based role inheritance
  incorrectly granted two newly registered API versions. Added exact @1 authority fences
  to preserve design@v2's existing reviewed profile. No new profile or grant. Added
  regression coverage and updated stale inventory assertions from 161 to 164.
- First focused registry test run failed on the stale inventory count; corrected after
  checking the two asset @2 contracts plus design_enrich_assets@1. One read-only SQL
  inspection used nonexistent created_at; fleet_task uses enqueued_at. No data changed.
- Browser initially encountered a stale dev-session screen; Sign in again rendered the
  normal login. Verified nonblank content, no framework overlay, no browser errors.
  APIs returned OpenAPI 200 and unauthenticated session 401.
- Second worker failure: cloned database stored multi-artifact recipe0-stage0@29,
  whereas this checkout's @29 is the sandbox recipe. Existing @30 combines both.
  Moved checked-in @29 to the established replay-only list; stored history unchanged.
  Workers successfully seeded @30. No recipe bytes, versions or DB rows were overwritten.
- Final checks: 52 authority/registry/toolbelt/launcher tests passed (5 skipped);
  23 recipe contract tests passed (1 DB-gated test skipped); changed Python files pass
  Ruff check/format and git diff whitespace. No full suite or paid agent turn run.
- All four fleet workers reached worker.start with concurrency=3 and all three slots.
  PIDs 33656/33660/33663/33667; design embedded worker also started with one slot.
  Frontend PID 26413, design 26312, platform 31069/31070. Process cwd and actual
  DB/Redis/storage environment checked; API OpenAPI responses all 200. Fresh startup
  logs contain no errors. Runtime inventory: .runtime/processes.json (recheck PIDs).
  The copied legacy backlog (54 queued, 4 claimed entity_research_job rows) remains
  unchanged and is not drained because that legacy runtime is disabled.
- Services were launched detached and remain running. Other worktrees were left alone.
  Startup fixes committed locally as 1b3c84a99; no push or PR.
