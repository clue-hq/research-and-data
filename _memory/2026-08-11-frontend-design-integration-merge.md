# 2026-08-11 — The frontend×design integration merge (`origin/main` → `integration/frontend-design-part-ii`)

The branch topology nobody should re-derive: PR #42 (`platform/frontend-integration` → **main**,
2026-08-10 14:58 UTC — apps/frontend + lanes B/D/E + FI-2, 185 commits) and PR #43
(`platform/design-integration` → **this branch**, 16:36 UTC — Part II D0–D8, 20 commits) landed on
**divergent lines**: this branch forked from main at `9260b882` (PR #40), *before* #42. PR #43's
merge was effectively a fast-forward (the branch had no unique commits). This session did the real
join: `git merge origin/main` (13 conflicted files, 190 auto-merged), all conflicts resolved, both
sides' behavior preserved.

## The four semantic reconciliations (what was decided, and why)

1. **Stream tokens — ONE owner kept (`clue_execution.stream_tokens`).** Lane-D's turn pair
   (`mint_turn_stream_token` / `consume_turn_stream_token`, `stream_token.turn_id` column from
   migration `98a5ddafa21b`) moved verbatim into the D7/D8 owner module;
   `clue_api.stream_tokens` stays a pure re-export (now 6 names). **Deliberately NOT unified with
   the D7 subject taxonomy**: `stream_token_subject_kind_known` CHECK pins
   `('project_run','design_run')`, so `subject_kind='agent_turn'` needs a vocabulary migration +
   the `test_run_event_subjects` parity surgery — recorded follow-up, not merge scope. **Tightening
   added**: `_CONSUME_SQL` (the subject/run consume) now requires `turn_id IS NULL` — a turn token
   is shaped like a workspace-wide row on the subject columns and would otherwise open any subject
   stream in its tenant. Lane-D's run-bound consume tightening is subsumed by the subject arm.
2. **Fleet — both kinds, order is load-bearing.** `FleetTaskKind` = `…, AGENT_TURN, DESIGN_JOB` —
   in THAT order because the DB enum parity test (`tests/fleet/test_fleet_db.py:61`) compares
   in-order, both migrations `ADD VALUE` (append), and on the merged graph **the frontend chain
   applies before the design chain** (verified via `alembic upgrade --sql`; also live in the smoke
   DB). `build_multi_work_worker` takes both optional handlers (`agent_turn_handler`,
   `design_handler`), each kind-guarded; fleet_main starts all five background loops (orphan sweep,
   chat sweep, stream-token sweep, design reaper, design event pruner).
3. **Toolbelt/authority/registry — pure union, counts re-derived.** Fork base 55 registry
   addresses; design +49; lane-D +5 (4 REQ-21 thread tools + `open_directive_confirmation_gate`).
   Merged: registry **109** addresses, toolbelt **102** names / **109** with @1 replays, authority
   audit **102**. All three tests updated with the arithmetic in comments; both sides' role
   assertions kept.
4. **Alembic — join revision `0bb98da7b5bb`** over heads `6f81d8fd729a` (design D8) +
   `5d7ab295742b` (frontend), both rooted at `c6d84aa84b79`. db-smoke up→base→up green on a fresh
   DB. (Do NOT count heads by eyeballing files — the 3 phase-C tips are joined by `fc1f3d22a167`;
   `uv run alembic heads` is the only truth. I reproduced the documented false-4-head mistake with
   a regex scan before catching it.)

## Other resolutions

- **pyproject**: union `clue_design` + `clue_auth` in isort/mypy/import-linter lists; two
  seam-tightening additions neither side could write (auth contract forbids `clue_design`; design
  S4 contract forbids `clue_auth`). 26 contracts kept. uv.lock = HEAD's + `uv lock`
  (adds clue-auth, pyjwt only).
- **AGENTS.md/CLAUDE.md**: main's frontend charter kept with a dated supersession of its
  "design integration is NOT happening on this branch" bullet (this merge is the event it
  predicted); the orientation paragraph now says Parts I & II done, III & IV pending.
- **Latent main bug fixed in-merge**: main's `test_resolved_snapshot_materializes_through_c61_backend`
  stats `stage0-interview/v9` while main's own profile v23 pins **v10** — fails on pristine main;
  fixed to v10 (the auto-merge preserved the stale line because both parents carried it verbatim).
- **run_event single-owner + design_run_event retirement guards hold** on the merged tree
  (grep-verified; guard tests green). Lane-D's `agent_turn_event_stream` is a *different* table
  (turn-scoped transport buffer, DAL in `clue_api/chat/turn_events.py`) — no ownership collision.

## Pre-existing debt on origin/main (NOT merge-introduced; fixed in follow-up commits, not the merge commit)

- 5 mypy errors: `chat/router.py` (dict literals where `HomeBrandWire`/`SidebarProjectWire`/
  `SidebarPageMeta` pydantic wires are expected ×3), `projections/threads.py:350`
  (`object` → datetime), `account_research_turn_wiring.py:237` (None union attr). Locks identical
  across HEAD/main/merged (ruff 0.15.17, mypy, pydantic 2.13.4) — so these are red on main itself.
- 9 files of ruff format drift, all byte-identical to origin/main.

## Follow-ups recorded

- **Token-scope unification** (turn scope → `subject_kind='agent_turn'`): vocabulary-CHECK
  migration + `RUN_EVENT_SUBJECT_KINDS` growth + parity-test update; drop `turn_id` at leisure.
- **Turn outbox vs widened run_event**: lane-D's premise ("a turn cannot ride run_event —
  run_id NOT NULL") is false post-D7 (subject widening). Whether turn token-delta frames should
  ever ride the durable subject stream is a Part-III-adjacent design question — the tables serve
  different retention/granularity contracts today; do not force it.
- Part III is now unblocked (Part II merged + C8 in ancestry). Part IV editor-core extraction can
  start any time.

## Verification (fresh exclusive DBs on the NATIVE postgres 127.0.0.1:5432; docker db is shadowed)

Offline root suite exit 0 (true exit, no pipe) · resolved wiring/audit tests 50 pass ·
fleet+lane-D-stream+design DB tests 166 pass · db-smoke up→base→up through `0bb98da7b5bb` ·
single head · 26/26 contracts · ruff clean · enum order verified in-DB (`agent_turn` before
`design_job`) · design-API suite green after `npm ci` in `apps/editor` (7 web-export failures were
missing-node_modules environmental; 15/15 pass after install) · agent-runtime suite exit 0
(~570 tests, 2 skips — its pytest config suppresses the summary line; trust the exit code) ·
DB-gated batches on exclusive fresh DBs: db ✓, durable+projections+execution ✓, api ✓*, research ✓*.

## Closing entry — every failure accounted for (do not re-diagnose)

- **Never run the whole `tests/` tree in one process against one DB.** `tests/db/test_db_migrations`
  downgrades the shared DB to base mid-suite by design; an all-in-one DB run shows ~27 cascade
  failures (waterfall/discovery/durable/fleet) that are pure invocation error. The supported
  protocol is per-batch exclusive fresh DBs (this is what the D8 note meant) — all batches green.
- **`tests/api/test_agent_turn_wiring_db.py::test_durable_turn_history_replay_and_dsar_are_body_free_and_fail_closed`
  is RED on pristine origin/main** (verified in a clean origin/main worktree, fresh synced venv,
  fresh migrated DB): `ValueError: opening context requires exactly one current user instruction`
  at `clue_agents/context.py:763`. Pre-existing main debt, not merge-caused; carried over. Fix
  belongs to the lane-D/chat owner.
- **`tests/identity/test_workspace_locality.py::test_ann_candidates_are_workspace_scoped`** is
  order-dependent (global-state pollution when co-batched with claimstore/verification suites);
  passes in isolation and in the D8-style groupings. Pre-existing flake class, not merge-caused.
- **Pipe discipline**: `pytest … | tail` swallows the exit code — three early "green" runs were
  unverified because of this. Capture to a file and echo `$?`; never trust a piped pytest.

## Post-merge standalone live run (2026-08-12) — design subsystem driven end to end

Launch recipe that works in THIS worktree (the design README's venv-era commands are stale):
fresh DB `lumen_design_dev` migrated to head, then
`CLUE_DATABASE_URL=postgresql+asyncpg://127.0.0.1:5432/lumen_design_dev
CLUE_STORAGE_FS_ROOT=/tmp/lumen-dev-storage LUMEN_API_CORS_ORIGINS=… uv run uvicorn
lumen_api.main:app --port 8002` from the repo root (lumen-api is a workspace member; no
PYTHONPATH needed), and `npm --prefix apps/editor run dev -- --port 3002` from
`subsystems/clue-design` with `NEXT_PUBLIC_LUMEN_API_BASE_URL=http://127.0.0.1:8002` +
`NEXT_PUBLIC_LUMEN_WASM_CORE=1` + `NEXT_PUBLIC_LUMEN_CANVASKIT=1` (predev self-provisions
canvaskit/fonts/wasm; editor `npm ci` + cargo/wasm32 required; wasm-pack rides in node_modules).

Verified live: `/build-info` engine_commit `7b992f8c6ec8` == freshly built browser WASM stamp
(W5 handshake); strict O4 seam behaves exactly as designed (401 bare / 200 scoped / 404
cross-tenant, workspace auto-ensured); document CRUD works via curl with `X-Workspace-Id`;
editor UI + wasm engine fully live (artboard create, layers, undo, CanvasKit canvas).

**Pre-existing gap surfaced (design line, NOT merge-caused — editor tree byte-identical to the
pre-merge tip):** the D2.5A strict-header migration to `lumenFetch` only covered
exportRunner / preflightRunner / agentRunner / libraryFonts / runEventStream. `documentStore`,
`brandHub`, `webDocuments`, and the app pages (`app/new`, `app/brand/kits/*`) still default
`fetchImpl = fetch` (bare, no header) and no call site injects `lumenFetch` — so the editor's
document-save and brand-kit reads 401 against the strict seam (`EditorApp.tsx:257` etc.). The
standalone editor's persistence path has been broken since D2.5A went strict; nobody live-drove
it until this run. Fix is mechanical: default `fetchImpl = lumenFetch` in those modules (or
inject at call sites). Owner: design subsystem / pre-Part-IV hygiene.
