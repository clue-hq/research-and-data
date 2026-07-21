# PB — the stage-2 `campaign_run` → `project_run` rename (the full-repo playbook)

**Status:** playbook (not yet executed). The *stage-1* half already landed on the
`platform/b1-fleet-worker` lane (`ProjectRunWorker` + `project_run_id` across the fleet-owned
surfaces — see `docs/specs/PB-B1-fleet-worker.md` §"§1a vocabulary" and
`_memory/2026-07-22-b1-rename-stage1.md`). **This document is the reference for the integrator to
execute stage 2 immediately after Phase B integration and *before* B4 opens.**

**When to run.** After **B2 → B3 → B1** are merged and all gates are green, and **before B4
opens** — B4's projection API / toolbelt must be *born* speaking project vocabulary, not retrofit
it. Running it earlier collides with the unmerged lanes; running it later means B4 ships
`campaign_run_id` and inherits the same dual-vocabulary debt this rename exists to kill.

---

## 1. Ruling & scope

Harness doc **§1a**: *project* = the end-to-end ABM motion (everything historically called
"campaign_run"); *campaign* = a **channel program within a project** (a still-valid future
concept). This rename is **token-precise over the run machinery only**:

| From | To |
|---|---|
| `campaign_run_id` | `project_run_id` |
| `campaign_run` (table, type prefix, prose identifier) | `project_run` |
| `CampaignRun`, `CampaignRunRow`, `CampaignRunStore`/`DbCampaignRunStore`, `CampaignRunStatus` | `ProjectRun`, `ProjectRunRow`, `ProjectRunStore`/`DbProjectRunStore`, `ProjectRunStatus` |
| `CampaignRunId` | `ProjectRunId` |
| `CampaignPhase` | `ProjectPhase` |
| `new_campaign_run_id` | `new_project_run_id` |
| `campaign_phase` (DB enum type) | `project_phase` |
| `campaign_run_status` (DB enum type) | `project_run_status` |

**Bare `campaign` is NEVER auto-replaced** — it stays the channel-program concept. Prose like
"per-campaign hard cap", "campaign-level orchestration", "campaign artifacts" is **judgment-
reviewed by hand**, not swept. The safe rule: only replace a token that carries `campaign_run` /
`CampaignRun` / `CampaignPhase` (with lookaround so compounds like `CampaignRunWorker` are
caught); never `campaign` alone.

**Measured scope** (re-measure before executing — counts drift; roots
`libs/ subsystems/ platform/ tests/ scripts/`, `*.py`, excluding `alembic/versions/`):

| token | occurrences (measured 2026-07-22, post stage-1) |
|---|---|
| `campaign_run_id` | ~1081 |
| `CampaignPhase` | ~370 |
| `CampaignRunId` | ~344 |
| `CampaignRunStatus` | ~119 |
| `CampaignRunRow` | ~38 |
| `DbCampaignRunStore` | ~12 |
| `new_campaign_run_id` | ~277 |
| `CampaignRun` (bare word) | ~88 |
| distinct `*.py` files touched | ~122 |

(The design-time estimate was ~2,470 across 161 files; stage-1 already renamed the fleet's share
and `CampaignRunWorker` no longer exists. **Re-grep to get current numbers before you start.**)

---

## 2. Precedent — the A3.1 `workspace_id` rename

`_memory/2026-07-17-a31-workspace-id-rename.md` is the proven pattern for exactly this shape of
change (`tenant_id`/`client_id` → `workspace_id`). Copy its discipline:

- **One hand-written, fully reversible migration** (a hash revision id off the then-current head);
  `up → down → up` verified on a clean per-branch DB.
- **Historical migration *files* stay byte-identical** — never rewrite `alembic/versions/*`. The
  new migration renames the *live* schema; the old files keep the old names.
- **Mechanical token rename** over `libs/ subsystems/ platform/ tests/ scripts/`; **collisions
  judgment-reviewed by hand** (A3.1's one true collision was `profiling/context.py`'s
  client/tenant duality — expect the analogue here to be *nothing*, since campaign_run has no
  merged-concept twin, but verify).
- **A guard test with an empty allowlist** locks it in.

**A3.1 gotchas to re-check here (each bit us or nearly did):**

1. **plpgsql trigger bodies reference columns by name at *runtime*** — a `RENAME COLUMN` does not
   rewrite them, so every trigger/function that names `campaign_run_id` (or a renamed table/enum)
   must be **dropped and recreated**. A3.1 recreated three immutability guards.
2. **A view's *output aliases* do not follow `RENAME COLUMN`** — Postgres rewrites a view's
   internal column refs on rename, but `… AS campaign_run_id` output aliases stay, so any view
   naming the column must be **dropped and recreated**. A3.1 hit `labeled_dataset`; it carries
   `campaign_run_id` here too (below).
3. **A test that reads a *historical* migration file by filename must keep the old filename
   string** — the sed must not "fix" a string that names a real on-disk file. (A3.1:
   `tests/compliance/test_posture.py`.)

---

## 3. Migration checklist (one new reversible migration)

Create with `alembic revision -m "campaign_run to project_run rename"` (hash id, `down_revision`
= the then-current single head — **expect an `alembic merge` join to already exist** post-B
integration; chain off *that* head). Hand-write `upgrade()`/`downgrade()`, fully reversible.
**Re-grep `alembic/versions/` for `campaign_run_id` / `campaign_run` / `campaign_phase` /
`campaign_run_status` before finalizing — the carrier set below is the 2026-07-22 snapshot and
new milestones may have added tables.**

### 3a. Table & type renames
- `ALTER TABLE campaign_run RENAME TO project_run;`  (+ its pkey `campaign_run_pkey` →
  `project_run_pkey`, and the named CHECKs `campaign_run_cap_nonneg`,
  `campaign_run_spent_nonneg`, `campaign_run_estimated_nonneg`,
  `campaign_run_icp_version_positive`, `campaign_run_cutoffs_is_object` → `project_run_*`; the FK
  `campaign_run_project_fk` and indexes `campaign_run_project`, `campaign_run_workspace` →
  `project_run_*`).
- `ALTER TYPE campaign_phase RENAME TO project_phase;`
- `ALTER TYPE campaign_run_status RENAME TO project_run_status;`
  (DB **enum values do not carry the token** — the phase labels are `reverse_profiling`,
  `discovery`, `deep`, … and the status labels `active`/`paused`/… — *verify* and rename only the
  type names, never the values.)

### 3b. `RENAME COLUMN campaign_run_id → project_run_id` on every carrying table
Carriers found 2026-07-22 (re-grep to confirm; **`run_lease` and `fleet_task` are NOT here — they
are already `project_run_id` from stage 1**):
- `account_run` (index `account_run_workspace_run` and any `campaign_run_id`-named index/constraint follow)
- `budget_event`
- `account_handoff` (+ indexes `account_handoff_campaign_run`, `account_handoff_workspace_run` → `account_handoff_project_*`)
- `handoff_event` (+ `handoff_event_run_status` if it carries the column)
- `review_session` (+ `review_action` if it carries it)
- `disposition`, `disposition_provenance`
- `cost_estimate`
- `adjustment_journal`, `campaign_phase_checkpoint` (the M7.3 state-machine tables)
- the **M12.3 handoff outbox** composite index (the `(workspace_id, campaign_run_id)` ordering key on `handoff_event`) → recreate as `(workspace_id, project_run_id)`

### 3c. Triggers / functions to **drop + recreate** (bodies name columns/enums at runtime — gotcha 1)
Files that define triggers/functions referencing `campaign_run` (re-grep; 2026-07-22 set):
`ce08f0be1c20` (M7.3 campaign_run immutability/guard), `a6628f6432c6` (M7.5 budget),
`c48ebe0a1e62` (M13.1 review), `3b470c5fdcb4` (M13.2 disposition guard), and the guards
`b61cd4887129` (A3.1) recreated. Recreate each over the renamed table/column/enum.

### 3d. Views to **drop + recreate** (output aliases don't follow rename — gotcha 2)
- `labeled_dataset` (M13.2) — its body carries `d.campaign_run_id AS campaign_run_id`; drop and
  recreate selecting `d.project_run_id AS project_run_id`.

### 3e. `downgrade()` mirrors every step (rename back; recreate triggers/views with the old
names). `up → down → up` on a clean DB must be green.

### 3f. `campaign_phase_checkpoint` **table name** — judgment call. The *type* `campaign_phase` →
`project_phase` is mechanical; the *table* `campaign_phase_checkpoint` is run machinery and
arguably `project_phase_checkpoint`. Decide explicitly and rename the table + its pkey/indexes if
so (recommended, for one-term consistency). Do the same review for any other `campaign_phase_*`
table name.

---

## 4. Code rename checklist (mechanical, over `libs/ subsystems/ platform/ tests/ scripts/`)

1. **Frozen `clue_core` via a contract-delta** (same process as the other scheduled
   contract-deltas — e.g. the M9.5 `Freshness` promotions): `CampaignRunId → ProjectRunId`,
   `CampaignPhase → ProjectPhase`, `new_campaign_run_id → new_project_run_id`,
   `IdempotencyScope`/`phase_key`/`account_step_key` helpers that name campaign_run. `PhaseContext.
   campaign_run_id → project_run_id`. **`IdempotencyScope` member NAMES and helper/param names flip
   here, but the member VALUE strings (`"account_step"`, `"campaign_phase"`) DO NOT — they are frozen
   durable data baked into every ledger key at rest; see the §4.5 judgment-review bullet before
   touching this enum.**
2. **`clue_research.durable`**: `CampaignRun → ProjectRun`, `CampaignRunRow → ProjectRunRow`,
   `CampaignRunStatus → ProjectRunStatus`, `DbCampaignRunStore → DbProjectRunStore`,
   `AccountScheduler` and the `RunOne`/`AccountSpec` seams' `campaign_run_id` kwargs, the
   `durable/campaign_run.py` / `durable/campaign.py` module files (rename the files + their imports).
3. **`clue_api` deep-handler protocol kwarg**: `DeepAccountScheduler.run_accounts(campaign_run_id=…)
   → project_run_id=…` (this is the seam stage-1 pinned as fleet exception 1).
4. **THEN flip stage-1's marked fleet exceptions** — grep `platform/fleet tests/fleet` for the
   marker comment `§1a rename: flips at stage 2` and, at each, change the pinned legacy token to
   the project spelling:
   - `QueueBackedScheduler.run_accounts(campaign_run_id=…)` → `project_run_id=…` (and the
     `test_scheduler_satisfies_the_deep_handler_seam` assertion follows the deep handler);
   - the `RunDriver` protocol `status(campaign_run_id)` / `advance(campaign_run_id)` params and
     every scripted fake driver (`ScriptedDriver`, `ExplodingDriver`, `_ProbeDriver`);
   - the exit-gate harness's `ctx.campaign_run_id` read and its `run_accounts(campaign_run_id=…)`
     call; the exit-gate test's `SELECT … FROM campaign_run` (now `project_run`) and any
     `machine.start(campaign_run_id=…)`.
   After this pass, **the marker comments themselves are deleted** (the exception no longer exists).
5. **Judgment-review list (do NOT blind-sweep):**
   - **durable idempotency-key strings are immutable DATA, not code** (replay-critical — the
     single most dangerous mechanical mistake in this rename). `clue_core.idempotency.
     idempotency_key(scope, *parts)` returns `f"{scope}:{sha256(scope‖parts)}"`, so the
     `IdempotencyScope` member *VALUE* strings (`"account_step"`, `"campaign_phase"`) are baked
     into **every** durable ledger key **at rest** — as the key prefix *and* inside the hash
     payload — and are also written verbatim into the `idempotency_ledger.scope` column (a
     Postgres `idempotency_scope` ENUM whose DB values are `'account_step'`/`'campaign_phase'` —
     migration `df78df38b168`; those DB enum values are pinned for the same reason). Stage 2
     renames the Python member *NAME* only (`CAMPAIGN_PHASE → PROJECT_PHASE`) plus the
     helper/parameter names (`phase_key`/`account_step_key`/kwargs); **the value strings
     (`"account_step"`, `"campaign_phase"`) are frozen forever.** A mechanical executor that
     "helpfully" renames the value to `"project_phase"` changes the derived key for every
     in-flight run → at the rename deploy, runs re-execute already-committed phases (a double-spend
     / double-write regression the M7.4 ledger exists to prevent). During the stage-2 contract-delta
     add a mandatory inline comment at the enum member —
     `# value frozen: baked into ledger keys at rest — never rename; see PB-rename playbook §4.5`.
     Renaming a value would require a key-rewrite data migration over the entire idempotency
     ledger (and its `scope` column) — **explicitly out of stage-2 scope.**
   - **enum VALUE strings vs type names** — the DB `campaign_phase`/`campaign_run_status` *values*
     do not carry the token; rename only the type names and the Python enum *class* names, never
     the member string values.
   - **config keys / policy keys** — any `CLUE_*` / config-schema key naming campaign_run.
   - **HTTP / API field names** — request/response JSON fields (esp. anything B-facing).
   - **`scripts/` CLI flags + `scripts/README.md`** — e.g. a `--campaign-run-id` flag → `--project-run-id`.
   - **structured-log field names** — `campaign_run_id=` log kwargs.
   - **prose in docstrings / comments** mentioning "campaign run" as the *run* → "project run";
     but leave "campaign" (channel program), "per-campaign", "campaign artifacts" alone.
6. Run `uv run ruff check --fix . && uv run ruff format .` — expect import-order churn (the
   renamed symbols re-sort) and a few reflowed long lines.

---

## 5. Guard test — `tests/test_project_rename_guard.py`

A3.1-style. Grep `libs/ subsystems/ platform/ tests/ scripts/` for the tokens `campaign_run` /
`CampaignRun` / `CampaignPhase` (with lookaround so compounds are caught), **allowlist EMPTY**.
Exclusions: `alembic/versions/` (history is immutable), `docs/architecture/` prose (governed
separately), and the guard file itself. **Deliberately NO guard on bare `campaign`** — it stays a
valid concept. Add a scan-scope sanity check: all five roots present and `> N` files scanned (so a
mis-pathed guard can't pass vacuously — the zsh no-word-split trap that hid this rename's own
measurement is a live example of a scan silently covering nothing).

---

## 6. Docs to touch

- **Harness doc `clue-hq-harness-architecture-and-requirements.md` §1a** — add one line recording
  that the mechanical `campaign_run → project_run` rename landed on `<date>`.
- **`CLAUDE.md`** — the orientation text (durable-execution bullet's state-machine list) and the
  `[rename×integration]` backlog entry: mark stage 2 **done**, drop the "MUST run before B4" note.
- **Specs referencing `campaign_run`** — `PB-B1-fleet-worker.md` (its §1a note can shrink to "done
  at stage 2"), any B2/B3/B4 briefs, and the M7/M12/M13 specs that name the table/type in prose.

---

## 7. Gate

1. `set -a; source .env; set +a; make db-fresh && uv run alembic upgrade head` — clean to the new head.
2. `make check` — green, **and green on an immediate rerun** (the audit's non-hermetic-rerun gate).
3. `make db-smoke` — `up → down → up`, **single head** (`alembic heads` returns one). Expect an
   `alembic merge` join already present from B integration; the new rename migration chains off it.
4. `scripts/01–06` stub-mode chain unchanged (if the scripts touch renamed CLI flags, update them
   in §4.5 and re-run).
5. The new `tests/test_project_rename_guard.py` passes with its empty allowlist.

---

## 8. Why not aliases / gradual deprecation

**One-term discipline.** A back-compat alias (`campaign_run_id = project_run_id`) or a deprecation
window leaves *two* names live, which is exactly the debt the `tenant_id` vs `client_id` backlog
item records — that duality lingered because the two lanes never atomically unified, and it is
still an open cleanup. A3.1 proved the opposite works: an **atomic rename + an empty-allowlist
guard** flips the whole repo in one reversible migration and one mechanical code pass, and the
guard makes backsliding a build failure. Do that. No shims.
