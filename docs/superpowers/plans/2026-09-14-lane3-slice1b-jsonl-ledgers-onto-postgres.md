# Lane 3 slice 1b — JSONL ledgers onto Postgres — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every paid call the platform makes through `ProviderCaller` lands as a row in `provider_call_ledger`, so the cost read (slice 1) sees the onboarding lane, the display prewrite and the persona-evidence tool instead of naming them as "not covered"; and every OpenRouter ledger row carries the model and token usage the read groups by.

**Architecture:** Three call sites today build a `ProviderCaller` over `FileRawSink` + `JsonlLedger` and never drain. This slice gives them the same shape the research and discovery lanes already use: a buffered caller (`BufferedLedger`, and `BufferedRawSink` where an artifact store is in hand) drained under a database connection through the existing `drain_provider_calls`, with a `LedgerStamp` that now admits a run without a project and names its lane. No new table, no migration (the ledger's project, run and job columns are already nullable). One shared helper builds the buffered caller and one small generic wrapper carries a client together with its spend, so a test double that returns a bare client keeps working (spend `None` = nothing to drain).

**Tech Stack:** Python 3.12, SQLAlchemy async `text()`, dataclasses, pytest with the rolled-back-connection DB harness, `uv`.

**Spec:** `docs/superpowers/specs/2026-09-14-telemetry-and-cost-observability-design.md` §2 (R2, R8, R10, R11, R12), §3 "Onboarding / display / evidence spend" row, §5.5, §9 slice 1b. Mechanics recorded in `_memory/2026-09-14-lane3-slice1-cost-read.md` "Discovered, recorded, not done here". Rulings ledger: `_memory/2026-09-14-lane3-telemetry-rulings.md`.

## Global Constraints

- **Worktree and branch.** Lane 3's worktree, branch `lane3/slice1b-jsonl-ledgers`, off `research-streaming` at or after the PR #55 merge (`61de59d50`). No file lane 1 is editing is touched by this slice (it stays inside `platform/api/clue_api/arv2/**`, `onboarding_evidence_tools.py`, `fleet_main.py`'s onboarding composition, `clue_projections/cost.py`, tests, docs).
- **Postgres is the ledger of record (R2).** Nothing here computes a cost; the rows carry what the provider's own metering said, as they do today on disk.
- **Every provider goes through `ProviderCaller` (R10).** This slice adds no second write path: the drain is the existing `drain_provider_calls`, the stamp is the existing `LedgerStamp` widened, the rows are the existing shape.
- **Legacy research lane untouched (R11).** Nothing under `subsystems/research/clue_research/**`.
- **Design subsystem untouched (R12 hold).**
- **No migration.** `provider_call_ledger.project_id`, `project_run_id` and `entity_research_job_id` are nullable (`alembic/versions/65fb2128c904_arv2_d1_display_substrate.py`). `uv run alembic heads` stays at one head, unchanged.
- **Raw bodies stay saved before parse (Appendix A law 1).** Where an `ArtifactSink` is in hand (the onboarding fleet handler) raw bodies buffer and drain to the artifact store. Where none is (the display prewrite on the request path and the operator script; the evidence tool inside a chat turn) raw bodies keep going to disk under `CLUE_ARV2_RAW_ROOT` and the ledger row records the file reference in `extras_json.raw_ref`. Only the *ledger* moves to Postgres everywhere.
- **Test doubles keep working.** `FakeExa` / `FakeArtifacts` / `_factory(transport)` / `make_caller` in `tests/arv2` and `tests/api` are wrapped, never rewritten: a client with `spend=None` drains nothing.
- **Tests spend no money.** DB tests only against the lane's throwaway database (`CLUE_DATABASE_URL` from the worktree `.env`, loaded with `set -a; source .env; set +a`); scope every run to the files named; never `make check` with real keys; `--ignore-glob='*_live.py'` on any broader run.
- **The projections package writes nothing** (`tests/projections/test_no_write_sql_guard.py`); Task 7 edits only a constant and a docstring there.
- **Gates per task:** `uv run ruff format <files> && uv run ruff check <paths>`, `uv run mypy`, `uv run lint-imports` after any import change.
- **Commits:** local only, never push; no AI attribution trailer; one commit per task.

## What the plan established (read before Task 1)

1. **Three sites, three postures.** The onboarding fleet handler (`arv2/onboarding_driver.py:281-311`, composed at `fleet_main.py:653-680`) holds a `conn_factory` **and** an `ArtifactSink` (`DurableAgentArtifactStore`) and settles each step under its own connection: it can drain raw bodies and rows exactly like account research (`account_research_tools.py:468-485`) and discovery (`discovery_driver.py:1196-1231`). Its catalog reconciler (`arv2/onboarding_reconcile.py:145-236`, factory at `fleet_main.py:700-727`) builds a caller per call the same way. The display prewrite (`arv2/display/page.py:99-118`, runner `display/runner.py:407-490`) runs inside the caller's transaction (`ensure_page(conn, ...)`, called from `frontend_read/display_pages.py:220` and `scripts/generate_arv2_display.py:192`) with a connection but no artifact store. The persona-evidence tool (`onboarding_evidence_tools.py:104-182`, built at `toolbelt_wiring.py:3095`) has `ctx.conn_factory` and `ctx.workspace_id` on every invocation and no artifact store.
2. **The drain already maps raw refs to artifact keys but does not return them** (`provider_ledger.py:181-215`, `keys` is local). The onboarding step stores `raw_artifact_key = run.raw_refs[-1]` (`onboarding_driver.py:679, 699`), which today is a file path from `FileRawSink` and would become a `raw:<sha>` content address under `BufferedRawSink`. `DrainReport` must return the mapping so the step cites the real artifact key. `onboarding_step.raw_artifact_key` is plain `text` with no FK (`0aa95f87eb49`), so both shapes are storable; only the meaning changes.
3. **`LedgerStamp` demands a project and a run** (`provider_ledger.py:116-124`: `project_id: str`, `project_run_id: str`, `job_id: UUID`). Onboarding is brand-level (`onboarding_run` has `workspace_id`, `brand_id`, no project), display and evidence have neither project nor run. The columns are nullable; the dataclass is not. It widens, and gains a `lane` so the workflow is readable off the row (`extras_json.lane`), which is what the cost read's "which workflow is expensive" needs without a join.
4. **`openrouter_cost_reader` (`arv2/openrouter.py:116-144`) returns no extras**, so every `chat/completions` row (structuring, Gemini transcribe / mine_quotes, display sections, catalog reconcile) has no `model` and no token counts; the research agent's `agent_completion` rows write them by hand (`account_research_agent.py:175-185`: `model`, `prompt_tokens`, `completion_tokens`, `cached_prompt_tokens`, `cost_source`). `CostReading.extras` is merged into the result row (`calls.py:88-100`, settle at `:630`), so one change in the reader fixes every writer. The read (`clue_projections/cost.py::_RESEARCH_MODEL_LINES`) already reads exactly those keys.
5. **Test doubles.** `tests/arv2/test_onboarding_driver.py:329-332` and `tests/arv2/test_onboarding_driver_db.py:75-79` pass `exa=lambda *, run_id, step_label: exa`; `:1018` passes a reconciler factory `factory(run_id)`; `tests/api/test_onboarding_evidence_tools.py:49-55, 75` pass `client_factory=lambda label: FakeExa(...)`; `tests/arv2/display/test_page_db.py:150-166` builds `LunaSectionRunner(ProviderCaller(... MemoryRawSink, MemoryLedger))`. The wrapper in Task 2 makes each a one-line change or none.

## File structure

| File | Responsibility |
| --- | --- |
| `platform/api/clue_api/arv2/openrouter.py:116-144` | **Modify.** The cost reader returns `model` + token usage in `extras`. |
| `platform/api/clue_api/arv2/provider_ledger.py` | **Modify.** `LedgerStamp` widened (+`lane`); `drain_provider_calls` optional raw/artifacts, returns `artifact_keys`, records undrained `raw_ref`; new `BufferedCaller`, `build_buffered_caller`, `SpendingClient`. |
| `platform/api/clue_api/arv2/onboarding_driver.py` | **Modify.** `ExaClientFactory` returns `SpendingClient[ExaAgentSurface]`; reconciler factory returns `SpendingClient[CatalogReconciler]`; the driver drains after each provider step; `build_onboarding_provider_caller` replaced. |
| `platform/api/clue_api/fleet_main.py:653-727` | **Modify.** The onboarding compositions build buffered callers. |
| `platform/api/clue_api/arv2/display/runner.py:407-431` | **Modify.** `LunaSectionRunner` carries its `spend`. |
| `platform/api/clue_api/arv2/display/page.py:99-118, 288-420` | **Modify.** Default factory buffers the ledger; `ensure_page` drains every runner under `conn`. |
| `platform/api/clue_api/onboarding_evidence_tools.py` | **Modify.** `client_factory` returns `SpendingClient`; `invoke` drains through `ctx.conn_factory`. |
| `platform/projections/clue_projections/cost.py` | **Modify.** `NOT_COVERED` shrinks to what is still true. |
| `.env.example:145-147` | **Modify.** The `CLUE_ARV2_RAW_ROOT` comment says what still lives there. |
| `tests/arv2/test_openrouter.py` | **Modify.** Reader extras. |
| `tests/arv2/test_provider_ledger_db.py` | **Modify.** Widened stamp, ledger-only drain, returned keys, `lane` in extras. |
| `tests/arv2/test_onboarding_driver.py`, `tests/arv2/test_onboarding_driver_db.py` | **Modify.** Doubles wrapped; DB test asserts ledger rows and the artifact-keyed step. |
| `tests/arv2/test_onboarding_reconcile.py` | **Modify.** Unchanged behaviour proven through the new factory shape. |
| `tests/arv2/display/test_page_db.py` | **Modify.** A page write lands its section rows. |
| `tests/api/test_onboarding_evidence_tools.py` | **Modify.** Doubles wrapped; one DB test for the drained row. |
| `tests/projections/test_cost_db.py` | **Modify.** `not_covered` assertion follows the constant. |
| `docs/superpowers/specs/2026-09-14-telemetry-and-cost-observability-design.md` §3, §5.5, §9 | **Modify.** Slice 1b done; what remains. |
| `docs/superpowers/plans/2026-09-13-lane-plan-index.md` | **Modify.** Lane 3 row 1b → this plan. |
| `_memory/2026-09-14-lane3-slice1b-jsonl-ledgers.md` | **Create.** Session note with the proof. |

---

### Task 1: The OpenRouter cost reader carries model and usage

**Files:**
- Modify: `platform/api/clue_api/arv2/openrouter.py:116-144`
- Test: `tests/arv2/test_openrouter.py`

**Interfaces:**
- Produces: `openrouter_cost_reader(response) -> CostReading` whose `extras` carries `model` (the served model id from the body's top-level `model`, `""` when absent), `prompt_tokens`, `completion_tokens`, `cached_prompt_tokens` (from `usage.prompt_tokens`, `usage.completion_tokens`, `usage.prompt_tokens_details.cached_tokens`; `0` when absent). Keys match the research agent's hand-written round rows (`account_research_agent.py:178-183`) so the cost read's `research_ledger` model lines cover every OpenRouter row.

- [ ] **Step 1: Write the failing test**

Append to `tests/arv2/test_openrouter.py`:

```python
def test_the_cost_reader_carries_the_model_and_token_usage_the_cost_read_groups_by() -> None:
    body = json.dumps(
        {
            "id": "gen-1",
            "model": "openai/gpt-5.6-luna",
            "usage": {
                "prompt_tokens": 1200,
                "completion_tokens": 80,
                "prompt_tokens_details": {"cached_tokens": 300},
                "cost": 0.0042,
            },
        }
    ).encode()
    reading = openrouter_cost_reader(HttpResponse(200, {}, body))
    assert reading.cost_usd == Decimal("0.0042")
    assert dict(reading.extras) == {
        "model": "openai/gpt-5.6-luna",
        "prompt_tokens": 1200,
        "completion_tokens": 80,
        "cached_prompt_tokens": 300,
    }


def test_the_cost_reader_extras_are_zero_and_blank_when_usage_is_missing() -> None:
    reading = openrouter_cost_reader(HttpResponse(200, {}, b'{"id":"gen-2"}'))
    assert dict(reading.extras) == {
        "model": "",
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cached_prompt_tokens": 0,
    }
    assert openrouter_cost_reader(HttpResponse(200, {}, b"not json")).extras == {}
```

(`json` and `Decimal` are already imported in that module; add them if not.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/arv2/test_openrouter.py -v -k "cost_reader"`
Expected: the two new tests FAIL (`{} != {...}`); the two existing ones PASS.

- [ ] **Step 3: Extend the reader**

Replace the tail of `openrouter_cost_reader` (from `request_id = body.get("id")`) with:

```python
    request_id = body.get("id")
    details_tokens = usage.get("prompt_tokens_details")
    details_tokens = details_tokens if isinstance(details_tokens, dict) else {}
    model = body.get("model")
    return CostReading(
        cost_usd=cost,
        provider_request_id=request_id if isinstance(request_id, str) else None,
        # The same four keys the research agent writes on its own model rounds
        # (account_research_agent.py), so the cost read's per-model lines cover every
        # OpenRouter row — structuring, media, display, catalog reconcile — not only the agent's.
        extras={
            "model": model if isinstance(model, str) else "",
            "prompt_tokens": _int(usage.get("prompt_tokens")),
            "completion_tokens": _int(usage.get("completion_tokens")),
            "cached_prompt_tokens": _int(details_tokens.get("cached_tokens")),
        },
    )


def _int(value: object) -> int:
    """A token count as the provider wrote it, or 0 — a missing count is not a measured zero
    anywhere it matters (cost has its own None), and the read sums these as plain integers."""
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
```

Update the docstring's first line to say the reading also carries model and usage.

- [ ] **Step 4: Run the tests and gates**

Run: `uv run pytest tests/arv2/test_openrouter.py tests/arv2/test_structuring_client.py tests/arv2/test_gemini_media_client.py -v --ignore-glob='*_live.py' && uv run ruff format platform/api/clue_api/arv2/openrouter.py && uv run ruff check platform/api/clue_api/arv2/openrouter.py && uv run mypy`
Expected: all PASS. (If either neighbour test file does not exist under that name, run `uv run pytest tests/arv2 -k "structuring or gemini" --ignore-glob='*_live.py'` instead.)

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/openrouter.py tests/arv2/test_openrouter.py
git commit -m "feat(arv2): the OpenRouter cost reader carries model and token usage on every ledger row

Same four extras keys the research agent writes on its own rounds, so structuring, media,
display and catalog-reconcile rows stop reading as 'unknown / 0 tokens' in the cost read."
```

---

### Task 2: The ledger substrate admits a run without a project, drains ledger-only, and hands back artifact keys

**Files:**
- Modify: `platform/api/clue_api/arv2/provider_ledger.py`
- Modify: `platform/api/clue_api/arv2/account_research_tools.py:479-484`, `platform/api/clue_api/arv2/account_research_driver.py:901-906`, `platform/api/clue_api/arv2/discovery_driver.py:1221-1226` (add `lane=`)
- Test: `tests/arv2/test_provider_ledger_db.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class LedgerStamp:
    workspace_id: str
    lane: str                       # "account_research" | "discovery" | "onboarding" | "display" | "persona_evidence"
    project_id: str | None = None
    project_run_id: str | None = None
    job_id: UUID | None = None      # entity_research_job_id: the research job, or the run that spent (discovery, onboarding)

@dataclass(frozen=True)
class DrainReport:
    rows: int; artifacts: int; cost_usd: Decimal; credits: Decimal; media_seconds: int
    artifact_keys: Mapping[str, str] = field(default_factory=dict)   # raw_ref -> artifact storage key

async def drain_provider_calls(conn, *, ledger: BufferedLedger, stamp: LedgerStamp,
                               raw: BufferedRawSink | None = None,
                               artifacts: ArtifactSink | None = None) -> DrainReport
# raw and artifacts: both or neither. Every row's extras_json gains "lane"; a row whose raw_ref was not
# drained to an artifact (a FileRawSink path, or a ledger-only drain) keeps it in extras_json.raw_ref.

@dataclass(frozen=True)
class BufferedCaller:
    caller: ProviderCaller
    ledger: BufferedLedger
    raw: BufferedRawSink | None     # None when raw bodies go to disk (FileRawSink) instead
    async def drain(self, conn, *, stamp: LedgerStamp, artifacts: ArtifactSink | None = None) -> DrainReport

def build_buffered_caller(*, transport: Transport, now: Callable[[], datetime],
                          raw_root: Path | None = None, ceilings: Ceilings | None = None,
                          sleep: Callable[[float], None] = time.sleep) -> BufferedCaller
# raw_root None -> BufferedRawSink (drain needs an ArtifactSink); raw_root given -> FileRawSink(raw_root), raw=None.

@dataclass(frozen=True)
class SpendingClient(Generic[T]):
    surface: T
    spend: BufferedCaller | None = None   # None: nothing to drain (every existing test double)
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/arv2/test_provider_ledger_db.py` (it already imports `drain_provider_calls`, `BufferedLedger`, `BufferedRawSink`, `LedgerStamp`, `rollback_conn`, `run_async`, `text`, and has `_result_row`, `_stamp`, `FakeArtifacts` helpers — reuse them):

```python
def test_a_stamp_without_a_project_lands_and_the_lane_rides_extras() -> None:
    run_id = uuid4()
    call_id = str(uuid4())

    async def scenario() -> dict[str, Any]:
        ledger = BufferedLedger()
        ledger.record(_result_row(row_id="lane-1", call_id=call_id, raw_ref=None))
        async with rollback_conn(seed_pack=False) as conn:
            report = await drain_provider_calls(
                conn,
                ledger=ledger,
                stamp=LedgerStamp(workspace_id="ws-lane", lane="onboarding", job_id=run_id),
            )
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT project_id, project_run_id, entity_research_job_id, extras_json "
                            "FROM provider_call_ledger WHERE call_id = :c AND phase = 'result'"
                        ),
                        {"c": _call_uuid(call_id)},
                    )
                )
                .mappings()
                .one()
            )
            return {"report": report, **dict(row)}

    got = run_async(scenario())
    assert got["report"].rows == 1 and got["report"].artifact_keys == {}
    assert got["project_id"] is None and got["project_run_id"] is None
    assert got["entity_research_job_id"] == run_id
    assert got["extras_json"]["lane"] == "onboarding"


def test_a_ledger_only_drain_keeps_the_file_raw_ref_in_extras() -> None:
    call_id = str(uuid4())

    async def scenario() -> dict[str, Any]:
        ledger = BufferedLedger()
        ledger.record(_result_row(row_id="disk-1", call_id=call_id, raw_ref="/tmp/raw/x.json"))
        async with rollback_conn(seed_pack=False) as conn:
            await drain_provider_calls(
                conn, ledger=ledger, stamp=LedgerStamp(workspace_id="ws-lane", lane="display")
            )
            return dict(
                (
                    await conn.execute(
                        text(
                            "SELECT response_artifact_key, extras_json FROM provider_call_ledger "
                            "WHERE call_id = :c AND phase = 'result'"
                        ),
                        {"c": _call_uuid(call_id)},
                    )
                )
                .mappings()
                .one()
            )

    got = run_async(scenario())
    assert got["response_artifact_key"] is None
    assert got["extras_json"]["raw_ref"] == "/tmp/raw/x.json"


def test_a_full_drain_returns_the_artifact_key_for_each_raw_ref() -> None:
    call_id = str(uuid4())

    async def scenario() -> tuple[Mapping[str, str], str | None]:
        raw, ledger, artifacts = BufferedRawSink(), BufferedLedger(), FakeArtifacts()
        ref = raw.save(_record(call_id=call_id), b'{"ok": true}')
        ledger.record(_result_row(row_id="full-1", call_id=call_id, raw_ref=ref))
        async with rollback_conn(seed_pack=False) as conn:
            report = await drain_provider_calls(
                conn,
                ledger=ledger,
                raw=raw,
                artifacts=artifacts,
                stamp=LedgerStamp(workspace_id="ws-lane", lane="onboarding", job_id=uuid4()),
            )
            key = (
                await conn.execute(
                    text(
                        "SELECT response_artifact_key FROM provider_call_ledger "
                        "WHERE call_id = :c AND phase = 'result'"
                    ),
                    {"c": _call_uuid(call_id)},
                )
            ).scalar_one()
            return report.artifact_keys, key

    keys, key = run_async(scenario())
    assert list(keys) and key == keys[next(iter(keys))]


def test_raw_without_artifacts_is_refused_before_any_row_lands() -> None:
    async def scenario() -> str:
        async with rollback_conn(seed_pack=False) as conn:
            try:
                await drain_provider_calls(
                    conn,
                    ledger=BufferedLedger(),
                    raw=BufferedRawSink(),
                    stamp=LedgerStamp(workspace_id="ws-lane", lane="display"),
                )
            except ValueError as error:
                return str(error)
            return "no error"

    assert "artifacts" in run_async(scenario())
```

Check the module's existing helper names (`_record`, `_call_uuid`, `FakeArtifacts`) at its top; if `_record` does not exist, build the `RawRecord` inline the way `_result_row`'s neighbour does. Import `Mapping` from `collections.abc` and `Any` from `typing` if missing.

- [ ] **Step 2: Run to verify they fail**

Run: `set -a; source .env; set +a; uv run pytest tests/arv2/test_provider_ledger_db.py -v`
Expected: the four new tests FAIL (`TypeError: unexpected keyword 'lane'` / missing `raw`); existing tests PASS.

- [ ] **Step 3: Widen the stamp, the drain, and add the two helpers**

In `platform/api/clue_api/arv2/provider_ledger.py`:

Replace `LedgerStamp`:

```python
@dataclass(frozen=True)
class LedgerStamp:
    """Whose spend this is.

    ``lane`` names the workflow that spent (``account_research``, ``discovery``, ``onboarding``,
    ``display``, ``persona_evidence``) and rides every row's ``extras_json`` so "which workflow is
    expensive" is a filter, not a join. ``project_id`` / ``project_run_id`` are ``None`` for work
    that has no project (onboarding is brand-level; a display page or an evidence search belongs to
    the workspace). ``job_id`` is the research job that spent, or the run that spent where the lane
    has runs and no jobs (discovery, onboarding) — the column has been named
    ``entity_research_job_id`` since D1; its meaning is "the unit of work that spent".
    """

    workspace_id: str
    lane: str
    project_id: str | None = None
    project_run_id: str | None = None
    job_id: UUID | None = None
```

Replace `DrainReport`:

```python
@dataclass(frozen=True)
class DrainReport:
    """What one drain landed. The three spend numbers are the ``result`` rows only — an estimate
    row is a reservation made before the wire, never money. ``artifact_keys`` maps each drained
    ``raw_ref`` to the artifact storage key it became, so a caller that stored a ``raw_ref`` on its
    own row (the onboarding step) can cite the artifact instead of a buffer address."""

    rows: int
    artifacts: int
    cost_usd: Decimal
    credits: Decimal
    media_seconds: int
    artifact_keys: Mapping[str, str] = field(default_factory=dict)
```

Replace `drain_provider_calls`'s signature and the first lines of its body:

```python
async def drain_provider_calls(
    conn: AsyncConnection,
    *,
    ledger: BufferedLedger,
    stamp: LedgerStamp,
    raw: BufferedRawSink | None = None,
    artifacts: ArtifactSink | None = None,
) -> DrainReport:
    """Persist every buffered ledger row — and, when ``raw`` and ``artifacts`` are both given,
    every buffered raw body first — and report what this drain cost.

    Bytes first, then the rows that cite them — a ledger row never names an artifact key that does
    not exist yet. When two attempts shared a body they share a ``raw_ref``; the last artifact
    written for that reference is the one the rows cite. A ledger-only drain (raw bodies already on
    disk through ``FileRawSink``) keeps each row's file reference in ``extras_json.raw_ref``.
    """
    if (raw is None) != (artifacts is None):
        raise ValueError("raw and artifacts go together: pass both to persist bodies, or neither")
    keys: dict[str, str] = {}
    persisted = 0
    if raw is not None and artifacts is not None:
        for ref, record, body in raw.drain():
            artifact = await artifacts.persist_body(
                workspace_id=stamp.workspace_id,
                data=artifact_payload(record, body),
                media_type="application/json",
            )
            keys[ref] = artifact.artifact_key
            persisted += 1
```

and its return gains `artifact_keys=keys`. In `_ledger_params`, replace the `extras_json` entry with:

```python
        "extras_json": json.dumps(
            _row_extras(row, stamp=stamp, keys=keys), sort_keys=True, default=_json_default
        ),
```

and add:

```python
def _row_extras(row: LedgerRow, *, stamp: LedgerStamp, keys: Mapping[str, str]) -> dict[str, object]:
    """The row's own extras plus the lane, plus the raw reference when it did not become an
    artifact (a file path from ``FileRawSink``, or a ledger-only drain)."""
    extras: dict[str, object] = {**row.extras, "lane": stamp.lane}
    if row.raw_ref and row.raw_ref not in keys:
        extras["raw_ref"] = row.raw_ref
    return extras
```

(The `extras_json` column was nullable-when-empty before; it is now always a JSON object because `lane` is always present. `_ledger_params`'s `"job_id": stamp.job_id` etc. stay; `None` binds as NULL.)

Append the two helpers (imports: `from typing import Generic, TypeVar`, `from pathlib import Path`, `import time`, `from collections.abc import Callable`, and `from .calls import Ceilings, ProviderCaller`, `from .sinks import FileRawSink`, `from .transport import Transport`):

```python
T = TypeVar("T")


@dataclass(frozen=True)
class BufferedCaller:
    """A :class:`ProviderCaller` whose ledger (and, when ``raw`` is set, whose raw bodies) buffer
    until :meth:`drain` lands them in Postgres. ``raw`` is ``None`` when bodies go to disk instead
    (``FileRawSink``); the rows then keep their file reference in ``extras_json.raw_ref``."""

    caller: ProviderCaller
    ledger: BufferedLedger
    raw: BufferedRawSink | None = None

    async def drain(
        self,
        conn: AsyncConnection,
        *,
        stamp: LedgerStamp,
        artifacts: ArtifactSink | None = None,
    ) -> DrainReport:
        return await drain_provider_calls(
            conn,
            ledger=self.ledger,
            stamp=stamp,
            raw=self.raw,
            artifacts=artifacts if self.raw is not None else None,
        )


def build_buffered_caller(
    *,
    transport: Transport,
    now: Callable[[], datetime],
    raw_root: Path | None = None,
    ceilings: Ceilings | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> BufferedCaller:
    """One caller per unit of work (R1's rule: a halt latched by one step's provider must not stop
    another's), buffering its ledger for a Postgres drain. With ``raw_root`` the raw bodies are
    written to disk as before and only the ledger buffers; without it the bodies buffer too and the
    drain must be handed an :class:`ArtifactSink`."""
    ledger = BufferedLedger()
    if raw_root is None:
        raw = BufferedRawSink()
        caller = ProviderCaller(
            transport=transport, raw_sink=raw, ledger=ledger, ceilings=ceilings, sleep=sleep, now=now
        )
        return BufferedCaller(caller=caller, ledger=ledger, raw=raw)
    raw_root.mkdir(parents=True, exist_ok=True)
    caller = ProviderCaller(
        transport=transport,
        raw_sink=FileRawSink(raw_root),
        ledger=ledger,
        ceilings=ceilings,
        sleep=sleep,
        now=now,
    )
    return BufferedCaller(caller=caller, ledger=ledger, raw=None)


@dataclass(frozen=True)
class SpendingClient(Generic[T]):
    """A provider client together with the buffered spend it writes, so the code that holds the
    database connection can land the rows. ``spend`` is ``None`` when there is nothing to drain —
    every offline test double, and any client whose caller ledgers elsewhere."""

    surface: T
    spend: BufferedCaller | None = None
```

Add `"BufferedCaller"`, `"SpendingClient"`, `"build_buffered_caller"` to `__all__`.

Then add `lane=` to the three existing `LedgerStamp(...)` constructions: `lane="account_research"` at `account_research_tools.py:479` and `account_research_driver.py:901`; `lane="discovery"` at `discovery_driver.py:1221`.

- [ ] **Step 4: Run the tests and gates**

Run: `set -a; source .env; set +a; uv run pytest tests/arv2/test_provider_ledger_db.py tests/arv2/test_discovery_driver.py tests/arv2/test_discovery_driver_db.py tests/arv2/test_account_research_driver_db.py tests/arv2/test_account_research_agent.py -v --ignore-glob='*_live.py' && uv run ruff format platform/api/clue_api/arv2/provider_ledger.py platform/api/clue_api/arv2/account_research_tools.py platform/api/clue_api/arv2/account_research_driver.py platform/api/clue_api/arv2/discovery_driver.py && uv run ruff check platform/api/clue_api/arv2 && uv run mypy && uv run lint-imports`
Expected: all PASS. If an existing test asserts `extras_json IS NULL` for a row with no extras, update it to expect `{"lane": "..."}` — that is the new contract, stated in Step 3.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/provider_ledger.py platform/api/clue_api/arv2/account_research_tools.py platform/api/clue_api/arv2/account_research_driver.py platform/api/clue_api/arv2/discovery_driver.py tests/arv2/test_provider_ledger_db.py
git commit -m "feat(arv2): the ledger stamp names its lane and admits work without a project; drains hand back artifact keys

LedgerStamp gains lane and nullable project/run/job; drain_provider_calls can land the ledger alone
(raw bodies on disk keep their file ref in extras) and returns raw_ref -> artifact key;
BufferedCaller / build_buffered_caller / SpendingClient are the one shape every lane uses next."
```

---

### Task 3: The onboarding lane lands on the Postgres ledger

**Files:**
- Modify: `platform/api/clue_api/arv2/onboarding_driver.py` (protocols `:197-208`, factory `:281-311`, `_exa_step` `:618-700`, `_lineup` `:730-760`, catalog sync `:826-850`, settle `:1030-1052`, and a new `_land_spend`)
- Modify: `platform/api/clue_api/fleet_main.py:653-727`
- Modify: `platform/api/clue_api/arv2/onboarding_reconcile.py:145-236` (constructor takes a `BufferedCaller`-producing factory; unchanged otherwise)
- Test: `tests/arv2/test_onboarding_driver.py`, `tests/arv2/test_onboarding_driver_db.py`, `tests/arv2/test_onboarding_reconcile.py`

**Interfaces:**
- Consumes: Task 2 `SpendingClient`, `BufferedCaller`, `build_buffered_caller`, `LedgerStamp(lane="onboarding", job_id=run_id)`, `DrainReport.artifact_keys`.
- Produces:
  - `ExaClientFactory.__call__(*, run_id: UUID, step_label: str) -> SpendingClient[ExaAgentSurface]`
  - `reconciler_factory: Callable[[UUID], SpendingClient[CatalogReconciler]] | None`
  - `build_onboarding_exa_client_factory(settings, secrets) -> ExaClientFactory` builds `build_buffered_caller(transport=HttpxTransport(), now=..., raw_root=None)` per step (bodies to the artifact store).
  - `build_onboarding_provider_caller` is **deleted** (its two callers move to `build_buffered_caller`).
  - `OnboardingRunWorkHandler._land_spend(scope, client: SpendingClient[Any]) -> DrainReport` drains under `_connection()` with `LedgerStamp(workspace_id=scope.workspace_id, lane="onboarding", job_id=scope.run_id)` and `artifacts=self._artifacts`; returns an empty report when `client.spend is None`.
  - The step's `raw_artifact_key` is `report.artifact_keys.get(run.raw_refs[-1], run.raw_refs[-1])` — the artifact key when the drain produced one, else the ref as-is (a test double's `raw/a`).

- [ ] **Step 1: Wrap the offline doubles and write the failing offline test**

In `tests/arv2/test_onboarding_driver.py`: add `from clue_api.arv2.provider_ledger import SpendingClient`; change line 332 to `exa=lambda *, run_id, step_label: SpendingClient(surface=exa),` and the reconciler factory at `:1018` to return `SpendingClient(surface=<the reconciler it built>)`. Then append:

```python
def test_a_step_client_with_no_spend_drains_nothing_and_keeps_its_raw_ref() -> None:
    exa = FakeExa(...)  # the module's usual completed-run fixture; copy the nearest test's setup
    store = FakeStore()
    handler = _handler(exa, store)
    run_async(handler.handle(_context(...)))  # the nearest test's driving call
    finished = [call for call in store.calls if call[0] == "finish_step"]
    assert finished and finished[0][1]["raw_artifact_key"] == "raw/a"
```

Replace the `...` with the exact fixture/driver calls the nearest existing "completed step" test uses (the file's `FakeExa` returns `raw_refs=("raw/a",)` at `:68`; `FakeStore` records `finish_step` kwargs — read its `finish_step` to match the tuple shape). This pins that a spend-less client is a no-op.

- [ ] **Step 2: Write the failing DB test**

In `tests/arv2/test_onboarding_driver_db.py`, wrap `:79` the same way (`SpendingClient(surface=exa)`), then add a test that builds the handler with a **spending** client over the scripted transport the module already uses for Exa (if it drives `FakeExa` only, build a real `ExaClient` over a `ScriptedJsonTransport` the way `tests/arv2/conftest.py::make_caller` does):

```python
def test_a_completed_run_lands_its_provider_rows_and_cites_artifact_keys() -> None:
    async def scenario() -> dict[str, Any]:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)                  # the module's workspace/brand/run seeding
            storage = _MemoryStorage()
            artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=conn_session_factory(conn))
            transport = _scripted_exa_transport()       # a completed agent run + two deep-reasoning replies
            def exa_factory(*, run_id: UUID, step_label: str) -> SpendingClient[Any]:
                spend = build_buffered_caller(transport=transport, now=lambda: datetime.now(UTC))
                return SpendingClient(surface=ExaClient(spend.caller, SecretStr("k")), spend=spend)
            handler = OnboardingRunWorkHandler(
                settings=Settings(_env_file=None),
                conn_factory=conn_session_factory(conn),
                artifacts=artifacts,
                exa=exa_factory,
                client_binder=None,
                synthesis=None,
                clock=lambda: date(2026, 9, 14),
            )
            await handler.handle(_work_context(seeded.run_id))
            rows = (
                await conn.execute(
                    text(
                        "SELECT provider, operation, label, extras_json->>'lane' AS lane, "
                        " project_id, entity_research_job_id, response_artifact_key "
                        "FROM provider_call_ledger WHERE workspace_id = :ws AND phase = 'result' "
                        "ORDER BY recorded_at"
                    ),
                    {"ws": seeded.workspace_id},
                )
            ).mappings().all()
            steps = (
                await conn.execute(
                    text("SELECT kind, raw_artifact_key FROM onboarding_step WHERE run_id = :r"),
                    {"r": seeded.run_id},
                )
            ).mappings().all()
            return {"rows": [dict(r) for r in rows], "steps": [dict(s) for s in steps]}

    got = run_async(scenario())
    assert got["rows"], "no provider rows landed"
    assert {r["lane"] for r in got["rows"]} == {"onboarding"}
    assert all(r["project_id"] is None for r in got["rows"])
    assert {str(r["entity_research_job_id"]) for r in got["rows"]} == {str(seeded.run_id)}
    keys = {r["response_artifact_key"] for r in got["rows"] if r["response_artifact_key"]}
    assert keys, "raw bodies did not reach the artifact store"
    cited = {s["raw_artifact_key"] for s in got["steps"] if s["raw_artifact_key"]}
    assert cited and cited <= keys, f"steps cite {cited}, drained {keys}"
```

Use the module's own seeding helper, work-context builder and scripted-transport helper names (read the top of the file; the DB test already composes `DurableAgentArtifactStore` at `:49-52` and a `FakeExa` at `:56`). If the module has no scripted Exa transport, build one with `ScriptedJsonTransport` from `tests/arv2/conftest.py` replaying: agent-run create → `{"id": "run-1", "status": "completed", "output": {...schema-valid...}}`, then the two deep-reasoning bodies the lineup expects (copy the response shapes from `tests/arv2/test_exa_client*.py`).

- [ ] **Step 3: Run both to verify they fail**

Run: `set -a; source .env; set +a; uv run pytest tests/arv2/test_onboarding_driver.py tests/arv2/test_onboarding_driver_db.py -v -k "no_spend or lands_its_provider_rows"`
Expected: FAIL (`AttributeError: 'SpendingClient' object has no attribute 'agent_run'` from the driver, then the DB assertion).

- [ ] **Step 4: Change the driver**

In `platform/api/clue_api/arv2/onboarding_driver.py`:

Imports: add `from clue_api.arv2.provider_ledger import BufferedCaller, DrainReport, LedgerStamp, SpendingClient, build_buffered_caller`; remove `FileRawSink`, `JsonlLedger` if now unused.

`ExaClientFactory`:

```python
class ExaClientFactory(Protocol):
    """One client per step, because one :class:`ProviderCaller` per step is R1's rule: a halt
    latched by one step's provider must not silently stop another step's calls. The client comes
    with its buffered spend so the driver — which holds the connection — can land the rows."""

    def __call__(self, *, run_id: UUID, step_label: str) -> SpendingClient[ExaAgentSurface]: ...
```

Delete `build_onboarding_provider_caller`. Rewrite `build_onboarding_exa_client_factory`'s inner factory:

```python
    def factory(*, run_id: UUID, step_label: str) -> SpendingClient[ExaAgentSurface]:
        del run_id, step_label  # the stamp, not the folder, now says whose spend this is
        spend = build_buffered_caller(transport=HttpxTransport(), now=lambda: datetime.now(UTC))
        return SpendingClient(surface=ExaClient(spend.caller, api_key), spend=spend)
```

Constructor: `reconciler_factory: Callable[[UUID], SpendingClient[CatalogReconciler]] | None = None`.

Add the drain method next to `_settle`:

```python
    async def _land_spend(self, scope: _Scope, client: SpendingClient[Any]) -> DrainReport:
        """Land the rows one step's provider calls buffered — under the driver's connection, before
        the step settles, so the step can cite the artifact its raw body became. A client with no
        spend (an offline double) lands nothing."""
        if client.spend is None:
            return DrainReport(rows=0, artifacts=0, cost_usd=Decimal(0), credits=Decimal(0), media_seconds=0)
        async with self._connection() as conn:
            return await client.spend.drain(
                conn,
                stamp=LedgerStamp(
                    workspace_id=scope.workspace_id, lane="onboarding", job_id=scope.run_id
                ),
                artifacts=self._artifacts,
            )
```

In `_exa_step` (`:643`): `client = self._exa(run_id=scope.run_id, step_label=label)` stays; the call becomes `client.surface.agent_run`; wrap so the drain always runs:

```python
        try:
            run = await asyncio.to_thread(client.surface.agent_run, query=query, output_schema=schema,
                                          effort=effort, system_prompt=system_prompt, label=label)
        except Exception as error:
            await self._land_spend(scope, client)
            await self._settle(scope, step_id, document_id, _failed_step(error))
            return
        landed = await self._land_spend(scope, client)
        raw_key = (
            landed.artifact_keys.get(run.raw_refs[-1], run.raw_refs[-1]) if run.raw_refs else None
        )
```

and both `_StepOutcome(...)` constructions below use `raw_artifact_key=raw_key`.

In `_lineup` (`:738`): `client = self._exa(...)`; the two `client.deep_reasoning` calls become `client.surface.deep_reasoning`; add `await self._land_spend(scope, client)` right after the `try/except` around them completes (both on the success path and in the `except` before the step settles failed — mirror `_exa_step`).

In the catalog-sync block (`:833`): 

```python
                reconciler_client = (
                    self._reconciler_factory(scope.run_id)
                    if self._reconciler_factory is not None
                    else None
                )
                links = await self._sync(conn, ..., reconciler=None if reconciler_client is None else reconciler_client.surface)
```

and after the `_sync` call's enclosing `async with self._connection()` block closes: `if reconciler_client is not None: await self._land_spend(scope, reconciler_client)`.

In `fleet_main.py`, `_build_catalog_reconciler_factory`'s inner `factory`:

```python
    def factory(run_id: UUID) -> SpendingClient[CatalogReconciler]:
        del run_id
        spend = build_buffered_caller(transport=HttpxTransport(), now=lambda: datetime.now(UTC))
        reconciler = OpenRouterCatalogReconciler(
            caller_factory=lambda: spend.caller,
            api_key=key,
            model=settings.onboarding_reconcile_model,
            base_url=base_url,
        )
        return SpendingClient(surface=reconciler, spend=spend)
```

(Import `build_buffered_caller`, `SpendingClient` from `clue_api.arv2.provider_ledger` and `HttpxTransport` from `clue_api.arv2.transport`; drop the `build_onboarding_provider_caller` import.) `OpenRouterCatalogReconciler` itself is unchanged: `caller_factory` still returns a `ProviderCaller`; it now returns the one buffered caller the driver drains. Update its docstring line "R1's rule: a fresh caller per hop" to say the caller is the run's buffered one.

In `tests/arv2/test_onboarding_reconcile.py`, nothing changes functionally (`caller_factory=lambda: make_caller(transport)` still returns a `ProviderCaller`); run it to prove it.

- [ ] **Step 5: Run every onboarding test and the gates**

Run: `set -a; source .env; set +a; uv run pytest tests/arv2/test_onboarding_driver.py tests/arv2/test_onboarding_driver_db.py tests/arv2/test_onboarding_reconcile.py tests/arv2/test_onboarding_store_db.py tests/api -k "onboarding" -v --ignore-glob='*_live.py' && uv run ruff format platform/api/clue_api/arv2/onboarding_driver.py platform/api/clue_api/fleet_main.py platform/api/clue_api/arv2/onboarding_reconcile.py && uv run ruff check platform/api/clue_api && uv run mypy && uv run lint-imports`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add platform/api/clue_api/arv2/onboarding_driver.py platform/api/clue_api/fleet_main.py platform/api/clue_api/arv2/onboarding_reconcile.py tests/arv2/test_onboarding_driver.py tests/arv2/test_onboarding_driver_db.py
git commit -m "feat(onboarding): every provider call of the onboarding lane lands on provider_call_ledger

Each step's Exa client and the run's catalog reconciler come with a buffered caller the driver
drains under its own connection (lane=onboarding, job_id=run_id, raw bodies to the artifact
store); the step cites the artifact key its raw body became. The JSONL ledger under
arv2_raw_root/onboarding is no longer written."
```

---

### Task 4: The display prewrite lands its section rows

**Files:**
- Modify: `platform/api/clue_api/arv2/display/runner.py:407-431`
- Modify: `platform/api/clue_api/arv2/display/page.py:99-118, 380-420`
- Test: `tests/arv2/display/test_page_db.py`

**Interfaces:**
- Consumes: Task 2 `BufferedCaller`, `build_buffered_caller(raw_root=...)`, `LedgerStamp(lane="display")`.
- Produces: `LunaSectionRunner(caller, *, api_key, base_url, model, timeout_s, spend: BufferedCaller | None = None)` with a read-only `spend` property; `default_runner_factory` builds `build_buffered_caller(transport=HttpxTransport(), now=..., raw_root=Path(settings.arv2_raw_root) / "raw")` per runner (raw bodies stay on disk; the ledger buffers); `ensure_page` drains every written runner's spend under `conn` after the section writes and before the blocks are inserted. Both callers of `ensure_page` are unchanged.

- [ ] **Step 1: Write the failing test**

In `tests/arv2/display/test_page_db.py`, add a second factory beside `_factory` and one test:

```python
def _spending_factory(transport: RoutingTransport, raw_root: Path) -> Any:
    """The production factory's shape after slice 1b: bodies on disk, ledger buffered for Postgres."""

    def build() -> LunaSectionRunner:
        spend = build_buffered_caller(
            transport=transport, now=lambda: datetime.now(UTC), raw_root=raw_root
        )
        return LunaSectionRunner(
            spend.caller,
            api_key=SecretStr("test-key"),
            base_url="https://openrouter.ai/api/v1",
            model="openai/gpt-5.6-luna",
            timeout_s=30.0,
            spend=spend,
        )

    return build


def test_a_page_write_lands_one_ledger_row_per_written_section(tmp_path: Path) -> None:
    async def scenario() -> tuple[PageResult, list[dict[str, Any]]]:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)                     # the module's fixture
            transport = _transport(seeded)                 # the module's routing transport
            result = await ensure_page(
                conn,
                workspace_id=seeded.workspace_id,
                subject_kind="account",
                subject_id=str(seeded.account),
                page="overview",
                settings=SETTINGS,
                runner_factory=_spending_factory(transport, tmp_path / "raw"),
            )
            rows = (
                await conn.execute(
                    text(
                        "SELECT label, extras_json FROM provider_call_ledger "
                        "WHERE workspace_id = :ws AND phase = 'result' ORDER BY recorded_at"
                    ),
                    {"ws": seeded.workspace_id},
                )
            ).mappings().all()
            return result, [dict(r) for r in rows]

    result, rows = run_async(scenario())
    assert len(rows) == len(result.generated)
    assert {r["extras_json"]["lane"] for r in rows} == {"display"}
    assert {r["extras_json"]["section_key"] for r in rows} == set(result.generated)
    assert all(r["extras_json"]["raw_ref"].endswith(".json") for r in rows)  # bodies on disk
    assert all(r["extras_json"]["model"] for r in rows)                      # Task 1's extras
```

Use the module's real seeding and transport helper names (read `_contact_page` at `:170-183` and the fixtures above it). The transport's reply body (`:144-148`) carries `"usage": {"cost": CALL_COST}` — add `"model": "openai/gpt-5.6-luna"` to that dict so Task 1's `model` extra is non-empty.

- [ ] **Step 2: Run to verify it fails**

Run: `set -a; source .env; set +a; uv run pytest tests/arv2/display/test_page_db.py -v -k "lands_one_ledger_row"`
Expected: FAIL with `TypeError: unexpected keyword argument 'spend'`.

- [ ] **Step 3: Give the runner its spend and drain it in `ensure_page`**

`display/runner.py`:

```python
    def __init__(
        self,
        caller: ProviderCaller,
        *,
        api_key: SecretStr,
        base_url: str,
        model: str,
        timeout_s: float,
        spend: BufferedCaller | None = None,
    ) -> None:
        self._caller = caller
        ...
        self._spend = spend

    @property
    def spend(self) -> BufferedCaller | None:
        """The buffered ledger this runner's caller writes, for the page to land; ``None`` when
        the caller ledgers elsewhere (the offline tests' MemoryLedger)."""
        return self._spend
```

(import `BufferedCaller` from `clue_api.arv2.provider_ledger`.)

`display/page.py` `default_runner_factory`'s `build`:

```python
    def build() -> LunaSectionRunner:
        spend = build_buffered_caller(
            transport=HttpxTransport(), now=lambda: datetime.now(UTC), raw_root=root / "raw"
        )
        return LunaSectionRunner(
            spend.caller, api_key=key, base_url=base_url, model=model, timeout_s=timeout_s, spend=spend
        )
```

(update the docstring: "live HTTP, file raw sink, buffered ledger landed on `provider_call_ledger` by `ensure_page`"; drop the `JsonlLedger` import.)

In `ensure_page`, right after `written` is gathered (`:397`) and before `usable` is computed:

```python
    # Land every section's provider rows on this page's transaction, before the blocks that
    # were paid for by them. A runner with no spend (an offline double) lands nothing.
    for entry in written:
        if entry.runner.spend is not None:
            await entry.runner.spend.drain(
                conn, stamp=LedgerStamp(workspace_id=workspace_id, lane="display")
            )
```

(import `LedgerStamp` from `clue_api.arv2.provider_ledger`.) `PageResult.cost_usd` keeps its existing source (`runner.totals()`).

- [ ] **Step 4: Run the display tests and gates**

Run: `set -a; source .env; set +a; uv run pytest tests/arv2/display -v --ignore-glob='*_live.py' && uv run pytest tests/api/test_frontend_read_display_pages_db.py -v && uv run ruff format platform/api/clue_api/arv2/display/runner.py platform/api/clue_api/arv2/display/page.py && uv run ruff check platform/api/clue_api/arv2/display && uv run mypy`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/display/runner.py platform/api/clue_api/arv2/display/page.py tests/arv2/display/test_page_db.py
git commit -m "feat(display): a page write lands one provider_call_ledger row per written section

The runner carries its buffered ledger and ensure_page drains it on the page's own transaction
(lane=display; raw bodies stay on disk, the row keeps the file ref). Both callers — the
frontend read and the operator script — are unchanged."
```

---

### Task 5: The persona-evidence tool lands its row

**Files:**
- Modify: `platform/api/clue_api/onboarding_evidence_tools.py:104-182, 217-250`
- Test: `tests/api/test_onboarding_evidence_tools.py`

**Interfaces:**
- Consumes: Task 2 `SpendingClient`, `build_buffered_caller(raw_root=...)`, `LedgerStamp(lane="persona_evidence")`; `ToolContext.conn_factory` / `.workspace_id` / `.operation_id`.
- Produces: `ExaSearchEvidenceTool(*, enabled, client_factory: Callable[[str], SpendingClient[ExaAgentSurface]] | None)`; `invoke` drains `client.spend` through `ctx.conn_factory` after the search, with `LedgerStamp(workspace_id=ctx.workspace_id, lane="persona_evidence")`; the CallSpec label already carries `ctx.operation_id`, so the row is joinable to the tool invocation.

- [ ] **Step 1: Wrap the doubles and write the failing DB test**

In `tests/api/test_onboarding_evidence_tools.py`: import `SpendingClient` and change every `client_factory=lambda label: FakeExa(...)` (`:75` and any others) to `client_factory=lambda label: SpendingClient(surface=FakeExa(...))`. Append:

```python
pytestmark_db = pytest.mark.usefixtures("require_profiling_db")


@pytestmark_db
def test_a_search_lands_its_ledger_row_under_the_tools_workspace(tmp_path: Path) -> None:
    async def scenario() -> list[dict[str, Any]]:
        async with rollback_conn(seed_pack=False) as conn:
            ws = f"ws_evidence_{uuid4().hex[:8]}"
            await seed_workspace(conn, ws)
            transport = _scripted_deep_reasoning_transport()   # one 200 reply shaped like ExaClient expects
            def factory(label: str) -> SpendingClient[Any]:
                spend = build_buffered_caller(
                    transport=transport, now=lambda: datetime.now(UTC), raw_root=tmp_path / "raw"
                )
                return SpendingClient(surface=ExaClient(spend.caller, SecretStr("k")), spend=spend)
            tool = ExaSearchEvidenceTool(enabled=True, client_factory=factory)
            ctx = ToolContext(
                workspace_id=ws, actor="agent", conn_factory=conn_session_factory(conn),
                operation_id=operation_id_from_key("evidence:test:1"),
            )
            await tool.invoke(ExaSearchEvidenceInput(query="how do CFOs describe close pain", num_results=3), ctx)
            return [
                dict(r) for r in (
                    await conn.execute(
                        text(
                            "SELECT provider, operation, label, extras_json FROM provider_call_ledger "
                            "WHERE workspace_id = :ws AND phase = 'result'"
                        ),
                        {"ws": ws},
                    )
                ).mappings().all()
            ]

    rows = run_async(scenario())
    assert len(rows) == 1 and rows[0]["provider"] == "exa"
    assert rows[0]["extras_json"]["lane"] == "persona_evidence"
    assert "exa_search_evidence" in rows[0]["label"]
```

Build `_scripted_deep_reasoning_transport()` from the deep-reasoning reply shape the Exa client tests use (`tests/arv2/test_exa_client*.py`, the `deep_reasoning` case) with `ScriptedJsonTransport` from `tests/arv2/conftest.py`. Imports: `rollback_conn`, `conn_session_factory` from `tests.profiling.conftest`; `run_async` from `tests.db.conftest`; `seed_workspace` from `tests._workspace`; `ExaClient` from `clue_api.arv2.exa_client`; `build_buffered_caller`, `SpendingClient` from `clue_api.arv2.provider_ledger`.

- [ ] **Step 2: Run to verify it fails**

Run: `set -a; source .env; set +a; uv run pytest tests/api/test_onboarding_evidence_tools.py -v`
Expected: the new test FAILS (`AttributeError: 'SpendingClient' object has no attribute 'deep_reasoning'`); the wrapped existing tests also fail the same way until Step 3.

- [ ] **Step 3: Change the tool**

In `onboarding_evidence_tools.py`: import `LedgerStamp`, `SpendingClient`, `build_buffered_caller` from `clue_api.arv2.provider_ledger`; drop `FileRawSink`, `JsonlLedger`, `ProviderCaller` imports if unused.

Constructor type: `client_factory: Callable[[str], SpendingClient[ExaAgentSurface]] | None`.

`invoke`:

```python
        client = self._client_factory(label)
        result = await asyncio.to_thread(
            lambda: client.surface.deep_reasoning(
                system_prompt=PERSONA_EVIDENCE_SYSTEM_PROMPT,
                query=inputs.query,
                output_schema=persona_evidence_output_schema(),
                num_results=inputs.num_results,
                include_domains=list(inputs.include_domains) or None,
                label=label,
            )
        )
        if client.spend is not None:
            # The row lands under the tool's own connection seam, in the workspace that invoked it.
            async with ctx.conn_factory() as conn:
                await client.spend.drain(
                    conn, stamp=LedgerStamp(workspace_id=ctx.workspace_id, lane="persona_evidence")
                )
```

Update the class docstring's "its only durable trace is the ARV2 raw record and ledger row" to say the ledger row is on `provider_call_ledger`. In `build_onboarding_evidence_tools`, `build_client`:

```python
        def build_client(label: str) -> SpendingClient[ExaAgentSurface]:
            # One caller per invocation: ProviderCaller's totals/latch are unlocked mutable state.
            spend = build_buffered_caller(
                transport=HttpxTransport(),
                now=lambda: datetime.now(UTC),
                raw_root=root / label.replace(":", "_"),
            )
            return SpendingClient(surface=ExaClient(spend.caller, secret), spend=spend)
```

- [ ] **Step 4: Run the tests and gates**

Run: `set -a; source .env; set +a; uv run pytest tests/api/test_onboarding_evidence_tools.py tests/api/test_toolbelt_wiring*.py -v --ignore-glob='*_live.py' && uv run ruff format platform/api/clue_api/onboarding_evidence_tools.py && uv run ruff check platform/api/clue_api/onboarding_evidence_tools.py && uv run mypy && uv run lint-imports`
Expected: all PASS (if no `test_toolbelt_wiring*` file exists, run `uv run pytest tests/api -k "toolbelt and registry" --ignore-glob='*_live.py'` for the registry-shape guard).

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/onboarding_evidence_tools.py tests/api/test_onboarding_evidence_tools.py
git commit -m "feat(toolbelt): exa_search_evidence lands its provider_call_ledger row under the invoking workspace

The tool drains its buffered caller through ctx.conn_factory after the search (lane=
persona_evidence; the label carries the operation id). Raw bodies stay on disk."
```

---

### Task 6: The `.env.example` comment tells the truth about the raw root

**Files:**
- Modify: `.env.example:145-147`

**Interfaces:** none.

- [ ] **Step 1: Rewrite the comment**

Replace lines 145-146 with:

```
# Raw request/response bodies for the display prewrite and the persona-evidence tool are written
# here (the onboarding, research and discovery lanes persist theirs to the artifact store). Since
# lane 3 slice 1b every ledger row lands in provider_call_ledger; no JSONL ledger is written.
```

Keep `CLUE_ARV2_RAW_ROOT=.artifacts/arv2` unchanged. Mirror the same three lines in the local `.env` if it carries the comment (parity rule: values unchanged, so nothing else moves).

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "docs(env): CLUE_ARV2_RAW_ROOT holds raw bodies only; the ledger is Postgres since slice 1b"
```

---

### Task 7: The cost read stops naming what is now covered

**Files:**
- Modify: `platform/projections/clue_projections/cost.py` (`NOT_COVERED`, module docstring)
- Test: `tests/projections/test_cost_db.py::test_not_covered_names_every_ledger_this_read_cannot_see`

**Interfaces:**
- Produces: `NOT_COVERED` becomes exactly:

```python
NOT_COVERED: tuple[str, ...] = (
    "design subsystem providers (text-to-image, ad-DNA model): no ledger rows yet (R12 hold)",
    "conversation-turn model calls recorded before agent_model_call.cost_usd existed: blank, "
    "counted as unpriced",
    "JSONL ledgers written before lane 3 slice 1b (onboarding / display / persona evidence history "
    "under CLUE_ARV2_RAW_ROOT): on disk, not imported",
)
```

- [ ] **Step 1: Update the test first**

In `tests/projections/test_cost_db.py`, replace the body of `test_not_covered_names_every_ledger_this_read_cannot_see` with:

```python
    _, report = _report()
    text_ = " ".join(report.not_covered)
    for word in ("design", "before", "JSONL"):
        assert word in text_
    assert "onboarding lane:" not in text_   # covered since slice 1b
```

- [ ] **Step 2: Run to verify it fails**

Run: `set -a; source .env; set +a; uv run pytest tests/projections/test_cost_db.py -v -k not_covered`
Expected: FAIL on the `"onboarding lane:" not in text_` assertion.

- [ ] **Step 3: Change the constant and the docstring**

Replace `NOT_COVERED` with the tuple above. In the module docstring, replace the paragraph starting "What this read cannot see" with:

```
What this read cannot see is named in ``not_covered`` on every report: the design subsystem's
own providers are held (design note R12); turn rows before the cost columns are blank; and the
JSONL ledgers the onboarding, display and persona-evidence callers wrote before slice 1b stay on
disk as history. Since slice 1b every ``ProviderCaller`` lands on ``provider_call_ledger``, with
``extras_json.lane`` naming the workflow (account_research / discovery / onboarding / display /
persona_evidence).
```

- [ ] **Step 4: Run the projections tests and the no-write guard**

Run: `set -a; source .env; set +a; uv run pytest tests/projections/test_cost_db.py tests/projections/test_no_write_sql_guard.py tests/projections/test_cost_cli.py -v && uv run ruff format platform/projections/clue_projections/cost.py && uv run ruff check platform/projections && uv run mypy`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add platform/projections/clue_projections/cost.py tests/projections/test_cost_db.py
git commit -m "feat(projections): the cost read's not_covered list shrinks to what is still true after slice 1b"
```

---

### Task 8: Live proof on the lane stack

**Files:**
- Create: `_memory/2026-09-14-lane3-slice1b-jsonl-ledgers.md`

**Interfaces:** consumes everything above on the lane stack (`./scripts/dev_stack_san_salvador.sh up|down|status`; frontend :3020).

- [ ] **Step 1: Restart the stack on the new code**

Run: `./scripts/dev_stack_san_salvador.sh down && ./scripts/dev_stack_san_salvador.sh up && ./scripts/dev_stack_san_salvador.sh status`
Expected: all processes up (workers staggered per the runbook note).

- [ ] **Step 2: Display prewrite — the cheap proof (cents)**

Pick one account with an existing overview page and force one section rewrite through the operator script, **not** in dry-run (dry-run rolls the transaction back, ledger rows included):

```bash
set -a; source .env; set +a
uv run python scripts/generate_arv2_display.py --workspace-id <ws> --account <account id or domain> --pages overview --force 2>&1 | tail -20
psql "$CLUE_DATABASE_URL" -c "
SELECT label, extras_json->>'lane' lane, extras_json->>'model' model, extras_json->>'prompt_tokens' in_tok,
       cost_usd, extras_json->>'raw_ref' raw_ref
FROM provider_call_ledger WHERE workspace_id = '<ws>' AND extras_json->>'lane' = 'display'
ORDER BY recorded_at DESC LIMIT 6;"
make cost-report ARGS="--workspace <ws>"
```

Expected: one `display-overview-<section>` row per rewritten section with `lane=display`, a non-empty model, token counts, a `raw_ref` ending in `.json`; the cost report's provider lines now include those rows and its NOT COVERED list no longer names display.

- [ ] **Step 3: Onboarding and persona evidence — founder-triggered (dollars)**

An onboarding run costs real money (several Exa agent runs and deep-reasoning passes). It is the founder's to trigger. When one has run on the lane stack after this slice:

```bash
psql "$CLUE_DATABASE_URL" -c "
SELECT provider, operation, count(*), sum(cost_usd), bool_and(response_artifact_key IS NOT NULL) bodies_in_store
FROM provider_call_ledger WHERE extras_json->>'lane' = 'onboarding' AND entity_research_job_id = '<onboarding run id>'
GROUP BY 1,2;"
psql "$CLUE_DATABASE_URL" -c "
SELECT s.kind, s.raw_artifact_key, (a.storage_key IS NOT NULL) cites_a_real_artifact
FROM onboarding_step s LEFT JOIN artifact a ON a.storage_key = s.raw_artifact_key
WHERE s.run_id = '<onboarding run id>';"
```

Expected: rows for `exa` (agent runs, deep reasoning) and `openrouter` (`catalog-reconcile`) under the run id; every body in the artifact store; every step's `raw_artifact_key` resolving to an `artifact` row. For persona evidence: one `exa` row with `lane=persona_evidence` per evidence search the synthesis turn made, under the invoking workspace. If the founder has not run one by close-out, record both as **owed** in the note, with these exact queries.

- [ ] **Step 4: Write the session note**

```markdown
# 2026-09-14 — Lane 3 slice 1b: JSONL ledgers onto Postgres — proven on the lane stack

Branch `lane3/slice1b-jsonl-ledgers`. Plan: `docs/superpowers/plans/2026-09-14-lane3-slice1b-jsonl-ledgers-onto-postgres.md`.
Commits: <the seven>.

## What landed
- `openrouter_cost_reader` extras: model + prompt/completion/cached tokens on every OpenRouter row.
- `LedgerStamp(workspace_id, lane, project_id=None, project_run_id=None, job_id=None)`; every row's
  `extras_json.lane`; ledger-only drains keep `extras_json.raw_ref`; `DrainReport.artifact_keys`;
  `BufferedCaller` / `build_buffered_caller` / `SpendingClient`.
- Onboarding lane (Exa steps + catalog reconcile) drains under the driver's connection, bodies to
  the artifact store, steps cite artifact keys. Display prewrite drains per page on its transaction.
  `exa_search_evidence@1` drains through `ctx.conn_factory`. No JSONL ledger is written anywhere.
- `NOT_COVERED` on the cost read shrinks to: design providers (R12), pre-cost-column turn rows,
  pre-1b JSONL history.

## Proof
- Display: <rows> for <account>, lane=display, model=<…>, in_tok=<…>; cost-report before/after.
- Onboarding: <run id> — <rows by provider/operation>; steps cite artifacts: <yes/OWED>.
- Persona evidence: <row / OWED>.
- Tests: <counts per file>; gates: ruff / mypy / lint-imports.

## Not done here
- Importing pre-1b JSONL history (on disk under CLUE_ARV2_RAW_ROOT) — deliberately not; the read says so.
- Display raw bodies and evidence raw bodies still on disk (no artifact store on those paths);
  the row keeps the file ref. Move them to the artifact store when the frontend read app gains
  one in scope (it has `evidence_storage`; `DurableAgentArtifactStore` needs a conn_factory too).
- Lane 3 slice 2 (roots: OTel + Sentry + traceparent) is next per the design note §9.
```

- [ ] **Step 5: Commit**

```bash
git add _memory/2026-09-14-lane3-slice1b-jsonl-ledgers.md
git commit -m "docs(memory): lane 3 slice 1b proven on the lane stack (onboarding proof owed if not run)"
```

---

### Task 9: Design note and lane index

**Files:**
- Modify: `docs/superpowers/specs/2026-09-14-telemetry-and-cost-observability-design.md` (§3 row, §5.5, §9)
- Modify: `docs/superpowers/plans/2026-09-13-lane-plan-index.md` (Lane 3 table row 1b)

- [ ] **Step 1: Design note**

§3 "Onboarding / display / evidence spend" row → State: `Landed on provider_call_ledger since slice 1b (lane=onboarding / display / persona_evidence in extras_json); raw bodies to the artifact store on the onboarding fleet path, on disk (file ref in extras) for display and evidence.`

§5.5: in the `not_covered` sentence replace "the onboarding lane, the display prewrite and the persona-evidence tool (JSONL ledgers on disk — **slice 1b** routes them to the Postgres ledger)" with "the JSONL history those three lanes wrote before slice 1b (on disk, not imported)"; add after the bullet list: `Every ledger row carries \`extras_json.lane\` (slice 1b), so "which workflow is expensive" is a filter on the provider lines.`

§9 item 1b → append `**Done 2026-09-14** (plan \`2026-09-14-lane3-slice1b-jsonl-ledgers-onto-postgres.md\`).`

- [ ] **Step 2: Lane index**

Row `1b` → `| 1b | \`2026-09-14-lane3-slice1b-jsonl-ledgers-onto-postgres.md\` | onboarding / display / persona-evidence callers land on \`provider_call_ledger\`; \`extras_json.lane\`; OpenRouter rows carry model + usage | 1 |`

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-09-14-telemetry-and-cost-observability-design.md docs/superpowers/plans/2026-09-13-lane-plan-index.md
git commit -m "docs(lane3): design note and lane index record slice 1b"
```

---

## Self-review

**Spec coverage.** §9 slice 1b "route the onboarding lane, the display prewrite and the persona-evidence tool to `provider_call_ledger`" → Tasks 3, 4, 5 over the substrate of Task 2. The slice 1 note's second assignment to 1b ("`chat/completions` rows carry no model or usage extras; fix belongs to those writers' CallSpec extras") → Task 1, fixed once in the reader rather than per writer, which every writer already uses. R10 (every provider through `ProviderCaller`) → no new write path; R11/R12 → no legacy or design file touched. §5.5's `not_covered` honesty → Task 7 keeps the list true rather than emptying it. §9 "each slice closes with a live proof" → Task 8, with the paid proof marked as the founder's and recorded as owed if not run.

**Placeholders.** Three places name "the module's fixture / helper" (Task 3 Step 1–2, Task 4 Step 1, Task 5 Step 1) because those test files' seeding helpers exist and must be reused rather than re-declared; each names the file and line range to read. No "TBD" or "handle edge cases" anywhere.

**Type consistency.** `LedgerStamp(workspace_id, lane, project_id=None, project_run_id=None, job_id=None)` is used identically in Tasks 2–5. `SpendingClient(surface=..., spend=...)` and `BufferedCaller.drain(conn, *, stamp, artifacts=None)` are defined in Task 2 and consumed unchanged in Tasks 3–5. `DrainReport.artifact_keys` is produced in Task 2 and read in Task 3. `build_buffered_caller(*, transport, now, raw_root=None, ...)` is called with `raw_root=None` (onboarding, bodies to artifacts) and with a path (display, evidence, bodies to disk), matching the both-or-neither rule enforced in `drain_provider_calls`.
