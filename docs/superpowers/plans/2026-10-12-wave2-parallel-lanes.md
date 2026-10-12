# Wave 2 in four parallel worktrees

**Founder decision (2026-10-12):** Wave 2 runs in four worktrees at once instead of one branch. The
founder coordinates the waits and merges between them. This file replaces the "one branch" part of
the master plan's "Execution order across the plan files"; that section still gives the order of
tasks **inside** each lane.

Every lane runs its plan with superpowers:subagent-driven-development: a fresh **Opus** implementer
per task, the lane's own controller reviews every task personally, no reviewer subagents, and the
implementer never starts subagents. Never push. Commits carry no Claude or AI attribution.

## 1. Who owns what

| Lane | Worktree | Branch | Runs | Test database |
|---|---|---|---|---|
| **C** | trenton (this one) | `puck/integration-wave1` | Lane C plan, all tasks | `clue_trenton_wave1` |
| **A** | new | `puck/w2-lane-a` | Lane A plan: Tasks 1–3, 8–25 (Tasks 4, 5, 7 are stubs; **Task 6 runs in A9**) | `clue_w2_lane_a` |
| **A9** | new | `puck/w2-a9` | A9 plan: X1–X5, Task 4, Task 5, **Lane A Task 6**, Task 6b, Task 7, X6, Task 16b | `clue_w2_a9` |
| **B** | new | `puck/w2-lane-b` | Lane B plan, all tasks | `clue_w2_lane_b` |

Plan files (all in `docs/superpowers/plans/`): Lane A `2026-10-11-lane-a-site-backend-and-publishing.md`,
A9 `2026-10-12-lane-a-a9-brand-fidelity-rewrite.md`, Lane B `2026-10-11-lane-b-site-agent-on-platform.md`,
Lane C `2026-10-11-lane-c-site-editor.md`. The master plan is
`2026-10-09-website-agent-on-puck-integration.md`.

The three new branches start at the commit that added this file. The test databases already exist on
trenton's Postgres server (`localhost:55160`), copied from `clue_trenton_wave1`, and each plan file
already names its own lane's database.

## 2. Handing work between lanes: tags and merges

All four worktrees share one repository, so a branch or tag made in one is visible in all of them at
once. Nothing is ever pushed.

- **Tag every task when it is complete** (reviewed and recorded in the ledger):
  `git tag w2/<plan>-task-<N>` on the task's last commit. `<plan>` is the plan file the task comes
  from: `a`, `a9`, `b` or `c`. So Lane A Task 6, run in the A9 lane, is tagged `w2/a-task-6`, and
  Lane B Task 13a is `w2/b-task-13a`.
- **Before a task that needs another lane's work, merge that lane's tag** (the needed tag or any newer
  tag from the same lane): `git merge --no-ff w2/a-task-11 -m "merge: Lane A through Task 11 (for B Task 3)"`.
  A merge brings everything that lane had merged too.
- **Record BASE after the merge**, so the next task's review package shows only that task's work.
- **If the tag does not exist yet**, do the next task that does not need it (section 3 lists them).
  When nothing is left, stop and tell the founder in one line which tag you are waiting for. The
  founder tells you when it exists; never poll for it.
- Every task whose plan text names another lane's work also has a grep check; a failing check stops
  that task, not the lane.

## 3. What each lane needs from the others

**Lane C (trenton).**
- C Tasks 1–8: need nothing. Do C Tasks 1–2 first and tag them, because Lane A Task 10 waits for
  `w2/c-task-2`. Tag C Task 3 as soon as it is done, because A9 Task X6 waits for `w2/c-task-3`.
- C Task 9 Step 7b needs `w2/a9-task-5`. Do the rest of Task 9; come back for Step 7b after merging it.
- C Tasks 10–14, 16: need nothing. C Task 15 runs the editor domain in trenton's stack.
- Live checks against a real site need Lane A through Task 14 and Lane B through Task 16. Record them as
  owed and run them at the end (section 6).

**Lane A.**
- Order: Tasks 1, 2, 3, then 8–17, then 18–25. **Lane A is the critical path:** Lane B waits for
  Tasks 3, 11 and 17, and A9 waits for Task 3. Do not detour before Task 17.
- Before **Task 10**, merge `w2/c-task-2`. Nothing else in Lane A needs another lane: the brand and
  section seams Lane A adds refuse politely (`site_inputs.unavailable`, `site.invalid`) until Lane B
  fills them.
- Task 6 is run by the A9 lane. Record it in Lane A's ledger as
  `Task 6: done in the A9 lane (tag w2/a-task-6)` and do not run it here.

**A9.**
- X1–X5 need nothing.
- Before **Task 4**, merge `w2/a-task-3`. Then Task 4, Task 5, Lane A Task 6 (from the Lane A plan),
  Task 6b, Task 7.
- Before **X6**, merge `w2/c-task-3`.
- Before **Task 16b**, merge `w2/a-task-17`.
- X1 changes the engine: rebuild this worktree's `lumen-api-helper` as the plan says. The other lanes
  keep their copied helper until they merge A9's X1 and a test of theirs needs the new `styles`
  group; then they rebuild theirs.

**Lane B.**
- Tasks 0, 1, 2, 4, 5 need nothing. Task 0 (the founder's text review) is already approved in full;
  record it complete. Run 0, 1, 2, then 4 and 5 while waiting for Lane A.
- Before **Task 3**, merge `w2/a-task-11`. Then Tasks 3, 6, 7, 8. Tasks 10 and 11 may run before
  Task 9 if their briefs name nothing from Task 9 (check, and record the ruling).
- Before **Task 9**, merge `w2/a-task-17` (it also brings Lane A Tasks 9, 12 and 14, which Tasks 12,
  13 and 14 need). Then 9, 12, 13, 13a, 14.
- Before **Task 15**, merge `w2/a9-task-6b` (it brings A9 Tasks 4 and 6b and Lane A Task 6). Then
  15, 16, 17.
- Task 18's live check spends money and runs in trenton with the founder's go. Task 13a's live use
  needs Lane C Task 11. Both go in the owed list (section 6).

## 4. Setting up a new worktree (once, before the first task)

Run from the new worktree's root, with `LANE` set to `lane-a`, `a9` or `lane-b` and `DB` to the lane's
database (`clue_w2_lane_a`, `clue_w2_a9` or `clue_w2_lane_b`):

```bash
T=/Users/aryankeshri/conductor/workspaces/research-and-data/trenton
git switch puck/w2-$LANE
sed -e "s#$T#$PWD#g" -e "s#:55160/clue_trenton\$#:55160/$DB#" -e "s#clue-agent-workspaces-trenton#clue-agent-workspaces-w2-$LANE#g" -e "s#lane-trenton#w2-$LANE#g" -e "s#DEV_STACK_LOG_PREFIX=/tmp/trenton#DEV_STACK_LOG_PREFIX=/tmp/w2-$LANE#" "$T/.env" > .env
mkdir -p subsystems/clue-design/target/release .artifacts subsystems/clue-design/apps/editor/public/vendor
cp -c "$T/subsystems/clue-design/target/release/lumen-api-helper" subsystems/clue-design/target/release/
cp -c "$T/subsystems/clue-design/apps/editor/public/vendor/tailwind-browser.js" subsystems/clue-design/apps/editor/public/vendor/
cp -c -R "$T/apps/frontend/public/vendor" apps/frontend/public/
uv sync --all-packages
(cd apps/frontend && npm install && npm run design-system:build)
```

Then check: `grep -c "$DB" .env` prints 2 (the app's database and the stack's), `grep -c trenton .env`
prints 0, and `.venv/bin/python -c "import lumen_api"` works. If the worktree was created on a
different branch and `git switch` refuses because of local changes, stop and ask the founder; never
reset a worktree that has work in it.

The `.env` points the app at the lane's own test database, so even a command that forgets to choose a
database cannot touch trenton's lane database.

## 5. Rules every lane follows

- **Databases.** Database tests run only on the lane's own test database. Trenton's lane database
  (`clue_trenton`) is never written. The plans' "with the design stack down" rule exists because live
  workers poll the database the tests use; only trenton runs a stack and it uses `clue_trenton`, so no
  stack ever polls a lane's test database and trenton's stack can stay up. If a queue-driven test
  still flakes, check `leased_by` on the job row before anything else.
- **Dev stacks:** see section 8 (each lane may run its own, on its own ports, database copy and Redis
  database number).
- **Memory.** Each lane writes only its own note: `_memory/2026-10-12-wave2-lane-a.md`, `-a9.md`,
  `-lane-b.md`, `-lane-c.md` (they exist already). Nobody edits `_memory/README.md` or the old
  `2026-10-08-puck-spike-phase2.md` note during Wave 2.
- **Standing rules:** never run the whole design suite; never run `*_live.py` or broad suites with real
  keys; no live model run and no brand-kit extraction without the founder's go; judgement goes in
  prompts, never in validators; no caps on agents; never touch a worktree outside the four; never type
  or print credentials.
- **Merge conflicts** happen mostly in files several lanes add to. Resolve them like this:
  - `.env.example`, `lumen_api/main.py`, `agent_registry_wiring.py`, site-kit's `src/index.ts`: keep
    both sides' additions.
  - Where Lane B replaces one of Lane A's seam assignments in `lumen_api/main.py`
    (`site_brand_loader`, `site_section_loader`), Lane B's line wins.
  - Registry count tests (the tool totals per registry and per profile): once both lanes' tools are
    merged, the expected number is the old number plus every lane's additions (Lane A Task 12 adds 3,
    Lane B Task 1 adds 1, and so on).
  - `apps/frontend/package-lock.json`: take either side, run `npm install` in `apps/frontend`, commit
    the regenerated file.
  - Migrations: only Lane B Task 2 adds one. If another appears, `alembic merge` as CLAUDE.md says.
  - After resolving, run the focused tests of both lanes' touched files before the next task.
- **Heavy builds.** The frontend build gate (Lane C, A9 X6) and the Rust build (A9 X1) are heavy. If
  the machine struggles, the founder staggers them.

## 6. The end: merging into trenton

When every lane is done, trenton merges `puck/w2-lane-a`, `puck/w2-a9` and `puck/w2-lane-b` into
`puck/integration-wave1`. Trenton then runs the owed list: the live checks against a real site (Lane
C's, Lane B Task 13a's live use, Lane B Task 18 with the founder's go), anything a lane recorded as
needing the stack, and C Task 15's editor domain. After that comes the one whole-branch review.

## 7. Start notes (paste one into each new session)

**Lane A**
> You are the controller for Wave 2 Lane A of the website-agent-on-Puck integration. Read
> `docs/superpowers/plans/2026-10-12-wave2-parallel-lanes.md` first; it is your charter. Set up this
> worktree as its section 4 says, with `LANE=lane-a` and `DB=clue_w2_lane_a`. Then execute
> `docs/superpowers/plans/2026-10-11-lane-a-site-backend-and-publishing.md` with
> superpowers:subagent-driven-development: Opus implementers only, you review every task yourself,
> no reviewer subagents. Order: Tasks 1, 2, 3, 8–17, 18–25; Task 6 belongs to the A9 lane. Merge
> `w2/c-task-2` before Task 10. Tag every completed task. Never push.

**A9**
> You are the controller for Wave 2 A9 (brand fidelity) of the website-agent-on-Puck integration.
> Read `docs/superpowers/plans/2026-10-12-wave2-parallel-lanes.md` first; it is your charter. Set up
> this worktree as its section 4 says, with `LANE=a9` and `DB=clue_w2_a9`. Then execute
> `docs/superpowers/plans/2026-10-12-lane-a-a9-brand-fidelity-rewrite.md` with
> superpowers:subagent-driven-development: Opus implementers only, you review every task yourself,
> no reviewer subagents. Order: X1–X5, Task 4, Task 5, Lane A Task 6 (from the Lane A plan), Task 6b,
> Task 7, X6, Task 16b. Merge `w2/a-task-3` before Task 4, `w2/c-task-3` before X6, `w2/a-task-17`
> before Task 16b. Tag every completed task. Never push.

**Lane B**
> You are the controller for Wave 2 Lane B of the website-agent-on-Puck integration. Read
> `docs/superpowers/plans/2026-10-12-wave2-parallel-lanes.md` first; it is your charter. Set up this
> worktree as its section 4 says, with `LANE=lane-b` and `DB=clue_w2_lane_b`. Then execute
> `docs/superpowers/plans/2026-10-11-lane-b-site-agent-on-platform.md` with
> superpowers:subagent-driven-development: Opus implementers only, you review every task yourself,
> no reviewer subagents. Order: 0, 1, 2, 4, 5; merge `w2/a-task-11`, then 3, 6, 7, 8 (10 and 11 may
> come before 9); merge `w2/a-task-17`, then 9, 12, 13, 13a, 14; merge `w2/a9-task-6b`, then 15, 16,
> 17. Task 18's live check waits for trenton and the founder. Tag every completed task. Never push.

## 8. Running a stack in a lane worktree (founder, 2026-10-12)

The founder decided each lane may run its own dev stack. This replaces section 5's "No dev stack
outside trenton" rule; live checks can now run in the lane that owns them, and section 6's owed
list shrinks to the checks that need another lane's work merged in.

**Databases.** Full copies of `clue_trenton` (2.7 GB each, made 2026-10-12 with trenton's stack
stopped, `CREATE DATABASE … TEMPLATE clue_trenton STRATEGY FILE_COPY`) on `localhost:55160`:
`clue_damascus` (Lane A), `clue_bangalore` (A9), `clue_chicago` (Lane B). Each worktree's
`.artifacts/ws_*` storage already matches trenton's (same file counts), so blobs resolve. The stack
runs on the copy; tests still run on the small test database (section 1). Never make another full
copy while a stack is connected to `clue_trenton`, and never several at once (the 2026-10-12
disk-full crash).

**Ports and Redis.** Each lane gets its own series so four stacks run side by side:

| Lane | Worktree | Frontend | Design API | Platform API | Platform twin | Page origin | Editor (Task 15) | Redis DB |
|---|---|---|---|---|---|---|---|---|
| C | trenton | 3029 | 8019 | 8029 | 8039 | 8049 | 3129 | 2 |
| A | damascus | 3027 | 8017 | 8027 | 8037 | 8047 | 3127 | 6 |
| A9 | bangalore | 3047 | 8147 | 8157 | 8167 | 8177 | 3147 | 7 |
| B | chicago | 3048 | 8148 | 8158 | 8168 | 8178 | 3148 | 8 |

Damascus keeps the series it already had (`scripts/dev_stack_damascus.sh`). Every worktree used Redis
database 2; with four copies of one database the record ids repeat, so id-keyed locks and rate-limit
keys would collide across lanes — hence one database number per lane.

**What to change in a lane's files** (the values only; never print secrets):
- `.env`: `DEV_STACK_FRONTEND_PORT`, `DEV_STACK_DESIGN_PORT`, `DEV_STACK_PLATFORM_PORT`,
  `DEV_STACK_PLATFORM2_PORT`, `CLUE_PAGES_ORIGIN_PORT`; `CLUE_APP_ORIGIN`,
  `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES` and `LUMEN_API_CORS_ORIGINS` (each names the frontend
  origin); `CLUE_DESIGN_API_BASE_URL` and `LUMEN_API_ORIGIN` (the design API port);
  `CLUE_DATABASE_URL` and `DEV_STACK_DB_URL` (the lane's copy); `CLUE_REDIS_URL` (`…/6379/<Redis DB>`);
  `DEV_STACK_EDITOR_PORT` once Task 15 has added it.
- `apps/frontend/.env.local`: `CLUE_API_BASE_URL` (platform port), `LUMEN_API_BASE_URL` (design
  port), `CLUE_APP_ORIGIN` (frontend origin).
- Start and stop the stack only with `scripts/dev_stack.sh` and the `.env` above (or the lane's own
  wrapper), detached (`nohup … & disown`), never by `pkill` on a shared pattern.
