# Site-turn durability (K4-1, K4-5) — plan for founder review

**Status:** draft for review. **Nothing is built until the founder approves this plan.**
**Findings:** K4-1 and K4-5 in `docs/superpowers/verification/2026-10-14-wave2-contract-review-findings.md`.
**Founder decisions (2026-10-16):**
1. A turn taken over after a worker dies **continues** from where it was; nothing finished is redone.
2. A live worker that missed its lease renewal **takes the lease back if nobody else has claimed the run**; if
   someone has, its save is refused.
3. **Deploys drain:** a worker being shut down finishes its current turn first, up to 10 minutes.
4. Session files (`plan.md`, `history.md`) are **one copy per site with a version number**; a stale worker
   reloads, never overwrites.
5. Storage is **one copy, updated**, never a pile of copies: one working copy per running turn, one session copy
   per site.

## 1. What the code does today (facts the plan rests on)

Read on 2026-10-16 (branch `site/publish-durability`, HEAD dc96d20e2):

- **Where the work lives.** The agent edits files in a local folder (`page.json`, `pages/`, `shell.json`,
  `plan.md`, …) through file tools and a few custom tools (`write_section`, `restore_version`, `fetch_page`,
  `generate_image`). The site is saved once, at the end of the turn (`design_write_site`). The conversation is
  checkpointed in Postgres (`checkpoints` tables, thread = run id) after every graph step, **asynchronously by
  default**, so the last step's checkpoint can be lost in a crash.
- **Resume today** always continues from the *latest* conversation checkpoint over a folder rebuilt from the
  stored site, which is the K4-1 bug.
- **Lease numbers repeat.** Releasing a lease deletes its row, so the next worker gets **generation 1 again**,
  the same number the old holder had. The reaper's re-offer clears the run's generation. So today **no fence can
  tell the old attempt from the new one.**
- **The final save is not fenced** by the lease at all. Only the run-completion write is, and only with
  `generation <= mine`, which a repeated generation passes.
- **A lease that lapsed cannot be renewed**, even when nobody took it. The worker declares "lease lost" and
  abandons the turn.
- **The inline design lane uses one fixed worker id in every process** (`"design-leg-inline-lane"`), so two
  processes can hold the same lease at once.
- **Deploys today:** on SIGTERM, a queued design turn is abandoned immediately and requeued. The old thread
  keeps running, unfenced, until Docker kills the container after **60 s** (`stop_grace_period: 60s`). Inline
  site turns (inside chat tasks) run to the end, but are also killed at 60 s.
- **The working folder is shared** by every worker container on the VM (bind mount `/srv/clue/lumen-agent`,
  keyed by the document's session), so an old attempt and its takeover can write into the **same folder**.
  This also means K4-5's stale-files race can happen in production today, not only with separate disks.
- **Session memory pointer:** "the newest session files" is found by the most recently updated run row. There is
  no version and no compare-and-set: last writer wins.
- **What LangGraph already gives us** (1.2.6): `durability="sync"` commits each step's checkpoint before the next
  starts; middleware sees the checkpoint id it runs from; a run can resume from a **specific** checkpoint id;
  `RunControl.request_drain()` stops cleanly at the next step boundary.
- **State held only in memory during a turn** that a resume must not lose:
  - the "files at the start of the turn" baseline used to decide whether anything changed;
  - sections written this turn;
  - images generated or found this turn (added to the brand in memory);
  - the turn's round and time counters.

## 2. Design

### 2.1 One working copy per running turn, matched to its conversation step (decision 1, 5)

- **Checkpoints commit synchronously** for site turns (`durability="sync"`), so a saved step is really saved.
- **After every agent round that changed files**, a new first-in-line middleware (`before_model`) writes the
  turn's **working copy**: the editable files (pages, shell, `plan.md`, `fetched/`) plus the in-memory turn state
  (sections written this turn, images added this turn, round and time counters). It is **one row per run**,
  overwritten each time, stamped with the conversation checkpoint id it matches. It is written only when the
  files' digest changed. At the end of the agent's answer, an `after_agent` hook stamps the final copy, so a
  takeover after the last step redoes nothing.
- **Storage:** a new table `design_site_turn_workspace(run_id PK, workspace_id, checkpoint_id, files jsonb,
  turn_state jsonb, files_sha256, attempt_generation, updated_at)`. Size is tens to a few hundred KB per running
  turn. The row is deleted when the turn completes (saved, failed or cancelled), and the run's conversation
  checkpoints are pruned at the same moment.
- **On takeover:**
  1. Build the folder from the stored site, as today, keeping the stored site as the "start of turn" baseline.
  2. If a working-copy row exists, lay its files over the folder and restore the turn state.
  3. Resume the conversation **from the checkpoint id stamped on the copy** (not the latest one), so files and
     conversation are at the same step. At most the one step in flight is redone.
  4. With no row, the turn had made no file changes yet: resume from the latest checkpoint as today, which is
     then safe.
- **Each attempt gets its own folder** (`…/sessions/<session>/attempts/<run>-g<generation>/`), so an old
  attempt and its takeover on the same disk never write into one place.

### 2.2 Leases that can tell attempts apart, and reclaim when nobody took over (decision 2)

- **Generations never repeat.** Releasing a lease keeps its row (marked released) instead of deleting it, so the
  next acquire is `generation + 1`. This is shared fleet code used by every kind of task, so it gets its own
  tests across task kinds. The reaper's re-offer stops clearing the run's generation.
- **Per-process worker ids** for the inline design lane (`design-leg-inline-lane:<host>:<pid>`).
- **Reclaim:** when a renew fails because the lease *expired*, the worker tries to re-acquire under the same
  worker id. If nobody else claimed it, it gets the lease back (generation +1, recorded on the run) and carries
  on. If someone else holds it, it stops.
- **The final save is fenced:** `design_write_site` for an agent-run save takes the run id and the attempt's
  generation, and checks, in the same transaction as the write, that the run is still held at that generation.
  Otherwise it refuses with a typed error and writes nothing. The run-completion write uses **equality**
  (`= my generation`) instead of `<=`.
- **The save gets an idempotency key** (run id plus attempt), so a retried save is one version, not two.

### 2.3 Drain on deploy (decision 3)

- On SIGTERM, a worker **stops taking new tasks**, and in-flight site turns (both the queued design path and the
  inline lane) **keep running** instead of being abandoned. The design-job handler no longer races
  `stop_requested`.
- **Bound:** after 10 minutes, still-running turns are asked to stop at the next step boundary
  (`RunControl.request_drain`). Their working copy and checkpoint are already saved, so the takeover continues
  them. The lease is then released (generation preserved, so the takeover is a new generation).
- **Compose:** `stop_grace_period` for the `chat` and `design` workers goes from 60 s to **11 minutes** (10
  minutes to finish, plus a margin to drain and exit).
- **Deploy-time effect:** a deploy can take up to about 11 minutes to roll those two containers while turns are
  running. With nothing running it is as fast as today.

### 2.4 Session files: one copy per site, versioned (decision 4)

- New table `design_site_session(workspace_id, document_id, version, manifest_sha256, updated_at,
  PK(workspace_id, document_id))`. The manifest is the existing content-addressed bundle (`plan.md`,
  `history.md`, `fetched/`). Only the pointer row is new.
- **Start of a request:** read the row. If the local copy was built from a different version (recorded in a small
  local marker file), restore from storage. Not only when the folder is missing.
- **End of a request:** save the new manifest with **compare-and-set** (`version = the version I started from`,
  then `+1`). If it fails, someone saved a newer copy meanwhile: the worker does not overwrite it, records a
  warning, and the next request loads the newer one.
- The old "newest run row" lookup is kept as a fallback for sites that have no row yet (existing sites), then
  removed once every active site has one.

### 2.5 Honest hand-back

A turn whose save changed nothing never says it built something. The hand-back says what was actually saved
(the existing "unchanged" outcome gets its own sentence instead of the agent's last words).

## 3. Tasks (each starts from a failing test)

1. **Lease generations never repeat; reclaim; per-process ids** (`platform/fleet/clue_fleet/lease.py`,
   `work_worker.py`, `platform/api/clue_api/design_fleet.py`, `subsystems/design/clue_design/runs.py`,
   reaper). Tests: release then acquire gives generation 2; an expired, unclaimed lease is reclaimed by its
   holder; a lease claimed by another worker is not; two inline-lane processes cannot hold one lease; the run
   claim and completion use equality.
2. **Fenced, idempotent save** (`toolbelt/site_documents.py` `WriteSiteTool`, `clue_design` site write,
   `main.py` site-turn `persist`). Tests: a fenced-out attempt's save is refused and writes nothing; the holder's
   save lands; a retried save makes one version.
3. **Working copy plus sync checkpoints plus resume-at-checkpoint** (new middleware in
   `lumen_agent/site/harness.py`, `lumen_agent/checkpoint.py`, the migration for `design_site_turn_workspace`,
   `main.py` `_execute_site_turn_job` / `run_site_agent_turn`, per-attempt folders, prune at completion).
   Tests, through the real executor with the real Postgres checkpointer and a scripted model:
   - **Worker dies right before the save** (the K4-1 probe): the takeover restores the files, makes **no new model
     call for finished steps**, and its save lands with the pages the first attempt built.
   - **Worker dies mid-turn** after building two pages: the takeover continues and the agent does not rebuild
     them.
   - **Crash between a checkpoint and a copy:** the takeover resumes from the copy's checkpoint and redoes at
     most one step.
   - A section written and an image generated before the death survive the takeover.
   - Round and time counters carry over.
   - The working-copy row and the run's checkpoints are gone after completion.
4. **Drain** (`work_worker.py`, `fleet_handler.py`, `design_fleet.py`, `runner.py`, `deploy/vm/compose.yaml`).
   Tests: SIGTERM during a turn finishes it and saves; a turn still running at the bound stops at a step boundary
   and a new worker continues it to the end; no new tasks are claimed after SIGTERM.
5. **Session files, one versioned copy** (migration for `design_site_session`, `clue_design/sessions.py`,
   `main.py` restore/snapshot). Tests: the K4-5 sequence (worker A request 1, worker B request 2, worker A request
   3 on a stale disk) makes request 3 see request 2's plan and history, and nothing is overwritten; a
   concurrent stale save is refused and logged.
6. **Honest hand-back** (`design_leg_wiring.py` `_web_turn_summary`, `_site_turn_response`). Test: a turn that
   saved nothing does not echo "Built …".
7. **Gates and a live check:** the site-turn suites, fleet suites, db-smoke for the two migrations (up, down, up
   on a throwaway DB), then on the lane stack: start a site turn, kill its worker mid-turn, and watch the takeover
   finish it without redoing finished steps.

Out of scope: the old web-document turn path (web documents are being removed), scene (ad) turns.

## 4. Points for the founder to confirm (they came out of the code read)

| # | Point | Recommendation |
|---|---|---|
| a | Lease generations stop repeating. This changes shared fleet code used by every kind of background task, not only site turns. | Yes; the fence is meaningless without it. Covered by tests across task kinds. |
| b | Deploys can take up to about 11 minutes to roll the `chat` and `design` workers while turns are running. | Accept. With nothing running, deploys are as fast as today. |
| c | A turn still running at the 10-minute bound is stopped at a step boundary and continued by the next worker. | Yes; this follows from decisions 1 and 3. |
| d | On a resumed turn, the agent's round and time limits **carry over** rather than restart. | Carry over, so a turn cannot run forever through repeated takeovers. |
| e | Existing sites keep using the old "newest run" lookup for session files until their first new request writes the versioned row. | Yes, no migration of old data. |

**Rough size:** about a day and a half across the seven tasks. Tasks 1 and 2 (fencing) land first, because the
rest depends on them.
