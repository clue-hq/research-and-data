# Sandbox ownership and private defaults

Founder authorized correcting the ownership/permission mismatch at creation instead of relying
on post-run repair. Scope: Docker runner, defensive sweep, regression coverage and operator docs.

- Runner now uses the worker's non-root UID/GID and a fixed child-only `umask 077` before
  `exec python -I -`; source remains on stdin. Root workers receive the existing
  `sandbox_unavailable` refusal. No new flags, image rebuild, migration or profile changes.
- Sweep avoids chmod for ordinary private files/directories; explicit mode overrides still get
  repaired and existing link/extension/quota rules stay in place.
- README, DEV_STACK and sandbox spec replace the old Linux uid-65534 caveat with the supported
  local-daemon ownership setup. User namespace remapping/remote Docker need matching mounts and IDs.
- First focused test run: 40 passed, one new regression test failed because this repo has no
  async pytest plugin. Converted it to the repo's synchronous `asyncio.run` style.
- Second focused run: the Docker-created CSV already passed snapshot/finalize; its test expected
  `text/csv`, but the current backend stores CSV as `application/octet-stream`. Aligned the test
  with current behavior; MIME/rendering changes are outside this correction.
- Final focused run: 144 tests passed across sandbox, run_python tool, workspace backend and
  workspace policy. Includes a real Docker run through snapshot_outputs with **no sweep**, exact
  bytes preserved, outputs emptied, and a read-only input mount refusing writes.
- Native Linux filesystem smoke: a temporary Docker-managed volume (no macOS bind-mount owner
  translation) retained the worker UID/GID and 0600/0700 modes; a second container read and edited
  the output without repair. Volume removed afterward.
- `make typecheck contracts`: 881 source files clean, all 28 import contracts kept. Changed-file
  lint and formatting clean; repository formatting passes when excluding untracked `attachments/`.
  Full `make lint` is blocked by 20 unformatted downloaded reference scripts; broad ruff also
  reports four existing errors in untouched `design_leg_wiring.py`, reproduced against HEAD.
  Initial formatter exclusion used an unsupported CLI flag; repeated successfully with --config.
- Before restart, checked this lane's database (clue_damascus on 55140): no claimed tasks or live
  work leases, 47 queued tasks. First DB check refused the generic default before querying because
  db_lifespan does not load .env; repeated with the lane's explicit dotenv DSN.
- Restarted only the Damascus fleet worker to load the runner change; no image rebuild, .env
  changes or database mutations. No paid model call or browser chat rerun in this correction.
- The first restart's child exited after the command session ended, with no startup error.
  Repeated the lane wrapper via detached Popen (`start_new_session=True`, stdin DEVNULL); the
  subsequent independent status check confirms one worker and all four app ports UP. Closing
  state: correction committed locally; downloaded references and .context files left untouched.
