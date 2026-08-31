# Part II D5 Round C — ingestion onto the fleet, the stranded-work reaper, workspace debts, the bridge ruling

Branch `platform/design-integration`, on top of `c24eeae0` (D4) **plus the uncommitted D5 Rounds
A + B** (`_memory/2026-08-09-part2-d5a-durable-foundation.md`,
`_memory/2026-08-09-part2-d5b-turns-on-the-fleet.md`). Uncommitted at the time of writing — the
reviewer commits. **This closes D5.**

## What landed

### 1. Ingestion onto the fleet

**Migration `ad332dc38f36`** (off `50b84c524fa2`, single head). `design_ingestion_job` gains the
same lease trio `design_agent_run` got in Round A (`leased_by` / `lease_generation` / `leased_at`,
nullable, all-or-nothing CHECK, `generation >= 1` CHECK) — a claim that cannot express a
generation cannot express takeover. Both tables gain `reoffer_count smallint NOT NULL DEFAULT 0`
(the reaper's durable retry budget). No enum change: `design_ingestion_status` already had
`queued`. Fully reversible; no downgrade guard needed (nullable observability columns + a
defaulted counter destroy no domain state).

**`clue_design.ingestion`** gained the exact twins of the run surface:
- `create_job(..., job_id=, work_id=)` — both ids minted by the caller so the frozen envelope can
  name the job it dispatches.
- `claim_job_for_execution` — the CAS, case-for-case identical to `claim_run_for_execution`
  (queued→running; same generation = idempotent re-claim; HIGHER generation = takeover; LOWER =
  refused `None`; terminal never re-claimed; unknown `work_id` = `DesignNotFoundError`, a poison
  task, not a refusal).
- `expected_generation=` on `set_running` / `set_stage` / `complete` / `fail`, raising the new
  `DesignJobFencedError` (sibling of `DesignRunFencedError`; kept separate because the two name
  different rows with different ids).
- `list_dispatched_running_jobs` / `reoffer_stranded_job` / `fail_stranded_job` (reaper input +
  the two CAS-guarded writes).

**Routes.** All three (`/website`, `/pdf`, `/assets`) now OFFER instead of dispatching
`BackgroundTasks`. `main._offer_ingestion_job` mints `job_id` + `work_id`, builds the
`DesignIngestionEnvelope`, and calls the new `IngestionJobStore.create_and_offer`, which inserts
the job and `enqueue_task`s its `design_job` in ONE bridge call = ONE transaction (the
`create_run_and_offer` / `launch_entity_research_run` precedent). **Staging now happens BEFORE
the job row exists** on the PDF/asset routes, so the row is created with its complete request and
`update_request` disappears from both routes. The website route's `run_in_threadpool` dance is
DELETED — `DesignStoreBridge._run_isolated` has handled "sync store called from a live loop"
since D2.3, so the extra hop bought nothing.

**Handler.** `DesignJobWorkHandler.handle` is now shape-agnostic: parse → claim (run or job DAL,
chosen by envelope type) → `asyncio.to_thread(self._execute)` raced against
`lease_lost`/`stop_requested` → terminal. `_execute` dispatches to `execute_agent_turn_job` /
`execute_web_turn_job` / the new `main.execute_ingestion_job`.

**Ingestion claim/takeover semantics as shipped** (asked for explicitly):
- The handler claims through the CAS *before* running anything; the pipeline's own
  `run_ingestion_job` still calls `set_running` (now fenced), which is an idempotent no-op on an
  already-claimed row and keeps the direct/CLI callers working unchanged.
- A re-offered job is claimable because `reoffer_stranded_job` CLEARS the lease trio: the row
  returns to `queued` with `lease_generation IS NULL`, which the CAS predicate admits at any
  generation. Leaving a stale generation behind would fence the very writes the next claimant is
  supposed to make.
- Cooperative stop is turn-parity: on `lease_lost`/`stop_requested` the handler returns
  `requeue=True` without awaiting the thread. Python cannot interrupt it, so the abandoned
  pipeline runs to completion and its writes are refused by the generation fence.
  `run_ingestion_job` catches `DesignJobFencedError` on every write and returns — **it does not
  stamp `failed` over the live attempt**, which is the one place a fence must not be treated as an
  error.

### 2. The stranded-run/job reaper

**In-handler containment.** An exception escaping the executor (a store fault, not a failed turn)
is caught in `handle`; `_terminalize_failed` writes the design row `failed` under the lease fence
(`design_job.handler_error` error envelope) and the `WorkResult` reports `handler_error` (or
`handler_error_uncontained` when even that write failed). Previously this marked only the FLEET
task failed and left the design row `running` with nobody coming for it.

**`lumen_api/fleet_reaper.py` (new).** Policy **re-offer once, then fail**:
- Stranded = design row `running` + NO live `work_lease` + fleet task terminal or absent.
  A live lease wins over any task state (Rule F1: the lease is the authoritative fence); a
  `queued`/`claimed` task means the work is on its way and is left alone.
- First sighting → `running` → `queued`, lease cleared, `reoffer_count += 1`, and the SAME
  `design_job` re-enqueued with `reopen_terminal=True` (load-bearing: the default enqueue is a
  no-op on a duplicate dedup key, so without it the row would return to `queued` with no task —
  a worse strand than the one being repaired). A re-offered turn re-executes via the
  checkpoint-restart path; its frozen envelope is unchanged.
- Second sighting → terminal `failed` with `STRANDED_CODE = "design.stranded"`, plus a terminal
  `error` run-event in the SAME transaction (so the SSE stream settles).
- Why 1 and not 0 or N: 0 throws away recoverable work for a transient fault; N turns a poison
  job into an infinite fleet-wide retry loop. The counter is a durable column because a
  process-local "I already retried this" dies with the process whose death caused the strand.
- A `stranded_after_s` grace window (default 120 s, compared against `updated_at`) keeps the
  reaper out of the moment between a claim and its first lease renewal.
- **S4 held:** the three DAL functions touch design rows only; the fleet join (`fleet_task`
  status by work id, `work_lease` liveness) is read in `fleet_reaper` and passed in as a decision.
  `clue_design` still imports no `clue_fleet` (import-linter 25/25).

**Composition, one implementation, two hosts** (the handler's precedent): `fleet_reaper` lives in
`lumen_api` because judging a stranded row means reading the design DAL, and `lumen_api ->
clue_api` is forbidden. `clue_api.design_fleet.start_design_reaper` is the thin lazy wrapper;
`fleet_main` starts it beside `_start_orphan_sweep` under `settings.design_runtime_enabled` +
`design_reaper_interval_s` (new, 300 s); the design API's lifespan starts it beside the embedded
worker under `lumen_design_reaper_interval_s` (new, 300 s), gated on the worker existing (a reaper
with no drain could re-offer work nothing would claim).

**Also fixed (Round-B defect found here).** The `claim_refused` / poison-task paths returned
`task_finalized=True` without finishing the task. In `LeasedWorkWorker`, `task_finalized=True`
means "the handler already called `finish_task` itself" (the `entity_research` contract), so the
row stayed `claimed` forever and was re-owned every stale window — an infinite 60 s loop. Those
paths now let the worker finish the task DONE.

### 3. The D2.5A workspace-threading debts

**Two live cross-tenant reads found and fixed** — both were `DescriptionStore()` (dev-workspace
default) inside `workspace_asset_library_manifest` and `reference_asset_manifest`, while the
asset-registry read beside them was correctly scoped. The reference one is on the **request**
path (`POST /agent/turns` → `resolve_agent_turn_references`), so every tenant's reference
manifest was annotated from the dev tenant's description rows. Both now take
`repo.workspace_id`.

**Signatures made loud (no default = no silent dev workspace):**
- `api_blob_store(workspace_id: str)` — was `Optional`.
- `resolve_agent_turn_brand_kit(payload, blobs)` / `resolve_web_turn_brand_kit(web_doc, blobs)` /
  `resolve_agent_turn_references(payload, blobs)` — `blobs` required.
- `resolve_account_assets(account_card, workspace_id)` — required.
- `run_agent_turn_preview(..., *, workspace_id)` / `run_web_agent_turn(..., *, workspace_id)` —
  required keyword. `run_web_agent_turn`'s old three-step fallback chain
  (`workspace_id or registry.blobs.workspace_id or default_workspace_id()`) is replaced by an
  explicit disagreement CHECK: a registry whose workspace differs now raises instead of silently
  re-scoping.
- The three `run_*_ingestion` pipelines take `workspace_id: str` (required) and a new
  `expected_generation`.
- `default_workspace_id` is no longer imported by `main.py` at all.

**The `api_blob_store()` settings-vs-`app.state.storage` residual is closed on the worker path,
and the survivor is argued rather than inherited.** The turn/ingestion executors now pass the
HOST's handles down: `blobs=_turn_blob_store(host, ws)` and a new
`engine_cache_root=_host_engine_cache_root(host, ws)` (new `DesignTurnHost.engine_cache_root`,
filled from `app.state.engine_cache_root` by the embedded worker). So on the worker path neither
the byte backend nor the engine-cache tree is re-derived from settings.

**Remaining implicit-workspace sites, each argued:**
1. `api_blob_store` itself still reads `storage_from_settings()`. It cannot do otherwise — it
   exists precisely for callers with no app handle (CLI, fixtures, off-request resolver
   defaults), and every worker-path caller now bypasses it via the host handles above.
2. `font_library.library_workspace_id()` reads the dev-workspace env var. **Deliberate, not a
   residual**: the font library is ONE curated, openly-licensed shared set provisioned per
   environment, not per-tenant data. Documented in place as a Part-IV (auth/tenancy) decision
   about giving it a first-class shared namespace.
3. `HybridRepository()` / `IngestionJobStore()` / `DescriptionStore()` still default their
   `workspace_id` — but only for DIRECT constructions (scripts, tests, which read the same env the
   per-test isolation fixture sets). No request path and no worker path reaches those defaults any
   more.
4. `read_public_design_blob` builds its bridge with `default_workspace_id()` and
   `ensure_workspace=False`. Deliberate and pre-existing (R-D4-7): the route is O4-exempt and the
   read itself is workspace-unscoped; the tenant name is only there to construct a bridge.

### 4. The honest O5-bridge ruling (docs only, no code change)

**The bridge does NOT die at D5.** D5 delivered durable execution: the daemon threads are gone,
in-flight work survives a restart, and the WORKER path is async-native. D5 never promised an async
REQUEST path — every design route is a synchronous FastAPI endpoint by design, and a synchronous
route needs a synchronous store. Retiring the bridge means making every route `async def`: surface
work, not durable-execution work, owned by **Part IV** (editor mounted in the platform shell) or
**Part-I Step-2** (week-one hygiene), whichever lands first.

Marker sweep (`grep "at D5"`), all four in-scope sites updated:
- `design_store.py` module docstring — the full ruling lives here.
- `design_store.py:_run_isolated` and `DesignBlobStore` — "dies with the bridge, at the surface
  work, not at D5".
- `main.py` SSE poll-cost comment.
- `docs/specs/PD-part2-design-substrate.md` §O5 — a dated CORRECTED note under the original
  ratification (the original text is left intact; the correction is appended).
- `clue_design/runs.py::list_running_runs_across_workspaces` — its "(Dies at D5)" note now says
  what actually happened: its CALLER died in Round B, the function survives unwired, and the
  reaper deliberately does not use it (it needs the lease/re-offer columns).

## Decisions / deviations

1. **A migration was written** (the brief allowed one "only if genuinely needed"). Takeover
   semantics for ingestion are unexpressible without a lease generation, and a bounded re-offer is
   unexpressible without a durable counter. Both tables, one migration, since neither half is
   useful alone.
2. **`reoffer_count` is a real column, not a payload key.** The frozen envelope is the immutable
   authority for what the work IS; a retry budget is execution state and does not belong in it.
3. **The reaper sweeps the whole database, not a workspace.** Same structural argument as
   `list_running_runs_across_workspaces`: a stranded row belongs to whichever tenant owns it, and
   a per-tenant sweep would leave every other tenant stranded forever. Consequence for tests: the
   new tests assert on THEIR row exactly and on the sweep counters only as lower bounds.
4. **Ingestion re-offer rebuilds its envelope; a turn re-offer replays the stored one.** A run
   stores its frozen envelope in `design_agent_run.payload`; an ingestion job does not (its
   durable authority is `request_json`, which the worker re-reads via `read_staged_request`). The
   three fields the envelope needs are columns on the job row and immutable, so rebuilding is
   exact — and the test parses the re-offered payload back through the handler's own union to
   prove it is executable, not merely well-shaped.
5. **`execute_ingestion_job` lives in `main.py`** and resolves `run_*_ingestion` from the module
   namespace. Not stylistic: the four ingestion route suites monkeypatch
   `main_module.run_*_ingestion` to inject their capture/extract/analyze stubs, and calling
   `lumen_ingestion.pipeline` directly from the handler would silently bypass all of them.
6. **`IngestionJobStore` carries `expected_generation` rather than threading it through every
   call.** One constructor argument fences every write the pipeline makes; the alternative was
   plumbing it through `run_ingestion_job`'s reporter closure and four call sites.

## Tests

New: `tests/design/test_design_fleet_reaper_db.py` (8 tests, DB-backed).
- `test_a_handler_exception_terminalizes_the_run_instead_of_stranding_it` — an exploding
  checkpointer factory faults INSIDE the claimed turn (the exact window that used to strand);
  the row lands `failed` with `design_job.handler_error` and the event stream carries its
  terminal marker.
- `test_the_reaper_reoffers_a_stranded_run_once_then_terminalizes_it` — pass 1: `queued`,
  `reoffer_count == 1`, lease cleared, a `queued` task exists again. Strand it again. Pass 2:
  `failed` with `design.stranded` + terminal event. Pass 3: unchanged.
- `test_the_reaper_never_touches_a_run_under_a_live_lease` — adversarially arranged (task looks
  terminal, lease is live) so the lease has to win.
- `test_the_reaper_leaves_a_still_queued_task_alone`.
- `test_the_reaper_recovers_a_stranded_ingestion_job_the_same_way` — including parsing the
  re-offered payload back through `DesignIngestionEnvelope`.
- `test_the_reaper_ignores_an_ingestion_job_that_was_never_dispatched` (no `work_id`).
- `test_ingestion_claim_cas_matches_the_run_cas_case_for_case` (all five CAS cases + poison).
- `test_a_fenced_ingestion_write_is_refused_rather_than_clobbering_the_takeover`.

Added to `tests/api/test_fleet_wiring.py`: the reaper is off without the runtime switch, and off
at a non-positive interval (the orphan-sweep convention).

Adapted: `tests/conftest.py` in the design suite grew `wait_for_ingestion_job` (ingestion is
asynchronous now — the POST returns `queued`), applied at 18 GET sites across the four ingestion
route suites; the two "missing staged bytes" tests now wait for the fleet pass BEFORE their direct
re-run (otherwise the two race and the worker's success overwrites the failure under test); the
four pipeline stubs take the new `expected_generation`; `test_api.py` gained a `_workspace_blobs()`
helper for the now-required `blobs` argument.

**`_purge_work` in the new test file is load-bearing**, and both hazards it closes were observed:
a leftover `queued` design task is drained by the NEXT test's worker (it misattributed a worker in
Round B's concurrency test), and a leftover `running` design row is *stranded work* to the next
test's reaper pass, which re-offers it and re-creates the queue row. It deletes the fleet task,
the lease, and the design row.

## Gates (every DB fresh AND migrated)

- `make db-smoke` equivalent on a throwaway DB (`clue_d5c`): up → base → head, **green**.
  `alembic heads` = **`ad332dc38f36` alone**.
- `tests/design/ tests/fleet/` on a fresh migrated DB: **171 passed** (Round B: 163; +8 = the new
  reaper file).
- Full design-API suite, canonical invocation, fresh DB (`clue_d5c_api`): **501 passed / 9 skipped
  / 0 failed** (510 collected), `EXIT=0` — identical to the Round-B baseline.
- Agent-runtime suite, no PYTHONPATH: **551 passed / 2 skipped** (unchanged).
- Editor: **untouched this round** (`apps/editor/` carries only Round-B's status-vocabulary
  widening); tsc/vitest not re-run.
- `uv run mypy` **590 files clean** · `ruff check` clean · `lint-imports` **25/25** ·
  `ruff format --check` = the known **23** pre-existing files (the new migration was formatted).
- Offline platform suite (`CLUE_DATABASE_URL=""`): **2199 passed / 1530 skipped** (Round B: 2197;
  +2 = the two new offline fleet-wiring reaper tests — the 8 DB-backed reaper tests correctly
  skip offline).

## Closing state (2026-08-09)

D5 is complete: turns AND ingestion are leased fleet work, no design row can sit `running`
forever (containment first, reaper second), no worker-path read or write picks a workspace
implicitly, and the bridge's death has an honest owner. All gates above were re-run after the
final docstring pass. Nothing is committed — the reviewer commits.

## Pre-existing defects found (reported, not fixed)

- **`tests/design/test_design_fleet_turns_db.py` needs the `logging` plugin.** It takes `caplog`,
  so `pytest -p no:logging` ERRORs at setup. Cosmetic (nobody runs it that way in CI) but it cost
  time here; noted so the next agent does not re-diagnose it as a regression.
- The Round-B `task_finalized` misuse described above was a real defect, and it IS fixed here.
- `clue_design.runs.list_running_runs_across_workspaces` is now unwired dead code (its caller died
  in Round B). Left in place with a corrected docstring rather than deleted mid-round.

## Residuals for D6/D7/D8

- **Zombie threads (unchanged).** A fenced-out worker's synchronous body — turn OR ingestion —
  runs to completion. Its writes are refused; it burns CPU and, for a turn, an LLM budget. The
  platform hard-fence-token work is still the `[B1×integration]` residual.
- **Resume-as-restart, not resume** (Round B). Making `LumenDesignTools` reconstructible from a
  run id is what would flip `checkpoint.py`'s restart branch into a real resume.
- **The reaper is time-based, not event-based.** It notices a strand within one interval (300 s)
  plus the grace window. A `LISTEN/NOTIFY` or a fleet-side "task failed with an un-terminalized
  subject" hook would make it prompt; not needed while the shape is rare by construction.
- **The O5 bridge dies at the SURFACE work** (Part IV / Part-I Step-2), per the ruling above —
  together with making the design routes `async def` and dropping `HybridRepository`'s legacy name.
- **D7 retires `design_run_event`** onto the platform run-event stream, which also deletes the SSE
  polling loop, its per-poll engine cost, and the `?workspace_id=` stream exemption.
- **The design tree is still outside the root lint/mypy/import-linter graph** (Part-I Step-2),
  along with folding `py_lumen_obs`/`py_lumen_config` into `clue_obs`/`clue_config`.
- **Cross-test queue bleed** (Round B) is now handled in the new file but NOT in the older ones; a
  per-suite queue namespace would end the class.
