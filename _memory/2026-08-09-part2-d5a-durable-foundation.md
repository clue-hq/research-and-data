# Part II D5 Round A — durable-execution foundation (schema, fleet kind, agent-runtime packaging)

Branch `platform/design-integration`, on top of `c24eeae0` (D4 complete). Uncommitted at the time
of writing — the reviewer commits. Round B owns the handler/worker/API switch.

## What landed

### Migrations (two, chained off `13cd5078d697`; single head `50b84c524fa2` throughout)

- **`be855c8f6993` — d5 fleet design job kind.** `ALTER TYPE fleet_task_kind ADD VALUE 'design_job'`.
  ONE mechanical kind for all design work (turns + ingestion), the `entity_research_job` precedent;
  the shape lives in the immutable envelope, not the queue taxonomy. `downgrade()` follows the R2
  precedent exactly: refuse while any `design_job` task exists, then rebuild the type without the
  label (PostgreSQL cannot drop one).
- **`50b84c524fa2` — d5 design run/job fleet reshape.**
  - `design_agent_run` gains `work_id uuid NOT NULL UNIQUE`, `checkpoint_thread_id text NOT NULL`,
    `kind design_run_kind NOT NULL` (new type `agent_turn|web_turn`), `payload jsonb NOT NULL
    DEFAULT '{}'` (+object CHECK), and the nullable lease-observability trio
    `leased_by`/`lease_generation`/`leased_at` (+ an all-or-nothing coherence CHECK and a
    `generation >= 1` CHECK). COMMENT ON every new column; table COMMENT refreshed (and restored
    on downgrade).
  - `design_run_status` **rebuilt** (not `ADD VALUE`) as `queued|running|succeeded|failed` — so the
    new label lands first in lifecycle order AND the widening is reversible. Downgrade refuses
    while any `queued` run exists.
  - `design_ingestion_job` gains nullable `work_id uuid` + partial UNIQUE `WHERE work_id IS NOT NULL`.
  - Backfill is byte-identical to the DAL derivation (below): uuid-inside-`run_<32 hex>`, else an
    MD5 fold of the whole run id. Guarded by a DB-backed test.

### `clue_design`

- `enums.py`: new `DesignRunKind`; `DesignRunStatus` gains `QUEUED` **first**; `design_run_kind`
  registered in `DESIGN_PG_ENUMS` so the existing parity test covers it automatically.
- `envelopes.py` (new): frozen, `extra="forbid"` pydantic `DesignTurnEnvelope` /
  `DesignIngestionEnvelope`, tagged union on `kind` (`agent_turn|web_turn|ingestion` — pydantic v2
  accepts a multi-value `Literal` as a discriminator tag; verified). Imports pydantic + stdlib +
  this package's enums only — **no `clue_fleet`** (Rule S4); `work_id` is a plain `UUID`, not the
  fleet newtype. `config` is a deliberately opaque JSON object.
- `runs.py`: `work_id_for_run` (total + deterministic — see the decision below); `create_run` now
  births **`queued`** and takes `kind` (default `AGENT_TURN`), `payload` (default `{}`), optional
  `work_id` / `checkpoint_thread_id` (defaults: the derivation, and `run_id` itself);
  `get_run_by_work_id` and `claim_run_for_execution` (fleet-plane, unscoped by workspace — the
  same structural exemption `list_running_runs_across_workspaces` already carries). The shipped
  DTO mapper is untouched; the D5 columns are served by a separate `_agent_run_job_from_row`.
- `ingestion.py`: `set_work_id`, `get_job_by_work_id`, `read_staged_request` (side-effect-free —
  no status/progress/`updated_at` change, which is what makes a requeue safe).

### Claim CAS semantics (implemented)

One `UPDATE ... RETURNING *` statement:
`WHERE work_id = :w AND status IN ('queued','running') AND (lease_generation IS NULL OR lease_generation <= :gen)`.

- `queued → running`, stamping `leased_by`/`lease_generation`/`leased_at`.
- same generation → **idempotent re-claim** (at-least-once redelivery must not stall a worker that
  already owns the lease).
- higher generation over a `running` row → **takeover allowed** (generations are monotonic, so a
  newer one proves the old lease expired; refusing would strand exactly the runs D5 rescues).
- lower generation → refused (`None`), and provably does not overwrite the live holder's stamp.
- terminal (`succeeded`/`failed`) → never re-claimed.
- unknown `work_id` → `DesignNotFoundError` (a poison task is a different answer from "someone
  else owns this").

### Agent-runtime packaging (the "one version story")

`subsystems/clue-design/apps/agent_runtime/pyproject.toml` (hatchling, dist `lumen-agent-runtime`,
package `lumen_agent`), entered as an explicit-path uv workspace member beside `apps/api`; the broad
`exclude = ["subsystems/clue-design"]` stays. **`deepagents==0.6.12`** — the platform's exact pin,
replacing the design tree's legacy `>=0.5.3,<1` floor; every other bound is the loosest range that
admits the already-resolved root-lock version, so `uv sync` re-resolved **nothing** (`uv.lock`
gained only the new package's 36 lines; zero version changes). **No version conflict arose.**
Registration edits: none needed — `lumen-api` is likewise absent from the root mypy `files`, isort
`known-first-party`, and import-linter `root_packages`; ruff's `extend-exclude` keeps the whole
design tree out of the root lint. Symmetric by construction; Part-I Step-2 owns burning that down.

## Decisions taken (deviations from the brief, with reasons)

1. **`work_id_for_run` is total and deterministic, not strict.** The brief implied a derivation
   from `run_{uuid4().hex}`. Making it *raise* on anything else broke 5 shipped design-API tests
   that hand-mint readable ids (`run_owned_ff23f5b651a3`). Rather than rewrite unrelated test
   fixtures, the function folds a non-conforming id through MD5 (`usedforsecurity=False`, an id
   derivation, not a security primitive). The property callers actually need is *determinism*
   (`get_run_by_work_id(work_id_for_run(id))` finds the run), not refusal. The migration backfill
   computes the identical thing; `test_the_dal_derivation_agrees_with_the_migration_backfill`
   checks both branches against Postgres's own evaluation so the two cannot drift.
2. **The pre-fleet API path claims its own run.** `create_run` births `queued`, but the shipped
   daemon-thread route creates a run and *is* its executor — leaving it `queued` broke the API's
   `wait_for_run` pollers (they treat "not running" as terminal) and the startup orphan sweep.
   `HybridRepository.create_run` therefore creates **and claims** in ONE transaction (the O5 rule),
   through the one sanctioned `queued → running` transition, stamped
   `leased_by="lumen-api-inprocess"`, generation 1. Chosen over giving `create_run` a `status`
   knob, which would let a run be born in any state. **Round B deletes the claim half.**
3. **`design_run_status` rebuilt rather than `ADD VALUE`-ed** — puts `queued` first in lifecycle
   order and makes the widening reversible.
4. **Two migrations, not one** — the fleet-enum touch (a platform table) is separable from the
   design reshape, and each is independently reversible.

## Gates (all re-run after the final edits unless noted)

- `alembic upgrade head → downgrade base → upgrade head` on a fresh throwaway DB (`clue_d5a_smoke`):
  **green**. `alembic heads` = **`50b84c524fa2` alone**.
- `tests/design/` on a fresh throwaway DB: **91 passed** (was 63; +28).
- `tests/fleet/` against a migrated DB: **69 passed** (includes the `fleet_task_kind` parity test).
- Design-API targeted set (`apps/api/tests/test_api.py` + `test_workspace_seam.py`) on a fresh DB:
  **135 passed** (the 5 that failed the first pass were the strict-derivation issue, fixed by
  decision 1 above and re-verified).
- Agent-runtime suite: **546 passed / 2 skipped** with the documented
  `PYTHONPATH=.:apps/api:apps/agent_runtime`, and **546/2 identically with no PYTHONPATH at all**
  — though that second result proves less than it looks: `apps/agent_runtime/tests/conftest.py`
  inserts those paths into `sys.path` itself.
- Offline platform suite: **2193 passed / 1518 skipped** (baseline 2178; +15 = the offline half of
  the new design tests).
- `uv run mypy` **589 files clean** · `uv run ruff check` clean · `uv run lint-imports` **25/25** ·
  `ruff format --check` = the known **23-file** pre-existing drift, **zero overlap** with D5 files.

## Residuals for Round B

- **`import lumen_agent.harness` still needs `PYTHONPATH=subsystems/clue-design`.** The package is
  real and installed, but `lumen_agent.harness` imports `py_lumen_obs`, which (like `py_lumen_config`)
  is still a bare PYTHONPATH-provided shim — exactly as for `lumen-api` since D2.1. An out-of-process
  fleet worker cannot rely on that. Round B (or Part-I Step-2) must either make the two shims real
  workspace members or complete their fold into `clue-config`/`clue-obs`. **This is a Round-B
  prerequisite, not a nice-to-have.**
- The API still passes neither `kind` nor `payload` to `create_run`, so every row is
  `kind='agent_turn'` with an empty envelope — including web turns. Round B's API switch fixes both
  together (splitting it would produce half-honest rows).
- `list_running_runs` / `list_running_runs_across_workspaces` (the restart orphan sweep) still scan
  `status='running'` only. Correct today because the in-process path claims immediately; they die
  with the daemon threads in Round B, when a leased job needs no sweep.
- `design_store.HybridRepository.create_run`'s claim half + `_INPROCESS_WORKER_ID` are Round-B
  deletions, marked as such in the docstring.
- Suspension/HITL statuses are deliberately absent from `design_run_status` (D5 ruling).
- `claim_run_for_execution` records design's own view of the lease; the authoritative fence remains
  the platform `work_lease` row. The `[B1×integration]` hard-fence-token residual applies here too.
