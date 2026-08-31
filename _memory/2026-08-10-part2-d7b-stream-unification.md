# Part II D7 Round B — the design leg streams on the platform outbox; `design_run_event` is gone

Branch `platform/design-integration`, on top of `84207d6c` (D6) + Round A (uncommitted, approved).
**No git writes** — reviewer commits. Round A note: `2026-08-10-part2-d7a-subject-widening.md`.

Round A widened `run_event`/`stream_token` with a generic `subject_kind`/`subject_id` pair. Round B
moves the design side onto it and **deletes the substrate it replaced**: the private per-run event
log, its `FOR UPDATE` sequence allocator, the polled SSE route, and the `?workspace_id=` auth
carrier.

## Files

| File | Purpose |
|---|---|
| `alembic/versions/eb9c5b963f40_d7_drop_design_run_event.py` | **NEW.** Drops `design_run_event` + its index; downgrade recreates the D1f shape byte-for-byte |
| `platform/execution/clue_execution/stream_tokens.py` | **NEW (relocated).** The mint/consume DAL, moved out of `clue_api`; adds `consume_subject_stream_token` (workspace as OUTPUT) |
| `platform/api/clue_api/stream_tokens.py` | Now a pure re-export — every pre-D7 import path still resolves |
| `platform/execution/clue_execution/__init__.py` | Exports the three token functions |
| `subsystems/clue-design/apps/api/lumen_api/run_stream.py` | **NEW.** The whole seam: `fenced_emit`, `emit_progress`, `complete_run_and_emit`, `legacy_event`, `sse_frame`, mint/consume, `stream_run_events`, `run_snapshot_events`, cadence constants |
| `subsystems/design/clue_design/runs.py` | `append_run_event`/`list_run_events`/`complete_run`/`list_running_runs_across_workspaces` **deleted**; `run_lease_generation` + `touch_run` exported (the two run-row facts the stream write needs) |
| `subsystems/design/clue_design/sequences.py` | `allocate_run_event_seq` deleted (two allocators remain) |
| `subsystems/design/clue_design/errors.py` | `DesignRunFencedError` docstring re-pointed at the new raisers |
| `lumen_api/design_store.py` | `resolve_stream_workspace_id` **deleted**; `append_run_event`→`emit_run_event`; `list_run_events(run_id)`; `complete_run` → `run_stream`; new `mint_run_stream_token`; `run_stream` imported LAZILY (see Defect below) |
| `lumen_api/main.py` | Polled SSE route + cadence constants + `sse_frame` deleted; `POST /agent/runs/{id}/stream-token` + token-gated `GET …/events` added; snapshot `events` re-sourced; executors take `lease_generation`; `_turn_design_tools(host, subject)` |
| `lumen_api/fleet_handler.py` | Sink → `store.emit_run_event`; passes `lease_generation` to the executor |
| `lumen_api/fleet_reaper.py` | Stranded terminal → `run_stream.fenced_emit(FAILED_TOPIC, terminal_payload(...))`, same transaction as the result |
| `lumen_api/toolbelt/wiring.py` | `_NoRunEventTransport` → `_DesignRunEventTransport` + `DesignRunSubject` + `DesignToolInvocations.bound_to()` |
| `apps/editor/src/engine/runEventStream.ts` | **NEW.** The fetch-stream SSE client (mint → connect → re-mint/resume) |
| `apps/editor/src/engine/editorConfig.ts` | `runStreamTokenUrl` + `runEventsUrl(base, runId, token)`; no `workspace_id` |
| `apps/editor/src/engine/agentRunner.ts`, `src/hooks/useWebAgentTurn.ts` | Factories take the run's ADDRESS, default to `openRunEventStream` |
| tests | `tests/design/{test_runs_dal_db,test_dal_foundation_db,test_design_fleet_turns_db,test_design_fleet_reaper_db}.py`, `tests/execution/test_run_event_subjects.py`, design-API `test_api.py` / `test_workspace_seam.py` / `test_write_path_governance.py` / `test_design_toolbelt.py`, editor `runEventStream.test.ts` + `agentStreaming.test.ts` |
| docs | `PD-part2-design-substrate.md` row 17 rewritten + D7-EXECUTED status; `lumen_agent/checkpoint.py` comment |

## The token relocation (R-D7-B4) — DONE, cleanly

Round A left subject-aware `mint`/`consume` in **`clue_api.stream_tokens`**, which `lumen_api` may
not import (Rule 5). The DAL therefore **moved to `clue_execution.stream_tokens`**, beside
`clue_execution.run_events` — the other half of the same one-transport seam and a package both
composition roots may import. `clue_api.stream_tokens` is now a re-export with no second
implementation; a parity test (`test_the_stream_token_store_is_one_module_with_one_subject_vocabulary`)
asserts the *same function objects* and the shared subject constant, so a fork cannot happen quietly.

New: **`consume_subject_stream_token(conn, *, token, subject_kind, subject_id) -> workspace_id | None`**
— the tenant is the RESULT, not a predicate, because the browser opening the stream cannot state
its workspace. It **requires** a subject (a NULL-subject workspace-wide token does not match), so a
stolen token cannot be widened into authority over an arbitrary run.

`resolve_stream_workspace_id` is deleted. The auth model is now: header-authed `POST
/agent/runs/{id}/stream-token` (404 on unknown/cross-tenant run — indistinguishable) → token-gated
`GET /agent/runs/{id}/events?stream_token=…`, no `?workspace_id=` anywhere.

## Mappings (topic + payload)

| writer | topic | payload |
|---|---|---|
| worker progress sink (`fleet_handler.sink` → `store.emit_run_event`) | `design.run.event` | `{"event_type": <design event name>, "data": {...}}` |
| terminal (`complete_run_and_emit`) | `design.run.completed` \| `design.run.failed` (by status) | `{"event_type": "result"\|"error", "data": <marker data>, "result": <FULL result envelope>}` |
| reaper stranded terminal | `design.run.failed` | same shape, `result` = the stranded envelope |
| **governed tool invocations** (`_DesignRunEventTransport`) | `design.run.event` | `{"event_type": <execution event type, e.g. "invocation.completed">, "data": <journal transport payload>}`, `execution_id` stamped on the row |

Serve layer: `legacy_event(row)` → `{seq, type, data, created_at}` (byte-compatible with the retired
`run_event_from_row`); `done` data = `payload["result"]`.

**Tool transport, argued.** The journal hands the transport the execution's `project_run_id` — for
design always NULL, so the journal substitutes the execution id. That is *not* the design run, so it
is discarded; the subject comes from a `DesignRunSubject(run_id, lease_generation)` carried by the
invoker. Present only on the worker path (threaded `envelope.run_id` + the handler's lease
generation through `execute_web_turn_job`); a REST-path invocation has **no subject and emits
nothing** — inventing one would put events on a timeline they do not belong to. The transport
swallows `DesignRunFencedError`/`DesignNotFoundError` (the journal is authoritative; `fenced_emit`
raises before writing, so the journal txn stays clean and still commits).

**Cost, stated:** every journal event of a run-bound invocation now also costs a SELECT (the fence),
an INSERT (the outbox row) and an UPDATE (`touch_run`), inside the journal's own transaction. On top
of D6's "~5 journal txns per governed write" that roughly doubles the per-write DB chatter *during a
turn* (request-path invocations are unaffected — no subject, no emit). Not optimised here on
purpose: the alternative is filtering the journal vocabulary in the transport, which is policy the
transport should not own. If it bites, the knob is a topic/level filter chosen at composition, never
a weaker journal.

## Rulings executed

* **R-D7-B1 — editor contract preserved, not migrated.** Two event names; progress body identical;
  `?after=` preserved and still beats `Last-Event-ID`; **0.25s live-tail** kept as an explicit
  override of the platform's 1.0s default, commented with why (the reveal pacing). `seq` is now the
  outbox's GLOBAL sequence — monotone per run, not gapless, which is all the editor ever needed
  (recon finding cited in the module docstring).
* **R-D7-B2 — terminal payload self-contained.** `clue_design.runs.complete_run` is deleted; the
  composition lives in `run_stream.complete_run_and_emit` (result written FIRST, then the event, one
  transaction, both fenced). The serve layer builds `done` from the event payload — proved by
  removal: `test_the_done_frame_is_built_from_the_terminal_event_not_the_run_row` blanks
  `design_agent_run.result_json` after completion and the stream still serves the envelope.
  **Defensive terminal branch: KEPT one release, re-documented as a LIVENESS net, not correctness.**
  Argument: both live terminal writers are transactional, so "terminal status, no terminal event" is
  unreachable through either — but `HybridRepository.set_run_result` still exists (an exempted
  facade name with zero callers, grep-proven) and *does* terminalize without emitting. Without the
  branch such a run would hang every subscriber forever. It reads the run row only when the stream
  is idle, never after a terminal event. Delete it with `set_run_result`.
* **R-D7-B3 — the zombie fence survives.** `run_stream.fenced_emit` reads the run row
  (`clue_design.runs.run_lease_generation` — also the existence/tenancy gate, raising
  `DesignNotFoundError` exactly as the old allocator did), refuses a stale generation **before any
  write**, then emits and calls `touch_run`. The `updated_at` bump is preserved deliberately: it is
  the reaper's staleness clock, and a chatty-but-healthy run that stopped refreshing it would be
  reaped alive. The handler's `DesignRunFencedError` warning branch and `except Exception: pass`
  best-effort semantics are unchanged.
* **R-D7-B5 — the editor swap.** ~180-line `runEventStream.ts`: mint via `lumenFetch`
  (header-authed) → `fetch`-stream the events url → hand-rolled SSE frame parser → dispatch to the
  same `progress`/`done` listeners → on drop, **re-mint** (tokens are single-use) and reconnect with
  `Last-Event-ID`. Unknown event names are dropped, documented against the platform stream's
  `stream.hello`/`stream.reset` (which this client will meet at Part IV). The injection seam kept
  its `EventSourceLike` shape (`addEventListener`/`close()`/`onerror`); only the factory's INPUT
  changed from a ready-made url to `{apiBaseUrl, runId}`, because the url cannot be built before the
  async mint. Both fakes still implement the interface unchanged.
* **R-D7-B6 — retirement.** See the grep proof below. `UNCONVERTED_MUTATIONS` stays a closed set of
  four with `append_run_event` → `emit_run_event` and rewritten prose.
* **R-D7-B7 — capacity honesty.** Loud note at the emit site (`run_stream` module docstring): no FK,
  no retention sweep, design payloads carry whole `operations` arrays. **D8 backlog line below.**

## Retirement completeness (grep proof)

`grep -rn "design_run_event|append_run_event|allocate_run_event_seq|list_running_runs_across_workspaces|resolve_stream_workspace_id|_NoRunEventTransport"` over `*.py|*.ts|*.tsx|*.md|*.sql`, excluding
`_memory/`, `.context/` and `alembic/versions/`, returns **only**: the D7 migration itself, D7
explanatory comments/docstrings naming what was retired, the three D7 tests that assert the deletion
(`allocate_run_event_seq` absent, `to_regclass('design_run_event') IS NULL`,
`list_running_runs_across_workspaces` absent), and the frozen historical phase doc
`subsystems/clue-design/.context/phase2b/2B-IMPLEMENTATION.md` (deliberately untouched — it is a
record of what was built in 2B). No live code path references any of them.

## Deviations

1. **`sse_frame` was relocated, not deleted.** R-D7-B6 lists it under "delete", but the stream still
   has to emit SSE frames; deleting it would mean inlining the same f-string. It moved to
   `run_stream.sse_frame` (byte-identical) with the rest of the stream. `lumen_api.main.sse_frame`
   is gone, and a test pins that.
2. **`design_store` imports `run_stream` lazily.** Discovered by a real test failure, not designed:
   importing any `clue_execution` submodule executes that package's `__init__`, which pulls
   `clue_execution.worker` → `clue_fleet` → `clue_research.durable` → LangGraph → `httpx`.
   `lumen_ingestion.describe` imports `design_store` and has a hygiene test
   (`test_import_pulls_no_pil_or_httpx`) that went red. The lazy hop is correct on the merits too —
   `design_store` is the design API's most-imported module and should not make every process pay for
   LangGraph at import. Documented at the accessor.
3. **No `stream.reset` frame.** R-D7-B1 pins this stream to exactly two event names, and a reset is
   indistinguishable from the fresh-connect replay the editor already performs on every mount. The
   replay horizon is 24h, so within a run a reconnect is always gapless.
4. **One engine per STREAM, not per poll.** The pre-D7 loop rebuilt a `HybridRepository` (hence an
   engine) every 250ms. `stream_run_events` holds one engine for the stream's lifetime and opens a
   connection+transaction per read — strictly better, same O5 property (created/disposed on the
   serving loop).
5. **PD contract row 17** rewritten to record the *generic* subject widening and its price
   (`subject_id` cannot carry an FK → no referential integrity or CASCADE from `run_event` to
   `design_agent_run`), rather than the "nullable design-subject FK column" the row originally
   sketched.

## Verification (fresh migrated throwaway DBs, ONE suite per DB; Postgres 127.0.0.1)

* `make db-smoke` equivalent on a clean `clue_d7b_smoke` — up → down → up green through BOTH D7
  migrations; `alembic heads` = **`eb9c5b963f40` alone**.
* Six-suite set (`tests/design` `tests/fleet` + `tests/api/test_toolbelt_wiring.py`
  `tests/agents/test_tool_authority_audit.py` `tests/api/test_agent_registry_wiring.py`
  `tests/api/test_journaled_invocation_roots.py`) — **206 passed**.
* `tests/durable` + `tests/projections` + `tests/execution/test_run_event_subjects.py` —
  **246 passed / 1 skipped** (Round A's 245 + the new token-relocation parity test). Battery total
  **452 / 1s** — the Round-A review number 451 plus that one test.
* **Full design-API suite** — canonical invocation, from `subsystems/clue-design/apps/api`:
  `CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@127.0.0.1:5432/clue_d7b_full3 PYTHONPATH=.:../agent_runtime uv run --project ../../../.. pytest tests -o addopts="-v --tb=short"`
  on an **exclusive, freshly created + migrated** DB → **548 passed / 9 skipped / 0 failed**,
  `EXIT=0` (D6 baseline 543/9/0; **+5** = 3 new `test_api.py` cases — token single-use/refusal
  matrix, mint-404, done-from-the-event — and 2 new `test_design_toolbelt.py` cases: request-path
  emits nothing, run-bound streams + is lease-fenced). Log `/tmp/d7b_design_full3.log`.
* **Design agent-runtime suite** (SERIAL, after the design suite) — **551 passed / 2 skipped**,
  exactly the baseline. Log `/tmp/d7b_runtime.log`.
* Offline platform suite (`CLUE_DATABASE_URL=""`) — **2204 passed / 1537 skipped** (Round A
  2203/1537; +1 = the parity test).
* Editor: `npx tsc --noEmit` clean; `npx vitest run` — **993 passed / 101 skipped** (baseline
  989/101; +4 = the new `runEventStream.test.ts`).
* `uv run mypy` **594** · `ruff check` clean · `ruff format --check` the known **23** · `lint-imports`
  **25 kept / 0 broken** (the token relocation needed no contract change).

**Gotcha for the next runner:** the root `pyproject` already sets `addopts = "-q"`. Passing `-q`
again makes it `-qq`, which **suppresses the pass/fail summary line entirely** — a run looks silent
and successful. Do not pass `-q`.

## Reviewer follow-up: the queued/running flake (fixed 2026-08-10)

The reviewer's independent full-suite run hit
`test_ingestion_pdf_route.py::test_ingest_pdf_failure_marks_job_failed_and_cleans_tmp` —
`job["status"] == "queued"` got `"running"`. **Confirmed in product code, not just accepted:**
`main._offer_ingestion` re-reads the row (`IngestionJobStore.require(job_ref["job_id"])`) *after*
the tool has committed the job **and** its `design_job` fleet task, and the embedded worker polls
at `poll_interval=0.1` (`main._build_embedded_fleet_worker`, on by default). So the claim can land
inside the response window: both `queued` and `running` are legitimate snapshots of a
successfully-created job. Pure scheduling race, load-dependent — which is why my runs passed.

**Test-only fix (no product change).** Five assertions widened to `in {"queued", "running"}`, each
with the same three-line comment naming the race and the D5 "queued is alive" ruling. All five are
the same defect because all three ingest routes share `_offer_ingestion`:

* `test_ingestion_pdf_route.py` ×2 · `test_ingestion_routes.py` ×2 · `test_ingestion_uploads_route.py` ×1

Two of them also carried a **stale** comment ("the background task runs after the response is
serialized (TestClient runs it synchronously before unblocking)") describing the pre-D5
BackgroundTasks world; that comment is replaced, not just appended to.

**Four sites deliberately left EXACT** — widening them would weaken a real contract, not remove a
flake:

* `test_web_turns.py:380`, `test_api.py:1327` — the two turn routes return a **literal**
  `{"status": "queued"}` (`main.py:2870` / `main.py:3051`), not a re-read. Nothing can race it.
* `test_api.py:1381` — the run is created with `repo.create_run` and never offered to the fleet, so
  no task exists for a worker to claim.
* `test_ingestion_jobs.py:40` — a direct `IngestionJobStore.create()` return in a store unit test;
  no route, no task, no worker.

**Verification** (fresh created + migrated throwaway DB `clue_d7b_ingest`, the three widened files):
**27 passed / 1 skipped**, and **4 consecutive runs** all green (the flake is load-dependent, so a
single green run proves little; repetition is the evidence). The design-suite total is unchanged at
**548/9/0** — that run passed under the *stricter* assertion, and the widened one accepts a superset.

## Pre-existing defects observed (reported, not fixed)

* `subsystems/clue-design/apps/api/tests/{test_api,test_web_turns}.py` still carry the 9 known
  F401/F821 under isolated ruff (D6 residual).
* The 23-file repo-wide `ruff format --check` drift predates this branch.
* `tests/test_ingestion_pdf_route.py:19` (F401 unused `Optional`) and
  `tests/test_ingestion_uploads_route.py:190` (E501) fail isolated ruff — **verified present at
  `HEAD`** and untouched by this slice's diff.
* The design tree is `extend-exclude`d from root ruff and `follow_imports=skip` for root mypy, so
  `run_stream.py` and the other `lumen_api` edits are linted only when named explicitly (they are
  E501/F-clean; the `Optional`/`Dict` style matches the surrounding tree deliberately).

## D8 leftovers

1. **Retention/pruning for `run_event` (R-D7-B7).** No FK, no cascade, no sweep — and design volume
   is materially higher than project-run volume (whole `operations` arrays per compile event, dozens
   per turn). Whoever builds it must also settle the standing `[B4×SSE]` reset-then-backlog question:
   once rows can vanish, a post-reset backlog stops being complete.
2. **No referential integrity from `run_event.subject_id` to `design_agent_run`.** The price of a
   generic subject taxonomy. Decide at D8 whether to keep it generic or add a kind-specific FK column.
3. **The D8 consolidation option from Round A still stands** — one owner for the outbox in
   `clue_execution` with `plan_replay` taking an injected reader, costing a frozen-`clue_core`
   contract-delta for the row model. The token relocation is half of that move already done.
4. **Delete the defensive terminal branch together with `HybridRepository.set_run_result`** (both
   caller-less; the branch exists only because the method does).
5. **`GET /agent/runs/{id}` still returns the whole stream** in its `events` key (no paging, capped
   at `REPLAY_PAGE_LIMIT`). Fine today; revisit with retention.
