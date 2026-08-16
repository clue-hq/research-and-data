# Part II D7 Round A — the `run_event` stream gains first-class subjects

Branch `platform/design-integration`, off `84207d6c` (D6 close). **No git writes** — reviewer commits.
Master-plan authority: `docs/specs/design-integration-master-plan.md` Part II item 5. Contract:
`docs/specs/PD-part2-design-substrate.md` slice D7.

Round A widens the platform stream so a design leg *can* be a subject. Round B swaps the design
side onto it (mounts the design SSE, retires `design_run_event`).

## What shipped

| File | Purpose |
|---|---|
| `alembic/versions/a02cbcb6e641_d7_run_event_subject_widening.py` | **NEW.** `run_event` + `stream_token` subject columns, CHECKs, index, C7.7 trigger rewrite, loud-refusing downgrade |
| `subsystems/research/clue_research/durable/run_events.py` | `design.*` topics; `RunEventRow.run_id` optional + `subject_kind`/`subject_id`; `emit_run_event` stamps the project subject (signature unchanged); `list_run_events` subject filters |
| `subsystems/research/clue_research/durable/__init__.py` | re-exports the new constants |
| `platform/execution/clue_execution/run_events.py` | **NEW.** `emit_design_run_event` + subject-aware reader + `plan_subject_replay` — the half `lumen_api` can reach |
| `platform/execution/clue_execution/__init__.py` | exports it (`RunEventRow` deliberately kept submodule-qualified) |
| `platform/projections/clue_projections/events.py` | `plan_replay` is subject-capable; project-run call sites unchanged |
| `platform/api/clue_api/stream_tokens.py` | tokens are **subject**-bound, not run-bound |
| `tests/execution/test_run_event_subjects.py` | **NEW.** CHECK matrix, design emitter, DAL-drift parity (4 guards run OFFLINE) |
| `tests/projections/test_run_events.py`, `tests/api/test_projections_app.py` | unchanged-stamping proof; subject-token test |

## Migration `a02cbcb6e641` (off head `2711924d1e29`)

`run_event`: `subject_kind text NOT NULL DEFAULT 'project_run'` (+ `run_event_subject_kind_known`
CHECK over `project_run|design_run`), `subject_id text NOT NULL` backfilled `run_id::text`
(+ `run_event_subject_id_nonempty`), `run_id` → NULLABLE, and the integrity CHECK
`run_event_subject_coherent`:

```
(subject_kind = 'project_run' AND run_id IS NOT NULL AND subject_id = run_id::text)
OR (subject_kind <> 'project_run' AND run_id IS NULL)
```

New index `run_event_workspace_subject_seq (workspace_id, subject_kind, subject_id, seq)`; the two
pre-D7 indexes stay (project-run readers still use them).

**text + CHECK, not a PG enum** — the taxonomy grows at Part III+; a CHECK swap is reversible,
`ALTER TYPE … ADD VALUE` is not. Documented in the migration docstring.

**Not zero-downtime, on purpose.** `subject_kind` defaults; `subject_id` does **not** (there is
nothing correct to default it to for a non-project subject). A pre-D7 writer therefore *fails* on
the NOT NULL instead of writing an unroutable row. Repo-wide that was exactly two writers, both
updated here: `emit_run_event` and the C7.7 `publish_research_view_event_to_run_outbox` trigger
(rewritten in this migration; pre-D7 body restored verbatim on downgrade).

**Downgrade refuses loudly** if any non-project subject row survives (R2/D5 precedent) — verified
live: `refusing to downgrade: run_event holds 2 non-project-run subject rows…`.

`run_event` is **not** in the C5.1 `_APPEND_ONLY_TABLES` list (checked, not assumed), so the
backfill UPDATE is legal.

### CHECK matrix (all proven against live Postgres)
| row | verdict |
|---|---|
| `project_run` + NULL `run_id` | refused `run_event_subject_coherent` |
| `design_run` + non-NULL `run_id` | refused `run_event_subject_coherent` |
| `project_run` + `subject_id ≠ run_id::text` | refused `run_event_subject_coherent` |
| unknown kind (`agent_run`) | refused `run_event_subject_kind_known` |
| blank `subject_id` | refused `run_event_subject_id_nonempty` |
| pre-D7 column list (no subject cols) | refused NOT NULL on `subject_id` |
| `design_run` + NULL `run_id` + non-blank id | **accepted** |

## `stream_token` — widened (it WAS run-keyed)

`stream_token.run_id uuid` existed and consumption was run-bound (`run_id IS NULL OR run_id =
:run_id`), so "no change needed" was false. Added nullable `subject_kind`/`subject_id`, backfilled
from `run_id`, with `stream_token_subject_kind_known` + `stream_token_subject_coherent` allowing
exactly three shapes: workspace-wide (all three NULL), project-run (`subject_id = run_id::text`),
other kind (`run_id IS NULL`, non-blank id).

The CHECK immediately **caught a real break**: the existing `mint_stream_token` INSERT (no subject
columns, non-NULL `run_id`) matched no branch. `stream_tokens.py` is now subject-aware; `run_id=`
still works unchanged for every existing caller, and naming a subject both ways at once is refused
rather than reconciled (a token bound to the subject the caller did not mean is an auth bug).

## THE PLACEMENT OUTCOME — **fallback**, with hard evidence

Preferred plan (promote `run_events` to `clue_execution`, thin re-export from
`clue_research.durable`) was **empirically tested and breaks a contract**:

* Probe: `clue_research/durable/_probe_promote.py` doing `from clue_execution import …` →
  `uv run lint-imports` = **24 kept, 1 BROKEN — "research never imports the fleet shell (one-way
  drive seam)" (F1)**. Chain: `clue_research → clue_execution/__init__ → clue_execution.worker →
  clue_fleet`.
* A submodule-targeted import (`from clue_execution.journal import …`) *does* pass the linter
  (probe 1: 25/25) — but only because grimp records the edge to the submodule. At **runtime** it
  still executes `clue_execution/__init__` → `clue_fleet`. That games F1 rather than honouring it;
  rejected on principle, not on lint output.
* Moving the module wholly into `clue_execution` is no better: rule **P1** forbids
  `clue_projections → clue_execution` (direct imports), so `plan_replay` could not read its own
  stream without a contract relaxation.
* `clue_spine` was considered as a neutral shared DAL home and rejected — it is strictly the
  workspace/brand/project/product object spine, and `clue_execution` is forbidden from importing it
  anyway (E1).

**So:** read side + project-run writer stay in `clue_research.durable.run_events` (what
`clue_projections` may import); the design writer + subject reader + replay planner live in
`clue_execution.run_events` (what `lumen_api` may import). Duplication is two SQL statements, one
row model, one planner — held together by parity tests, four of which run **offline** in
`make check`.

**Zero contract changes. 25 kept / 0 broken, unchanged.**

### D8 consolidation option (for whoever owns it)
Single owner in `clue_execution`, with `plan_replay` taking an **injected reader** — the dependency
inversion P1's own comment already endorses ("the concrete durable-backed readers are built at the
`clue_api` composition root and injected in"). Cost: a frozen-`clue_core` contract-delta to house
the row model. Deliberately out of Round A's scope.

## Consumer sweep (grep `run_event|emit_run_event|plan_replay|RunEventRow|stream_token`)

Adapted: `clue_projections/events.py` (subject-capable), `clue_api/stream_tokens.py` (subject-bound
— was broken by the CHECK), the C7.7 DB trigger. Verified-unaffected: `run_events_wiring.py`
(`DbRunEventEmitter`), `execution_wiring.py` (`ExecutionRunEventWriter`), `stage0_tools.py`,
`run_composition.py`, `fleet_main.py`, `projections_app.py` SSE (still project-run-scoped by
design this round), `test_no_write_sql_guard.py` (no new write SQL in `clue_projections` — still
passes). `subsystems/design/clue_design/{runs,sequences}.py` and `tests/design/*` touch the
*design-owned* `design_run_event` table, untouched this round (Round B retires it).

## Verification (fresh migrated throwaway DBs, ONE suite per DB)

* `db-smoke` (up → down → up on clean `clue_d7a_smoke` / `clue_d7a_smoke2`) clean;
  `alembic heads` = **`a02cbcb6e641` alone**.
* `tests/durable/` **196/1s** · `tests/projections/` **39** · `tests/execution/` **75** ·
  `tests/api/` **635/1s** · `tests/stage0/` **136** — all green, one fresh migrated DB each.
* Six-suite design/fleet/registry/guard set — **206 passed**, exactly the D6 baseline.
* Offline platform suite (`CLUE_DATABASE_URL=""`) — **2203 passed / 1537 skipped**
  (baseline 2199/1530; +4 = the offline DAL-drift guards, +7 skipped = the new DB-gated cases).
* **Full design-API suite** (canonical `uv run pytest tests` from
  `subsystems/clue-design/apps/api`, exclusive fresh migrated DB `clue_d7a_full`) —
  **543 passed / 9 skipped / 0 failed**, `EXIT=0`. Exactly the D6 baseline; nothing design-side
  changed, and the widened table underneath it is transparent. Log `/tmp/d7a_design_full.log`.
* `uv run mypy` **593** (592 + the new module) · `ruff check` clean · `ruff format --check` **23**
  (the known pre-existing drift, zero overlap) · `lint-imports` **25 kept / 0 broken**.

## Deviations + things Round B / the reviewer must know

1. **PD contract row 17 wording is now stale.** It says the D7 widening would be "nullable
   design-subject FK column + partial index, NOT a repurposed `run_id`". Shipped is the *generic*
   `subject_kind`/`subject_id` the master plan II.5 mandates (which does not repurpose `run_id`
   either — it nulls it). Consequence, stated plainly: **`subject_id` cannot carry an FK**, so a
   design run id in `run_event` has no referential integrity to `design_agent_run`. That is the
   price of a taxonomy that grows without a schema change. Doc not edited (Round B owns the D7
   contract-status pass) — decide whether to keep generic or add a kind-specific FK column.
2. `emit_design_run_event` lives in `clue_execution.run_events`, **not** in the research writer as
   the task sketched — see the placement finding. It is the only design-emitting surface.
3. The SSE endpoint is unchanged (project-run-scoped). Round B mounts the design stream.
4. Reset-then-backlog semantics still assume no `run_event` pruner ([B4×SSE] backlog item) — now
   true for design subjects too.

## What Round B calls

```python
from clue_execution.run_events import (
    emit_design_run_event,      # (conn, *, workspace_id, design_run_id, topic, payload=None,
                                #  execution_id=None) -> RunEventRow ; design.* topics only
    list_subject_run_events,    # (conn, *, workspace_id, subject_kind, subject_id, after_seq, limit)
    subject_event_created_at,   # horizon probe
    plan_subject_replay,        # full ReplayPlan semantics (reset / backlog / effective_cursor)
    DESIGN_RUN_SUBJECT_KIND, DESIGN_RUN_EVENT_TOPICS,
)
from clue_api.stream_tokens import mint_stream_token, consume_stream_token  # subject_kind/subject_id
```

Topics are the three coarse routing classes (`design.run.event|completed|failed`); the design
`event_type` free vocabulary rides **in the payload** — that is the contract Round B implements.

## Pre-existing defects observed (reported, not fixed)

* `subsystems/clue-design/apps/api/tests/{test_api,test_web_turns}.py` still carry the 9 known
  F401/F821 under isolated ruff (D6 residual).
* The 23-file `ruff format --check` drift predates this branch; none of it is D7's.
