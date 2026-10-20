# Discovery Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verified discovery rows land on the project's Target accounts tab while the Exa webset is still running, with a spinner on the tab and the tab opening itself at launch.

**Architecture:** The discovery driver lists the webset's items on every poll tick and verifies each new item in a bounded pool (one shared semaphore caps the Exa Answer calls in flight, and the gate questions of one candidate are issued together), landing each candidate in its own transaction as today. A new workspace-scoped read serves the project's latest discovery run; the frontend polls it every 5 s while a run is live, refetches the tab's rows on each tick, shows a spinner on the tab label, and opens the Target accounts surface when the chat stream delivers the completed launch tool part.

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy async / asyncio (backend, `platform/api/clue_api/arv2`), pytest (offline fakes + lane-DB suites), Next.js App Router / TypeScript / Zod / node:test (`apps/frontend`).

**Spec:** `docs/superpowers/specs/archive/2026-09-12-discovery-streaming-design.md`

## Global Constraints

- A row appears only when Exa found the company **and** Exa Answer verified it against every ICP gate (founder ruling 2026-09-12). Nothing else about what discovery writes changes.
- Polling on both ends. No Exa webhooks.
- The tab shows the climbing account count plus a spinner in its label while a run is live — **no other new UI** (founder ruling 2026-09-12; "dummy frontend is presentation truth").
- Every new env flag appears in `.env.example` with its default in the same commit; the lane `.env` stays at parity (CLAUDE.md parity rule).
- ARV2 tables are the only truth for the new read (ruling 2026-09-09).
- Never run `make check` or broad pytest with real keys sourced. Offline suites run without `.env`; DB suites run only against the lane DB (`set -a; source .env; set +a` then the named test files) with `-p no:cacheprovider`.
- Commit messages carry no AI attribution. Never push.
- Frontend gates: `cd apps/frontend && npm test && npm run lint && npx tsc --noEmit -p .` (50 pre-existing tsc errors is the baseline; no new ones) and `npm run build` at the end.

---

## File map

| File | Responsibility |
|---|---|
| `libs/clue-config/clue_config/settings.py` | new `arv2_discovery_verify_concurrency` setting |
| `.env.example` | `CLUE_ARV2_DISCOVERY_VERIFY_CONCURRENCY=4` |
| `tests/arv2/test_settings.py` | the setting's default and parity |
| `platform/api/clue_api/arv2/discovery_store.py` | `record_discovery_progress` (mid-run counters) |
| `tests/arv2/test_discovery_store_db.py` | its DB test |
| `platform/api/clue_api/arv2/discovery_driver.py` | the watch loop, the pool, parallel gates, per-tick counters |
| `tests/arv2/test_discovery_driver.py` | offline tests for the above |
| `tests/arv2/test_discovery_driver_db.py` | DB proof under concurrency (routed transport) |
| `platform/api/clue_api/frontend_read/contract_v1.py` | `DiscoveryRunStatusV1` response model |
| `platform/api/clue_api/frontend_read/discovery_status.py` | `GET /frontend/v1/projects/{project_id}/discovery/current` |
| `platform/api/clue_api/frontend_read/app.py` | registers the route |
| `tests/api/test_frontend_read_discovery_status.py` | DB test for the read |
| `apps/frontend/src/features/accounts/model/discovery-status.ts` | Zod schema + `discoveryRunLive` rule |
| `apps/frontend/src/features/accounts/model/discovery-status.test.ts` | rule tests |
| `apps/frontend/src/features/accounts/data/discovery-status.repository.ts` | `getDiscoveryStatus(projectId)` over `fetchRead` |
| `apps/frontend/src/app/api/projects/[projectId]/discovery/route.ts` | BFF route |
| `apps/frontend/src/app/api/projects/discovery-route.test.ts` | BFF route test (one segment above, per the `[segment]` glob pitfall) |
| `apps/frontend/src/features/chat-shell/model/discovery-launch-signal.ts` | pure rule: which transcript tool part means "discovery launched" |
| `apps/frontend/src/features/chat-shell/model/discovery-launch-signal.test.ts` | its tests |
| `apps/frontend/src/features/accounts/hooks/use-discovery-status.ts` | polling hook |
| `apps/frontend/src/features/chat-shell/components/chat-surface.tsx` | owns the hook; opens the surface on the signal; passes busy + refresh token down |
| `apps/frontend/src/features/chat-shell/components/artifact-stage.tsx` | pass-through props |
| `apps/frontend/src/features/chat-shell/components/artifact-tabs.tsx` | the spinner |
| `apps/frontend/src/features/chat-shell/components/chat-shell.module.css` | the spinner's rotation |
| `apps/frontend/src/features/accounts/components/project-target-accounts.tsx` | refetch on token change |
| `apps/frontend/src/features/chat-shell/model/chat-shell-contract.test.ts` | source-contract tests for the wiring |
| `apps/frontend/docs/api-contracts/accounts.md` | contract note |

---

### Task 1: The concurrency setting

**Files:**
- Modify: `libs/clue-config/clue_config/settings.py` (after `arv2_discovery_websets_usd_per_credit`, ~line 389)
- Modify: `.env.example` (after `CLUE_ARV2_DISCOVERY_WEBSETS_USD_PER_CREDIT=0.00449`, ~line 183)
- Modify: `.env` (same line; git-ignored — parity)
- Test: `tests/arv2/test_settings.py`

**Interfaces:**
- Produces: `Settings.arv2_discovery_verify_concurrency: int` (default 4, `ge=1`), env `CLUE_ARV2_DISCOVERY_VERIFY_CONCURRENCY`.

- [ ] **Step 1: Write the failing tests**

In `tests/arv2/test_settings.py`, add `"arv2_discovery_verify_concurrency"` to the `ARV2_DISCOVERY_SETTINGS` tuple, and inside `test_discovery_settings_defaults_and_env_names` add after the `arv2_discovery_websets_usd_per_credit` assertion:

```python
    # One cap for every Answer call a run has in flight (spec §2): candidates verify in a pool
    # and one candidate's gates are asked together, all under this semaphore.
    assert settings.arv2_discovery_verify_concurrency == 4
```

and after `monkeypatch.setenv("CLUE_ARV2_DISCOVERY_CRITERIA_GATE_KEYS", "geography")`:

```python
    monkeypatch.setenv("CLUE_ARV2_DISCOVERY_VERIFY_CONCURRENCY", "2")
```

and after `assert loaded.arv2_discovery_criteria_gate_keys == "geography"`:

```python
    assert loaded.arv2_discovery_verify_concurrency == 2
```

In `test_every_discovery_setting_is_in_env_example`, add `"CLUE_ARV2_DISCOVERY_VERIFY_CONCURRENCY=4"` to the tuple.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/arv2/test_settings.py -q -p no:cacheprovider`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'arv2_discovery_verify_concurrency'`, and the env-example assertion fails.

- [ ] **Step 3: Add the setting and the env lines**

In `settings.py`, directly after the `arv2_discovery_websets_usd_per_credit` field:

```python
    #: How many Exa Answer calls one discovery run may have in flight while verifying (spec
    #: 2026-09-12 §2). One semaphore serves both levels: candidates verify in a pool, and one
    #: candidate's gate questions are asked together. ``1`` reproduces the serial order the R4
    #: DB proof scripts by position. Env: ``CLUE_ARV2_DISCOVERY_VERIFY_CONCURRENCY``.
    arv2_discovery_verify_concurrency: int = Field(default=4, ge=1)
```

In `.env.example`, after the `CLUE_ARV2_DISCOVERY_WEBSETS_USD_PER_CREDIT=0.00449` line:

```
# Exa Answer calls one discovery run may have in flight while verifying (candidate pool + one
# candidate's gates asked together). 1 = the serial order of the first R4 runs.
CLUE_ARV2_DISCOVERY_VERIFY_CONCURRENCY=4
```

Add the same `CLUE_ARV2_DISCOVERY_VERIFY_CONCURRENCY=4` line to the lane `.env` at the same place (it is git-ignored; this keeps parity).

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/arv2/test_settings.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add libs/clue-config/clue_config/settings.py .env.example tests/arv2/test_settings.py
git commit -m "feat(arv2 r4): CLUE_ARV2_DISCOVERY_VERIFY_CONCURRENCY — the cap on Answer calls a discovery run has in flight"
```

---

### Task 2: Mid-run progress on the run row

**Files:**
- Modify: `platform/api/clue_api/arv2/discovery_store.py` (after `record_relaxed_search`, before `finish_discovery_run`, ~line 363)
- Test: `tests/arv2/test_discovery_store_db.py`

**Interfaces:**
- Produces: `async def record_discovery_progress(conn, *, run_id: UUID, found_strict: int, found_relaxed: int, analyzed: int) -> None` — updates the three counters on an `in_progress` run, never status, receipt or `finished_at`.

- [ ] **Step 1: Write the failing test**

Append to `tests/arv2/test_discovery_store_db.py` (import `record_discovery_progress` in the existing import block):

```python
def test_progress_updates_counters_without_landing_the_run() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn)
            row = _run(project)
            assert await create_discovery_run(conn, row) is True
            assert await begin_discovery_run(conn, run_id=row.run_id) is not None
            await record_discovery_progress(
                conn, run_id=row.run_id, found_strict=7, found_relaxed=0, analyzed=120
            )
            mid = await read_discovery_run(conn, run_id=row.run_id)
            assert mid is not None
            assert (mid.found_strict, mid.found_relaxed, mid.analyzed) == (7, 0, 120)
            assert mid.status == "in_progress"
            assert mid.finished_at is None and mid.receipt is None
            # A later tick only moves the numbers forward; landing still owns status + receipt.
            await record_discovery_progress(
                conn, run_id=row.run_id, found_strict=12, found_relaxed=3, analyzed=300
            )
            later = await read_discovery_run(conn, run_id=row.run_id)
            assert later is not None
            assert (later.found_strict, later.found_relaxed, later.analyzed) == (12, 3, 300)
    run_async(scenario())
```

- [ ] **Step 2: Run to verify it fails**

Run: `set -a; source .env; set +a; .venv/bin/pytest tests/arv2/test_discovery_store_db.py -q -p no:cacheprovider -k progress`
Expected: FAIL — `ImportError: cannot import name 'record_discovery_progress'`.

- [ ] **Step 3: Implement**

In `discovery_store.py`, add after `record_relaxed_search`:

```python
async def record_discovery_progress(
    conn: AsyncConnection,
    *,
    run_id: UUID,
    found_strict: int,
    found_relaxed: int,
    analyzed: int,
) -> None:
    """The §4 counters as they stand mid-run, written on every poll tick (spec 2026-09-12 §2).

    Only the numbers move. Status, the receipt and ``finished_at`` belong to
    :func:`finish_discovery_run`, so a reader that sees counters climbing on an ``in_progress``
    row is watching a run, not a run that landed twice.
    """
    await conn.execute(
        text(
            "UPDATE arv2_discovery_run SET found_strict = :found_strict, "
            " found_relaxed = :found_relaxed, analyzed = :analyzed WHERE run_id = :run_id"
        ),
        {
            "found_strict": int(found_strict),
            "found_relaxed": int(found_relaxed),
            "analyzed": int(analyzed),
            "run_id": run_id,
        },
    )
```

Add `"record_discovery_progress"` to the module's `__all__` if one exists (check with `grep -n __all__ platform/api/clue_api/arv2/discovery_store.py`); otherwise nothing else.

- [ ] **Step 4: Run to verify it passes**

Run: `set -a; source .env; set +a; .venv/bin/pytest tests/arv2/test_discovery_store_db.py -q -p no:cacheprovider`
Expected: PASS (whole file).

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/discovery_store.py tests/arv2/test_discovery_store_db.py
git commit -m "feat(arv2 r4): record_discovery_progress — the run's counters move on every poll tick"
```

---

### Task 3: One semaphore over verification hops; a candidate's gates asked together

**Files:**
- Modify: `platform/api/clue_api/arv2/discovery_driver.py` — `_RunState` (~line 205), `_compose` (~line 365), `_verify_gates` (~line 737), `_answer` (~line 761), `_verify_website` (~line 710)
- Test: `tests/arv2/test_discovery_driver.py`

**Interfaces:**
- Consumes: `Settings.arv2_discovery_verify_concurrency` (Task 1).
- Produces: `_RunState.hops: asyncio.Semaphore` (created in `_compose`); `_verify_gates` issues its Answer calls with `asyncio.gather`; every verification hop (`_answer`, and the website hop inside `_verify_website`) runs under `async with state.hops`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/arv2/test_discovery_driver.py`. These need `import threading` and `import time` at the top of the file (add them to the stdlib import block).

```python
class _CountingExa(_FakeExa):
    """``answer`` that measures how many calls overlap — the pool's observable."""

    def __init__(self, respond: Callable[[str], ExaAnswerResult], *, hold_s: float = 0.05) -> None:
        super().__init__(respond)
        self._lock = threading.Lock()
        self._in_flight = 0
        self.max_in_flight = 0
        self._hold_s = hold_s

    def answer(self, query: str, **kwargs: Any) -> ExaAnswerResult:
        with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            time.sleep(self._hold_s)
            return super().answer(query, **kwargs)
        finally:
            with self._lock:
                self._in_flight -= 1


def _one_company_run(
    monkeypatch: pytest.MonkeyPatch, *, concurrency: int
) -> tuple[_CountingExa, _Store]:
    """A strict pass over one all-pass company, driven to completion."""
    run = _run_row(criteria_gate_keys=("geography", "stage"))
    store = _Store(run)
    exa = _CountingExa(
        _responder(
            {
                "Acme": _company_answers(
                    "Acme",
                    "acme.com",
                    {"geography": "pass", "stage": "pass", "hiring": "pass", "intent": "pass"},
                )
            }
        )
    )
    websets = _FakeWebsets(
        get_views=[_view()],
        items_results=[_items(_item("Acme", "https://acme.com"))],
    )
    handler, *_ = _handler(
        store,
        exa=exa,
        websets=websets,
        monkeypatch=monkeypatch,
        settings=Settings(_env_file=None, arv2_discovery_verify_concurrency=concurrency),
    )
    context = WorkContext(
        work_id=arv2_discovery_work_id(run.run_id),
        payload={"run_id": str(run.run_id), "workspace_id": WORKSPACE},
        lease=LeaseGeneration(0),
        stop_requested=asyncio.Event(),
        lease_lost=asyncio.Event(),
    )
    asyncio.run(handler.handle(context))
    return exa, store


def test_a_candidates_gates_are_asked_together_under_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exa, store = _one_company_run(monkeypatch, concurrency=4)
    # Four gates, one website ask; the gates overlapped (the website ask ran alone, first).
    assert len(exa.gate_queries()) == 4
    assert exa.max_in_flight >= 2
    landed = store.named("finish_discovery_run")[0]
    assert landed["status"] == "completed"


def test_a_cap_of_one_keeps_the_serial_order(monkeypatch: pytest.MonkeyPatch) -> None:
    exa, _store = _one_company_run(monkeypatch, concurrency=1)
    assert exa.max_in_flight == 1
    # Website first, then the gates in document order — the R4 DB proof's positional script.
    assert "registrable domain" in exa.queries[0]
    assert [rule for rule in (_RULES[k] for k in ("geography", "stage", "hiring", "intent"))] == [
        next(rule for rule in _RULES.values() if rule in query) for query in exa.gate_queries()
    ]
```

Check the `WorkContext` constructor arguments against the existing tests in this file (search `WorkContext(`) and match them exactly; the field names above follow the driver DB test.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/arv2/test_discovery_driver.py -q -p no:cacheprovider -k "gates_are_asked_together or cap_of_one"`
Expected: `test_a_candidates_gates_are_asked_together_under_the_cap` FAILS on `exa.max_in_flight >= 2` (today it is 1); the cap-of-one test passes already (that is fine — it pins the order).

- [ ] **Step 3: Implement**

In `_RunState`, add a field (after `cost_usd`):

```python
    #: The one cap on verification hops in flight (Task 3): candidates verify in a pool and a
    #: candidate's gates are asked together, all under this semaphore. Built in ``_compose``.
    hops: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(1))
```

In `_compose`, when constructing `_RunState(...)`, pass:

```python
            hops=asyncio.Semaphore(self._settings.arv2_discovery_verify_concurrency),
```

Replace `_verify_gates` with:

```python
    async def _verify_gates(
        self, state: _RunState, company_name: str, verified: str
    ) -> tuple[GateVerdict, ...]:
        """Every hard gate the document states — asked together, then guarded in document order.

        The verdicts are assembled only once every answer is back, so parallel questions change
        nothing about what is decided; the semaphore on ``_answer`` decides how many are in flight.
        """
        answers = await asyncio.gather(
            *(
                self._answer(
                    state,
                    query=gate_question(company_name, f"https://{verified}", gate),
                    output_schema=OUTPUT_SCHEMA,
                    label=f"discovery-{gate.key}-{verified}",
                )
                for gate in state.brief.gates
            )
        )
        return tuple(
            apply_guards(
                gate=gate,
                answer=result.answer,
                citations=result.citations,
                company_domain=verified,
                company_name=company_name,
                today=state.today,
            )
            for gate, result in zip(state.brief.gates, answers, strict=True)
        )
```

In `_answer`, wrap the hop:

```python
        async with state.hops:
            return await self._hop(
                state,
                lambda caller: self._clients.exa(caller).answer(
                    query,
                    system_prompt=prompt,
                    output_schema=output_schema,
                    model=model,
                    label=label,
                ),
            )
```

In `_verify_website`, the website question is also an Answer hop: find its `await self._hop(` call and wrap it the same way with `async with state.hops:`. (If `_verify_website` calls `self._answer`, nothing to change — check.)

- [ ] **Step 4: Run the whole offline driver suite**

Run: `.venv/bin/pytest tests/arv2/test_discovery_driver.py -q -p no:cacheprovider`
Expected: PASS. If any existing test asserts the exact *order* of `exa.queries` across gates, it still passes: with the default `Settings(_env_file=None)` the cap is 4, but the `_FakeExa` used by those tests answers instantly, so gather's task start order (document order) is the observed order. If one flips, set `arv2_discovery_verify_concurrency=1` on that test's `Settings` and say why in a comment.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/discovery_driver.py tests/arv2/test_discovery_driver.py
git commit -m "feat(arv2 r4): a candidate's gate questions are asked together, under one cap on verification hops in flight"
```

---

### Task 4: Verify as items arrive — the watch loop and the pool

**Files:**
- Modify: `platform/api/clue_api/arv2/discovery_driver.py` — `_RunState` (add `claimed`), `_strict_pass` (~line 427), `_resume_webset` (~line 461), `_poll`/`_read_items` (~lines 516–553), `_relaxed_pass` (~line 925), `_connection` docstring (~line 1118)
- Test: `tests/arv2/test_discovery_driver.py`

**Interfaces:**
- Consumes: `record_discovery_progress` (Task 2), `state.hops` (Task 3).
- Produces: `async def _watch_and_verify(self, state, webset_id, *, pass_: Pass) -> None` — polls to idle, lists items every tick, dispatches unclaimed items to a task pool, drains the pool after the final read, records progress every tick. `_RunState.claimed: set[str]` (item ids). `_strict_pass`, `_resume_webset(verify=True)` and `_relaxed_pass` all go through it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/arv2/test_discovery_driver.py`:

```python
def _two_tick_websets(first: WebsetItem, second: WebsetItem) -> _FakeWebsets:
    """Tick 1: running, one item listed. Tick 2: idle, both items listed (the first re-listed)."""
    return _FakeWebsets(
        get_views=[_view(status="running"), _view(status="idle")],
        items_results=[_items(first), _items(first, second)],
    )


def _all_pass(company: str, domain: str) -> dict[str, ExaAnswerResult]:
    return _company_answers(
        company, domain, {"geography": "pass", "stage": "pass", "hiring": "pass", "intent": "pass"}
    )


def test_items_verify_as_they_arrive_and_a_relisted_item_is_never_verified_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row(criteria_gate_keys=("geography", "stage"))
    store = _Store(run)
    exa = _FakeExa(_responder({"Acme": _all_pass("Acme", "acme.com"), "Bolt": _all_pass("Bolt", "bolt.com")}))
    acme, bolt = _item("Acme", "https://acme.com"), _item("Bolt", "https://bolt.com")
    websets = _two_tick_websets(acme, bolt)
    handler, _conn, _writer, _drain, accounts = _handler(
        store, exa=exa, websets=websets, monkeypatch=monkeypatch
    )
    context = WorkContext(
        work_id=arv2_discovery_work_id(run.run_id),
        payload={"run_id": str(run.run_id), "workspace_id": WORKSPACE},
        lease=LeaseGeneration(0),
        stop_requested=asyncio.Event(),
        lease_lost=asyncio.Event(),
    )
    asyncio.run(handler.handle(context))

    # Items were read on BOTH ticks (the running one and the idle one), not only after idle.
    assert [call for call, _ in websets.calls] == ["create", "get", "items", "get", "items"]
    # Acme was verified once although it was listed twice; Bolt once.
    assert [w["primary_domain"] for w in accounts.created] == ["acme.com", "bolt.com"]
    assert len(store.named("record_verdicts")) == 2
    # Progress was recorded on every tick, before the run landed.
    progress = store.named("record_discovery_progress")
    assert [p["found_strict"] for p in progress] == [1, 2]
    landed = store.named("finish_discovery_run")[0]
    assert (landed["found_strict"], landed["status"]) == (2, "completed")


def test_the_pool_never_exceeds_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    run = _run_row(criteria_gate_keys=("geography", "stage"))
    store = _Store(run)
    names = ["Acme", "Bolt", "Cove", "Dune", "Echo"]
    exa = _CountingExa(
        _responder({n: _all_pass(n, f"{n.lower()}.com") for n in names}), hold_s=0.02
    )
    websets = _FakeWebsets(
        get_views=[_view()],
        items_results=[_items(*(_item(n, f"https://{n.lower()}.com") for n in names))],
    )
    handler, *_ = _handler(
        store,
        exa=exa,
        websets=websets,
        monkeypatch=monkeypatch,
        settings=Settings(_env_file=None, arv2_discovery_verify_concurrency=2),
    )
    context = WorkContext(
        work_id=arv2_discovery_work_id(run.run_id),
        payload={"run_id": str(run.run_id), "workspace_id": WORKSPACE},
        lease=LeaseGeneration(0),
        stop_requested=asyncio.Event(),
        lease_lost=asyncio.Event(),
    )
    asyncio.run(handler.handle(context))
    assert exa.max_in_flight == 2
    assert len(store.named("record_verdicts")) == 5


def test_a_provider_halt_in_one_task_suspends_the_whole_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row(criteria_gate_keys=("geography", "stage"))
    store = _Store(run)

    def respond(query: str) -> ExaAnswerResult:
        if "Bolt" in query:
            raise ProviderHalted(provider="exa", reason_code="rate_limited", detail="429")
        return _responder({"Acme": _all_pass("Acme", "acme.com")})(query)

    exa = _FakeExa(respond)
    websets = _FakeWebsets(
        get_views=[_view()],
        items_results=[_items(_item("Acme", "https://acme.com"), _item("Bolt", "https://bolt.com"))],
    )
    handler, *_ = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)
    context = WorkContext(
        work_id=arv2_discovery_work_id(run.run_id),
        payload={"run_id": str(run.run_id), "workspace_id": WORKSPACE},
        lease=LeaseGeneration(0),
        stop_requested=asyncio.Event(),
        lease_lost=asyncio.Event(),
    )
    result = asyncio.run(handler.handle(context))
    landed = store.named("finish_discovery_run")[0]
    assert landed["status"] == "needs_review"
    assert landed["receipt"]["failure"] == "provider_halted"
    assert result.outcome == "needs_review"
```

Check `ProviderHalted`'s constructor in `platform/api/clue_api/arv2/errors.py` and match its keyword names; check the exact `receipt["failure"]` value the existing halt test asserts (search `PROVIDER_HALTED` in the test file) and use that constant.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/arv2/test_discovery_driver.py -q -p no:cacheprovider -k "as_they_arrive or never_exceeds or halt_in_one_task"`
Expected: the first fails on the `websets.calls` order (today: `create, get, get, items`), and on `record_discovery_progress` (the fake store has no such method → `AttributeError`). Add to `_Store`:

```python
    async def record_discovery_progress(self, conn: Any, **kwargs: Any) -> None:
        del conn
        self.events.append(("record_discovery_progress", kwargs))
```

Re-run: still FAIL on the call order and the progress list.

- [ ] **Step 3: Implement the watch loop**

In `_RunState` add:

```python
    #: Item ids this attempt has handed to the pool — claimed when a task is taken, never when it
    #: finishes, so a re-listed item on the next tick is not verified twice.
    claimed: set[str] = field(default_factory=set)
```

Replace the tail of `_strict_pass` (from `view = await self._poll(state, view.webset_id)` to the end) with:

```python
        await self._watch_and_verify(state, view.webset_id, pass_="strict")
```

Replace the tail of `_resume_webset` (from `view = await self._poll(state, webset_id)` to the end of the method) with:

```python
        log.info(
            "arv2.discovery_resume",
            run_id=str(state.run.run_id),
            webset_id=webset_id,
            already=len(state.seen),
        )
        await self._watch_and_verify(state, webset_id, pass_="resume")
```

Replace the tail of `_relaxed_pass` (from `view = await self._poll(state, webset_id)` to the end) with:

```python
        await self._watch_and_verify(state, webset_id, pass_="relaxed")
```

Add the new method after `_read_items`:

```python
    async def _watch_and_verify(
        self, state: _RunState, webset_id: str, *, pass_: Literal["strict", "relaxed", "resume"]
    ) -> None:
        """Poll the webset to ``idle`` and verify every new item on every tick (spec §2).

        Each tick lists the webset (a row is priced once per run, so re-listing costs nothing),
        hands every unclaimed item to a task, records the counters, and sleeps. On ``idle`` one
        last list catches stragglers, and the pool is drained before returning. ``pass_`` decides
        the candidate's recorded pass: a resume labels each item by the search that found it.

        Containment is per task (``_verify_contained``); ``ProviderHalted`` and the wall clock
        are not contained — the first of either cancels the pool and re-raises, so ``_run`` lands
        the run ``needs_review`` exactly as it does today.
        """
        tasks: set[asyncio.Task[None]] = set()

        def _label(item: WebsetItem) -> Pass:
            if pass_ == "resume":
                return "strict" if self._is_strict_item(state, item) else "relaxed"
            return pass_

        async def _tick(final: bool) -> None:
            items = await self._read_items(state, webset_id)
            strict = [item for item in items if self._is_strict_item(state, item)]
            if pass_ == "relaxed":
                fresh = [
                    item
                    for item in items
                    if (registrable_domain(item.url) or "") not in state.seen
                ]
                state.found_relaxed = max(state.found_relaxed, len(fresh))
            else:
                state.found_strict = max(state.found_strict, len(strict))
                if len(items) > len(strict):
                    state.found_relaxed = max(state.found_relaxed, len(items) - len(strict))
            for item in items:
                if item.item_id in state.claimed:
                    continue
                if pass_ == "relaxed" and (registrable_domain(item.url) or "") in state.seen:
                    continue
                state.claimed.add(item.item_id)
                tasks.add(
                    asyncio.create_task(self._verify_contained(state, item, pass_=_label(item)))
                )
            async with self._connection() as conn:
                await self._store.record_discovery_progress(
                    conn,
                    run_id=state.run.run_id,
                    found_strict=state.found_strict,
                    found_relaxed=state.found_relaxed,
                    analyzed=state.analyzed,
                )
            if final:
                await self._drain_pool(tasks)
            else:
                await self._reap(tasks)

        try:
            while True:
                if self._clock() > state.deadline:
                    raise _WallExceeded(
                        f"webset {webset_id} did not reach idle within "
                        f"{self._settings.arv2_discovery_wall_s}s"
                    )
                view = await self._hop(
                    state, lambda caller: self._clients.websets(caller).get(webset_id)
                )
                self._read_searches(state, view)
                if view.status == "idle":
                    await _tick(final=True)
                    return
                await _tick(final=False)
                await self._sleep(self._settings.arv2_discovery_poll_interval_s)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    @staticmethod
    async def _reap(tasks: set[asyncio.Task[None]]) -> None:
        """Surface a finished task's uncontained exception now, not at the end of the run."""
        done = {task for task in tasks if task.done()}
        tasks.difference_update(done)
        for task in done:
            if not task.cancelled() and task.exception() is not None:
                raise task.exception()  # type: ignore[misc]

    @staticmethod
    async def _drain_pool(tasks: set[asyncio.Task[None]]) -> None:
        """Wait for every task; the first uncontained exception cancels the rest and propagates."""
        if not tasks:
            return
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            if not task.cancelled() and task.exception() is not None:
                for other in tasks:
                    other.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise task.exception()  # type: ignore[misc]
        await asyncio.gather(*tasks)
        tasks.clear()
```

Add `Literal` to the `typing` import at the top of the module if absent. `_poll` becomes unused: delete it (and any test that referenced it directly — search `_poll` in the tests). Keep `_read_items` as is.

Update the `_connection` docstring to:

```python
        """A pooled connection per caller. Since 2026-09-12 candidates verify concurrently, each in
        its own transaction; the engine hands every task its own connection, so nothing here is
        shared between them."""
```

- [ ] **Step 4: Run the whole offline driver suite**

Run: `.venv/bin/pytest tests/arv2/test_discovery_driver.py -q -p no:cacheprovider`
Expected: PASS. Tests that asserted the old `create, get, get, items` order need their expectation updated to `create, get, items, get, items` (running then idle) — that is the behaviour change, state it in the test's comment. Tests scripting a single `get` view already return `idle` on the first tick and see `create, get, items`.

- [ ] **Step 5: Run ruff and mypy**

Run: `.venv/bin/ruff check platform/api/clue_api/arv2/discovery_driver.py tests/arv2/test_discovery_driver.py && .venv/bin/ruff format --check platform/api/clue_api/arv2 tests/arv2 && .venv/bin/mypy platform/api/clue_api/arv2/discovery_driver.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add platform/api/clue_api/arv2/discovery_driver.py tests/arv2/test_discovery_driver.py
git commit -m "feat(arv2 r4): discovery verifies items as Exa finds them — per-tick listing, a bounded pool, progress on the run row"
```

---

### Task 5: The DB proof under concurrency

**Files:**
- Modify: `tests/arv2/test_discovery_driver_db.py`

**Interfaces:**
- Consumes: the driver of Tasks 3–4; `settings_for` from `tests/arv2/icp_fixture.py`.

- [ ] **Step 1: Pin the existing positional scenario to the serial cap**

The existing end-to-end test scripts nine responses **by position** (`_OneCallPerHop`). Under the default cap of 4 the website asks of two candidates would race for the first two answers. Find where that test builds its `Settings` (search `settings_for(` in the file) and pass `arv2_discovery_verify_concurrency=1`, with this comment above it:

```python
    # The script below is positional (its docstring says why). One hop in flight keeps the order
    # it pins; the concurrent path is proven by the routed scenario further down.
```

If `settings_for` does not accept overrides, read `tests/arv2/icp_fixture.py::settings_for` and use `settings.model_copy(update={"arv2_discovery_verify_concurrency": 1})` on its result instead.

Run: `set -a; source .env; set +a; .venv/bin/pytest tests/arv2/test_discovery_driver_db.py -q -p no:cacheprovider`
Expected: PASS with the new item-listing order — if the script's `get`/`items` positions no longer match (`running` view now triggers an `items` read before the idle `get`), insert an empty items page `_json({"data": [], "hasMore": False})` after the first `_webset_body(status="running", ...)` response and keep the rest in order.

- [ ] **Step 2: Add a routed transport double and the concurrent scenario**

Append to the file:

```python
class _RoutedTransport:
    """A :class:`ScriptedTransport` per hop that picks its one response by what the request asks.

    Under a cap above one the order of provider calls is not a contract any more, so a positional
    script cannot describe the run. Each route is ``(needle, response)``; ``send`` consumes the
    first unconsumed route whose needle appears in the request body (or, for a bodiless GET, in
    the URL). Still one transport per hop, still the lane's one permitted double.
    """

    def __init__(self, routes: list[tuple[str, HttpResponse]]) -> None:
        self._routes = list(routes)

    def __call__(self) -> Any:
        routes = self._routes

        class _Transport(ScriptedTransport):
            def __init__(self) -> None:
                super().__init__([])

            def send(self, request: Any) -> HttpResponse:
                haystack = (request.body or b"").decode() + str(request.url)
                for index, (needle, response) in enumerate(routes):
                    if needle in haystack:
                        del routes[index]
                        return response
                raise AssertionError(f"no routed response for {haystack[:200]!r}")

        return _Transport()

    @property
    def remaining(self) -> int:
        return len(self._routes)


def _company_routes(name: str, domain: str) -> list[tuple[str, HttpResponse]]:
    quote = f"{name} closed a Series A in March 2025 and is hiring in Boston."
    news = f"https://{domain}/news"
    return [
        (
            f"registrable domain",  # the website ask; disambiguated by the name below
            _json(_answer_body({"website_domain": domain, "evidence_url": news}, citation_url=news, citation_text=quote)),
        ),
        (GEOGRAPHY_RULE, _json(_gate_answer(quote, news))),
        (STAGE_RULE, _json(_gate_answer(quote, news))),
    ]
```

The website ask's needle must include the company name so two companies' website answers cannot cross: replace the `"registrable domain"` needle with `f"{name}"` **and** keep the gate needles as `f"{name}"` + rule by joining: use `f"{name} {GEOGRAPHY_RULE}"`? No — Exa Answer bodies carry the query text, which names the company and quotes the rule, so use the needle `f"{name}"` for the website route and `f"{GEOGRAPHY_RULE}"`/`f"{STAGE_RULE}"` for the gates **but filter by name first**: implement `_Transport.send` as: find routes whose needle appears; among them prefer one whose `company` tag also appears. Concretely change the route tuples to three-tuples `(company, needle, response)` and match `company in haystack and needle in haystack`. Rewrite `_company_routes` accordingly:

```python
def _company_routes(name: str, domain: str) -> list[tuple[str, str, HttpResponse]]:
    quote = f"{name} closed a Series A in March 2025 and is hiring in Boston."
    news = f"https://{domain}/news"
    website = _json(
        _answer_body(
            {"website_domain": domain, "evidence_url": news}, citation_url=news, citation_text=quote
        )
    )
    return [
        (name, "registrable domain", website),
        (name, GEOGRAPHY_RULE, _json(_gate_answer(quote, news))),
        (name, STAGE_RULE, _json(_gate_answer(quote, news))),
    ]
```

and in `_Transport.send`: `for index, (company, needle, response) in enumerate(routes): if company in haystack and needle in haystack: ...`. The webset routes carry `("", "websets/v0/websets", ...)` needles: `(""` matches every haystack) — list them **first** in the order the driver polls: running view, empty items page, idle view, full items page, and make `send` scan routes in order so the poll sequence is consumed positionally while Answer routes are content-matched.

Then the scenario:

```python
def test_two_candidates_verify_concurrently_each_in_its_own_transaction() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await load_core_pack(conn)
            await load_arv2_pack(conn)
            fixture = await seed_icp_fixture(conn)
            routes: list[tuple[str, str, HttpResponse]] = [
                ("", "websets/v0/websets", _json(_webset_body(status="running", found=0, analyzed=0))),
                ("", "/items", _json({"data": [], "hasMore": False})),
                ("", "websets/v0/websets", _json(_webset_body(status="idle", found=2, analyzed=200))),
                (
                    "",
                    "/items",
                    _json(
                        {
                            "data": [
                                _item_body("itm-a", name="Alpha", url="https://alpha.com", employees=50),
                                _item_body("itm-b", name="Beta", url="https://beta.com", employees=60),
                            ],
                            "hasMore": False,
                        }
                    ),
                ),
                *_company_routes("Alpha", "alpha.com"),
                *_company_routes("Beta", "beta.com"),
            ]
            transport = _RoutedTransport(routes)
            settings = settings_for(fixture).model_copy(
                update={"arv2_discovery_verify_concurrency": 4}
            )
            handler = Arv2DiscoveryWorkHandler(
                settings=settings,
                conn_factory=_conn_factory_for(conn),
                storage=fixture.storage,
                artifacts=fixture.artifacts,
                clients=_LiveClientsForTest(settings),
                writer=LenientClaimWriter(lenient=True),
                transport_factory=transport,
                clock=_clock(),
                sleep=_no_sleep,
            )
            receipt = await launch_arv2_discovery(conn, fixture.request(), ...)
            # ^ copy the exact launch call the existing test makes (search `launch_arv2_discovery(`)
            result = await handler.handle(_context_for(receipt.run_id, fixture.workspace_id))
            assert result.outcome == "completed"
            candidates = await list_candidates(conn, run_id=receipt.run_id)
            assert sorted(c.domain for c in candidates) == ["alpha.com", "beta.com"]
            assert all(c.disposition == "pass" for c in candidates)
            assert transport.remaining == 0
    run_async(scenario())
```

Copy `_conn_factory_for`, `_context_for`, the `launch_arv2_discovery(...)` call and the `_LiveClientsForTest(...)` construction **verbatim from the existing test in this file** (they exist under those or similar names — search the file; do not invent them). The webset-creation POST also needs a route: add `("", "websets/v0/websets", <create body>)` as the very first route, copying the create response body the existing script uses.

- [ ] **Step 3: Run**

Run: `set -a; source .env; set +a; .venv/bin/pytest tests/arv2/test_discovery_driver_db.py -q -p no:cacheprovider`
Expected: PASS (both scenarios).

- [ ] **Step 4: Commit**

```bash
git add tests/arv2/test_discovery_driver_db.py
git commit -m "test(arv2 r4): the discovery DB proof under a concurrent cap — routed transport, two candidates in their own transactions"
```

---

### Task 6: The read — the project's current discovery run

**Files:**
- Modify: `platform/api/clue_api/frontend_read/contract_v1.py` (append)
- Create: `platform/api/clue_api/frontend_read/discovery_status.py`
- Modify: `platform/api/clue_api/frontend_read/app.py` (import + `register_discovery_status_route(router, conn_factory=conn_factory)` after `register_account_logo_route`)
- Test: `tests/api/test_frontend_read_discovery_status.py`

**Interfaces:**
- Produces: `GET /frontend/v1/projects/{project_id}/discovery/current` → `{"data": DiscoveryRunStatusV1 | null}` with `DiscoveryRunStatusV1 = {run_id, status, asked, found, verified, shown, started_at, finished_at}`.

- [ ] **Step 1: Write the failing test**

```python
"""``GET /frontend/v1/projects/{id}/discovery/current`` — the project's latest discovery run."""

from __future__ import annotations

from uuid import uuid4

import pytest

from clue_api.arv2.discovery_store import (
    CandidateRow,
    DiscoveryRunRow,
    begin_discovery_run,
    create_discovery_run,
    record_discovery_progress,
    record_verdicts,
    upsert_candidate,
)
from clue_api.frontend_read.app import FRONTEND_READ_PREFIX
from clue_core import ProjectPhase, ProjectRunId
from clue_research.durable.project_run import ensure_project_run
from tests._workspace import seed_project
from tests.claimstore.conftest import migrated_db, require_claimstore_db, rollback_conn  # noqa: F401
from tests.db.conftest import run_async

from .test_frontend_read_accounts_list import _app, _client

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

WS = "ws_discovery_status"


async def _run_for(conn, project) -> DiscoveryRunRow:  # noqa: ANN001
    project_run_id = uuid4()
    await ensure_project_run(
        conn,
        project_run_id=ProjectRunId(project_run_id),
        project_id=project.project_id,
        workspace_id=project.workspace_id,
        icp_key="clue-abm-buyers",
        icp_version=1,
        phase=ProjectPhase.DEEP,
    )
    row = DiscoveryRunRow(
        run_id=uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        brand_id=str(project.brand_id),
        project_run_id=project_run_id,
        icp_artifact_key="ws/abc",
        icp_artifact_sha256="b" * 64,
        icp_key="clue-abm-buyers",
        icp_version=1,
        requested_by_user_id="user-1",
        request_sha256=uuid4().hex * 2,
        target_count=20,
        strict_count=35,
        relaxed_enabled=True,
        criteria_gate_keys=("geography", "stage"),
    )
    assert await create_discovery_run(conn, row) is True
    return row


def test_none_then_the_latest_run_with_its_counts() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await seed_project(conn, WS)
            path = f"{FRONTEND_READ_PREFIX}/projects/{project.project_id}/discovery/current"
            headers = {"X-Workspace-Id": WS}
            async with _client(_app(conn)) as client:
                empty = await client.get(path, headers=headers)
            assert empty.status_code == 200 and empty.json()["data"] is None

            row = await _run_for(conn, project)
            assert await begin_discovery_run(conn, run_id=row.run_id) is not None
            await record_discovery_progress(
                conn, run_id=row.run_id, found_strict=5, found_relaxed=0, analyzed=90
            )
            for domain, disposition in (("a.com", "pass"), ("b.com", "unclear"), ("c.com", "pending")):
                candidate_id = await upsert_candidate(
                    conn,
                    CandidateRow(
                        candidate_id=uuid4(),
                        run_id=row.run_id,
                        workspace_id=WS,
                        project_id=project.project_id,
                        pass_="strict",
                        domain=domain,
                        websets_url=f"https://{domain}",
                        name=domain,
                        provider_snapshot={},
                    ),
                )
                if disposition != "pending":
                    await record_verdicts(
                        conn,
                        candidate_id=candidate_id,
                        verdicts=[],
                        fit=0.5,
                        disposition=disposition,
                        account_entity_id=None,
                    )
            async with _client(_app(conn)) as client:
                live = await client.get(path, headers=headers)
                other = await client.get(path, headers={"X-Workspace-Id": "ws_someone_else"})
            body = live.json()["data"]
            assert body["run_id"] == str(row.run_id)
            assert body["status"] == "in_progress"
            assert (body["asked"], body["found"], body["verified"], body["shown"]) == (None, 5, 2, 2)
            assert body["started_at"] is not None and body["finished_at"] is None
            # Another workspace never sees this project's run.
            assert other.status_code in (200, 404)
            if other.status_code == 200:
                assert other.json()["data"] is None
    run_async(scenario())
```

Check `record_verdicts`'s signature in `discovery_store.py` and pass exactly its keyword names (`account_entity_id` may be required non-null — if so, insert an account with `insert_account_entity` as the driver DB test does and pass its id). Check `seed_project`'s return shape in `tests/_workspace.py`.

- [ ] **Step 2: Run to verify it fails**

Run: `set -a; source .env; set +a; .venv/bin/pytest tests/api/test_frontend_read_discovery_status.py -q -p no:cacheprovider`
Expected: FAIL — 404 on the path (route not registered).

- [ ] **Step 3: Implement the contract, the route, the registration**

Append to `contract_v1.py` (follow the file's existing model style; it uses pydantic `BaseModel` with camelCase or snake_case — check `AccountV1` and match its `model_config`):

```python
class DiscoveryRunStatusV1(BaseModel):
    """The project's latest discovery run, for the Target accounts tab's live poll (2026-09-12)."""

    run_id: str
    status: Literal["not_started", "in_progress", "needs_review", "completed", "suspended"]
    asked: int | None
    found: int
    verified: int
    shown: int
    started_at: str | None
    finished_at: str | None


class DiscoveryRunStatusResponseV1(BaseModel):
    data: DiscoveryRunStatusV1 | None
```

Create `discovery_status.py`:

```python
"""``GET /frontend/v1/projects/{project_id}/discovery/current`` — the latest discovery run.

The Target accounts tab polls this while a run is live (spec 2026-09-12 §3): it is the only thing
the frontend reads to know a run is in flight, how far Exa has got, and when to stop polling.
ARV2's own tables are the only source (ruling 2026-09-09). ``found`` is the run's strict + relaxed
count as the driver last recorded it; ``verified`` counts candidates with a disposition;
``shown`` counts the pass/partial/unclear ones — the rows the tab is about to list.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from clue_api.frontend_read.app import WorkspaceDep
from clue_api.frontend_read.contract_v1 import DiscoveryRunStatusResponseV1, DiscoveryRunStatusV1
from clue_api.frontend_read.v1_shared import iso_utc
from clue_db import ConnFactory

__all__ = ["register_discovery_status_route"]

_LATEST_RUN = text(
    """
    SELECT r.run_id, r.status, r.asked, r.found_strict, r.found_relaxed, r.started_at,
           r.finished_at,
           (SELECT count(*) FROM arv2_discovery_candidate c
             WHERE c.run_id = r.run_id AND c.disposition <> 'pending') AS verified,
           (SELECT count(*) FROM arv2_discovery_candidate c
             WHERE c.run_id = r.run_id
               AND c.disposition IN ('pass', 'partial', 'unclear')) AS shown
    FROM arv2_discovery_run r
    WHERE r.workspace_id = :workspace_id AND r.project_id = :project_id
    ORDER BY r.created_at DESC, r.run_id DESC
    LIMIT 1
    """
)


def register_discovery_status_route(router: APIRouter, *, conn_factory: ConnFactory) -> None:
    @router.get(
        "/projects/{project_id}/discovery/current", response_model=DiscoveryRunStatusResponseV1
    )
    async def get_discovery_status(
        project_id: str, workspace_id: WorkspaceDep
    ) -> DiscoveryRunStatusResponseV1:
        async with conn_factory() as conn:
            row = (
                await conn.execute(
                    _LATEST_RUN, {"workspace_id": workspace_id, "project_id": project_id}
                )
            ).mappings().first()
        if row is None:
            return DiscoveryRunStatusResponseV1(data=None)
        return DiscoveryRunStatusResponseV1(
            data=DiscoveryRunStatusV1(
                run_id=str(row["run_id"]),
                status=str(row["status"]),
                asked=row["asked"],
                found=int(row["found_strict"] or 0) + int(row["found_relaxed"] or 0),
                verified=int(row["verified"]),
                shown=int(row["shown"]),
                started_at=iso_utc(row["started_at"]) if row["started_at"] else None,
                finished_at=iso_utc(row["finished_at"]) if row["finished_at"] else None,
            )
        )
```

Check `iso_utc`'s signature in `v1_shared.py` (it exists; the accounts-list test imports it) and adapt the call if it takes a different argument.

In `app.py`, next to the account-logo import add `from clue_api.frontend_read.discovery_status import register_discovery_status_route`, and after `register_account_logo_route(router, conn_factory=conn_factory)` add:

```python
    # The project's latest discovery run — the Target accounts tab's live poll (2026-09-12).
    register_discovery_status_route(router, conn_factory=conn_factory)
```

- [ ] **Step 4: Run to verify it passes; ruff; mypy**

Run: `set -a; source .env; set +a; .venv/bin/pytest tests/api/test_frontend_read_discovery_status.py -q -p no:cacheprovider && .venv/bin/ruff check platform/api/clue_api/frontend_read tests/api/test_frontend_read_discovery_status.py && .venv/bin/mypy platform/api/clue_api/frontend_read/discovery_status.py`
Expected: PASS, clean.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/frontend_read/contract_v1.py platform/api/clue_api/frontend_read/discovery_status.py platform/api/clue_api/frontend_read/app.py tests/api/test_frontend_read_discovery_status.py
git commit -m "feat(frontend-read): GET /projects/{id}/discovery/current — the latest discovery run and its counts"
```

---

### Task 7: Frontend model, repository and BFF route

**Files:**
- Create: `apps/frontend/src/features/accounts/model/discovery-status.ts`
- Create: `apps/frontend/src/features/accounts/model/discovery-status.test.ts`
- Create: `apps/frontend/src/features/accounts/data/discovery-status.repository.ts`
- Create: `apps/frontend/src/app/api/projects/[projectId]/discovery/route.ts`
- Create: `apps/frontend/src/app/api/projects/discovery-route.test.ts`

**Interfaces:**
- Produces: `DiscoveryRunStatusSchema`, `type DiscoveryRunStatus`, `discoveryRunLive(status: DiscoveryRunStatus | null): boolean`; `getDiscoveryStatus(projectId, read = fetchRead): Promise<DiscoveryRunStatus | null>`; BFF `GET /api/projects/:projectId/discovery` → `{ data: DiscoveryRunStatus | null }`, `Cache-Control: no-store`, 502 on failure.

- [ ] **Step 1: Write the failing model test**

`discovery-status.test.ts`:

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { DiscoveryRunStatusSchema, discoveryRunLive } from "./discovery-status";

const base = {
  run_id: "r1",
  status: "in_progress",
  asked: 35,
  found: 12,
  verified: 4,
  shown: 3,
  started_at: "2026-09-12T10:00:00Z",
  finished_at: null,
};

test("a run is live while it is not started or in progress, and not otherwise", () => {
  assert.equal(discoveryRunLive(DiscoveryRunStatusSchema.parse(base)), true);
  assert.equal(discoveryRunLive(DiscoveryRunStatusSchema.parse({ ...base, status: "not_started" })), true);
  for (const status of ["completed", "needs_review", "suspended"]) {
    assert.equal(discoveryRunLive(DiscoveryRunStatusSchema.parse({ ...base, status })), false);
  }
  assert.equal(discoveryRunLive(null), false);
});

test("an unknown status parses as not live rather than breaking the poll", () => {
  assert.equal(discoveryRunLive(DiscoveryRunStatusSchema.parse({ ...base, status: "paused" })), false);
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/frontend && npx tsx --test src/features/accounts/model/discovery-status.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the model**

`discovery-status.ts`:

```ts
import { z } from "zod";

/**
 * The project's latest discovery run as `/frontend/v1/projects/:id/discovery/current` serves it
 * (spec 2026-09-12 §3). Snake case on the wire, kept as-is: this document is polled, never
 * rendered field by field.
 */
export const DiscoveryRunStatusSchema = z.object({
  run_id: z.string().min(1),
  // `.catch`: an additive backend status must never kill the poll; it reads as "not live".
  status: z
    .enum(["not_started", "in_progress", "needs_review", "completed", "suspended"])
    .catch("completed"),
  asked: z.number().int().nullable(),
  found: z.number().int().nonnegative(),
  verified: z.number().int().nonnegative(),
  shown: z.number().int().nonnegative(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
});

export type DiscoveryRunStatus = z.infer<typeof DiscoveryRunStatusSchema>;

export const DiscoveryRunStatusResponseSchema = z.object({
  data: DiscoveryRunStatusSchema.nullable(),
});

/** Poll while the driver is still working; stop on the first terminal status. */
export function discoveryRunLive(status: DiscoveryRunStatus | null): boolean {
  return status !== null && (status.status === "not_started" || status.status === "in_progress");
}
```

- [ ] **Step 4: Run the model test**

Run: `cd apps/frontend && npx tsx --test src/features/accounts/model/discovery-status.test.ts`
Expected: PASS.

- [ ] **Step 5: Write the repository and the BFF route**

`discovery-status.repository.ts`:

```ts
import { fetchRead } from "./frontend-api";
import {
  DiscoveryRunStatusResponseSchema,
  type DiscoveryRunStatus,
} from "../model/discovery-status";

/** The project's latest discovery run, or `null` when none has been launched. */
export async function getDiscoveryStatus(
  projectId: string,
  read: typeof fetchRead = fetchRead,
): Promise<DiscoveryRunStatus | null> {
  const body = await read(`/projects/${encodeURIComponent(projectId)}/discovery/current`);
  return DiscoveryRunStatusResponseSchema.parse(body).data;
}
```

`app/api/projects/[projectId]/discovery/route.ts`:

```ts
import { getDiscoveryStatus } from "@/features/accounts/data/discovery-status.repository";

/**
 * The Target accounts tab's live poll (spec 2026-09-12 §3). One read, forwarded through the
 * authenticated accounts read client; never cached, since it is the thing that changes.
 */
export async function GET(_request: Request, { params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  try {
    const data = await getDiscoveryStatus(projectId);
    return Response.json({ data }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json(
      { error: "Unable to read discovery progress. Please try again." },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
}
```

- [ ] **Step 6: Write the BFF route test** (one segment above, like `api/accounts/route.test.ts`)

`app/api/projects/discovery-route.test.ts`:

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { GET } from "./[projectId]/discovery/route";

// Sits one segment ABOVE `[projectId]/discovery/` on purpose: `npm test` glob-expands each path,
// and a test inside a bracketed segment is collected as ZERO tests (accounts.md, tab lift).

test("a failed read is retryable, uncached, and carries no upstream detail", async (t) => {
  t.mock.method(globalThis, "fetch", async () => {
    throw new Error("private upstream connection details");
  });
  const response = await GET(new Request("http://localhost/api/projects/prj_1/discovery"), {
    params: Promise.resolve({ projectId: "prj_1" }),
  });
  assert.equal(response.status, 502);
  assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.deepEqual(await response.json(), {
    error: "Unable to read discovery progress. Please try again.",
  });
});
```

- [ ] **Step 7: Run tests, lint, tsc**

Run: `cd apps/frontend && npm test 2>&1 | grep -E "^ℹ (tests|pass|fail)" && npm run lint && npx tsc --noEmit -p . 2>&1 | grep -c "error TS"`
Expected: all pass (count = previous + 3), lint 0 errors, tsc error count unchanged at the baseline (50).

- [ ] **Step 8: Commit**

```bash
git add apps/frontend/src/features/accounts/model/discovery-status.ts apps/frontend/src/features/accounts/model/discovery-status.test.ts apps/frontend/src/features/accounts/data/discovery-status.repository.ts "apps/frontend/src/app/api/projects/[projectId]/discovery/route.ts" apps/frontend/src/app/api/projects/discovery-route.test.ts
git commit -m "feat(frontend): discovery status model, repository and BFF route for the Target accounts tab's live poll"
```

---

### Task 8: The launch signal rule

**Files:**
- Create: `apps/frontend/src/features/chat-shell/model/discovery-launch-signal.ts`
- Create: `apps/frontend/src/features/chat-shell/model/discovery-launch-signal.test.ts`

**Interfaces:**
- Produces: `discoveryLaunchToOpen({ transcript, knownToolCallIds }): string | null` — the `toolCallId` of a newly completed `launch_arv2_discovery` tool part, else `null`. The caller banks every tool call id it has seen (same discipline as `artifactToAutoOpen`).

- [ ] **Step 1: Write the failing test**

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { discoveryLaunchToOpen, type LaunchSignalMessage } from "./discovery-launch-signal";

function message(parts: LaunchSignalMessage["parts"]): LaunchSignalMessage {
  return { parts };
}
const done = { kind: "tool" as const, toolName: "launch_arv2_discovery", toolCallId: "c1", state: "output-available" as const };

test("a completed discovery launch that was not seen before opens the surface", () => {
  assert.equal(discoveryLaunchToOpen({ transcript: [message([done])], knownToolCallIds: new Set() }), "c1");
});

test("a launch already banked, a launch still running, and another tool all stay quiet", () => {
  assert.equal(discoveryLaunchToOpen({ transcript: [message([done])], knownToolCallIds: new Set(["c1"]) }), null);
  assert.equal(
    discoveryLaunchToOpen({ transcript: [message([{ ...done, state: "input-available" }])], knownToolCallIds: new Set() }),
    null,
  );
  assert.equal(
    discoveryLaunchToOpen({ transcript: [message([{ ...done, toolName: "launch_account_research" }])], knownToolCallIds: new Set() }),
    null,
  );
});

test("a refused launch never opens anything", () => {
  assert.equal(
    discoveryLaunchToOpen({ transcript: [message([{ ...done, state: "output-error" }])], knownToolCallIds: new Set() }),
    null,
  );
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/frontend && npx tsx --test src/features/chat-shell/model/discovery-launch-signal.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```ts
/**
 * When does the rail open the Target accounts surface by itself? (spec 2026-09-12 §4)
 *
 * The moment the stream delivers a **completed** `launch_arv2_discovery` tool part on this
 * thread — the same discipline as `artifact-auto-open`: the caller banks every tool call id it
 * has seen, so a cold load's replayed backlog opens nothing and a launch opens the surface once.
 * A refused launch (`output-error`/`output-denied`) produces no run and opens nothing.
 */
export const DISCOVERY_LAUNCH_TOOL = "launch_arv2_discovery";

/** The slice of a transcript message this decision reads; `TranscriptMessage` satisfies it. */
export interface LaunchSignalMessage {
  parts: readonly { kind: string; toolName?: string; toolCallId?: string; state?: string }[];
}

export function discoveryLaunchToOpen({
  transcript,
  knownToolCallIds,
}: {
  transcript: readonly LaunchSignalMessage[];
  knownToolCallIds: ReadonlySet<string>;
}): string | null {
  for (const message of transcript) {
    for (const part of message.parts) {
      if (part.kind !== "tool" || part.toolName !== DISCOVERY_LAUNCH_TOOL) continue;
      if (part.state !== "output-available" || !part.toolCallId) continue;
      if (knownToolCallIds.has(part.toolCallId)) continue;
      return part.toolCallId;
    }
  }
  return null;
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd apps/frontend && npx tsx --test src/features/chat-shell/model/discovery-launch-signal.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/features/chat-shell/model/discovery-launch-signal.ts apps/frontend/src/features/chat-shell/model/discovery-launch-signal.test.ts
git commit -m "feat(chat-shell): the discovery launch signal — a completed launch_arv2_discovery part opens the target-accounts surface once"
```

---

### Task 9: The polling hook, the wiring, the spinner, the refetch

**Files:**
- Create: `apps/frontend/src/features/accounts/hooks/use-discovery-status.ts`
- Modify: `apps/frontend/src/features/chat-shell/components/chat-surface.tsx` (imports; after the `addToOpenChat` hook; the `ArtifactStage` props)
- Modify: `apps/frontend/src/features/chat-shell/components/artifact-stage.tsx` (two new props passed through)
- Modify: `apps/frontend/src/features/chat-shell/components/artifact-tabs.tsx` (`targetAccountsBusy` prop + spinner)
- Modify: `apps/frontend/src/features/chat-shell/components/chat-shell.module.css` (`.galleryTabSpinner`)
- Modify: `apps/frontend/src/features/accounts/components/project-target-accounts.tsx` (`refreshToken` prop)
- Create: `apps/frontend/src/features/chat-shell/model/chat-shell-contract.test.ts` (source-contract tests)

**Interfaces:**
- Consumes: `getDiscoveryStatus`, `discoveryRunLive` (Task 7), `discoveryLaunchToOpen` (Task 8), `shell.openTargetAccounts()`.
- Produces: `useDiscoveryStatus(projectId, { pollMs = 5000, prime }) → { status, live, tick }`; `ArtifactStage`/`ArtifactTabs` prop `targetAccountsBusy?: boolean`; `ArtifactStage` prop `targetAccountsRefreshToken?: number` → `ProjectTargetAccounts` prop `refreshToken?: number`.

- [ ] **Step 1: Write the source-contract tests** (house style: the repo's DOM-less runner pins wiring by source text)

`chat-shell-contract.test.ts`:

```ts
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

function source(path: string) {
  return readFileSync(new URL(path, import.meta.url), "utf8");
}
const surface = source("../components/chat-surface.tsx");
const stage = source("../components/artifact-stage.tsx");
const tabs = source("../components/artifact-tabs.tsx");
const tab = source("../../accounts/components/project-target-accounts.tsx");
const hook = source("../../accounts/hooks/use-discovery-status.ts");

test("the shell polls discovery every 5 s while live and opens the surface on the launch signal", () => {
  assert.match(surface, /useDiscoveryStatus\(projectId/);
  assert.match(surface, /discoveryLaunchToOpen\(\{/);
  assert.match(surface, /shell\.openTargetAccounts\(\)/);
  assert.match(hook, /pollMs = 5000/);
  assert.match(hook, /discoveryRunLive\(/);
});

test("the tab label spins while a run is live, and the tab refetches on every tick", () => {
  assert.match(surface, /targetAccountsBusy=\{discovery\.live\}/);
  assert.match(surface, /targetAccountsRefreshToken=\{discovery\.tick\}/);
  assert.match(stage, /targetAccountsBusy=\{targetAccountsBusy\}/);
  assert.match(stage, /refreshToken=\{targetAccountsRefreshToken\}/);
  assert.match(tabs, /targetAccountsBusy \? \(\s*<ProjectIcon className=\{styles\.galleryTabSpinner\} name="loader"/);
  assert.match(tab, /\[active, attempt, data, projectId, refreshToken\]|refreshToken/);
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/frontend && npx tsx --test src/features/chat-shell/model/chat-shell-contract.test.ts`
Expected: FAIL (hook file missing; regexes unmatched).

- [ ] **Step 3: The hook**

`use-discovery-status.ts`:

```ts
"use client";

import { useEffect, useRef, useState } from "react";
import {
  DiscoveryRunStatusResponseSchema,
  discoveryRunLive,
  type DiscoveryRunStatus,
} from "../model/discovery-status";

/**
 * The project's discovery run, polled while it is live (spec 2026-09-12 §3).
 *
 * Reads on mount; while the run is live it re-reads every `pollMs` and bumps `tick` on each
 * read so the Target accounts tab refetches its rows. `prime` bumps once from outside (the
 * launch signal) so the first poll after a launch does not wait a whole interval. A failed
 * read keeps the last status and tries again on the next tick; polling stops on the first
 * terminal status.
 */
export function useDiscoveryStatus(
  projectId: string,
  { pollMs = 5000, prime = 0 }: { pollMs?: number; prime?: number } = {},
): { status: DiscoveryRunStatus | null; live: boolean; tick: number } {
  const [status, setStatus] = useState<DiscoveryRunStatus | null>(null);
  const [tick, setTick] = useState(0);
  const live = discoveryRunLive(status);
  const liveRef = useRef(live);
  liveRef.current = live;

  useEffect(() => {
    let cancelled = false;
    async function read() {
      try {
        const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/discovery`, {
          cache: "no-store",
        });
        if (!response.ok) return;
        const next = DiscoveryRunStatusResponseSchema.parse(await response.json()).data;
        if (cancelled) return;
        setStatus(next);
        setTick((current) => current + 1);
      } catch {
        // Keep the last status; the next tick tries again.
      }
    }
    void read();
    const interval = window.setInterval(() => {
      if (liveRef.current) void read();
    }, pollMs);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [pollMs, prime, projectId]);

  return { status, live, tick };
}
```

Note: the interval is created regardless and only reads while live; `prime` changes re-run the effect (an immediate read after a launch). Rendering a stale `status` while not live costs nothing.

- [ ] **Step 4: Wire the chat surface**

In `chat-surface.tsx`:

imports — add:

```ts
import { useDiscoveryStatus } from "@/features/accounts/hooks/use-discovery-status";
import { discoveryLaunchToOpen } from "../model/discovery-launch-signal";
```

After the `addToOpenChat` hook block add:

```ts
  // The Target accounts tab's live poll (spec 2026-09-12 §3): the status decides the spinner,
  // each read bumps the token the tab refetches on, and the launch signal primes the first read.
  const [discoveryPrime, setDiscoveryPrime] = useState(0);
  const discovery = useDiscoveryStatus(projectId, { prime: discoveryPrime });
```

and `useState` to the React import (`import { useEffect, useRef, useState } from "react";`).

After the artifact auto-open effect add:

```ts
  // Founder ruling 2026-09-12: when the agent launches discovery, the rail opens the Target
  // accounts surface by itself. The rule is `../model/discovery-launch-signal`; this effect only
  // transports it, banking every tool call id it has seen so a replayed backlog opens nothing.
  const knownLaunchIds = useRef<Set<string> | null>(null);
  const openTargetAccounts = shell.openTargetAccounts;
  useEffect(() => {
    const known = knownLaunchIds.current;
    if (known === null) {
      knownLaunchIds.current = new Set(
        chat.transcript.flatMap((message) =>
          message.parts.flatMap((part) => (part.kind === "tool" ? [part.toolCallId] : [])),
        ),
      );
      return;
    }
    const opening = discoveryLaunchToOpen({ transcript: chat.transcript, knownToolCallIds: known });
    for (const message of chat.transcript) {
      for (const part of message.parts) if (part.kind === "tool") known.add(part.toolCallId);
    }
    if (opening === null) return;
    openTargetAccounts();
    setDiscoveryPrime((current) => current + 1);
  }, [chat.transcript, openTargetAccounts]);
```

On the `<ArtifactStage ... />` element add two props next to `onOpenTargetAccounts`:

```ts
        targetAccountsBusy={discovery.live}
        targetAccountsRefreshToken={discovery.tick}
```

- [ ] **Step 5: Thread through the stage and the tabs**

`artifact-stage.tsx`: destructure `targetAccountsBusy` and `targetAccountsRefreshToken`; type them:

```ts
  /** True while the project's discovery run is live: the Target accounts tab label spins. */
  targetAccountsBusy?: boolean;
  /** Bumped on every discovery poll read: the tab refetches its rows (spec 2026-09-12 §3). */
  targetAccountsRefreshToken?: number;
```

Pass `targetAccountsBusy={targetAccountsBusy}` to `<ArtifactTabs>` and `refreshToken={targetAccountsRefreshToken}` to `<ProjectTargetAccounts>`.

`artifact-tabs.tsx`: add `targetAccountsBusy` to the destructuring and the props type (`targetAccountsBusy?: boolean;`); change the Target accounts label to:

```tsx
                <ProjectIcon name="target-accounts" size={12} />
                <span>Target accounts</span>
                {targetAccountsBusy ? (
                  <ProjectIcon className={styles.galleryTabSpinner} name="loader" size={12} />
                ) : null}
```

Check `ProjectIcon` accepts `className` (the agent-activity row passes one, so it does).

`chat-shell.module.css`: append

```css
/* The Target accounts tab's live-run spinner: the chat's own rotating loader glyph. */
.galleryTabSpinner {
  margin-left: 4px;
  animation: galleryTabSpin 1s linear infinite;
}

@keyframes galleryTabSpin {
  to { transform: rotate(360deg); }
}
```

- [ ] **Step 6: Refetch the tab on the token**

`project-target-accounts.tsx`: add `refreshToken?: number` to `ProjectTargetAccounts`'s props (destructure it), and change the fetch effect to refetch whenever the token changes without dropping `data`:

```ts
  const [data, setData] = useState<ProjectAccountsResponse | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    // First load when the tab becomes active; afterwards every discovery tick (`refreshToken`)
    // re-reads without dropping `data`, so the table keeps its columns, selection and page
    // while verified rows climb in (spec 2026-09-12 §3).
    if (!active) return;
    const request = new AbortController();
    fetch(`/api/projects/${encodeURIComponent(projectId)}/accounts`, { signal: request.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("Unable to load project accounts");
        return ProjectAccountsResponseSchema.parse(await response.json());
      })
      .then((result) => { if (!request.signal.aborted) { setData(result); setError(false); } })
      .catch(() => { if (!request.signal.aborted && data === null) setError(true); });
    return () => request.abort();
    // `data` is deliberately not a dependency: it changes on every read.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, attempt, projectId, refreshToken]);
```

The `data` guard in `.catch` keeps a failed refetch from blanking a table that already has rows (spec §5). Because `data` is read inside the effect but not a dependency, the lint disable comment stays with its one-line reason.

- [ ] **Step 7: Run everything**

Run: `cd apps/frontend && npm test 2>&1 | grep -E "^ℹ (tests|pass|fail)" && npm run lint && npx tsc --noEmit -p . 2>&1 | grep -c "error TS" && npm run build 2>&1 | tail -3`
Expected: all tests pass, lint 0 errors, tsc at the baseline, build green.

- [ ] **Step 8: Commit**

```bash
git add apps/frontend/src/features/accounts/hooks/use-discovery-status.ts apps/frontend/src/features/chat-shell/components/chat-surface.tsx apps/frontend/src/features/chat-shell/components/artifact-stage.tsx apps/frontend/src/features/chat-shell/components/artifact-tabs.tsx apps/frontend/src/features/chat-shell/components/chat-shell.module.css apps/frontend/src/features/accounts/components/project-target-accounts.tsx apps/frontend/src/features/chat-shell/model/chat-shell-contract.test.ts
git commit -m "feat(frontend): the Target accounts tab polls the live discovery run, spins, refetches its rows, and opens itself on launch"
```

---

### Task 10: Contract note and memory

**Files:**
- Modify: `apps/frontend/docs/api-contracts/accounts.md` (append after "Seam edit 3")
- Modify: `_memory/2026-09-11-san-salvador-lane-stack.md` (append)

- [ ] **Step 1: Append to `accounts.md`**

```markdown
**Seam edit 4 — the tab streams a live discovery run** (spec
`docs/superpowers/specs/archive/2026-09-12-discovery-streaming-design.md`). A new read,
`GET /frontend/v1/projects/:projectId/discovery/current` (BFF mirror
`GET /api/projects/:projectId/discovery`), serves the project's latest discovery run:
`{ run_id, status, asked, found, verified, shown, started_at, finished_at }` or `null`. While
`status` is `not_started`/`in_progress` the chat shell polls it every 5 s, the "Target accounts"
tab label carries the chat's rotating loader glyph, and the tab re-reads
`/api/projects/:projectId/accounts` on every tick without dropping its rows, so verified
accounts appear as the driver lands them. A completed `launch_arv2_discovery` tool part on the
open thread opens the surface once (`chat-shell/model/discovery-launch-signal.ts`). Backend:
the driver now lists the webset on every poll tick and verifies new items in a bounded pool
(`CLUE_ARV2_DISCOVERY_VERIFY_CONCURRENCY`, default 4), one candidate's gates asked together;
a row still appears only after every gate is verified.
```

- [ ] **Step 2: Append to the memory note**

```markdown

## Discovery streaming landed (plan 2026-09-12-discovery-streaming)

Driver: per-tick `items()` + task pool under one semaphore (`arv2_discovery_verify_concurrency`,
default 4; 1 = the old serial order, which the positional DB script pins), gates of one candidate
gathered, `record_discovery_progress` per tick. Read: `/frontend/v1/projects/{id}/discovery/current`.
Frontend: `useDiscoveryStatus` (5 s while live) in chat-surface → spinner on the tab label +
`refreshToken` refetch in `ProjectTargetAccounts`; `discoveryLaunchToOpen` opens the surface on a
completed launch part. Owed: the founder's signed-in walk (launch discovery from chat → tab opens →
rows climb → spinner stops).
```

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/docs/api-contracts/accounts.md _memory/2026-09-11-san-salvador-lane-stack.md
git commit -m "docs: discovery streaming — the tab's live poll contract and the lane memory note"
```

---

## Self-review

- **Spec coverage.** §2 driver: Tasks 3–5 (pool, gates together, per-tick listing, claim at dispatch, straggler read on idle, counters per tick, containment, resume). §3 read: Task 6. §4 frontend: Tasks 7–9 (open on launch, poll while live, spinner, reload restores from the read alone since the hook reads on mount). §5 failures: hook keeps last status; tab keeps rows on a failed refetch; refused launch produces no `output-available` part. §6 tests: each task carries its own. §7: no webhooks, no new tab text.
- **Placeholder scan.** Task 5 tells the implementer to copy four helpers verbatim from the existing DB test by name rather than inventing them — that is a lookup instruction, not a placeholder; the names to search are given. Task 6 names `iso_utc` and `record_verdicts` checks explicitly.
- **Type consistency.** `record_discovery_progress(conn, *, run_id, found_strict, found_relaxed, analyzed)` is used identically in Tasks 2, 4 and 6. `discoveryRunLive`, `DiscoveryRunStatusResponseSchema`, `useDiscoveryStatus`, `discoveryLaunchToOpen`, `targetAccountsBusy`, `targetAccountsRefreshToken`, `refreshToken` are spelled the same in Tasks 7–9 and in the source-contract test.
