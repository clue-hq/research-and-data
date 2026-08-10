# Part II D8 Round 1 — one outbox owner, one planner; the dead terminal path deleted

Branch `platform/design-integration`, on top of `a2963f0e` (D7 close). **No git writes** — the
reviewer commits. Two frozen rulings executed: R-D8-1/2 (outbox consolidation) and R-D8-3
(dead-code deletion). Round 2 (retention/pruning) and DSAR are explicitly NOT in this round.

## Workstream B — outbox consolidation

D7 shipped the `run_event` stream as two thin DALs over one table (project half in
`clue_research.durable.run_events`, design/subject half in `clue_execution.run_events`) bound by
four offline parity tests. D8 collapsed it by **inverting the read dependency** rather than
relocating code, which is what makes it legal under F1/E1/P1 at once.

### The contract-delta (frozen `clue_core`)

New module **`libs/clue-core/clue_core/run_event.py`**, recorded the established way — a
`**Contract-delta 2026-08-10 …**` paragraph opening the module docstring (same pattern as
`clue_core/memory.py`'s "PB-B3 contract-delta", `entity.py`'s inline `contract-delta 2026-07-24`
and `verification.py`'s `AgeOutCandidate` promotion note). It holds:

- `RunEventTopic` (StrEnum) · `RUN_EVENT_TOPICS` · `DESIGN_RUN_EVENT_TOPICS`
- `PROJECT_RUN_SUBJECT_KIND` / `DESIGN_RUN_SUBJECT_KIND` / `RUN_EVENT_SUBJECT_KINDS`
- `NARRATIVE_EMIT_SKIPPED_KEY`
- `RunEventRow` (pydantic — core already depends on pydantic and on nothing else)
- `ReplayPlan` + **`plan_replay`** (the planner body) + the `RunEventReader` Protocol

All re-exported from `clue_core/__init__.py`. **No new dependency**: the reader Protocol is
*connection-bound* (`cursor_created_at(seq)` / `events_after(after_seq, limit)`), so `clue_core`
never sees `AsyncConnection` and keeps pydantic as its single dependency.

**Deliberate deviation from the brief, flagged:** the brief put only the *Protocol* in `clue_core`
and left `plan_replay` in `clue_projections`. That cannot fold `plan_subject_replay` in (E1 forbids
`clue_execution → clue_projections`), so the duplication would have survived as a second planner.
The planner body therefore moved to `clue_core` — the only package on both sides of the
`clue_projections` ⊥ `clue_execution` ban — and the brief's *preferred* outcome (one planner)
is achieved. `clue_projections.events` is now a documented re-export shim (same precedent as
`clue_api.stream_tokens` at D7-B4); `from clue_projections import plan_replay, ReplayPlan` still
resolves, to the same function object.

### The DAL

`platform/execution/clue_execution/run_events.py` is now the single owner: `emit_run_event`
(project), `emit_design_run_event` (design, refusals unchanged), `list_run_events` (the superset
reader), `event_created_at`, plus **`DbRunEventReader`** (frozen dataclass binding conn + tenant +
optional subject/run filters — the one concrete `RunEventReader`). SQL is byte-identical to D7's
(the C7.7 DB trigger writes the same columns).

**Deleted as genuine duplicates** (not just moved): `list_subject_run_events` (== `list_run_events`
with a subject), `subject_event_created_at` (== `event_created_at`), `plan_subject_replay`,
`SubjectReplayPlan` (field-identical to `ReplayPlan`).

`subsystems/research/clue_research/durable/run_events.py` **deleted**; its import block and 11
`__all__` entries removed from `durable/__init__.py` (replaced by a comment saying where it went).
Verified first by grep: **zero** callers inside `clue_research` — the module was only ever there
because `clue_projections` may import research read surfaces but not `clue_execution`.

### Call sites repointed

| file | change |
|---|---|
| `clue_api/projections_app.py` | `list_run_events` from `clue_execution.run_events`; `plan_replay(DbRunEventReader(conn, workspace_id=…, run_id=…), …)` — the reader is built at the composition root |
| `clue_api/stage0_tools.py` | `RunEventTopic` ← `clue_core`; `emit_run_event` ← `clue_execution.run_events` |
| `clue_api/run_events_wiring.py` | same split; `ProjectRunRow`/`ProjectRunStatus` stay on `clue_research.durable` |
| `clue_api/execution_wiring.py` | `emit_run_event` folded into the existing `from clue_execution import (…)` |
| `clue_api/toolbelt_wiring.py`, `clue_projections/run_views.py` | `NARRATIVE_EMIT_SKIPPED_KEY` ← `clue_core` |
| `lumen_api/run_stream.py` | shapes ← `clue_core`; `DbRunEventReader`/`emit_design_run_event`/`list_run_events` ← `clue_execution.run_events`; `_reader()` helper; `plan_replay(_reader(...), …)` |
| tests | `tests/projections/test_run_events.py`, `test_run_views.py`, `tests/execution/{test_journal,test_run_event_subjects}.py`, `tests/stage0/test_phase_c4_governed.py`, `tests/api/{test_projections_app,test_c7_research_view_serving}.py`, `tests/design/test_design_fleet_reaper_db.py` |

`lumen_api/design_store.py`'s **lazy** `_run_stream()` import is untouched (the httpx-hygiene tax
is unchanged this round, per the brief).

### Parity tests → single-ownership guards (R-D8-2)

`tests/execution/test_run_event_subjects.py`: the four offline drift guards were **replaced**, not
deleted, by identity assertions —

- `…_row_model_has_exactly_one_definition` — `exec_run_events.RunEventRow is clue_core.RunEventRow`
- `…_topic_and_subject_vocabularies_have_exactly_one_definition` — same-object identity **plus**
  every invariant the old parity test proved (enum ⇄ allow-list, design ⊂ stream, exact `design.*`
  prefix, subject-kind set)
- `…_replay_planner_has_exactly_one_definition` — `clue_projections.plan_replay is
  clue_core.plan_replay`, and the four D7 twin names are asserted **absent** from
  `clue_execution.run_events`; plus "the planner takes a reader, not a conn"
- `…_outbox_dal_has_exactly_one_owner` — `clue_research.durable` exposes none of the seven names,
  and `import clue_research.durable.run_events` raises `ModuleNotFoundError`

The stream-token same-object parity test is untouched and passing. The DB-gated behavioral tests
all survive; `both_replay_planners_agree` became
`the_one_planner_plans_a_design_subject_exactly_as_it_plans_a_project_run` (same three cases, plus
a new assertion that the *reader's* subject filter — not the planner — is what scopes the stream).

## Workstream C — dead-code deletion (R-D8-3)

Deleted as one unit, caller-lessness grep-verified first:

- `HybridRepository.set_run_result` (`lumen_api/design_store.py`). The DAL
  `clue_design.runs.set_run_result` **stays** — `run_stream.complete_run_and_emit` and the runs-DAL
  tests use it.
- The defensive terminal branch in `run_stream.stream_run_events`, the idle-only `finished`
  computation feeding it, and `_terminal_run` (its only reader).
- `tests/test_write_path_governance.py`: `UNCONVERTED_MUTATIONS` is now the **three** run-lifecycle
  writes (`create_run` / `complete_run` / `emit_run_event`); equality assertion, module docstring
  and the `#:` prose updated; `set_run_result` added to
  `test_the_deleted_dead_facade_methods_stay_deleted`.

Two notes written at the deletion sites, both load-bearing for Round 2:

1. `terminal_payload`'s docstring: the serve layer now **never reads the run row at all** — a
   structural property of `stream_run_events`, not a claim about timing.
2. **A terminal `run_event` row must never be pruned.** Recorded twice on purpose — in
   `run_stream.py`'s module docstring (new "hard constraint that pruner inherits" paragraph) and at
   the exact loop position where the branch was, and again in `clue_execution/run_events.py`'s
   Retention paragraph. The terminal event is now the *only* thing that closes a subscriber's
   stream; the liveness net that used to cover a missing one is gone.

## Gates (all from repo root unless noted; two throwaway DBs, never shared)

`clue_d8r1_a` (platform) · `clue_d8r1_b` (design API) — both freshly created + migrated.

| gate | result | baseline |
|---|---|---|
| `alembic upgrade head` on a fresh DB · `alembic heads` | green · **`eb9c5b963f40` alone** | unchanged, no new migration |
| offline `CLUE_DATABASE_URL="" uv run pytest` | **2204 passed / 1537 skipped** | 2204/1537 — exact (4 parity tests replaced 1:1 by 4 guards) |
| `tests/design tests/fleet …` six-suite set | **206 passed** | 206 |
| `tests/durable tests/projections tests/execution/test_run_event_subjects.py` | **246 passed / 1 skipped** | 246/1s |
| `tests/api/test_projections_app.py … test_journal.py` | **30 passed** | n/a (new combination) |
| `uv run mypy` | **594 files, 0 issues** | 594 |
| `uv run ruff check .` | clean | clean |
| `uv run ruff format --check .` | **23** would reformat | 23 — **zero added** |
| `uv run lint-imports` | **25 kept / 0 broken** | 25/0 |
| design-API `test_write_path_governance.py test_api.py test_workspace_seam.py` (DB `_b`) | **145 passed** | — |

The design tree is ruff-excluded at root, so the three touched design files were also checked with
isolated ruff: `check` clean; `format` drift in `run_stream.py`/`design_store.py` **verified
pre-existing at HEAD** (`git show HEAD:… | ruff format --check`), and the one line I touched in
`test_write_path_governance.py` is formatter-clean.

## Incidental

`alembic/versions/a02cbcb6e641_…py`'s comment named `clue_research.durable.run_events` as a mirror
of the subject-kind CHECK; repointed to `clue_core.run_event`. Comment only — no migration
behaviour, no revision id, no DDL touched.

## Still open (Round 2 / later)

- **Retention/pruning for `run_event`** (R-D7-B7) — now carrying the hard constraint above, plus
  the standing `[B4×SSE]` reset-then-backlog question.
- No referential integrity from `run_event.subject_id` to `design_agent_run` (generic-subject price,
  ruled accepted at D7).
- `GET /agent/runs/{id}` still returns the whole stream in `events` (capped at `REPLAY_PAGE_LIMIT`).
- DSAR reach over design rows — untouched here by instruction.
