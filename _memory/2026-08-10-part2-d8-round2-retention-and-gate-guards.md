# Part II D8 Round 2 — retention, with floors; and the gate clauses turned into tests

Branch `platform/design-integration`, on top of `a2963f0e` (D7 close) **plus Round 1's uncommitted
tree** (outbox consolidation + dead-code deletion), which was the baseline and was not touched.
**No git writes** — the reviewer commits. Two frozen rulings executed: R-D8-4 (retention) and
R-D8-5 (gate-verification guards). **No DSAR work of any kind** (assessment-only slice, founder
instruction).

## Workstream A — retention (R-D8-4)

Two sweeps land, and they are deliberately asymmetric because they are different *kinds* of
deletion. That asymmetry is the whole design and is asserted by a test
(`test_the_pruner_is_disabled_by_default_and_the_token_sweep_is_not`).

### A1. `stream_token` sweep — semantically free, **default ON** (3600s)

Both consume statements require `used_at IS NULL AND expires_at > now()`, so a used or expired row
is unreadable by every code path in the repo; deleting it is unobservable at the API surface. There
was no DELETE at all before this, and rows accumulated at the design editor's reconnect rate (one
mint per connect, 60s TTL).

- `clue_execution.stream_tokens.sweep_stream_tokens(conn, *, grace_s=DEFAULT_SWEEP_GRACE_S) -> int`.
  Predicate is written as **two range comparisons** (`expires_at < now()-grace OR used_at <
  now()-grace`) rather than `used_at IS NOT NULL`, so the planner can BitmapOr two indexes instead
  of seq-scanning. `used_at < …` is NULL-safe, so an unused token is never matched by that half.
- `DEFAULT_SWEEP_GRACE_S = 3600.0` (module constant, not a setting).
- Exported from `clue_execution/__init__.py`; `clue_api.stream_tokens` re-export **not** widened
  (the D7 parity test lists three request-path names and this is a background job).
- Loop `_stream_token_sweep_loop` / `_start_stream_token_sweep` in `clue_api/fleet_main.py`,
  copied from `_orphan_sweep_loop` exactly (interval setting, `<= 0` disables, one transaction per
  pass, fault logged never fatal); task cancelled on drain beside the others.

### A2. design `run_event` pruner — destructive, **default OFF** (interval `0.0`)

Split across the S4 boundary the D5 reaper already draws:

| half | where | what |
|---|---|---|
| eligibility | `clue_design.runs.list_prunable_terminal_runs(conn, *, terminal_before_s, limit=500)` + `TERMINAL_RUN_STATUSES` | terminal (`succeeded`/`failed`) runs whose `updated_at` is older than the window; cross-tenant, oldest-first, bounded |
| deletion | `clue_execution.run_events.prune_design_run_progress_events(conn, *, workspace_id, subject_id) -> int` | the outbox keeps ONE SQL owner (R-D8-1) |
| composition | `lumen_api/event_pruner.py` (new) | the two halves + the floors + the loop |
| wiring | `clue_api/design_fleet.py::start_design_event_pruner` → `fleet_main.py` | lazy import, own switch |

**The five floors, exactly as implemented** (none configurable):

1. **Only design progress rows.** `subject_kind = 'design_run'` and `topic = 'design.run.event'`
   are SQL **literals** in the DELETE, not parameters — a `project_run` subject is unreachable from
   this statement, so the platform stream's reset-then-backlog completeness is untouched *by
   construction*.
2. **A terminal row is never deleted, and one must survive.** The two terminal topics are outside
   the topic filter, and the statement additionally requires `EXISTS (… terminal row for this
   subject …)`, so a subject with no terminal event is skipped whole rather than partly.
3. **Only terminal runs.** Eligibility filters `status = ANY(terminal)`; age is never sufficient.
4. **`RETENTION_FLOOR_SECONDS = 7 * 86_400`**, and `effective_retention_s(configured) =
   max(configured, floor)` — clamped **up** with a logged `design_event_pruner.retention_clamped`
   warning, never honoured downward. The floor strictly exceeds `run_stream.REPLAY_HORIZON_SECONDS`
   (86_400); that inequality is asserted directly by a test. Clamping happens inside
   `prune_design_run_events`, so *every* entry point gets it (loop, test, operator one-off).
5. **Prefix-only.** A design run's terminal event is its last durable write, so removing all its
   progress rows removes a contiguous prefix of the subject's seq range — never a mid-range hole.

Settings added to `clue_config.Settings`: `stream_token_sweep_interval_s = 3600.0`,
`design_run_event_prune_interval_s = 0.0` (the founder switch),
`design_run_event_retention_s = 2_592_000.0` (30d).

`start_design_event_pruner` is gated on **its own interval**, deliberately NOT on
`design_runtime_enabled`: the handler and reaper act on *work* (a deployment that doesn't drain
design turns must not claim or re-offer it), whereas retention is a substrate property. Default-0
means a design-less deployment never reaches the lazy `lumen_api` import; an enabled-but-unavailable
import raises `DesignRuntimeUnavailable`, matching the handler/reaper precedent.

### Migration `6f81d8fd729a` (indexes only, `down_revision = eb9c5b963f40`)

`stream_token_expires_at` · partial `stream_token_used_at … WHERE used_at IS NOT NULL` ·
`design_agent_run_status_updated (status, updated_at)`. No table/column/constraint/trigger change,
so it is trivially reversible; each index carries a `COMMENT ON INDEX` explaining its sweep.

**Gotcha recorded:** the design-run index was first written partial —
`WHERE status::text IN ('succeeded','failed')` — and Postgres rejects it: *"functions in index
predicate must be marked IMMUTABLE"* (the enum→text cast). Writing the predicate against the enum
type instead would pin the index to the type's current OID, which the D5 rebuild has already
changed once. A plain composite on `(status, updated_at)` avoids both and survives a future enum
rebuild (PG reindexes on `ALTER COLUMN … TYPE`).

### Caveat sites updated (the standing [B4×SSE] question, answered)

- `clue_core.run_event.plan_replay` forward-note (review F5): rewritten from "no sweep exists" to
  the two-part answer — project subjects are undeletable by the one sweep, so the original claim
  stays *literally* true for the platform stream; the design stream's floors mean a within-horizon
  cursor can never observe a hole and an over-horizon cursor resets to 0 where the surviving
  terminal row still closes the stream. A future sweep breaking either floor owes the revisit.
- `lumen_api/run_stream.py`: the "Nothing here prunes" capacity-honesty paragraph now describes the
  pruner, its floors, the [B4×SSE] answer, and — stated plainly — that `GET /agent/runs/{id}`
  replays from seq 0, so a pruned run's snapshot returns the terminal event only. Accepted by
  ruling for a default-off sweep scoped to week-old finished runs; the run row + `result_json` are
  untouched. The in-loop D8 comment at the deleted defensive branch now names the pruner as the
  thing that honours the constraint.
- `clue_execution/run_events.py` Retention paragraph: same, from the DAL's side.

## Workstream D — gate-verification guards (R-D8-5)

1. **Catalog-driven tenancy** — `tests/design/test_design_schema_db.py::
   test_every_design_table_is_tenant_scoped`. `information_schema` for every `design\_%` BASE TABLE
   (25 today); each must have `workspace_id` and it must be `NOT NULL`. This is the only form that
   closes Part II gate clause 1 as literally stated — a hand-enumerated test only ever covers the
   tables its author remembered.
2. **Retirement guard** — `tests/design/test_design_source_guards.py`, three tests: the allowlist
   guard, an allowlist **staleness** guard (an allowlisted file that no longer mentions the table is
   a failure), and a `tokenize`-based guard that no surviving mention is a Python `NAME` token
   (mentions must be prose/SQL, never live code).
   **Design note worth keeping:** the match is a **whole-word** regex
   `(?<![A-Za-z0-9_])design_run_event(?![A-Za-z0-9_])`. The first version matched the bare substring
   and immediately flagged this round's own `design_run_event_prune_interval_s` /
   `prune_design_run_events` — genuinely different identifiers. The boundary also excludes the live
   `emit_design_run_event` and the migrations' `design_run_event_run` /
   `design_run_event_seq_unique` DDL names.
3. **SQLite guard** — same file. `sqlite3.connect(` must appear **nowhere** in production design
   code; `import sqlite3` **only** in the three modules that hold the D2.5B exemption, asserted as a
   set equality (so a fourth cannot appear and a retired one cannot silently linger):
   `lumen_api/main.py` (`@app.exception_handler(sqlite3.Error)`), `lumen_api/design_store.py`
   (raises `sqlite3.IntegrityError` from Postgres constraint violations — this one is NOT named in
   the brief but exists and is the load-bearing site), `lumen_api/custom_component_compiler.py`
   (`except (…, sqlite3.Error)`). Scope: `lumen_api`, `lumen_ingestion`, `clue_design`; tests
   excluded (two design API tests import `sqlite3` to assert the exemption working).
   **Out of scope, noted:** `apps/agent_runtime/evaluation/brand_fidelity.py` has a real
   `sqlite3.connect(` — an offline eval harness reading its own local file, not the design API.
4. **Kill→resume on the REAL Postgres checkpointer** —
   `tests/design/test_design_fleet_turns_db.py::
   test_a_taken_over_run_finds_its_checkpoint_thread_on_the_real_postgres_saver`.
   **Real composition, not a fallback.** `checkpointer_factory=_publishing_checkpointer`, which
   calls the production `lumen_api.fleet_handler.postgres_design_checkpointer` verbatim (real sync
   `PostgresSaver`, real platform DB, opened in the turn thread, keyed by the run's
   `checkpoint_thread_id`); the only addition is publishing the opened saver through a
   `threading.local()` so the stub runner can reach it — necessary because the
   `DesignTurnHost.agent_turn_runner` seam receives `(payload, root)`, not the checkpointer that
   `run_agent_turn_preview` is handed. The stub body is a real two-node LangGraph graph; attempt 1
   parks in the second node *after* the first superstep's checkpoint is committed (the test waits
   on real rows in `public.checkpoints` before killing worker A), worker A is cancelled outright,
   the lease ages out, worker B claims at a higher generation, reads the thread back through a
   fresh saver (`get_state` + `saver.list`), and then drives through the production
   `lumen_agent.checkpoint.invoke_turn_graph` seam — which clears the thread and re-runs from the
   top, logging `turn.checkpoint_restart` (asserted).
   The docstring says exactly what it certifies: **resume-as-restart with checkpoint continuity**,
   NOT mid-turn resume.
   Housekeeping: the saver's tables are outside Alembic and outside the test's rollback, so the test
   deletes its own thread from `checkpoint_writes`/`checkpoint_blobs`/`checkpoints` in a `finally`.

## Files changed

| file | why |
|---|---|
| `platform/execution/clue_execution/stream_tokens.py` | `sweep_stream_tokens`, `DEFAULT_SWEEP_GRACE_S`, `_SWEEP_SQL`, retention paragraph |
| `platform/execution/clue_execution/run_events.py` | `prune_design_run_progress_events` + literals; Retention paragraph rewritten |
| `platform/execution/clue_execution/__init__.py` | export `sweep_stream_tokens` |
| `platform/api/clue_api/fleet_main.py` | token-sweep loop + both new background tasks + drain list + docstring |
| `platform/api/clue_api/design_fleet.py` | `start_design_event_pruner` (own switch, lazy import) |
| `libs/clue-config/clue_config/settings.py` | three new knobs, with the ON/OFF rationale inline |
| `libs/clue-core/clue_core/run_event.py` | `plan_replay` F5 forward-note → the D8 answer |
| `subsystems/design/clue_design/runs.py` | `TERMINAL_RUN_STATUSES`, `list_prunable_terminal_runs` |
| `subsystems/clue-design/apps/api/lumen_api/event_pruner.py` | **new** — the pruner + floors + loop |
| `subsystems/clue-design/apps/api/lumen_api/run_stream.py` | capacity-honesty + [B4×SSE] + snapshot consequence |
| `alembic/versions/6f81d8fd729a_…py` | the three indexes |
| `tests/execution/test_retention_sweeps_db.py` | **new** — 9 substrate tests |
| `tests/design/test_design_event_pruner_db.py` | **new** — 8 eligibility/floor/SSE tests |
| `tests/design/test_design_source_guards.py` | **new** — 4 offline guards |
| `tests/design/test_design_schema_db.py` | +catalog tenancy test |
| `tests/design/test_design_fleet_turns_db.py` | +real-checkpointer takeover test |

## Gates

Five throwaway DBs, never shared: `clue_d8r2_a` (dev/iterate + db-smoke), `clue_d8r2_g1`,
`clue_d8r2_g2`, `clue_d8r2_g3`, `clue_d8r2_b` (design API), plus `clue_d8r2_base` (baseline probe)
and `clue_d8r2_smoke`.

| gate | result | baseline |
|---|---|---|
| db-smoke: up → down(base) → up on a fresh DB | green | — |
| `alembic heads` / `current` | **`6f81d8fd729a` alone** | new head, single |
| offline `CLUE_DATABASE_URL="" uv run pytest` | **2208 passed / 1556 skipped** | 2204/1537 → **+4 passed / +19 skipped**, exactly the new tests (4 offline guards; 19 DB-gated) |
| `tests/design tests/fleet tests/toolbelt` (fresh DB) | **221 passed** | **207** measured on a stashed tree, same command, fresh DB (Round 1's note says 206 — one off; my delta is exactly the 14 new design tests) |
| `tests/durable tests/projections tests/execution/test_run_event_subjects.py` + new file | **255 passed / 1 skipped** | 246/1s → +9, exactly the new retention file |
| `tests/execution` (fresh DB) | **85 passed** | unchanged |
| `uv run mypy` | **594 files, 0 issues** | 594 |
| `uv run ruff check .` | clean | clean |
| `uv run ruff format --check .` | **23** would reformat | 23 — **zero added** (verified by stash-diffing the file list; 5 files initially drifted and were formatted back) |
| `uv run lint-imports` | **25 kept / 0 broken** | 25/0 |
| design API `test_api.py test_workspace_seam.py test_write_path_governance.py` (fresh MIGRATED DB) | **145 passed** | 145 |

**Gotcha (cost 2 minutes, will cost the next agent more):** the design-API spot suites need the
throwaway DB **migrated** first (`alembic upgrade head`) — an unmigrated fresh DB gives 89 failed /
56 passed, which looks like a real regression.

Design tree is ruff-excluded at root, so the two touched/added design files were checked with
isolated ruff (`--isolated --line-length 100 --select E,F,I,B,SIM,C4`): `event_pruner.py` clean;
`run_stream.py` format drift **verified pre-existing at HEAD** (`git show HEAD:… | ruff format
--check`). `event_pruner.py` keeps `fleet_reaper.py`'s local typing style (`Optional[...]`,
`List[str]`) on purpose — it copies that module, and the design tree is not governed by the root
UP rules.

## Still open

- **DSAR reach over design rows** — untouched by instruction; `docs/specs/PD-D8-dsar-assessment.md`
  (Round 1's uncommitted artefact) is the assessment.
- The pruner has **never been run against production-shaped volume**; the loop's `limit=500` per
  pass is a guess sized for "drain over several passes", not a measurement.
- `GET /agent/runs/{id}` still returns the whole stream in `events` (capped at `REPLAY_PAGE_LIMIT`)
  — pruning shrinks the tail case but does not bound the live case.
- No referential integrity from `run_event.subject_id` to `design_agent_run` (generic-subject price,
  ruled accepted at D7). The pruner's `EXISTS`-on-terminal is what stands in for it.
