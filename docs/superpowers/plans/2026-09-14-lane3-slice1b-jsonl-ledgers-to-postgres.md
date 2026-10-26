# Lane 3 slice 1b — every provider call on the Postgres ledger — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route the three JSONL provider ledgers (onboarding lane, display prewrite, persona-evidence tool) onto `provider_call_ledger`, and make every OpenRouter ledger row carry the model and token counts, so the cost read's `not_covered` list shrinks to the design subsystem and pre-column receipts.

**Architecture:** No new table or flag. `LedgerStamp` gains optional project / run / job fields. Each of the three callers builds its `ProviderCaller` over a `BufferedRawSink` + `BufferedLedger` it owns and drains them with the existing `drain_provider_calls` right after its calls: the onboarding driver under its own connection with the run id as the job (D1); the display page after its sections, sequentially, in its own transaction (D2); the evidence tool under the toolbelt's connection factory, refusing before spend when no artifact store is composed (D3). `openrouter_cost_reader` stamps `model` and the three token counts into its reading's extras, which `ProviderCaller._settle` already merges onto the result row.

**Tech Stack:** Python 3.12, SQLAlchemy async `text()`, pytest with the repo's rolled-back-connection DB harness, `uv`.

**Spec:** `docs/superpowers/specs/archive/2026-09-14-lane3-slice1b-jsonl-ledgers-to-postgres-design.md` (decisions D1–D3 ruled 2026-09-14). Parent: `docs/superpowers/specs/archive/2026-09-14-telemetry-and-cost-observability-design.md` §5.5, §9 item 1b.

## Global Constraints

- **Branch and base.** Work continues on `lane3/slice1-cost-read` in the `semarang` workspace (slice 1 is on it; PR #55 is open onto `research-streaming`). One commit per task, local only, never push; no AI attribution trailer.
- **Database.** This checkout's `.env` names `clue_semarang`, which a LIVE stack uses and which is behind the migration head. Never run tests or alembic against it. Every DB test runs after this preamble: `set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_lane3-cost-read"` and after confirming `uv run alembic current` prints `d36bc7d32c9a (head)`. No migration is part of this slice; no alembic upgrade/downgrade, no `make db-smoke`.
- **Tests spend no money.** Run only the test files each task names; never `make check`, never a broad `pytest`; `--ignore-glob='*_live.py'` when a directory is named.
- **Postgres is the ledger of record (R2).** No cost is recomputed; the reader stamps what the provider said. `phase='result'` rows are money; estimate rows are reservations.
- **R11 / R12.** Nothing under `subsystems/research/clue_research/**`, `subsystems/clue-design/**` or `apps/frontend/**` is edited.
- **Gates per task:** `uv run ruff format <files> && uv run ruff check <files>`, `uv run mypy` (baseline: exactly 4 pre-existing errors in `subsystems/design/clue_design/ad_assets.py:149`, `platform/api/clue_api/arv2/account_research_claims.py:1387`, `platform/api/clue_api/arv2/account_research_driver.py:181-182`; the gate is "no new error"), `uv run lint-imports` (26 kept, 0 broken) after any import change.
- **Shell is zsh:** pass file lists as separate words or arrays, never one unquoted scalar. Never `git stash` (the stash stack is shared).
- **The no-write guard** (`tests/projections/test_no_write_sql_guard.py`) scans every projections file, prose included, for INSERT INTO / UPDATE … SET / DELETE FROM / CREATE TABLE / ALTER TABLE / TRUNCATE — Task 6 must not spell them in `cost.py`.

## What the plan discovered (read before Task 1)

1. `LedgerStamp` (`arv2/provider_ledger.py:118-124`) requires all four fields; `_ledger_params` passes them straight through and the three columns are nullable, with no foreign key on `entity_research_job_id`. Making the three optional is the whole stamp change.
2. The onboarding driver's persona-only runs (`_personas_only`) make no `ProviderCaller` calls of their own (their spend is the synthesis turns' `agent_model_call` rows plus the evidence tool). So the spec's "project id from a project-local persona ICP" never has a row to stamp: the driver's stamp is `workspace_id` + `job_id = run_id`, nothing else. Recorded as a spec refinement, not a deviation.
3. `ensure_page` runs its sections concurrently on the caller's single connection; a drain per section inside the gather would race on that connection. The buffers are created before the gather and drained after it, in a `finally`, sequentially.
4. `ExaSearchEvidenceTool.invoke` runs in tool contexts whose `conn_factory` may be the production `transaction` (needs an engine) — offline tool tests therefore need a null connection factory; the drain executes no SQL when nothing was buffered.
5. `tests/arv2/test_calls.py`'s exact-extras assertion uses its own reader, not `openrouter_cost_reader`, so Task 2 changes no existing assertion. `tests/arv2/display/test_page_db.py`'s transport answers `{"usage": {"cost": …}}` with no token fields, so those rows gain zero counts and no `model` key.
6. `build_onboarding_exa_client_factory(settings, secrets)` used `settings` only for the raw-root folder; it becomes `build_onboarding_exa_client_factory(secrets)`.

## File structure

| File | Responsibility |
| --- | --- |
| `platform/api/clue_api/arv2/provider_ledger.py` | **Modify.** `LedgerStamp` optional fields. |
| `platform/api/clue_api/arv2/openrouter.py` | **Modify.** Reader stamps model + token counts. |
| `platform/api/clue_api/arv2/onboarding_driver.py` | **Modify.** Factory protocols take sinks; per-step buffers; drain after each provider step. |
| `platform/api/clue_api/fleet_main.py` | **Modify.** Reconciler factory takes sinks; Exa factory call. |
| `platform/api/clue_api/arv2/display/page.py` | **Modify.** `RunnerFactory` takes sinks; page drains after the gather in its own transaction. |
| `scripts/generate_arv2_display.py` | **Modify.** Composes the artifact store and the spend transaction. |
| `platform/api/clue_api/onboarding_evidence_tools.py` | **Modify.** Tool owns buffers, refuses without an artifact store, drains under `ctx.conn_factory`. |
| `platform/api/clue_api/toolbelt_wiring.py` | **Modify.** Passes the artifact store to the evidence tools. |
| `platform/projections/clue_projections/cost.py` | **Modify.** `NOT_COVERED` shrinks to two entries; docstring. |
| `tests/arv2/test_provider_ledger_db.py` | **Modify.** Workspace-only stamp test. |
| `tests/arv2/test_openrouter.py` | **Modify.** Reader extras tests. |
| `tests/arv2/test_onboarding_driver.py` | **Modify.** Fakes take sinks; drain assertions. |
| `tests/arv2/test_onboarding_driver_db.py` | **Modify.** Ledger rows land with the run as the job. |
| `tests/arv2/test_persona_run_db.py` | **Modify.** `_unused_exa` signature. |
| `tests/api/test_fleet_wiring.py` | **Modify.** Reconciler factory signature. |
| `tests/arv2/display/test_page_db.py` | **Modify.** Factory takes sinks; ledger assertions. |
| `tests/arv2/display/test_display_live.py` | **Modify.** `ensure_page` call gains the two arguments (live; not run). |
| `tests/api/test_onboarding_evidence_tools.py` | **Modify.** Null connection factory; refusal case; factory signature. |
| `tests/api/test_onboarding_evidence_tools_db.py` | **Create.** The drain lands one row under the context's factory. |
| `tests/projections/test_cost_db.py` | **Modify.** `not_covered` assertion. |
| `docs/superpowers/specs/archive/2026-09-14-telemetry-and-cost-observability-design.md` | **Modify.** §3 row, §5.5, §9 item 1b. |
| `docs/superpowers/plans/2026-09-13-lane-plan-index.md` | **Modify.** Row 1b. |
| `_memory/2026-09-14-lane3-slice1b-jsonl-ledgers-to-postgres.md` | **Create.** Session note (controller). |

---

### Task 1: `LedgerStamp` gains optional project, run and job

**Files:**
- Modify: `platform/api/clue_api/arv2/provider_ledger.py:118-124` (and the module docstring's sentence about `entity_research_job_id`)
- Test: `tests/arv2/test_provider_ledger_db.py`

**Interfaces:**
- Produces: `LedgerStamp(workspace_id: str, project_id: str | None = None, project_run_id: str | None = None, job_id: UUID | None = None)`. `drain_provider_calls` and `_ledger_params` are unchanged; a NULL field lands as NULL. Every existing caller passes all four and keeps working.

- [ ] **Step 1: Write the failing test**

Append to `tests/arv2/test_provider_ledger_db.py`:

```python
def test_a_workspace_only_stamp_lands_null_project_run_and_job() -> None:
    """Slice 1b: a display page or a chat-turn tool has no project, run or job to stamp — the
    row is workspace spend, and the three columns say so with NULL rather than a placeholder."""

    async def scenario():  # type: ignore[no-untyped-def]
        ledger = BufferedLedger()
        ledger.record(_result_row(row_id="r-ws-only", call_id=str(uuid4()), raw_ref=None))
        async with rollback_conn(seed_pack=False) as conn:
            await drain_provider_calls(
                conn,
                raw=BufferedRawSink(),
                ledger=ledger,
                artifacts=FakeArtifacts(),
                stamp=LedgerStamp(workspace_id="ws_only"),
            )
            row = (
                await conn.execute(
                    text(
                        "SELECT workspace_id, project_id, project_run_id, entity_research_job_id "
                        "FROM provider_call_ledger WHERE ledger_id = :id"
                    ),
                    {"id": uuid5(NAMESPACE_URL, "arv2-ledger:r-ws-only")},
                )
            ).one()
        return tuple(row)

    assert run_async(scenario()) == ("ws_only", None, None, None)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_lane3-cost-read"; uv run pytest tests/arv2/test_provider_ledger_db.py -v`
Expected: the new test FAILS with `TypeError: LedgerStamp.__init__() missing 3 required positional arguments`; the existing tests pass.

- [ ] **Step 3: Make the fields optional**

In `platform/api/clue_api/arv2/provider_ledger.py` replace the `LedgerStamp` class with:

```python
@dataclass(frozen=True)
class LedgerStamp:
    """Whose spend this is. ``workspace_id`` is the one fact every row carries; the project, the
    project run and the job are stamped when the spender has them and left NULL when it does not
    (slice 1b: an onboarding run stamps its own id as the job; a display page or a chat-turn tool
    stamps the workspace alone)."""

    workspace_id: str
    project_id: str | None = None
    project_run_id: str | None = None
    job_id: UUID | None = None
```

In the module docstring, change the sentence
`` ``provider_call_ledger.entity_research_job_id`` carries the R2 ``arv2_research_job.job_id`` — the column was named by D1 before R2 existed; its meaning is "the job that spent". ``
to
`` ``provider_call_ledger.entity_research_job_id`` carries the R2 ``arv2_research_job.job_id``, a discovery run id, or (slice 1b) an onboarding run id — the column was named by D1 before R2 existed; its meaning is "the job that spent", and it is NULL for spend with no job (a display page, a chat-turn tool). ``

- [ ] **Step 4: Run the tests and gates**

Run: `set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_lane3-cost-read"; uv run pytest tests/arv2/test_provider_ledger_db.py tests/arv2/test_discovery_driver.py -v --ignore-glob='*_live.py' && uv run ruff format platform/api/clue_api/arv2/provider_ledger.py tests/arv2/test_provider_ledger_db.py && uv run ruff check platform/api/clue_api/arv2/provider_ledger.py tests/arv2/test_provider_ledger_db.py && uv run mypy`
Expected: all PASS; mypy still exactly 4 pre-existing errors.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/provider_ledger.py tests/arv2/test_provider_ledger_db.py
git commit -m "feat(arv2-ledger): LedgerStamp's project, run and job are optional

A display page or a chat-turn tool has no project, run or job; the columns are nullable and
carry no foreign key, so the stamp says NULL rather than inventing one (lane 3 slice 1b)."
```

---

### Task 2: The OpenRouter cost reader stamps the model and the token counts

**Files:**
- Modify: `platform/api/clue_api/arv2/openrouter.py:116-145` (`openrouter_cost_reader`; add `_count` beside `_decimal`)
- Test: `tests/arv2/test_openrouter.py`

**Interfaces:**
- Produces: for any JSON body, `CostReading.extras` carries `prompt_tokens`, `completion_tokens`, `cached_prompt_tokens` (ints, 0 when absent) and `model` (only when the body's `model` is a non-empty string). A non-JSON body still yields `CostReading()` (empty extras). `ProviderCaller._settle` merges these onto the result row under the spec's extras and before `cost_source` — no wrapper change.

- [ ] **Step 1: Write the failing tests**

Append to `tests/arv2/test_openrouter.py`:

```python
def test_the_cost_reader_stamps_the_model_and_the_token_counts() -> None:
    """Slice 1b: every OpenRouter row carries what the research agent's rows already carry, so
    the cost read's per-model view covers the structuring, media and reconcile calls too."""
    body = (
        b'{"id":"gen-2","model":"x-ai/grok-4.6","usage":{"cost":0.01,"prompt_tokens":900,'
        b'"completion_tokens":200,"prompt_tokens_details":{"cached_tokens":300}}}'
    )
    reading = openrouter_cost_reader(HttpResponse(200, {}, body))
    assert reading.cost_usd == Decimal("0.01")
    assert reading.extras == {
        "model": "x-ai/grok-4.6",
        "prompt_tokens": 900,
        "completion_tokens": 200,
        "cached_prompt_tokens": 300,
    }


def test_a_body_without_usage_or_model_counts_zero_and_names_no_model() -> None:
    reading = openrouter_cost_reader(HttpResponse(200, {}, b'{"id":"gen-3"}'))
    assert reading.extras == {"prompt_tokens": 0, "completion_tokens": 0, "cached_prompt_tokens": 0}
    assert openrouter_cost_reader(HttpResponse(200, {}, b"not json")).extras == {}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/arv2/test_openrouter.py -v`
Expected: the two new tests FAIL (`reading.extras == {}`); the existing four pass.

- [ ] **Step 3: Implement**

In `platform/api/clue_api/arv2/openrouter.py`, add after `_decimal`:

```python
def _count(value: object) -> int:
    """A provider-reported token count as an int, 0 when absent or not a number."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0
    return int(value)
```

and replace the tail of `openrouter_cost_reader` (from `request_id = body.get("id")` to the end of the function) with:

```python
    request_id = body.get("id")
    # Slice 1b: the model and the token counts ride the reading's extras, so every row written
    # through this reader (structuring, media, reconcile, display) carries what the research
    # agent's rows already carry and the cost read's per-model view stays whole.
    token_details = usage.get("prompt_tokens_details")
    token_details = token_details if isinstance(token_details, dict) else {}
    extras: dict[str, object] = {
        "prompt_tokens": _count(usage.get("prompt_tokens")),
        "completion_tokens": _count(usage.get("completion_tokens")),
        "cached_prompt_tokens": _count(token_details.get("cached_tokens")),
    }
    model = body.get("model")
    if isinstance(model, str) and model:
        extras["model"] = model
    return CostReading(
        cost_usd=cost,
        provider_request_id=request_id if isinstance(request_id, str) else None,
        extras=extras,
    )
```

Extend the function's docstring with one sentence: `The model and the token counts (``prompt_tokens``, ``completion_tokens``, ``prompt_tokens_details.cached_tokens``) ride ``extras`` under the same keys the research agent's rows use.`

- [ ] **Step 4: Run the tests and gates**

Run: `set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_lane3-cost-read"; uv run pytest tests/arv2/test_openrouter.py tests/arv2/test_calls.py tests/arv2/test_onboarding_reconcile.py tests/arv2/test_structuring_client.py tests/arv2/test_gemini_media_client.py tests/arv2/display/test_page_db.py -v --ignore-glob='*_live.py' && uv run ruff format platform/api/clue_api/arv2/openrouter.py tests/arv2/test_openrouter.py && uv run ruff check platform/api/clue_api/arv2/openrouter.py tests/arv2/test_openrouter.py && uv run mypy`
Expected: all PASS (no existing test asserts an OpenRouter row's exact extras); mypy unchanged.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/openrouter.py tests/arv2/test_openrouter.py
git commit -m "feat(arv2-openrouter): the cost reader stamps the model and the token counts

Structuring, media, reconcile and display rows now carry model / prompt_tokens /
completion_tokens / cached_prompt_tokens like the research agent's rounds, so the cost read's
per-model view no longer shows them as unknown (lane 3 slice 1b)."
```

---

### Task 3: The onboarding lane drains every provider step onto the ledger

**Files:**
- Modify: `platform/api/clue_api/arv2/onboarding_driver.py` (imports; `ExaClientFactory`; `build_onboarding_provider_caller`; `build_onboarding_exa_client_factory`; `OnboardingRunWorkHandler.__init__`; the recon step ~L642-660; the lineup step ~L738-760; `_catalog_sync` ~L825-850; new `_stamp` / `_drain`)
- Modify: `platform/api/clue_api/fleet_main.py:657` and `:679-725` (`_build_catalog_reconciler_factory`)
- Test: `tests/arv2/test_onboarding_driver.py`, `tests/arv2/test_onboarding_driver_db.py`, `tests/arv2/test_persona_run_db.py:256`, `tests/api/test_fleet_wiring.py:501-548`

**Interfaces:**
- Consumes: Task 1's `LedgerStamp(workspace_id=, job_id=)`; `BufferedRawSink`, `BufferedLedger`, `drain_provider_calls`, `DrainReport` from `clue_api.arv2.provider_ledger`; `RawSink`, `LedgerSink` from `clue_api.arv2.sinks`.
- Produces:
  - `ExaClientFactory.__call__(self, *, run_id: UUID, step_label: str, raw: RawSink, ledger: LedgerSink) -> ExaAgentSurface`
  - `build_onboarding_provider_caller(*, raw: RawSink, ledger: LedgerSink) -> ProviderCaller`
  - `build_onboarding_exa_client_factory(secrets: Secrets) -> ExaClientFactory`
  - `OnboardingRunWorkHandler(..., reconciler_factory: Callable[[RawSink, LedgerSink], CatalogReconciler] | None = None, drain: DrainProviderCalls = drain_provider_calls)` where `DrainProviderCalls = Callable[..., Awaitable[DrainReport]]` (called with the same keyword arguments as `drain_provider_calls`).
  - The stamp for every drain of a run: `LedgerStamp(workspace_id=scope.workspace_id, job_id=scope.run_id)` (D1; discovery item 2).

- [ ] **Step 1: Update the offline driver tests and write the failing ones**

In `tests/arv2/test_onboarding_driver.py`:

Add to the imports:

```python
from clue_api.arv2.provider_ledger import DrainReport, LedgerStamp
from clue_api.arv2.sinks import LedgerRow
```

Add after `FakeArtifacts`:

```python
class FakeDrain:
    """Records every drain the driver asks for: the stamp and the rows it was handed."""

    def __init__(self) -> None:
        self.calls: list[tuple[LedgerStamp, list[LedgerRow]]] = []

    async def __call__(self, conn: Any, *, raw: Any, ledger: Any, artifacts: Any, stamp: LedgerStamp) -> DrainReport:
        del conn, artifacts
        rows = ledger.drain()
        raw.drain()
        self.calls.append((stamp, rows))
        return DrainReport(rows=len(rows), artifacts=0, cost_usd=Decimal(0), credits=Decimal(0), media_seconds=0)


def _recording_factory(exa: FakeExa) -> Any:
    """The production factory's shape: one client per step over the step's own sinks. It writes
    one result row into the step's ledger so a drain has something to land."""

    def factory(*, run_id: Any, step_label: str, raw: Any, ledger: Any) -> FakeExa:
        del raw
        ledger.record(
            LedgerRow(
                row_id=f"{run_id}:{step_label}",
                call_id=str(uuid4()),
                phase="result",
                provider="exa",
                operation="agent_run",
                label=step_label,
                recorded_at=datetime(2026, 9, 7, tzinfo=UTC),
                http_status=200,
                latency_ms=5,
                attempts=1,
                cost_usd=Decimal("0.02"),
                outcome="ok",
                extras={"cost_source": "metered"},
            )
        )
        return exa

    return factory
```

(add `from datetime import UTC, date, datetime` and `from decimal import Decimal` / `from uuid import uuid4` to the imports if not already present — `date` and `uuid4` are.)

Change `_handler` so its signature gains `drain: Any = None` and its body passes
`exa=_recording_factory(exa)` instead of `exa=lambda *, run_id, step_label: exa`, and
`drain=drain or FakeDrain()` as a new keyword to `OnboardingRunWorkHandler(...)`.

In `test_the_catalog_sync_gets_a_reconciler_built_for_this_run`, replace `def factory(run_id: Any) -> Reconciler:` / `built.append(run_id)` with:

```python
    def factory(raw: Any, ledger: Any) -> Reconciler:
        built.append((raw, ledger))
        return Reconciler()
```

and the assertion `assert built == [run_id]` with `assert len(built) == 1`. Update its docstring to: `"""One reconciler per run, built over the catalog step's own buffered sinks so its call lands on the ledger with the run's stamp (slice 1b) — the factory takes the sinks, not a folder."""`

Append two tests:

```python
def test_every_provider_step_drains_its_rows_with_the_run_as_the_job() -> None:
    """Slice 1b, D1: the recon subjects, the lineup and the catalog step each drain once, and
    every drain is stamped with the workspace and the run id as the job — never a project."""
    exa = _all_answers()
    drain = FakeDrain()
    run_id = uuid4()

    asyncio.run(_handler(exa, FakeStore(), drain=drain).handle(_context(run_id)))

    labels = sorted(row.label for _stamp, rows in drain.calls for row in rows)
    assert labels == sorted(["overview", "reviews", "product_research:MagicFlow", "lineup"]) or labels == sorted(
        ["overview", "reviews", "product_research:MagicFlow", "lineup", "catalog-reconcile"]
    )
    assert {stamp for stamp, _rows in drain.calls} == {
        LedgerStamp(workspace_id="ws-drv", job_id=run_id)
    }


def test_a_step_whose_provider_call_raises_still_drains() -> None:
    """The failed call's estimate and error rows are money and evidence; the drain runs in the
    step's finally, whatever the call's outcome."""
    exa = _all_answers()
    original = exa.agent_run

    def boom(**kw: Any) -> Any:
        if kw.get("label", "").startswith("reviews"):
            raise RuntimeError("provider down")
        return original(**kw)

    exa.agent_run = boom  # type: ignore[method-assign]
    drain = FakeDrain()
    store = FakeStore()

    asyncio.run(_handler(exa, store, drain=drain).handle(_context(uuid4())))

    assert store.landed("reviews")["status"] == "failed"
    assert any(row.label == "reviews" for _stamp, rows in drain.calls for row in rows)
```

(The exact set of recon subject labels depends on the fixtures' `_all_answers`; the implementer reads `_all_answers`/`_agent` to make the expected label list exact — the assertion must name every step the run takes, one drain per step, and the catalog step drains even when the reconciler is `None`, so include `"catalog-reconcile"` only if the driver drains the catalog buffers unconditionally, which it must: write the assertion as an exact equality once the driver's labels are known.)

Also in `tests/arv2/test_persona_run_db.py:256` change `_unused_exa` to:

```python
def _unused_exa(*, run_id: UUID, step_label: str, raw: Any, ledger: Any) -> Any:
    del run_id, step_label, raw, ledger
    raise AssertionError("a personas run makes no Exa call of its own")
```

(keep the body's existing intent if it differs — the point is the signature).

In `tests/api/test_fleet_wiring.py::test_the_catalog_reconciler_is_composed_per_run_only_with_a_model_credential`, replace `reconciler = composed._reconciler_factory(run_id)` (and the `run_id = uuid4()` line before it) with:

```python
    from clue_api.arv2.sinks import MemoryLedger, MemoryRawSink

    reconciler = composed._reconciler_factory(MemoryRawSink(), MemoryLedger())
```

and change the docstring's second sentence to `run**, built over the catalog step's own sinks so its one call lands on the ledger with the run's stamp (slice 1b).`

- [ ] **Step 2: Run the offline tests to verify they fail**

Run: `uv run pytest tests/arv2/test_onboarding_driver.py tests/api/test_fleet_wiring.py -v --ignore-glob='*_live.py'`
Expected: FAIL on `TypeError` (the driver calls the factory with `run_id`/`step_label` only and `OnboardingRunWorkHandler` has no `drain` keyword).

- [ ] **Step 3: Implement the driver**

In `platform/api/clue_api/arv2/onboarding_driver.py`:

Imports: replace `from clue_api.arv2.sinks import FileRawSink, JsonlLedger` with

```python
from clue_api.arv2.provider_ledger import (
    BufferedLedger,
    BufferedRawSink,
    DrainReport,
    LedgerStamp,
    drain_provider_calls,
)
from clue_api.arv2.sinks import LedgerSink, RawSink
```

remove `from pathlib import Path` if nothing else uses it (`ruff check` says), and keep `Settings` imported only if still used (the handler takes `settings`; yes).

Replace `ExaClientFactory`:

```python
class ExaClientFactory(Protocol):
    """One client per step, because one :class:`ProviderCaller` per step is R1's rule: a halt
    latched by one step's provider must not silently stop another step's calls. The step's sinks
    are the driver's (slice 1b): it buffers the step's raw bodies and ledger rows and drains them
    onto the artifact store and ``provider_call_ledger`` after the step's calls."""

    def __call__(
        self, *, run_id: UUID, step_label: str, raw: RawSink, ledger: LedgerSink
    ) -> ExaAgentSurface: ...
```

Add after it:

```python
#: The drain the driver runs after each provider step — injectable so the offline tests record
#: every drain without a database, the way the store and the synchronizer are injected.
DrainProviderCalls = Callable[..., Awaitable[DrainReport]]
```

(`Awaitable` is already imported from `collections.abc` for `known_products`; add it if not.)

Replace `build_onboarding_provider_caller`:

```python
def build_onboarding_provider_caller(*, raw: RawSink, ledger: LedgerSink) -> ProviderCaller:
    """One caller for one step, over the step's own sinks. Since slice 1b nothing is written to
    disk: the sinks buffer, and the driver drains them onto the artifact store and the ledger."""
    return ProviderCaller(
        transport=HttpxTransport(), raw_sink=raw, ledger=ledger, now=lambda: datetime.now(UTC)
    )
```

Replace `build_onboarding_exa_client_factory`:

```python
def build_onboarding_exa_client_factory(secrets: Secrets) -> ExaClientFactory:
    """The production factory. A blank key is unset (``.env.example`` ships the empty line), so it
    fails here at composition rather than as a provider 401 in the middle of a run."""
    key = secrets.exa_api_key
    if key is None or not key.get_secret_value().strip():
        raise ValueError("CLUE_EXA_API_KEY is required for the onboarding lane")
    api_key = SecretStr(key.get_secret_value())

    def factory(
        *, run_id: UUID, step_label: str, raw: RawSink, ledger: LedgerSink
    ) -> ExaAgentSurface:
        del run_id, step_label  # the sinks are the step's identity now; the labels ride the rows
        return ExaClient(build_onboarding_provider_caller(raw=raw, ledger=ledger), api_key)

    return factory
```

In `OnboardingRunWorkHandler.__init__`: change the `reconciler_factory` annotation to `Callable[[RawSink, LedgerSink], CatalogReconciler] | None = None`, add `drain: DrainProviderCalls = drain_provider_calls,` after it, store `self._drain_calls = drain`, and replace the reconciler comment with:

```python
        # A factory, not a reconciler: the model stage spends through a ``ProviderCaller`` built
        # over the catalog step's own buffered sinks, so its one call lands on the ledger with
        # this run's stamp (slice 1b). ``None`` is a composed lane without the model stage — the
        # ladder then stops after its deterministic rungs, which is what it did before the stage
        # existed.
```

Add two methods after `_connection`:

```python
    def _stamp(self, scope: _Scope) -> LedgerStamp:
        """D1 (slice 1b): a run's provider spend is the workspace's, with the run id as the job,
        so ``make cost-report --job <run id>`` answers "what did this onboarding cost". No project:
        the whole-brand walk is brand-scoped, and a personas run makes no provider call here."""
        return LedgerStamp(workspace_id=scope.workspace_id, job_id=scope.run_id)

    async def _drain(
        self,
        scope: _Scope,
        raw: BufferedRawSink,
        ledger: BufferedLedger,
        *,
        step_label: str,
        conn: AsyncConnection | None = None,
    ) -> None:
        """Land a step's buffered raw bodies and ledger rows: under the driver's own connection,
        or on ``conn`` when the caller already holds one (the catalog step). A drain that fails
        raises — the rows are the call's money, and losing them quietly is the one thing this
        lane must never do; ``handle``'s containment then fails the run loudly."""
        if conn is not None:
            report = await self._drain_calls(
                conn, raw=raw, ledger=ledger, artifacts=self._artifacts, stamp=self._stamp(scope)
            )
        else:
            async with self._connection() as own:
                report = await self._drain_calls(
                    own, raw=raw, ledger=ledger, artifacts=self._artifacts, stamp=self._stamp(scope)
                )
        log.info(
            "onboarding.ledger_drained",
            run_id=str(scope.run_id),
            step=step_label,
            rows=report.rows,
            artifacts=report.artifacts,
            cost_usd=str(report.cost_usd),
        )
```

Recon step (the block starting `label = f"{kind}:{subject}" if subject else kind`): replace

```python
        label = f"{kind}:{subject}" if subject else kind
        client = self._exa(run_id=scope.run_id, step_label=label)
        try:
            run = await asyncio.to_thread(
                client.agent_run,
                query=query,
                output_schema=schema,
                effort=effort,
                system_prompt=system_prompt,
                label=label,
            )
        except Exception as error:
            # A provider halt or a transport failure is a step outcome, not a run failure.
            await self._settle(scope, step_id, document_id, _failed_step(error))
            return
```

with

```python
        label = f"{kind}:{subject}" if subject else kind
        raw, ledger = BufferedRawSink(), BufferedLedger()
        client = self._exa(run_id=scope.run_id, step_label=label, raw=raw, ledger=ledger)
        try:
            run = await asyncio.to_thread(
                client.agent_run,
                query=query,
                output_schema=schema,
                effort=effort,
                system_prompt=system_prompt,
                label=label,
            )
        except Exception as error:
            # A provider halt or a transport failure is a step outcome, not a run failure.
            await self._settle(scope, step_id, document_id, _failed_step(error))
            return
        finally:
            # Whatever the call's outcome, its rows are money: land them (slice 1b).
            await self._drain(scope, raw, ledger, step_label=label)
```

Lineup step: replace

```python
        client = self._exa(run_id=scope.run_id, step_label="lineup")
```

with

```python
        raw, ledger = BufferedRawSink(), BufferedLedger()
        client = self._exa(run_id=scope.run_id, step_label="lineup", raw=raw, ledger=ledger)
```

and add to the `try:` that wraps the two `deep_reasoning` calls a `finally:` clause after its `except Exception as error:` block:

```python
        finally:
            await self._drain(scope, raw, ledger, step_label="lineup")
```

Catalog step (`_catalog_sync`): replace

```python
                reconciler = (
                    self._reconciler_factory(scope.run_id)
                    if self._reconciler_factory is not None
                    else None
                )
                links = await self._sync(
                    conn,
                    workspace_id=scope.workspace_id,
                    brand_id=scope.brand_id,
                    document_id=document_id,
                    products=products,
                    reconciler=reconciler,
                )
```

with

```python
                raw, ledger = BufferedRawSink(), BufferedLedger()
                reconciler = (
                    self._reconciler_factory(raw, ledger)
                    if self._reconciler_factory is not None
                    else None
                )
                try:
                    links = await self._sync(
                        conn,
                        workspace_id=scope.workspace_id,
                        brand_id=scope.brand_id,
                        document_id=document_id,
                        products=products,
                        reconciler=reconciler,
                    )
                finally:
                    # The step already holds the connection: drain on it (slice 1b).
                    await self._drain(
                        scope, raw, ledger, step_label="catalog-reconcile", conn=conn
                    )
```

Add `"DrainProviderCalls"` to `__all__` (alphabetical). Update the module docstring's first paragraph sentence about where records go if it names the raw root (search the file for `arv2_raw_root`).

- [ ] **Step 4: Implement the fleet composition**

In `platform/api/clue_api/fleet_main.py`: add `from clue_api.arv2.sinks import LedgerSink, RawSink` to the imports; change line 657 to `exa = build_onboarding_exa_client_factory(secrets)`; in `_build_catalog_reconciler_factory` change the return annotation to `Callable[[RawSink, LedgerSink], CatalogReconciler] | None` and the inner factory to:

```python
    def factory(raw: RawSink, ledger: LedgerSink) -> CatalogReconciler:
        return OpenRouterCatalogReconciler(
            caller_factory=lambda: build_onboarding_provider_caller(raw=raw, ledger=ledger),
            api_key=key,
            model=settings.onboarding_reconcile_model,
            base_url=base_url,
        )
```

and rewrite the docstring's first paragraph to: `A **factory of one reconciler per run**, not a reconciler: the call spends through R1's ``ProviderCaller`` built over the catalog step's own buffered sinks, so its one call lands on ``provider_call_ledger`` with the run's stamp (slice 1b) — the driver hands the factory the sinks.` (keep the rest about credentials).

Check `platform/api/clue_api/arv2/onboarding_driver.py` and `fleet_main.py` for the removed `Path`/`Settings` imports with `uv run ruff check`.

- [ ] **Step 5: Write the failing DB test**

Append to `tests/arv2/test_onboarding_driver_db.py` (add `from decimal import Decimal`, `from datetime import UTC, datetime`, `from sqlalchemy import text`, `from clue_api.arv2.sinks import LedgerRow` to its imports):

```python
def test_every_provider_step_lands_its_rows_on_the_ledger_with_the_run_as_the_job() -> None:
    """Slice 1b, D1: the run's rows are on provider_call_ledger, stamped with the workspace and
    the run id as the job, no project, and each cites the artifact its raw body became."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-ledger-db"
            project = await seed_project(conn, ws, name="O3 ledger")
            await seed_principal(conn, workspace_id=ws, user_id=USER)
            run_id = uuid4()
            await create_run(
                conn,
                run_id=run_id,
                workspace_id=ws,
                brand_id=project.brand_id,
                company_domain="insighthealth.ai",
                requested_by_user_id=USER,
            )
            artifacts = DurableAgentArtifactStore(
                storage=_MemoryStorage(),  # type: ignore[arg-type]
                conn_factory=conn_session_factory(conn),
            )
            exa = FakeExa(
                {"overview": _agent(OVERVIEW), "reviews": _agent(REVIEWS), "product_research": _agent(PRODUCT)},
                _deep([{"name": "MagicFlow", "short_description": "Orchestration.", "offering_kind": "platform"}]),
            )

            def factory(*, run_id: object, step_label: str, raw: object, ledger: object) -> FakeExa:
                assert hasattr(ledger, "record")
                ledger.record(  # type: ignore[attr-defined]
                    LedgerRow(
                        row_id=f"{run_id}:{step_label}",
                        call_id=str(uuid4()),
                        phase="result",
                        provider="exa",
                        operation="agent_run",
                        label=step_label,
                        recorded_at=datetime(2026, 9, 7, tzinfo=UTC),
                        http_status=200,
                        latency_ms=5,
                        attempts=1,
                        cost_usd=Decimal("0.02"),
                        outcome="ok",
                        extras={"cost_source": "metered"},
                    )
                )
                return exa

            handler = OnboardingRunWorkHandler(
                settings=Settings(_env_file=None),
                conn_factory=conn_session_factory(conn),
                artifacts=artifacts,
                exa=factory,
            )
            context = WorkContext(
                task_id=uuid4(),
                work_id=onboarding_work_id(run_id),
                worker_id="t",
                lease_generation=LeaseGeneration(1),
                payload={
                    "run_id": str(run_id),
                    "workspace_id": ws,
                    "brand_id": project.brand_id,
                    "company_domain": "insighthealth.ai",
                    "company_name": "Insight Health",
                },
                stop_requested=asyncio.Event(),
                lease_lost=asyncio.Event(),
            )

            await handler.handle(context)

            rows = (
                await conn.execute(
                    text(
                        "SELECT label, workspace_id, project_id, project_run_id, "
                        " entity_research_job_id, cost_usd, extras_json "
                        "FROM provider_call_ledger WHERE workspace_id = :ws AND phase = 'result' "
                        "ORDER BY label"
                    ),
                    {"ws": ws},
                )
            ).mappings().all()
            assert [row["label"] for row in rows] == sorted(
                ["lineup", "overview", "product_research:MagicFlow", "reviews"]
            )
            assert {row["entity_research_job_id"] for row in rows} == {run_id}
            assert all(row["project_id"] is None and row["project_run_id"] is None for row in rows)
            assert sum(row["cost_usd"] for row in rows) == Decimal("0.08")

    run_async(scenario())
```

(The exact label list must match the run's steps; the implementer confirms it against the existing test's step kinds — the recon subjects are the `_agent` keys plus the product-research subject `MagicFlow` from the lineup, so adjust to what the run actually opens.)

Also update the existing test's `exa=lambda *, run_id, step_label: exa,` to `exa=lambda *, run_id, step_label, raw, ledger: exa,`.

- [ ] **Step 6: Run every test this task touches, plus the gates**

Run: `set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_lane3-cost-read"; uv run pytest tests/arv2/test_onboarding_driver.py tests/arv2/test_onboarding_driver_db.py tests/arv2/test_persona_run_db.py tests/api/test_fleet_wiring.py tests/arv2/test_onboarding_reconcile.py -v --ignore-glob='*_live.py' && uv run ruff format platform/api/clue_api/arv2/onboarding_driver.py platform/api/clue_api/fleet_main.py tests/arv2/test_onboarding_driver.py tests/arv2/test_onboarding_driver_db.py tests/arv2/test_persona_run_db.py tests/api/test_fleet_wiring.py && uv run ruff check platform/api/clue_api/arv2/onboarding_driver.py platform/api/clue_api/fleet_main.py tests/arv2 tests/api/test_fleet_wiring.py && uv run mypy && uv run lint-imports`
Expected: all PASS; mypy unchanged; import-linter 26/0.

- [ ] **Step 7: Commit**

```bash
git add platform/api/clue_api/arv2/onboarding_driver.py platform/api/clue_api/fleet_main.py tests/arv2/test_onboarding_driver.py tests/arv2/test_onboarding_driver_db.py tests/arv2/test_persona_run_db.py tests/api/test_fleet_wiring.py
git commit -m "feat(onboarding): every provider step lands its rows on provider_call_ledger

The driver owns a buffered raw sink and ledger per step, hands them to the Exa client and
catalog-reconciler factories, and drains after each step's calls under its own connection,
stamped with the workspace and the run id as the job (D1). No JSONL, no raw folder on disk
(lane 3 slice 1b)."
```

---

### Task 4: The display prewrite lands its spend in its own transaction

**Files:**
- Modify: `platform/api/clue_api/arv2/display/page.py` (imports; `RunnerFactory`; `default_runner_factory`; `_Written`; `_write_section`; `ensure_page`)
- Modify: `scripts/generate_arv2_display.py` (docstring; imports; `_run`)
- Test: `tests/arv2/display/test_page_db.py`, `tests/arv2/display/test_display_live.py:145-155`

**Interfaces:**
- Consumes: Task 1's `LedgerStamp(workspace_id=)`; `ArtifactSink`, `BufferedRawSink`, `BufferedLedger`, `drain_provider_calls` from `clue_api.arv2.provider_ledger`; `ConnFactory`, `transaction` from `clue_db`; `DurableAgentArtifactStore` from `clue_api.agent_turn_wiring`; `build_storage_backend` from `clue_api.storage_wiring`.
- Produces:
  - `RunnerFactory = Callable[[RawSink, LedgerSink], LunaSectionRunner]` (re-exported by `clue_api.arv2.display`).
  - `_write_section(..., raw: BufferedRawSink, ledger: BufferedLedger, semaphore)` — the buffers are created by the caller.
  - `ensure_page(conn, *, workspace_id, subject_kind, subject_id, page, settings, runner_factory, artifacts: ArtifactSink, spend_conn_factory: ConnFactory, force=False, regenerate_stale=False)`.

- [ ] **Step 1: Update the DB test's factory and write the failing test**

In `tests/arv2/display/test_page_db.py`:

Add to the imports: `from clue_api.arv2.sinks import LedgerSink, RawSink`, `from tests.arv2.test_provider_ledger_db import FakeArtifacts`, `from tests.profiling.conftest import conn_session_factory`, and `from clue_api.arv2.provider_ledger import BufferedLedger, BufferedRawSink`. Remove `MemoryLedger, MemoryRawSink` from the sinks import if nothing else uses them.

Replace `_factory`:

```python
def _factory(transport: RoutingTransport) -> Any:
    """One runner per section, each with its own caller over the section's sinks — the
    production factory's shape."""

    def build(raw: RawSink, ledger: LedgerSink) -> LunaSectionRunner:
        return LunaSectionRunner(
            ProviderCaller(transport=transport, raw_sink=raw, ledger=ledger, now=lambda: datetime.now(UTC)),
            api_key=SecretStr("test-key"),
            base_url="https://openrouter.ai/api/v1",
            model="openai/gpt-5.6-luna",
            timeout_s=30.0,
        )

    return build
```

Change `_contact_page` to pass the two new arguments, defaulting them when the caller did not:

```python
async def _contact_page(
    conn: AsyncConnection, seeded: Seeded, transport: RoutingTransport, **kwargs: Any
) -> PageResult:
    kwargs.setdefault("artifacts", FakeArtifacts())
    kwargs.setdefault("spend_conn_factory", conn_session_factory(conn))
    return await ensure_page(
        conn,
        workspace_id=seeded.workspace_id,
        subject_kind="contact",
        subject_id=str(seeded.nick),
        page="contact",
        settings=SETTINGS,
        runner_factory=_factory(transport),
        **kwargs,
    )
```

Every other direct `ensure_page(` call in the file (the account-page test at ~L390 and any others) gains `artifacts=FakeArtifacts(), spend_conn_factory=conn_session_factory(conn),`. The direct `_write_section(` call at ~L560 gains `raw=BufferedRawSink(), ledger=BufferedLedger(),`. The `default_runner_factory(SETTINGS, present)()` call at ~L435 becomes `default_runner_factory(SETTINGS, present)(BufferedRawSink(), BufferedLedger())`.

Append:

```python
def test_the_page_lands_its_provider_spend_on_the_ledger_with_the_workspace_stamp() -> None:
    """Slice 1b: one result row per section call, workspace-stamped, no project / run / job,
    each citing the artifact its raw body became; the page's cost is the rows' sum."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            transport = RoutingTransport()
            artifacts = FakeArtifacts()
            result = await _contact_page(conn, seeded, transport, artifacts=artifacts)
            rows = (
                await conn.execute(
                    text(
                        "SELECT provider, operation, project_id, project_run_id, "
                        " entity_research_job_id, cost_usd, response_artifact_key, extras_json "
                        "FROM provider_call_ledger "
                        "WHERE workspace_id = :ws AND phase = 'result' ORDER BY recorded_at"
                    ),
                    {"ws": seeded.workspace_id},
                )
            ).mappings().all()
            assert len(rows) == len(transport.sections)
            assert {(r["provider"], r["operation"]) for r in rows} == {("openrouter", "chat/completions")}
            assert all(
                r["project_id"] is None and r["project_run_id"] is None and r["entity_research_job_id"] is None
                for r in rows
            )
            assert sum((r["cost_usd"] for r in rows), Decimal(0)) == result.cost_usd
            assert all(r["response_artifact_key"] for r in rows)
            assert len(artifacts.bodies) == len(rows)

    run_async(_run())


def test_the_spend_is_drained_through_the_injected_factory_not_the_page_connection() -> None:
    """D2: the script hands ``transaction`` as the spend factory so a rolled-back --dry-run page
    still records its money; the page never drains on its own connection."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            opened: list[int] = []

            @asynccontextmanager
            async def spend_factory() -> AsyncIterator[AsyncConnection]:
                opened.append(1)
                yield conn

            await _contact_page(conn, seeded, RoutingTransport(), spend_conn_factory=spend_factory)
            assert opened == [1]

    run_async(_run())
```

(add `from contextlib import asynccontextmanager` and `from collections.abc import AsyncIterator` to the imports.)

- [ ] **Step 2: Run the DB tests to verify they fail**

Run: `set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_lane3-cost-read"; uv run pytest tests/arv2/display/test_page_db.py -v`
Expected: FAIL with `TypeError: ensure_page() got an unexpected keyword argument 'artifacts'` (and the factory `TypeError`).

- [ ] **Step 3: Implement the page**

In `platform/api/clue_api/arv2/display/page.py`:

Imports: replace `from clue_api.arv2.sinks import FileRawSink, JsonlLedger` with

```python
from clue_api.arv2.provider_ledger import (
    ArtifactSink,
    BufferedLedger,
    BufferedRawSink,
    LedgerStamp,
    drain_provider_calls,
)
from clue_api.arv2.sinks import LedgerSink, RawSink
from clue_db import ConnFactory
```

remove `from pathlib import Path` if unused.

```python
RunnerFactory = Callable[[RawSink, LedgerSink], LunaSectionRunner]
```

`default_runner_factory`: delete the `root = Path(settings.arv2_raw_root)` line and replace `build`:

```python
    def build(raw: RawSink, ledger: LedgerSink) -> LunaSectionRunner:
        caller = ProviderCaller(
            transport=HttpxTransport(), raw_sink=raw, ledger=ledger, now=lambda: datetime.now(UTC)
        )
        return LunaSectionRunner(
            caller, api_key=key, base_url=base_url, model=model, timeout_s=timeout_s
        )
```

and change its docstring's first line to `"""The factory a real page uses: live HTTP, one caller per section over the section's sinks.`

`_write_section`: add `raw: BufferedRawSink, ledger: BufferedLedger,` keyword parameters (after `runner_factory`) and replace `runner = runner_factory()` with `runner = runner_factory(raw, ledger)`. `_Written` is unchanged.

`ensure_page`: add `artifacts: ArtifactSink,` and `spend_conn_factory: ConnFactory,` keyword parameters after `runner_factory`; extend the docstring with:

```
    The sections' provider spend does NOT ride ``conn``: their rows and raw bodies are drained
    after the sections return, sequentially, under ``spend_conn_factory`` (D2, slice 1b) — so a
    caller that rolls the page back (``--dry-run``) still records the money it spent. A page
    belongs to an account, not a project or a run, so the rows are workspace spend.
```

Replace the gather block with:

```python
    semaphore = asyncio.Semaphore(max(1, settings.arv2_display_max_parallel))
    buffers = [(BufferedRawSink(), BufferedLedger()) for _ in to_write]
    try:
        written: list[_Written] = list(
            await asyncio.gather(
                *(
                    _write_section(
                        page=page,
                        subject=subject,
                        client=client,
                        recipes=recipes,
                        section=item,
                        people=people,
                        settings=settings,
                        runner_factory=runner_factory,
                        raw=raw,
                        ledger=ledger,
                        semaphore=semaphore,
                    )
                    for item, (raw, ledger) in zip(to_write, buffers, strict=True)
                )
            )
        )
    finally:
        # One connection, one section at a time: a drain inside the gather would race on it.
        async with spend_conn_factory() as spend_conn:
            for raw, ledger in buffers:
                await drain_provider_calls(
                    spend_conn,
                    raw=raw,
                    ledger=ledger,
                    artifacts=artifacts,
                    stamp=LedgerStamp(workspace_id=workspace_id),
                )
```

- [ ] **Step 4: Implement the script**

In `scripts/generate_arv2_display.py`: add `from clue_api.agent_turn_wiring import DurableAgentArtifactStore`, `from clue_api.storage_wiring import build_storage_backend`, and change `from clue_db import db_lifespan` to `from clue_db import db_lifespan, transaction`. In `_run`, right after `async with db_lifespan(args.database_url) as engine:` add

```python
        # Slice 1b: the pages' provider spend lands on provider_call_ledger in its own
        # transactions (D2) — a --dry-run page rolls back, its spend rows do not.
        artifacts = DurableAgentArtifactStore(
            storage=build_storage_backend(settings), conn_factory=transaction
        )
```

and pass `artifacts=artifacts, spend_conn_factory=transaction,` to `ensure_page`. In the module docstring change `--dry-run runs the whole thing in one transaction, prints the report, and rolls it back (the calls still happen and are still paid for).` to `--dry-run runs the whole thing in one transaction, prints the report, and rolls the page back; the calls still happen, are still paid for, and their rows on provider_call_ledger are kept (they commit on their own).`

In `tests/arv2/display/test_display_live.py` (a live test, skipped without keys; keep it importable) pass `artifacts=FakeArtifacts(), spend_conn_factory=conn_session_factory(conn),` to its `ensure_page` call, importing `FakeArtifacts` from `tests.arv2.test_provider_ledger_db` and `conn_session_factory` from `tests.profiling.conftest` (check the names of its connection variable first).

- [ ] **Step 5: Run the tests and gates**

Run: `set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_lane3-cost-read"; uv run pytest tests/arv2/display -v --ignore-glob='*_live.py' && uv run python -c "import tests.arv2.display.test_display_live" && uv run ruff format platform/api/clue_api/arv2/display/page.py scripts/generate_arv2_display.py tests/arv2/display/test_page_db.py tests/arv2/display/test_display_live.py && uv run ruff check platform/api/clue_api/arv2/display scripts/generate_arv2_display.py tests/arv2/display && uv run mypy && uv run lint-imports && uv run python scripts/generate_arv2_display.py --help`
Expected: all PASS; the live module imports; `--help` prints usage.

- [ ] **Step 6: Commit**

```bash
git add platform/api/clue_api/arv2/display/page.py scripts/generate_arv2_display.py tests/arv2/display/test_page_db.py tests/arv2/display/test_display_live.py
git commit -m "feat(display): the prewrite's section spend lands on provider_call_ledger in its own transaction

Each section's caller writes to buffered sinks; the page drains them sequentially after the
gather under an injected spend factory, workspace-stamped. The script passes transaction, so
a --dry-run page that rolls back still records the money it spent (D2, lane 3 slice 1b)."
```

---

### Task 5: The persona-evidence tool drains under the turn's connection and refuses without an artifact store

**Files:**
- Modify: `platform/api/clue_api/onboarding_evidence_tools.py` (imports; `ExaSearchEvidenceTool.__init__` / `preconditions` / `invoke`; `build_onboarding_evidence_tools`)
- Modify: `platform/api/clue_api/toolbelt_wiring.py:3095-3098`
- Test: `tests/api/test_onboarding_evidence_tools.py`; create `tests/api/test_onboarding_evidence_tools_db.py`

**Interfaces:**
- Consumes: Task 1's `LedgerStamp(workspace_id=)`; `ArtifactSink`, buffers and `drain_provider_calls` from `clue_api.arv2.provider_ledger`; `DurableAgentArtifactStore` (already imported in `toolbelt_wiring`).
- Produces:
  - `ExaSearchEvidenceTool(*, enabled: bool, client_factory: Callable[[str, RawSink, LedgerSink], ExaAgentSurface] | None, artifacts: ArtifactSink | None = None)`.
  - `build_onboarding_evidence_tools(*, settings, secrets, artifacts: ArtifactSink | None = None) -> tuple[Tool, ...]`.
  - A new precondition reason code `artifacts_not_configured` (D3).

- [ ] **Step 1: Update the offline tests and write the failing ones**

In `tests/api/test_onboarding_evidence_tools.py`:

Replace `_ctx()` so the offline tests never need an engine:

```python
@asynccontextmanager
async def _no_db() -> AsyncIterator[None]:
    """The drain executes no SQL when nothing was buffered; the offline fakes buffer nothing."""
    yield None


def _ctx() -> ToolContext:
    return ToolContext(
        workspace_id="ws-evidence",
        actor="agent",
        conn_factory=_no_db,  # type: ignore[arg-type]
        operation_id=operation_id_from_key("o4-evidence", "test"),
    )
```

(add `from contextlib import asynccontextmanager` and `from collections.abc import AsyncIterator`; drop the `transaction` import if unused.)

Add a `FakeArtifacts` (copy the class from `tests/arv2/test_provider_ledger_db.py`, or import it: `from tests.arv2.test_provider_ledger_db import FakeArtifacts`).

Every `ExaSearchEvidenceTool(enabled=True, client_factory=lambda label: fake)` becomes `ExaSearchEvidenceTool(enabled=True, client_factory=lambda label, raw, ledger: fake, artifacts=FakeArtifacts())`, and the descriptor test's `client_factory=None` construction gains `artifacts=None`.

Change the refusal parametrize to:

```python
@pytest.mark.parametrize(
    ("enabled", "factory", "artifacts", "code"),
    [
        (False, lambda label, raw, ledger: FakeExa(_deep([], [])), FakeArtifacts(), "persona_evidence_disabled"),
        (True, None, FakeArtifacts(), "exa_not_configured"),
        (True, lambda label, raw, ledger: FakeExa(_deep([], [])), None, "artifacts_not_configured"),
    ],
)
def test_it_refuses_before_spend_when_off_or_unconfigured(
    enabled: bool, factory: object, artifacts: object, code: str
) -> None:
    async def scenario() -> None:
        tool = ExaSearchEvidenceTool(enabled=enabled, client_factory=factory, artifacts=artifacts)  # type: ignore[arg-type]
        failures = await tool.preconditions(
            ExaSearchEvidenceInput(query="pain of practice managers"), _ctx()
        )
        assert [f.reason_code for f in failures] == [code]

    asyncio.run(scenario())
```

Create `tests/api/test_onboarding_evidence_tools_db.py`:

```python
"""Lane 3 slice 1b: the persona-evidence tool lands its call on ``provider_call_ledger`` under
the tool context's own connection factory, workspace-stamped (the context carries no project)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.sinks import LedgerRow
from clue_api.onboarding_evidence_tools import ExaSearchEvidenceInput, ExaSearchEvidenceTool
from clue_toolbelt import ToolContext, operation_id_from_key
from tests.api.test_onboarding_evidence_tools import FakeExa, _deep
from tests.arv2.test_provider_ledger_db import FakeArtifacts
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def test_an_invocation_lands_its_row_under_the_contexts_connection_with_the_workspace_stamp() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws = f"ws_evidence_{uuid4().hex[:8]}"
            fake = FakeExa(_deep([], []))
            artifacts = FakeArtifacts()

            def factory(label: str, raw: Any, ledger: Any) -> FakeExa:
                ledger.record(
                    LedgerRow(
                        row_id=f"evidence:{label}",
                        call_id=str(uuid4()),
                        phase="result",
                        provider="exa",
                        operation="deep-reasoning",
                        label=label,
                        recorded_at=datetime(2026, 9, 14, tzinfo=UTC),
                        http_status=200,
                        latency_ms=7,
                        attempts=1,
                        cost_usd=Decimal("0.015"),
                        outcome="ok",
                        extras={"cost_source": "metered"},
                    )
                )
                return fake

            tool = ExaSearchEvidenceTool(enabled=True, client_factory=factory, artifacts=artifacts)
            ctx = ToolContext(
                workspace_id=ws,
                actor="agent",
                conn_factory=conn_session_factory(conn),
                operation_id=operation_id_from_key("o4-evidence", "db"),
            )
            await tool.invoke(ExaSearchEvidenceInput(query="pain of practice managers"), ctx)
            row = (
                await conn.execute(
                    text(
                        "SELECT workspace_id, project_id, project_run_id, entity_research_job_id, "
                        " cost_usd, label FROM provider_call_ledger "
                        "WHERE workspace_id = :ws AND phase = 'result'"
                    ),
                    {"ws": ws},
                )
            ).mappings().one()
            assert (row["project_id"], row["project_run_id"], row["entity_research_job_id"]) == (None, None, None)
            assert row["cost_usd"] == Decimal("0.015000")
            assert row["label"].startswith("exa_search_evidence:")

    run_async(scenario())
```

(`FakeExa` and `_deep` are the offline test module's; `operation_id_from_key` is what that module imports from `clue_toolbelt` — copy its import line. The label prefix is `EXA_SEARCH_EVIDENCE_TOOL_NAME + ":"`; import the constant instead of spelling it if its value differs.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_lane3-cost-read"; uv run pytest tests/api/test_onboarding_evidence_tools.py tests/api/test_onboarding_evidence_tools_db.py -v`
Expected: FAIL with `TypeError: ExaSearchEvidenceTool.__init__() got an unexpected keyword argument 'artifacts'`.

- [ ] **Step 3: Implement the tool**

In `platform/api/clue_api/onboarding_evidence_tools.py`:

Imports: replace `from clue_api.arv2.sinks import FileRawSink, JsonlLedger` with

```python
from clue_api.arv2.provider_ledger import (
    ArtifactSink,
    BufferedLedger,
    BufferedRawSink,
    LedgerStamp,
    drain_provider_calls,
)
from clue_api.arv2.sinks import LedgerSink, RawSink
```

and remove `from pathlib import Path` if unused.

Constructor and preconditions:

```python
    def __init__(
        self,
        *,
        enabled: bool,
        client_factory: Callable[[str, RawSink, LedgerSink], ExaAgentSurface] | None,
        artifacts: ArtifactSink | None = None,
    ) -> None:
        self._enabled = enabled
        self._client_factory = client_factory
        # Slice 1b, D3: the call's raw body becomes an artifact and its rows land on the ledger;
        # without an artifact store the tool refuses before spending rather than keeping half.
        self._artifacts = artifacts

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        del inputs, ctx
        if not self._enabled:
            return _fail(
                "persona_evidence_disabled",
                "CLUE_ONBOARDING_PERSONA_EVIDENCE_ENABLED is off in this deployment",
            )
        if self._client_factory is None:
            return _fail("exa_not_configured", "CLUE_EXA_API_KEY is not configured in this process")
        if self._artifacts is None:
            return _fail(
                "artifacts_not_configured",
                "no artifact store is composed in this process, so the call's raw body could "
                "not be kept; refusing before spend",
            )
        return ()
```

`invoke`:

```python
    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ExaSearchEvidenceInput)
        assert self._client_factory is not None and self._artifacts is not None
        label = f"{self.name}:{ctx.operation_id}"
        raw, ledger = BufferedRawSink(), BufferedLedger()
        client = self._client_factory(label, raw, ledger)
        try:
            result = await asyncio.to_thread(
                lambda: client.deep_reasoning(
                    system_prompt=PERSONA_EVIDENCE_SYSTEM_PROMPT,
                    query=inputs.query,
                    output_schema=persona_evidence_output_schema(),
                    num_results=inputs.num_results,
                    include_domains=list(inputs.include_domains) or None,
                    label=label,
                )
            )
        finally:
            # Slice 1b: the call's rows are money whatever its outcome; they land under the
            # turn's own connection factory. The context carries no project, so this is
            # workspace spend.
            async with ctx.conn_factory() as conn:
                await drain_provider_calls(
                    conn,
                    raw=raw,
                    ledger=ledger,
                    artifacts=self._artifacts,
                    stamp=LedgerStamp(workspace_id=ctx.workspace_id),
                )
        output = ExaSearchEvidenceOutput(
            passages=_passages(result),
            cost_usd=str(result.cost_usd) if result.cost_usd is not None else "0",
            request_id=result.request_id,
        )
        return ToolResult(
            tool=self.name, version=self.version, references=output.model_dump(mode="json")
        )
```

Update the class's `replay.durable_identity` string to `"ARV2 ledger row on provider_call_ledger keyed on the call; the tool writes no domain state"`.

`build_onboarding_evidence_tools`:

```python
def build_onboarding_evidence_tools(
    *, settings: Settings, secrets: Secrets | None, artifacts: ArtifactSink | None = None
) -> tuple[Tool, ...]:
```

(docstring gains: `` ``artifacts`` is the store the call's raw body lands in; without one the tool refuses ``artifacts_not_configured`` before any spend (slice 1b, D3). ``) and its inner factory becomes:

```python
        def build_client(label: str, raw: RawSink, ledger: LedgerSink) -> ExaAgentSurface:
            # One caller per invocation: ProviderCaller's totals/latch are unlocked mutable state.
            del label  # the label rides the rows; the sinks are the invocation's
            caller = ProviderCaller(
                transport=HttpxTransport(), raw_sink=raw, ledger=ledger, now=lambda: datetime.now(UTC)
            )
            return ExaClient(caller, secret)
```

with `root = Path(...)` removed, and the return passing `artifacts=artifacts` to the tool.

In `platform/api/clue_api/toolbelt_wiring.py` change the composition to:

```python
    for tool in build_onboarding_evidence_tools(
        settings=resolved_settings,
        secrets=secrets,
        artifacts=(
            None
            if storage is None
            else DurableAgentArtifactStore(storage=storage, conn_factory=conn_factory)
        ),
    ):
        registry.register(tool, make_default=True)
```

- [ ] **Step 4: Run the tests and gates**

Run: `set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_lane3-cost-read"; uv run pytest tests/api/test_onboarding_evidence_tools.py tests/api/test_onboarding_evidence_tools_db.py tests/api/test_toolbelt_wiring.py tests/agents/test_tool_authority_audit.py -v --ignore-glob='*_live.py' && uv run ruff format platform/api/clue_api/onboarding_evidence_tools.py platform/api/clue_api/toolbelt_wiring.py tests/api/test_onboarding_evidence_tools.py tests/api/test_onboarding_evidence_tools_db.py && uv run ruff check platform/api/clue_api/onboarding_evidence_tools.py platform/api/clue_api/toolbelt_wiring.py tests/api/test_onboarding_evidence_tools.py tests/api/test_onboarding_evidence_tools_db.py && uv run mypy && uv run lint-imports`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/onboarding_evidence_tools.py platform/api/clue_api/toolbelt_wiring.py tests/api/test_onboarding_evidence_tools.py tests/api/test_onboarding_evidence_tools_db.py
git commit -m "feat(evidence-tool): the persona-evidence call lands on provider_call_ledger under the turn's connection

The tool owns buffered sinks per invocation and drains them in a finally under the tool
context's connection factory, workspace-stamped. Without a composed artifact store it refuses
artifacts_not_configured before spending (D3, lane 3 slice 1b)."
```

---

### Task 6: The cost read stops listing the three ledgers; the docs say so

**Files:**
- Modify: `platform/projections/clue_projections/cost.py` (module docstring's "What this read cannot see" paragraph; `NOT_COVERED`)
- Modify: `tests/projections/test_cost_db.py::test_not_covered_names_every_ledger_this_read_cannot_see`
- Modify: `docs/superpowers/specs/archive/2026-09-14-telemetry-and-cost-observability-design.md` (§3 row "Onboarding / display / evidence spend"; §5.5 last paragraph; §9 item 1b)
- Modify: `docs/superpowers/plans/2026-09-13-lane-plan-index.md` (Lane 3 table row 1b)

**Interfaces:** none new. `NOT_COVERED` keeps its name and type (`tuple[str, ...]`), exported unchanged.

- [ ] **Step 1: Update the failing test**

In `tests/projections/test_cost_db.py` replace `test_not_covered_names_every_ledger_this_read_cannot_see` with:

```python
def test_not_covered_names_only_the_ledgers_this_read_still_cannot_see() -> None:
    """Slice 1b routed the onboarding, display and evidence ledgers onto Postgres; what is left
    is the design subsystem (R12 hold) and the turn rows written before the cost columns."""
    _, report = _report()
    text_ = " ".join(report.not_covered)
    assert "design" in text_ and "before" in text_
    for word in ("onboarding", "display", "evidence"):
        assert word not in text_
    assert len(report.not_covered) == 2
```

- [ ] **Step 2: Run it to verify it fails**

Run: `set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_lane3-cost-read"; uv run pytest tests/projections/test_cost_db.py -v`
Expected: the renamed test FAILS (`"onboarding" in text_`).

- [ ] **Step 3: Shrink the list and reword the docstring**

In `cost.py` replace `NOT_COVERED` with:

```python
#: The spend this read cannot see. Constant and printed on every report so a partial total is
#: never mistaken for a whole one. Each entry names the ledger and the reason. (Slice 1b routed
#: the onboarding lane, the display prewrite and the persona-evidence tool onto
#: provider_call_ledger, so they are no longer listed.)
NOT_COVERED: tuple[str, ...] = (
    "design subsystem providers (text-to-image, ad-DNA model): no ledger rows yet (R12 hold)",
    "conversation-turn model calls recorded before agent_model_call.cost_usd existed: blank, "
    "counted as unpriced",
)
```

and the module docstring paragraph beginning `What this read cannot see` with:

```
What this read cannot see is named in ``not_covered`` on every report: the design subsystem's
own providers are held (design note R12); turn rows before the cost columns are blank. Every
other paid call — ARV2 research, discovery, onboarding, the display prewrite, the persona-evidence
tool — is on ``provider_call_ledger`` since slice 1b.
```

(No write-SQL token appears in either.)

- [ ] **Step 4: Update the two docs**

Design note §3: change the row `| Onboarding / display / evidence spend | ProviderCaller with JsonlLedger (…) | On disk, not queryable — slice 1b routes them to provider_call_ledger. |` to `| Onboarding / display / evidence spend | ProviderCaller over buffered sinks drained by the onboarding driver, the display page and the evidence tool (slice 1b) | On provider_call_ledger since 2026-09-14; the onboarding run id is the job stamp. |`.

Design note §5.5: change the sentence `Every report carries a \`not_covered\` list naming the spend this read cannot see: the onboarding lane, the display prewrite and the persona-evidence tool (JSONL ledgers on disk — **slice 1b** routes them to the Postgres ledger), the design subsystem's providers (R12 hold), and pre-cost-column turn rows.` to `Every report carries a \`not_covered\` list naming the spend this read cannot see: the design subsystem's providers (R12 hold) and pre-cost-column turn rows. Slice 1b (2026-09-14) put the onboarding lane, the display prewrite and the persona-evidence tool on the Postgres ledger, and made every OpenRouter row carry its model and token counts.`

Design note §9 item `1b.`: change its text to `1b. **JSONL ledgers onto Postgres — DONE 2026-09-14.** The onboarding lane, the display prewrite and the persona-evidence tool drain their \`ProviderCaller\` sinks onto \`provider_call_ledger\` (design: \`2026-09-14-lane3-slice1b-jsonl-ledgers-to-postgres-design.md\`); OpenRouter rows carry model and usage.`

Lane index Lane 3 table row 1b: `| 1b | \`2026-09-14-lane3-slice1b-jsonl-ledgers-to-postgres.md\` | onboarding / display / evidence spend on \`provider_call_ledger\`; OpenRouter rows carry model and usage; \`not_covered\` shrinks to R12 + pre-column rows | 1 |`.

- [ ] **Step 5: Run the tests and gates**

Run: `set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_lane3-cost-read"; uv run pytest tests/projections/test_cost_db.py tests/projections/test_no_write_sql_guard.py tests/projections/test_cost_cli.py -v && uv run ruff format platform/projections/clue_projections/cost.py tests/projections/test_cost_db.py && uv run ruff check platform/projections tests/projections/test_cost_db.py && uv run mypy`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add platform/projections/clue_projections/cost.py tests/projections/test_cost_db.py docs/superpowers/specs/archive/2026-09-14-telemetry-and-cost-observability-design.md docs/superpowers/plans/2026-09-13-lane-plan-index.md
git commit -m "feat(projections): the cost read's not_covered list shrinks to the design hold and pre-column rows

Slice 1b put the onboarding, display and evidence ledgers on provider_call_ledger; the design
note and lane index record it."
```

---

### Task 7: Verification and the memory note (controller)

**Files:**
- Create: `_memory/2026-09-14-lane3-slice1b-jsonl-ledgers-to-postgres.md`; add its index line to `_memory/README.md`

- [ ] **Step 1: The whole-slice test set on the lane database**

Run: `set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_lane3-cost-read"; env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/arv2 tests/projections tests/api/test_onboarding_evidence_tools.py tests/api/test_onboarding_evidence_tools_db.py tests/api/test_fleet_wiring.py tests/api/test_toolbelt_wiring.py tests/agents/test_tool_authority_audit.py -q --ignore-glob='*_live.py' -p no:cacheprovider`
Expected: green (the `tests/db` round-trip suite is not in this set: it needs a fresh empty DB and no migration changed).

- [ ] **Step 2: The zero-spend proof**

Run `make cost-report ARGS="--workspace ws_869a9f51487443c8800453995cdb52cf"` on the lane DB and confirm the `NOT COVERED` block now lists two items. Real onboarding rows cannot appear until a real run happens (founder-triggered: `POST /onboarding` on a stack running this branch spends roughly $3–8); record it under "Verification owed".

- [ ] **Step 3: Write and commit the note**

The note records: what landed (per task, commits), the three decisions, the discovery that persona runs make no driver-side provider call (so the stamp is workspace + job only), the proof run, verification owed (the live onboarding run; the display prewrite against a real account), and follow-ups (historical `chat/completions` rows keep `unknown`; the design subsystem R12). Add the README index line and commit with `docs(memory): lane 3 slice 1b — every provider call on the Postgres ledger`.

---

## Self-review

**Spec coverage.** §3.1 stamp → Task 1. §3.2 onboarding (factories take sinks, driver drains after each step, D1 stamp, reconciler factory) → Task 3. §3.3 display (factory takes sinks, sequential drain after the gather, D2 own transaction, script composition) → Task 4. §3.4 evidence tool (buffers, `ctx.conn_factory` drain, D3 refusal, wiring passes the store) → Task 5. §3.5 reader extras → Task 2. §3.6 cost read + docs → Task 6. §5 testing → each task's tests; the live proof → Task 7. §4 "what does not change" → no task touches R11/R12 files, `ProviderCaller` or `LedgerRow`.

**Spec refinement recorded.** §3.2's "project id from a project-local persona ICP": persona-only runs make no driver-side provider call, so there is no row to stamp; the driver's stamp is workspace + job (Task 3, discovery 2).

**Placeholders.** None: every step carries its code. Two assertions in Task 3 (the exact recon-subject label list) are marked for the implementer to make exact against the fixtures rather than guessed here.

**Type consistency.** `LedgerStamp(workspace_id=, job_id=)` (Task 1) is what Tasks 3–5 build; `RawSink`/`LedgerSink` are the protocol names in `clue_api.arv2.sinks`; `BufferedRawSink`/`BufferedLedger`/`drain_provider_calls`/`DrainReport`/`ArtifactSink` are `clue_api.arv2.provider_ledger`'s; `ExaClientFactory`'s keyword names (`run_id`, `step_label`, `raw`, `ledger`) match every fake; `RunnerFactory(raw, ledger)` positional in Task 4 matches `_factory`'s `build(raw, ledger)`; the evidence tool's `client_factory(label, raw, ledger)` positional matches its tests.
