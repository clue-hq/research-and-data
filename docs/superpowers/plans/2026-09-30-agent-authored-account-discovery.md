# Agent-authored account discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Head of ABM writes the account-discovery brief itself; the platform runs it with mechanical top-ups, excludes companies by gate role, locks the project and the thread, supports Stop, and wakes the agent with a summary when a run ends.

**Architecture:** A new tool version `launch_arv2_discovery@2` stores the agent's brief on the run row. The existing fleet driver runs up to `1 + CLUE_ARV2_DISCOVERY_MAX_TOPUPS` searches with that same brief (Websets or Exa `/search`), applies each gate's role, and at the end writes a summary and hands it to an injected wake seam that queues a derived Head-of-ABM turn in the launching thread. A partial unique index is the project lock; `dispatch_next_thread_turn` holds a thread's queue while its discovery is unreleased and lets the wake turn go first.

**Tech Stack:** Python 3.12, SQLAlchemy async + asyncpg, Alembic, Pydantic v2, pytest; Next.js/TypeScript/Zod frontend (`tsx --test`).

**Spec:** `docs/superpowers/specs/2026-09-30-agent-authored-account-discovery-design.md` (read it first; its §2 rulings and §6 texts are binding).

## Global Constraints

- The pinned, confirmed ICP stays a launch precondition; no code reads text out of it on the discovery path (`compile_brief` is not called by the launch or the driver).
- Gate roles are exactly `must`, `must_not`, `prefer`. An `unclear` verdict never excludes.
- Excluded companies never join the project's accounts and never count toward `target_count`.
- At most `1 + CLUE_ARV2_DISCOVERY_MAX_TOPUPS` searches per run; default `CLUE_ARV2_DISCOVERY_MAX_TOPUPS=3`.
- The brief is never shown to the customer: no chat part, no card, no frontend field carries it.
- Shipped skill / prompt / tool text is industry-agnostic: placeholders only (`<kind of buyer>`, `<the seller's kind of product>`), never a real industry. The §6 texts of the spec are used verbatim.
- Every new setting appears in `.env.example` (and the local `.env`) with its default in the same commit; removed settings are removed from both.
- Alembic: a hash revision id chained to the single head (`6eb27d45f570` at plan time — re-check with `uv run alembic heads`), reversible, named constraints.
- `clue_api.arv2` imports nothing from `clue_api.turn_action`, `clue_api.chat` or `clue_api.agent_turn_submission`; the wake is an injected seam implemented outside `arv2`.
- A catalog change is a new version (never edit a published profile or skill version in place); the manual's generated chapters come only from `make manual`.
- Tests never run with real provider keys: `--ignore-glob='*_live.py'`; DB suites run with the lane stack down.
- No AI attribution in commits.

## Review Focus

1. **Two threads launch in the same second** → exactly one run is created; the other call gets `discovery_in_progress` (not a 500). Pinned in Task 3.
2. **A replayed launch (same turn action) while its own run is active** → the replay returns the same run, it is not refused by the lock. Pinned in Task 3.
3. **Stop pressed while the webset is still finding** → the webset is cancelled, the billed rows land on the ledger, verified companies stay, the run ends `stopped`, the wake still arrives. Pinned in Task 4.
4. **The user sends two messages during a discovery** → both are held, the wake turn runs first, then the two messages in order. Pinned in Task 5.
5. **A CLI / fleet launch with no thread** → the run releases its project lock at its end (no wake), so the project is not locked forever. Pinned in Task 4.

---

### Task 1: Schema and store for briefs, locks, stop and wake

**Files:**
- Create: `alembic/versions/<new-hash>_agent_authored_discovery.py` (`uv run alembic revision -m "agent authored discovery"`, down_revision = current head)
- Modify: `platform/api/clue_api/arv2/discovery_store.py`
- Test: `tests/arv2/test_discovery_store_db.py`

**Interfaces:**
- Produces (store): `DiscoveryRunRow` gains `source: str = "websets"`, `brief: Mapping[str, Any] | None = None`, `launched_thread_id: str | None = None`, `launching_turn_id: UUID | None = None`, `end_reason: str | None = None`, `summary: Mapping[str, Any] | None = None`, `stop_requested_at: datetime | None = None`, `wake_turn_id: UUID | None = None`, `released_at: datetime | None = None`. `DiscoveryStatus` adds `"stopped"`. `Disposition` adds `"excluded"`. `CandidateRow` gains `excluded_by_gate: str | None = None`. `SearchKind` adds `"round"`; `SearchRow` gains `source: str = "websets"`.
- Produces functions:
  - `async def active_discovery_for_project(conn, *, workspace_id: str, project_id: str) -> DiscoveryRunRow | None`
  - `async def active_discoveries_for_threads(conn, *, workspace_id: str, thread_ids: Sequence[str]) -> dict[str, DiscoveryRunRow]`
  - `async def request_discovery_stop(conn, *, workspace_id: str, project_id: str, run_id: UUID) -> DiscoveryRunRow | None`
  - `async def stop_requested(conn, *, run_id: UUID) -> bool`
  - `async def end_discovery_run(conn, *, run_id: UUID, status: DiscoveryStatus, end_reason: str, summary: Mapping[str, Any], release: bool) -> None` (sets `finished_at`, `status`, `end_reason`, `summary_json`; `released_at = now()` when `release`)
  - `async def record_wake_turn(conn, *, run_id: UUID, wake_turn_id: UUID) -> None`
  - `async def release_discovery_for_turn(conn, *, workspace_id: str, turn_id: UUID) -> UUID | None` (sets `released_at` on the run whose `wake_turn_id = turn_id`; returns its run id)

- [ ] **Step 1: Write the migration**

```python
"""agent authored discovery: brief, source, thread lock, stop, wake, exclusion (spec 2026-09-30)."""

from alembic import op

revision = "<generated>"
down_revision = "6eb27d45f570"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE arv2_discovery_run
            ADD COLUMN source text NOT NULL DEFAULT 'websets',
            ADD COLUMN brief_json jsonb NULL,
            ADD COLUMN launched_thread_id text NULL,
            ADD COLUMN launching_turn_id uuid NULL,
            ADD COLUMN end_reason text NULL,
            ADD COLUMN summary_json jsonb NULL,
            ADD COLUMN stop_requested_at timestamptz NULL,
            ADD COLUMN wake_turn_id uuid NULL,
            ADD COLUMN released_at timestamptz NULL,
            ADD CONSTRAINT arv2_discovery_run_source CHECK (source IN ('websets', 'search')),
            ADD CONSTRAINT arv2_discovery_run_end_reason CHECK (end_reason IS NULL OR end_reason IN
                ('filled', 'dry', 'round_cap', 'wall_clock', 'stopped', 'failed'))
        """
    )
    op.execute("ALTER TABLE arv2_discovery_run DROP CONSTRAINT arv2_discovery_run_status")
    op.execute(
        "ALTER TABLE arv2_discovery_run ADD CONSTRAINT arv2_discovery_run_status CHECK (status IN "
        "('not_started', 'in_progress', 'needs_review', 'completed', 'suspended', 'stopped'))"
    )
    # Every run that already exists is released: the lock is for runs launched from now on.
    op.execute("UPDATE arv2_discovery_run SET released_at = COALESCE(finished_at, now())")
    op.execute(
        "CREATE UNIQUE INDEX arv2_discovery_run_project_active ON arv2_discovery_run "
        "(workspace_id, project_id) WHERE released_at IS NULL"
    )
    op.execute(
        "CREATE INDEX arv2_discovery_run_thread_active ON arv2_discovery_run "
        "(workspace_id, launched_thread_id) WHERE released_at IS NULL"
    )
    op.execute(
        """
        ALTER TABLE arv2_discovery_candidate
            ADD COLUMN excluded_by_gate text NULL,
            DROP CONSTRAINT arv2_discovery_candidate_disposition,
            ADD CONSTRAINT arv2_discovery_candidate_disposition CHECK (disposition IN
                ('pending', 'pass', 'partial', 'unclear', 'duplicate_of_existing', 'found_before',
                 'excluded')),
            ADD CONSTRAINT arv2_discovery_candidate_excluded_gate
                CHECK ((disposition = 'excluded') = (excluded_by_gate IS NOT NULL))
        """
    )
    op.execute(
        """
        ALTER TABLE arv2_discovery_search
            ADD COLUMN source text NOT NULL DEFAULT 'websets',
            DROP CONSTRAINT arv2_discovery_search_kind,
            ADD CONSTRAINT arv2_discovery_search_kind
                CHECK (kind IN ('strict', 'strict_topup', 'relaxed', 'round')),
            DROP CONSTRAINT arv2_discovery_search_ordinal,
            ADD CONSTRAINT arv2_discovery_search_ordinal CHECK (ordinal BETWEEN 1 AND 16),
            ADD CONSTRAINT arv2_discovery_search_source CHECK (source IN ('websets', 'search'))
        """
    )
    op.execute(
        """
        ALTER TABLE agent_turn_submission
            DROP CONSTRAINT agent_turn_submission_derivation_kind,
            ADD CONSTRAINT agent_turn_submission_derivation_kind
                CHECK (derivation IS NULL OR derivation IN
                    ('design_leg_redelivery', 'design_leg_first_turn', 'discovery_finished'))
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM agent_turn_submission WHERE derivation = 'discovery_finished'")
    op.execute(
        """
        ALTER TABLE agent_turn_submission
            DROP CONSTRAINT agent_turn_submission_derivation_kind,
            ADD CONSTRAINT agent_turn_submission_derivation_kind
                CHECK (derivation IS NULL OR derivation IN
                    ('design_leg_redelivery', 'design_leg_first_turn'))
        """
    )
    op.execute("DELETE FROM arv2_discovery_search WHERE kind = 'round' OR ordinal > 3")
    op.execute(
        """
        ALTER TABLE arv2_discovery_search
            DROP CONSTRAINT arv2_discovery_search_source,
            DROP CONSTRAINT arv2_discovery_search_ordinal,
            ADD CONSTRAINT arv2_discovery_search_ordinal CHECK (ordinal BETWEEN 1 AND 3),
            DROP CONSTRAINT arv2_discovery_search_kind,
            ADD CONSTRAINT arv2_discovery_search_kind
                CHECK (kind IN ('strict', 'strict_topup', 'relaxed')),
            DROP COLUMN source
        """
    )
    op.execute("DELETE FROM arv2_discovery_candidate WHERE disposition = 'excluded'")
    op.execute(
        """
        ALTER TABLE arv2_discovery_candidate
            DROP CONSTRAINT arv2_discovery_candidate_excluded_gate,
            DROP CONSTRAINT arv2_discovery_candidate_disposition,
            ADD CONSTRAINT arv2_discovery_candidate_disposition CHECK (disposition IN
                ('pending', 'pass', 'partial', 'unclear', 'duplicate_of_existing', 'found_before')),
            DROP COLUMN excluded_by_gate
        """
    )
    op.execute("DROP INDEX arv2_discovery_run_thread_active")
    op.execute("DROP INDEX arv2_discovery_run_project_active")
    op.execute("UPDATE arv2_discovery_run SET status = 'completed' WHERE status = 'stopped'")
    op.execute("ALTER TABLE arv2_discovery_run DROP CONSTRAINT arv2_discovery_run_status")
    op.execute(
        "ALTER TABLE arv2_discovery_run ADD CONSTRAINT arv2_discovery_run_status CHECK (status IN "
        "('not_started', 'in_progress', 'needs_review', 'completed', 'suspended'))"
    )
    op.execute(
        """
        ALTER TABLE arv2_discovery_run
            DROP CONSTRAINT arv2_discovery_run_end_reason,
            DROP CONSTRAINT arv2_discovery_run_source,
            DROP COLUMN released_at, DROP COLUMN wake_turn_id, DROP COLUMN stop_requested_at,
            DROP COLUMN summary_json, DROP COLUMN end_reason, DROP COLUMN launching_turn_id,
            DROP COLUMN launched_thread_id, DROP COLUMN brief_json, DROP COLUMN source
        """
    )
```

- [ ] **Step 2: Write the failing store tests** (append to `tests/arv2/test_discovery_store_db.py`, reusing its existing run-row helper for a minimal `DiscoveryRunRow`; name it `_run_row(...)` if the file's helper is named differently, use that one)

```python
def test_only_one_unreleased_run_per_project(require_db):
    async def _check():
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            first = _run_row(request_sha256="a" * 64, launched_thread_id="thr_a")
            second = _run_row(request_sha256="b" * 64, launched_thread_id="thr_b")
            assert await store.create_discovery_run(conn, first)
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await store.create_discovery_run(conn, second)
            active = await store.active_discovery_for_project(
                conn, workspace_id=first.workspace_id, project_id=first.project_id
            )
            assert active is not None and active.run_id == first.run_id
            await txn.rollback()
    run_async(_check())


def test_end_with_release_frees_the_project(require_db):
    async def _check():
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            row = _run_row(request_sha256="c" * 64, launched_thread_id=None)
            await store.create_discovery_run(conn, row)
            await store.end_discovery_run(
                conn, run_id=row.run_id, status="completed", end_reason="filled",
                summary={"asked": 3}, release=True,
            )
            assert await store.active_discovery_for_project(
                conn, workspace_id=row.workspace_id, project_id=row.project_id
            ) is None
            await txn.rollback()
    run_async(_check())


def test_the_wake_turn_releases_its_run(require_db):
    async def _check():
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            row = _run_row(request_sha256="d" * 64, launched_thread_id="thr_w")
            await store.create_discovery_run(conn, row)
            await store.end_discovery_run(
                conn, run_id=row.run_id, status="completed", end_reason="dry",
                summary={}, release=False,
            )
            wake = uuid4()
            await store.record_wake_turn(conn, run_id=row.run_id, wake_turn_id=wake)
            by_thread = await store.active_discoveries_for_threads(
                conn, workspace_id=row.workspace_id, thread_ids=["thr_w"]
            )
            assert by_thread["thr_w"].wake_turn_id == wake
            released = await store.release_discovery_for_turn(
                conn, workspace_id=row.workspace_id, turn_id=wake
            )
            assert released == row.run_id
            assert await store.active_discoveries_for_threads(
                conn, workspace_id=row.workspace_id, thread_ids=["thr_w"]
            ) == {}
            await txn.rollback()
    run_async(_check())


def test_stop_is_recorded_once_and_read_back(require_db):
    async def _check():
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            row = _run_row(request_sha256="e" * 64, launched_thread_id="thr_s")
            await store.create_discovery_run(conn, row)
            assert not await store.stop_requested(conn, run_id=row.run_id)
            stopped = await store.request_discovery_stop(
                conn, workspace_id=row.workspace_id, project_id=row.project_id, run_id=row.run_id
            )
            assert stopped is not None and stopped.stop_requested_at is not None
            assert await store.stop_requested(conn, run_id=row.run_id)
            await txn.rollback()
    run_async(_check())


def test_an_excluded_candidate_must_name_its_gate(require_db):
    async def _check():
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            row = _run_row(request_sha256="f" * 64, launched_thread_id=None)
            await store.create_discovery_run(conn, row)
            bad = _candidate_row(row, domain="x.com", disposition="excluded", excluded_by_gate=None)
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await store.upsert_candidate(conn, bad)
            await txn.rollback()
    run_async(_check())
```

- [ ] **Step 3: Run them to verify they fail**

Run (lane stack down): `set -a; source .env; set +a; uv run alembic upgrade head && uv run pytest tests/arv2/test_discovery_store_db.py -q`
Expected: FAIL (`active_discovery_for_project` not defined / new columns missing in the store).

- [ ] **Step 4: Implement the store changes**

In `discovery_store.py`: extend the literals and dataclasses exactly as listed under **Interfaces**; add the new columns to `_RUN_COLUMNS` (`source, brief_json, launched_thread_id, launching_turn_id, end_reason, summary_json, stop_requested_at, wake_turn_id, released_at`), `_SEARCH_COLUMNS` (`source`), `_CANDIDATE_COLUMNS` (`excluded_by_gate`); write them in `create_discovery_run`, `create_search`, `upsert_candidate`; read them in `_run`/`_search`/`_candidate` (jsonb through the module's existing `_dump_json`/decode). Then add:

```python
_ACTIVE = "released_at IS NULL"


async def active_discovery_for_project(
    conn: AsyncConnection, *, workspace_id: str, project_id: str
) -> DiscoveryRunRow | None:
    row = (
        await conn.execute(
            text(
                f"SELECT {_RUN_COLUMNS} FROM arv2_discovery_run "
                f"WHERE workspace_id = :w AND project_id = :p AND {_ACTIVE}"
            ),
            {"w": workspace_id, "p": project_id},
        )
    ).mappings().first()
    return None if row is None else _run(row)


async def active_discoveries_for_threads(
    conn: AsyncConnection, *, workspace_id: str, thread_ids: Sequence[str]
) -> dict[str, DiscoveryRunRow]:
    if not thread_ids:
        return {}
    rows = (
        await conn.execute(
            text(
                f"SELECT {_RUN_COLUMNS} FROM arv2_discovery_run WHERE workspace_id = :w "
                f"AND launched_thread_id = ANY(:t) AND {_ACTIVE}"
            ),
            {"w": workspace_id, "t": list(thread_ids)},
        )
    ).mappings()
    return {str(r["launched_thread_id"]): _run(r) for r in rows}


async def request_discovery_stop(
    conn: AsyncConnection, *, workspace_id: str, project_id: str, run_id: UUID
) -> DiscoveryRunRow | None:
    await conn.execute(
        text(
            "UPDATE arv2_discovery_run SET stop_requested_at = COALESCE(stop_requested_at, now()) "
            f"WHERE run_id = :r AND workspace_id = :w AND project_id = :p AND {_ACTIVE}"
        ),
        {"r": run_id, "w": workspace_id, "p": project_id},
    )
    run = await read_discovery_run(conn, run_id=run_id)
    if run is None or run.workspace_id != workspace_id or run.project_id != project_id:
        return None
    return run


async def stop_requested(conn: AsyncConnection, *, run_id: UUID) -> bool:
    value = await conn.scalar(
        text("SELECT stop_requested_at IS NOT NULL FROM arv2_discovery_run WHERE run_id = :r"),
        {"r": run_id},
    )
    return bool(value)


async def end_discovery_run(
    conn: AsyncConnection,
    *,
    run_id: UUID,
    status: DiscoveryStatus,
    end_reason: str,
    summary: Mapping[str, Any],
    release: bool,
) -> None:
    await conn.execute(
        text(
            "UPDATE arv2_discovery_run SET status = :s, end_reason = :e, "
            "summary_json = CAST(:j AS jsonb), finished_at = COALESCE(finished_at, now()), "
            "released_at = CASE WHEN :rel THEN now() ELSE released_at END WHERE run_id = :r"
        ),
        {"s": status, "e": end_reason, "j": _dump_json(summary), "rel": release, "r": run_id},
    )


async def record_wake_turn(conn: AsyncConnection, *, run_id: UUID, wake_turn_id: UUID) -> None:
    await conn.execute(
        text("UPDATE arv2_discovery_run SET wake_turn_id = :t WHERE run_id = :r"),
        {"t": wake_turn_id, "r": run_id},
    )


async def release_discovery_for_turn(
    conn: AsyncConnection, *, workspace_id: str, turn_id: UUID
) -> UUID | None:
    released = await conn.scalar(
        text(
            "UPDATE arv2_discovery_run SET released_at = now() WHERE workspace_id = :w "
            f"AND wake_turn_id = :t AND {_ACTIVE} RETURNING run_id"
        ),
        {"w": workspace_id, "t": turn_id},
    )
    return None if released is None else UUID(str(released))
```

Add the new names to `__all__`. `SHOWN_DISPOSITIONS` stays `("pass", "partial", "unclear")` — `excluded` is not shown.

- [ ] **Step 5: Run the store tests, the migration smoke and the enum/parity tests**

Run: `uv run pytest tests/arv2/test_discovery_store_db.py -q && make db-smoke`
Expected: PASS; `db-smoke` up → down → up clean on a throwaway DB; `uv run alembic heads` prints one head.

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/*_agent_authored_discovery.py platform/api/clue_api/arv2/discovery_store.py tests/arv2/test_discovery_store_db.py
git commit -m "Discovery runs carry the agent's brief, a project lock, stop and wake"
```

---

### Task 2: The brief model and gate roles

**Files:**
- Create: `platform/api/clue_api/arv2/discovery_request.py`
- Test: `tests/arv2/test_discovery_request.py`

**Interfaces:**
- Consumes: `clue_api.arv2.discovery_brief.Gate`, `parse_window_months`; `clue_api.arv2.discovery_verifier.GateVerdict`.
- Produces:
  - `GateRole = Literal["must", "must_not", "prefer"]`, `DiscoverySource = Literal["websets", "search"]`
  - `class BriefGate(BaseModel)`: `key: str` (`^[a-z][a-z0-9_]{1,63}$`), `rule: str` (1–500), `test: str` (1–800), `role: GateRole`
  - `class DiscoveryBrief2(BaseModel)`: `source: DiscoverySource`, `query: str` (1–600), `criteria: list[str]` (1–5 items, each 1–300), `gates: list[BriefGate]` (2–8, unique keys)
  - `def verifier_gates(brief: DiscoveryBrief2) -> tuple[Gate, ...]`
  - `@dataclass(frozen=True) class RoleOutcome: excluded_by: str | None; fit: float | None; shown_disposition: str | None`
  - `def apply_roles(brief: DiscoveryBrief2, verdicts: Sequence[GateVerdict]) -> RoleOutcome`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from pydantic import ValidationError

from clue_api.arv2.discovery_request import DiscoveryBrief2, apply_roles, verifier_gates
from clue_api.arv2.discovery_verifier import GateVerdict


def _brief(**over):
    base = {
        "source": "websets",
        "query": "Companies of <kind> that run <activity>.",
        "criteria": ["The company runs <activity>."],
        "gates": [
            {"key": "is_buyer", "rule": "The company runs <activity>.",
             "test": "Its site describes it.", "role": "must"},
            {"key": "sells_product", "rule": "The company sells <product> to <buyers>.",
             "test": "Its product pages.", "role": "must_not"},
            {"key": "uses_stack", "rule": "A <system> is in use within the last 24 months.",
             "test": "A job post names one.", "role": "prefer"},
        ],
    }
    return DiscoveryBrief2.model_validate({**base, **over})


def _v(key, verdict):
    return GateVerdict(key, verdict, "", "", "", "", "ok", verdict)


def test_structural_limits_are_enforced():
    with pytest.raises(ValidationError):
        _brief(criteria=[f"c{i}" for i in range(6)])
    with pytest.raises(ValidationError):
        _brief(gates=_brief().model_dump()["gates"][:1])
    with pytest.raises(ValidationError):
        dup = _brief().model_dump()["gates"]
        dup[1]["key"] = "is_buyer"
        _brief(gates=dup)
    with pytest.raises(ValidationError):
        _brief(source="linkedin")


def test_verifier_gates_carry_the_window():
    gates = verifier_gates(_brief())
    assert [g.key for g in gates] == ["is_buyer", "sells_product", "uses_stack"]
    assert gates[2].window_months == 24


def test_a_failed_must_excludes():
    out = apply_roles(_brief(), [_v("is_buyer", "fail"), _v("sells_product", "fail"),
                                 _v("uses_stack", "pass")])
    assert out.excluded_by == "is_buyer" and out.fit is None


def test_a_passed_must_not_excludes():
    out = apply_roles(_brief(), [_v("is_buyer", "pass"), _v("sells_product", "pass"),
                                 _v("uses_stack", "pass")])
    assert out.excluded_by == "sells_product"


def test_unclear_never_excludes_and_fit_counts_must_and_prefer_only():
    out = apply_roles(_brief(), [_v("is_buyer", "unclear"), _v("sells_product", "unclear"),
                                 _v("uses_stack", "pass")])
    assert out.excluded_by is None
    assert out.fit == pytest.approx(0.75)  # (0.5 + 1) / 2 — the must_not gate is not scored
    assert out.shown_disposition == "unclear"


def test_a_failed_prefer_is_shown_as_partial():
    out = apply_roles(_brief(), [_v("is_buyer", "pass"), _v("sells_product", "fail"),
                                 _v("uses_stack", "fail")])
    assert out.excluded_by is None and out.shown_disposition == "partial"
    assert out.fit == pytest.approx(0.5)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/arv2/test_discovery_request.py -q` — Expected: FAIL (module missing). First confirm the `GateVerdict` positional field order with `sed -n '/^class GateVerdict/,/^$/p' platform/api/clue_api/arv2/discovery_verifier.py` and adjust `_v` to it.

- [ ] **Step 3: Implement**

```python
"""The discovery brief the Head of ABM writes (spec 2026-09-30 §3), and how gate roles decide."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clue_api.arv2.discovery_brief import Gate, parse_window_months
from clue_api.arv2.discovery_verifier import GateVerdict, disposition

GateRole = Literal["must", "must_not", "prefer"]
DiscoverySource = Literal["websets", "search"]


class BriefGate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    rule: str = Field(min_length=1, max_length=500)
    test: str = Field(min_length=1, max_length=800)
    role: GateRole


class DiscoveryBrief2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: DiscoverySource
    query: str = Field(min_length=1, max_length=600)
    criteria: list[str] = Field(min_length=1, max_length=5)
    gates: list[BriefGate] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def _check(self) -> DiscoveryBrief2:
        if any(not c.strip() or len(c) > 300 for c in self.criteria):
            raise ValueError("every criterion is 1-300 characters")
        keys = [g.key for g in self.gates]
        if len(set(keys)) != len(keys):
            raise ValueError("gate keys must be unique")
        return self


def verifier_gates(brief: DiscoveryBrief2) -> tuple[Gate, ...]:
    return tuple(
        Gate(key=g.key, rule=g.rule, test=g.test, window_months=parse_window_months(g.rule, g.test))
        for g in brief.gates
    )


@dataclass(frozen=True)
class RoleOutcome:
    excluded_by: str | None
    fit: float | None
    shown_disposition: str | None


def apply_roles(brief: DiscoveryBrief2, verdicts: Sequence[GateVerdict]) -> RoleOutcome:
    """A failed ``must`` or a passed ``must_not`` excludes; an unclear never does. Fit and the
    shown disposition are over the ``must`` and ``prefer`` gates only."""
    role = {g.key: g.role for g in brief.gates}
    for v in verdicts:
        if (role[v.gate_key] == "must" and v.verdict == "fail") or (
            role[v.gate_key] == "must_not" and v.verdict == "pass"
        ):
            return RoleOutcome(excluded_by=v.gate_key, fit=None, shown_disposition=None)
    scored = [v for v in verdicts if role[v.gate_key] != "must_not"]
    if not scored:
        return RoleOutcome(excluded_by=None, fit=None, shown_disposition="unclear")
    earned = sum(1.0 if v.verdict == "pass" else 0.5 if v.verdict == "unclear" else 0.0 for v in scored)
    return RoleOutcome(excluded_by=None, fit=earned / len(scored), shown_disposition=disposition(scored))
```

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/arv2/test_discovery_request.py -q` → PASS; `uv run ruff check platform/api/clue_api/arv2/discovery_request.py`.

- [ ] **Step 5: Commit** — `git add platform/api/clue_api/arv2/discovery_request.py tests/arv2/test_discovery_request.py && git commit -m "The discovery brief the agent writes, and how gate roles exclude"`

---

### Task 3: `launch_arv2_discovery@2` and the project lock

**Files:**
- Modify: `platform/api/clue_api/arv2/discovery_launch.py`
- Test: `tests/arv2/test_discovery_launch_db.py`

**Interfaces:**
- Consumes: Task 1 store (`active_discovery_for_project`, new `DiscoveryRunRow` fields), Task 2 `DiscoveryBrief2`.
- Produces: `Arv2DiscoveryRequest` gains `brief: DiscoveryBrief2 | None = None`; `launch_arv2_discovery` refuses a request without `brief` with code `brief_required`, refuses `discovery_in_progress` (message names the active `run_id` and `launched_thread_id`), and writes `brief_json`, `source`, `launched_thread_id`, `launching_turn_id`. New tool class `LaunchArv2DiscoveryV2Tool` (`name="launch_arv2_discovery"`, `version="2"`, input `LaunchArv2DiscoveryV2Input`). `LaunchArv2DiscoveryTool` (`@1`) stays registered and its `preconditions` always return `PreconditionFailure("discovery_tool_retired", "…use launch_arv2_discovery@2…")`. `build_arv2_discovery_tools` returns both.

- [ ] **Step 1: Write the failing DB tests** (in `tests/arv2/test_discovery_launch_db.py`, reusing its existing seed/fixture helpers for a project with a pinned confirmed ICP and a turn submission; `BRIEF` is the Task 2 `_brief()` dict)

```python
def test_a_launch_records_the_agents_brief_and_its_thread(require_db): ...
    # launch with brief=DiscoveryBrief2.model_validate(BRIEF) and launching_turn_ref of a seeded
    # submission on thread "thr_1"; assert run.brief == BRIEF, run.source == "websets",
    # run.launched_thread_id == "thr_1", run.relaxed_enabled is False, run.criteria_gate_keys == ()

def test_a_second_ask_while_one_runs_is_refused_by_name(require_db): ...
    # first launch (request_key "k1") succeeds; second (request_key "k2", other thread) raises
    # Arv2DiscoveryRefused with code "discovery_in_progress" and the first run id in its message

def test_replaying_the_same_ask_returns_the_same_run(require_db): ...
    # launch twice with request_key "k1": second receipt.replayed is True, same run_id, no refusal

def test_a_launch_without_a_brief_is_refused(require_db): ...
    # Arv2DiscoveryRequest(..., brief=None) -> code "brief_required"

def test_two_simultaneous_launches_create_one_run(require_db): ...
    # two connections, two different request keys, both in open transactions: the second insert
    # hits arv2_discovery_run_project_active; assert it surfaces as Arv2DiscoveryRefused
    # ("discovery_in_progress"), never as IntegrityError
```

Write each body in the file's existing style (its `_launch` helper shows the seed + call pattern); assert exactly the lines in the comments.

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/arv2/test_discovery_launch_db.py -q` → FAIL.

- [ ] **Step 3: Implement**

In `discovery_launch.py`:
1. Remove the `compile_brief` / `BriefError` import and the compile block; `criteria_gate_keys = ()`, `relaxed_enabled = False`.
2. Add `brief: DiscoveryBrief2 | None = None` to `Arv2DiscoveryRequest`; at the top of `launch_arv2_discovery` (after the enabled/target checks) raise `Arv2DiscoveryRefused("brief_required", "a discovery run is launched with the brief the Head of ABM wrote")` when it is `None`.
3. Resolve the launching turn and thread with one read (same prefix parsing as `_requesting_human`):

```python
_TURN_THREAD = text(
    "SELECT thread_id FROM agent_turn_submission WHERE turn_id = :turn_id AND workspace_id = :w"
)


async def _launching_turn(conn: AsyncConnection, request: Arv2DiscoveryRequest) -> tuple[UUID | None, str | None]:
    ref = request.launching_turn_ref or request.request_key
    if not ref or not ref.startswith(_TURN_ACTION_PREFIX):
        return None, None
    try:
        turn_id = UUID(ref[len(_TURN_ACTION_PREFIX):])
    except ValueError:
        return None, None
    thread = await conn.scalar(_TURN_THREAD, {"turn_id": turn_id, "w": request.workspace_id})
    return (turn_id, str(thread)) if thread else (None, None)
```

4. `_request_sha256` payload gains `"brief": request.brief.model_dump(mode="json")` and drops `relaxed_enabled`/`criteria_gate_keys`.
5. Before inserting: `active = await active_discovery_for_project(...)`; if `active` is not `None` and `active.request_sha256 != request_sha` → raise `Arv2DiscoveryRefused("discovery_in_progress", f"discovery run {active.run_id} is already running in conversation {active.launched_thread_id or 'outside chat'} of this project")`.
6. Wrap `create_discovery_run(...)` in `async with conn.begin_nested():` and catch `sqlalchemy.exc.IntegrityError` whose `str()` contains `arv2_discovery_run_project_active` → re-read `active_discovery_for_project` and raise the same `discovery_in_progress` refusal. Pass `brief=request.brief.model_dump(mode="json")`, `source=request.brief.source`, `launched_thread_id`, `launching_turn_id` into `DiscoveryRunRow`.
7. The v2 tool:

```python
class LaunchArv2DiscoveryV2Input(ToolInput):
    project_id: str
    target_count: int = Field(default=20, ge=1, le=500)
    source: DiscoverySource
    query: str
    criteria: list[str]
    gates: list[BriefGate]


class LaunchArv2DiscoveryV2Tool(LaunchArv2DiscoveryTool):
    version = "2"
    model_description = (
        "Launch account discovery for one project with the search you write: what kind of company "
        "to find (query), what every company must satisfy (criteria), and the checks run on every "
        "company found (gates, each with a role: must, must_not or prefer). Read section 7b of the "
        "stage0-interview skill before calling. The project needs a confirmed ICP and product set. "
        "A successful result means the run was created or replayed, never that companies were "
        "found; this conversation stays busy until the run ends and you get a turn with its "
        "summary. " + tool_manual_link("launch_arv2_discovery")
    )
    input_model = LaunchArv2DiscoveryV2Input
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + project + the approving user action + the brief + target count",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("project_id", "target_count", "source"))

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, LaunchArv2DiscoveryV2Input)
        assert self._service is not None and ctx.action_ref is not None
        try:
            brief = DiscoveryBrief2.model_validate(
                inputs.model_dump(include={"source", "query", "criteria", "gates"})
            )
        except ValidationError as bad:
            raise PreconditionFailed([PreconditionFailure("brief_invalid", str(bad))]) from bad
        request = Arv2DiscoveryRequest(
            workspace_id=ctx.workspace_id,
            project_id=inputs.project_id,
            requested_by_user_id=ctx.actor_id or ctx.actor,
            launching_turn_ref=ctx.action_ref if ctx.principal_kind == "service" else None,
            request_key=ctx.action_ref,
            target_count=inputs.target_count,
            brief=brief,
        )
        try:
            receipt = await self._service.launch(request)
        except Arv2DiscoveryRefused as refused:
            raise PreconditionFailed([PreconditionFailure(refused.code, str(refused))]) from refused
        return ToolResult(
            tool=self.name, version=self.version,
            references={"run_id": str(receipt.run_id), "replayed": receipt.replayed},
            replayed=receipt.replayed,
        )
```

`@1`'s `preconditions` returns the retirement refusal; `build_arv2_discovery_tools` returns `(LaunchArv2DiscoveryTool(service), LaunchArv2DiscoveryV2Tool(service))`. Update `Arv2DiscoveryRefused`'s docstring code list.

- [ ] **Step 4: Run** — `uv run pytest tests/arv2/test_discovery_launch_db.py tests/arv2/test_discovery_launch_requester.py -q` → PASS. Update any old test that launched through `@1` or expected `compile_brief` behaviour to the v2 request (these tests describe the retired behaviour; replace, don't delete coverage).

- [ ] **Step 5: Commit** — `git commit -m "launch_arv2_discovery@2: the agent's brief, one discovery per project"`

---

### Task 4: The driver — rounds with the same brief, roles, stop, summary, end

**Files:**
- Modify: `platform/api/clue_api/arv2/discovery_driver.py`
- Test: `tests/arv2/test_discovery_driver_db.py`, `tests/arv2/test_discovery_driver.py`

**Interfaces:**
- Consumes: Tasks 1–2; `ExaClient.search(query, category="company", num_results=…, exclude_domains=…)`.
- Produces: a `DiscoveryWake` protocol in the driver module (`async def queue(self, conn: AsyncConnection, run: DiscoveryRunRow, summary: Mapping[str, Any], message: str) -> UUID | None`), accepted by `Arv2DiscoveryWorkHandler(..., wake: DiscoveryWake | None = None)` and `build_arv2_discovery_handler(..., wake=None)`; `def summary_message(run_id: UUID, summary: Mapping[str, Any]) -> str` (the spec §6.3 text).

- [ ] **Step 1: Write the failing tests** (extend the file's scripted-transport fakes: `_script()`, `_RoutedTransport`, `_company_routes`)

```python
# tests/arv2/test_discovery_driver_db.py
def test_rounds_repeat_the_same_brief_until_filled(require_db): ...
    # target 3; round 1 webset yields 2 companies (one excluded by a must_not), round 2 yields 2 more;
    # assert the two searches sent the identical query/criteria, round 2 excluded round 1's webset,
    # 3 companies joined the project, the excluded one is a candidate with disposition "excluded"
    # and excluded_by_gate set, and summary_json["end_reason"] == "filled"

def test_the_run_ends_at_the_round_cap(require_db): ...
    # settings.arv2_discovery_max_topups = 1; every round yields only excluded companies;
    # assert exactly 2 searches, run.end_reason == "round_cap", no project accounts

def test_a_round_with_nothing_new_ends_dry(require_db): ...

def test_the_search_source_excludes_seen_domains(require_db): ...
    # source "search": round 2's /search body carries exclude_domains == every domain seen

def test_stop_cancels_the_webset_and_keeps_what_was_verified(require_db): ...
    # request_discovery_stop after the first item is verified; assert a websets cancel call,
    # a final items read, run.status == "stopped", end_reason "stopped", the verified company kept

def test_a_threadless_run_releases_its_lock_at_the_end(require_db): ...
    # launched_thread_id None; after the run: active_discovery_for_project(...) is None, no wake

def test_a_threaded_run_hands_its_summary_to_the_wake(require_db): ...
    # a fake DiscoveryWake records (run_id, message); assert message == summary_message(...) and
    # the run is NOT released (released_at IS NULL) and wake_turn_id is recorded

# tests/arv2/test_discovery_driver.py (offline)
def test_the_summary_message_matches_the_spec_shape(): ...
    # summary_message(uuid, {...}) == the exact multi-line text of spec §6.3 for a fixed summary
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/arv2/test_discovery_driver.py tests/arv2/test_discovery_driver_db.py -q` → FAIL.

- [ ] **Step 3: Implement** (edit points in `discovery_driver.py`)

1. **Settings:** read `self._settings.arv2_discovery_max_topups` (Task 7 adds it; until then add the field in `libs/clue-config/clue_config/settings.py` here: `arv2_discovery_max_topups: int = Field(default=3, ge=0, le=15)`).
2. **`_compose`:** replace the `compile_brief(...)` call with
   `brief2 = DiscoveryBrief2.model_validate(run.brief)` — when `run.brief is None` raise `Arv2DiscoveryRefused("brief_missing", "this run was launched without an agent brief")` (contained → `needs_review`). Keep `state.brief` a `DiscoveryBrief` built as `DiscoveryBrief(query=brief2.query, criteria=tuple(brief2.criteria), criteria_gate_keys=(), gates=verifier_gates(brief2), exclusions=())` and add `state.brief2 = brief2`, `state.excluded: dict[str, list[str]] = {}`, `state.rounds_dry = False`.
3. **`_search` loop** (replaces the strict/topup/relaxed sequencing and `_criteria_for`):

```python
    async def _search(self, state: _RunState) -> None:
        last = 1 + self._settings.arv2_discovery_max_topups
        for ordinal in range(len(state.searches) + 1, last + 1):
            if state.shown >= state.run.target_count or state.end_reason is not None:
                return
            if await self._stop_requested(state):
                state.end_reason = "stopped"
                return
            search = await self._open_search(state, ordinal, "round", state.brief.criteria)
            before = len(state.seen)
            if state.brief2.source == "search":
                await self._run_search_round(state, search)
            else:
                await self._run_search(state, search)
            if len(state.seen) == before:
                state.end_reason = "dry"
                return
        if state.shown < state.run.target_count and state.end_reason is None:
            state.end_reason = "round_cap"
```

   (`state.end_reason: str | None = None` is a new `_RunState` field; `"filled"` is set in `_land` when `shown >= target_count`.) Delete `_criteria_for`, `relaxed_criteria` and their tests.
4. **`_open_search`:** record `source=state.brief2.source` on the `SearchRow`; `exclude_webset_ids` as today.
5. **`_run_search_round` (search source):**

```python
    async def _run_search_round(self, state: _RunState, search: SearchRow) -> None:
        exclude = sorted(state.seen | state.project_domains | state.found_before)
        result = await self._hop(
            state,
            lambda caller: self._clients.exa(caller).search(
                state.brief.query, category="company", num_results=min(100, 2 * search.asked),
                exclude_domains=exclude or None, label=f"discovery-search-{search.ordinal}",
            ),
        )
        items = [_item_from_hit(hit) for hit in result.results if hit.url]
        state.found_by_search[search.ordinal] = len(items)
        tasks = []
        for item in items:
            domain = registrable_domain(item.url) or ""
            if not domain or domain in state.seen:
                continue
            state.seen.add(domain)
            tasks.append(asyncio.create_task(self._verify_contained(state, item, pass_="strict")))
        await self._drain_pool(set(tasks))
        async with self._connection() as conn:
            await self._store.finish_search(conn, run_id=state.run.run_id, ordinal=search.ordinal,
                                            found=len(items), analyzed=None, recall_estimate=None)
```

   with `_item_from_hit(hit) -> WebsetItem` building a `WebsetItem(item_id=f"search:{hit.url}", search_id=None, url=hit.url, name=hit.title or hit.url, description=(hit.text or "")[:400], hq_city=None, hq_state=None, hq_country_code=None, employees=None, revenue_annual=None, funding_total=None, evaluations=(), raw={"url": hit.url, "title": hit.title})`.
6. **Stop inside a webset round:** in `_watch_and_verify`'s loop, before each poll: `if await self._stop_requested(state): raise _Stopped()`; `_Stopped(Arv2Error)` is caught in `_run` → `await self._stop_webset(state)` (existing: cancel + final read) → `state.end_reason = "stopped"`. `_stop_requested` opens a connection and calls `store.stop_requested`.
7. **`_verify_candidate`:** after `verdicts = await self._verify_gates(...)`:

```python
        outcome = apply_roles(state.brief2, verdicts)
        if outcome.excluded_by is not None:
            async with self._connection() as conn:
                await self._store.upsert_candidate(
                    conn, replace(row, disposition="excluded", excluded_by_gate=outcome.excluded_by,
                                  verdicts=tuple(v.as_json() for v in verdicts)),
                )
            state.excluded.setdefault(outcome.excluded_by, []).append(item.name)
            return
        fit, outcome_disposition = outcome.fit, outcome.shown_disposition
```

   and use `fit`/`outcome_disposition` where the code used `fit_score(verdicts)`/`disposition(verdicts)`.
8. **Summary and end** — in `_land` (and the stop/failure paths):

```python
def build_summary(state: _RunState) -> dict[str, Any]:
    return {
        "asked": state.run.target_count,
        "added": state.shown,
        "excluded": sum(len(v) for v in state.excluded.values()),
        "unclear": state.unclear_count,
        "excluded_by": [
            {"gate": gate, "role": next(g.role for g in state.brief2.gates if g.key == gate),
             "count": len(names), "example": names[0]}
            for gate, names in sorted(state.excluded.items(), key=lambda kv: -len(kv[1]))
        ],
        "criteria_rates": [{"criterion": c, "rate": r} for c, r in state.strict_rates],
        "searches": len(state.searches),
        "end_reason": state.end_reason,
        "spend_usd": str(state.cost_usd),
    }


def summary_message(run_id: UUID, summary: Mapping[str, Any]) -> str:
    ended = summary["end_reason"]
    if ended == "round_cap":
        ended = f"round cap ({summary['searches']} searches)"
    lines = [
        f"Discovery finished (run {run_id}). Asked for {summary['asked']}, added "
        f"{summary['added']}, excluded {summary['excluded']}, unclear {summary['unclear']}.",
        f"Ended: {ended.replace('_', ' ')}.",
    ]
    if summary["excluded_by"]:
        lines.append("Excluded by: " + "; ".join(
            f"{e['gate']} ({e['role']}) {e['count']} — e.g. {e['example']}"
            for e in summary["excluded_by"]) + ".")
    if summary["criteria_rates"]:
        lines.append("Criteria pass rates, last search: " + "; ".join(
            f"\"{c['criterion']}\" {round(float(c['rate']))}%" for c in summary["criteria_rates"]
            if c["rate"] is not None) + ".")
    lines.append(f"Spend: ${Decimal(summary['spend_usd']):.2f}.")
    return "\n".join(lines)
```

   (`state.unclear_count` increments when `outcome_disposition == "unclear"`.) At the end of `_run`: `end_reason = state.end_reason or ("filled" if state.shown >= target else "dry")`; status `"stopped"` for stopped, `"needs_review"` for failures (`end_reason="failed"`), else `"completed"`. Then in one transaction:

```python
        threaded = state.run.launched_thread_id is not None and self._wake is not None
        async with self._connection() as conn:
            await self._store.end_discovery_run(conn, run_id=run.run_id, status=status,
                                                end_reason=end_reason, summary=summary,
                                                release=not threaded)
            if threaded:
                wake_turn = await self._wake.queue(conn, run, summary,
                                                   summary_message(run.run_id, summary))
                if wake_turn is None:
                    await self._store.end_discovery_run(conn, run_id=run.run_id, status=status,
                                                        end_reason=end_reason, summary=summary,
                                                        release=True)
                else:
                    await self._store.record_wake_turn(conn, run_id=run.run_id,
                                                       wake_turn_id=wake_turn)
```

   The contained-failure path (`_contain`) calls the same end block with `end_reason="failed"` so a failed run still wakes the agent and releases its locks.

- [ ] **Step 4: Run** — `uv run pytest tests/arv2/test_discovery_driver.py tests/arv2/test_discovery_driver_db.py tests/arv2/test_discovery_verifier.py -q` → PASS (update the existing tests that asserted strict/topup/relaxed sequencing to the round model).

- [ ] **Step 5: Commit** — `git commit -m "Discovery driver: rounds with the agent's brief, roles, stop, summary"`

---

### Task 5: Thread hold, wake turn, release, stop route

**Files:**
- Create: `platform/api/clue_api/discovery_wake.py`
- Modify: `platform/api/clue_api/agent_turn_submission.py` (dispatch + ordering + `DERIVATION_DISCOVERY_FINISHED`), the `AGENT_TURN` handler's post-terminal path (find it with `grep -n "dispatch_next_thread_turn" platform/api/clue_api/agent_turn_fleet_wiring.py`), `clue_projections.threads_running` (find with `grep -rn "def threads_running" libs platform`), `platform/api/clue_api/fleet_main.py` (compose the wake into `build_arv2_discovery_handler`), `platform/api/clue_api/chat/router.py` (stop route)
- Test: `tests/api/test_discovery_wake_db.py`

**Interfaces:**
- Consumes: Task 1 store functions; Task 4 `DiscoveryWake` protocol.
- Produces: `class DbDiscoveryWake` (implements `DiscoveryWake.queue`); `DERIVATION_DISCOVERY_FINISHED = "discovery_finished"`; route `POST /api/v1/projects/{project_id}/discovery-runs/{run_id}/stop` → `{"run_id": str, "stop_requested": bool}` (mount beside the existing thread/turn routes in `chat/router.py`, same auth dependency as the turn stop route).

- [ ] **Step 1: Write the failing DB tests**

```python
def test_the_wake_is_a_derived_turn_that_goes_first(require_db): ...
    # seed a thread with a finished launching turn and TWO user submissions accepted while the
    # run was active; DbDiscoveryWake.queue(...) returns a turn id; dispatch_next_thread_turn
    # offers the WAKE turn (derivation "discovery_finished", derived_from = launching turn),
    # not the earlier user submissions

def test_user_turns_are_held_while_a_discovery_is_unreleased(require_db): ...
    # active run on the thread, no wake yet: dispatch_next_thread_turn returns None

def test_finishing_the_wake_turn_releases_the_run_then_the_queue_moves(require_db): ...
    # mark the wake task done, run the post-terminal hook: release_discovery_for_turn releases,
    # and the next dispatch offers the first held user submission

def test_a_running_discovery_marks_its_thread_running(require_db): ...
    # threads_running(workspace, [thread]) contains the thread while the run is unreleased

def test_stop_route_marks_the_run(require_db): ...
    # POST .../discovery-runs/{run}/stop -> 200 {"stop_requested": true}; another project's run -> 404
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/api/test_discovery_wake_db.py -q` → FAIL.

- [ ] **Step 3: Implement**

`discovery_wake.py`:

```python
"""The Head of ABM's turn at the end of a discovery run (spec 2026-09-30 §4 "The wake")."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_submission import (
    DERIVATION_DISCOVERY_FINISHED,
    dispatch_next_thread_turn,
    get_submission,
    insert_submission,
    turn_id_for_submission,
)
from clue_api.arv2.discovery_store import DiscoveryRunRow
from clue_api.conversation_capture import CONVERSATION_CONTEXT_BINDING_KIND, persist_user_turn


class DbDiscoveryWake:
    def __init__(self, artifacts) -> None:  # DurableAgentArtifactStore, as the turn route uses
        self._artifacts = artifacts

    async def queue(
        self, conn: AsyncConnection, run: DiscoveryRunRow, summary: Mapping[str, Any], message: str
    ) -> UUID | None:
        if run.launched_thread_id is None or run.launching_turn_id is None:
            return None
        launching = await get_submission(conn, workspace_id=run.workspace_id,
                                         turn_id=run.launching_turn_id)
        if launching is None:
            return None
        key = f"discovery-finished:{run.run_id}"
        turn_id = turn_id_for_submission(workspace_id=run.workspace_id,
                                         thread_id=run.launched_thread_id, idempotency_key=key)
        captured = await persist_user_turn(
            conn, artifacts=self._artifacts, workspace_id=run.workspace_id, brand_id=run.brand_id,
            project_id=run.project_id, turn_id=turn_id, message=message,
            binding_kind=CONVERSATION_CONTEXT_BINDING_KIND,
        )
        await insert_submission(
            conn, turn_id=turn_id, workspace_id=run.workspace_id, project_id=run.project_id,
            thread_id=run.launched_thread_id,
            submitted_by_user_id=launching.submitted_by_user_id,
            submitted_via_membership_id=launching.submitted_via_membership_id,
            onboarding_input_id=captured.onboarding_input_id,
            message_artifact_key=captured.artifact_ref.artifact_key,
            message_sha256=captured.artifact_ref.content_sha256,
            idempotency_key=key, derivation=DERIVATION_DISCOVERY_FINISHED,
            derived_from_turn_id=run.launching_turn_id,
        )
        await dispatch_next_thread_turn(conn, workspace_id=run.workspace_id,
                                        thread_id=run.launched_thread_id)
        return turn_id
```

(Check `captured.artifact_ref` field names against `CapturedUserTurn` and the digest attribute name on the artifact ref; use what they are.)

`agent_turn_submission.py`:
- `DERIVATION_DISCOVERY_FINISHED = "discovery_finished"`.
- In `dispatch_next_thread_turn`, after the `queue_hold_control_id` check:

```python
    discovery = (
        await conn.execute(
            text(
                "SELECT wake_turn_id FROM arv2_discovery_run WHERE workspace_id = :w "
                "AND launched_thread_id = :t AND released_at IS NULL LIMIT 1"
            ),
            {"w": workspace_id, "t": thread_id},
        )
    ).first()
    only_turn = None
    if discovery is not None:
        if discovery[0] is None:
            return None  # the discovery is still running: hold the thread
        only_turn = UUID(str(discovery[0]))  # its wake goes first
```

  and when `only_turn` is set, select that submission instead of `_NEXT_PENDING_SQL` (skip it and return `None` if its task is already terminal). (Raw SQL here, not the store: this module may read the table, and `clue_api.arv2` must not import this module.)
- `_NEXT_PENDING_SQL` is unchanged (the wake is chosen explicitly above).

Post-terminal hook in the `AGENT_TURN` handler, immediately before its existing `dispatch_next_thread_turn(...)` call, in the same transaction:

```python
    await release_discovery_for_turn(conn, workspace_id=workspace_id, turn_id=turn_id)
```

`threads_running`: union in `SELECT launched_thread_id FROM arv2_discovery_run WHERE workspace_id = :w AND launched_thread_id = ANY(:t) AND released_at IS NULL`.

`fleet_main.py`: pass `wake=DbDiscoveryWake(<the durable artifact store the turn handler is composed with>)` to `build_arv2_discovery_handler`.

Stop route in `chat/router.py`: authorize as the turn-stop route does, then `request_discovery_stop(conn, workspace_id=who.workspace_id, project_id=project_id, run_id=run_id)`; `None` → 404 `DISCOVERY_RUN_NOT_FOUND`.

- [ ] **Step 4: Run** — `uv run pytest tests/api/test_discovery_wake_db.py tests/api -k "dispatch or thread or submission" -q --ignore-glob='*_live.py'` → PASS.

- [ ] **Step 5: Commit** — `git commit -m "Hold a thread during its discovery; wake the Head of ABM first; Stop"`

---

### Task 6: Reads — the run read, the thread wire, status.md

**Files:**
- Modify: `platform/api/clue_api/arv2/read_tools.py` (`read_discovery_run` → `@3`), `platform/api/clue_api/chat/schemas.py` (`ThreadWire.discovery`), the thread list/detail handlers in `chat/router.py`, the `status.md` compiler (find with `grep -rn "SHOWN_DISPOSITIONS" platform/api/clue_api --include=*.py`)
- Test: `tests/arv2/test_read_tools_discovery_db.py` (or the existing read-tool test file for `read_discovery_run`), `tests/api/test_chat_threads_db.py` (existing thread-listing test file)

**Interfaces:**
- Produces: `ReadDiscoveryRunOutput` (v3) adds `source: str`, `end_reason: str | None`, `summary: dict[str, Any] | None`, `excluded: tuple[DiscoveryCandidateView, ...]`, and each candidate view adds `excluded_by_gate: str | None`; `ThreadDiscoveryWire(_Wire)`: `run_id: str`, `stoppable: bool` (`True` until the run has an end reason); `ThreadWire.discovery: ThreadDiscoveryWire | None = None`.

- [ ] **Step 1: Failing tests** — the read returns the summary, end reason and the excluded companies separately from the shown ones; a thread with an unreleased run lists `discovery={"run_id": …, "stoppable": true}`, and after release `discovery` is `null`; `status.md` counts exclude `excluded`.
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** — `read_discovery_run@3` (keep `@2` registered for replay); the thread handlers call `active_discoveries_for_threads` once per page (same place `threads_running` is called) and pass `discovery=` into `thread_wire(...)` (add the parameter); `status.md` reads `end_reason` and the excluded count.
- [ ] **Step 4: Run** — the two test files → PASS.
- [ ] **Step 5: Commit** — `git commit -m "Discovery reads: summary, end reason, exclusions; the thread knows its discovery"`

---

### Task 7: Settings

**Files:**
- Modify: `libs/clue-config/clue_config/settings.py`, `.env.example`, `.env` (local), `tests/test_config_settings.py`

- [ ] **Step 1: Failing test** in `tests/test_config_settings.py`:

```python
def test_discovery_top_ups_default_and_bounds(monkeypatch):
    assert Settings().arv2_discovery_max_topups == 3
    monkeypatch.setenv("CLUE_ARV2_DISCOVERY_MAX_TOPUPS", "16")
    with pytest.raises(ValidationError):
        Settings()


def test_the_retired_discovery_settings_are_gone():
    fields = Settings.model_fields
    assert "arv2_discovery_criteria_gate_keys" not in fields
    assert "arv2_discovery_relaxed_auto" not in fields
```

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** — `arv2_discovery_max_topups: int = Field(default=3, ge=0, le=15)` (if Task 4 already added it, keep one definition); delete `arv2_discovery_criteria_gate_keys` and `arv2_discovery_relaxed_auto` and every reader (`grep -rn "criteria_gate_keys\|relaxed_auto" platform libs scripts --include=*.py`; `scripts/launch_arv2_discovery.py` loses `--criteria-gates`/`--no-relaxed` and gains `--brief PATH` — a JSON file validated as `DiscoveryBrief2`). In `.env.example` and `.env`: add `CLUE_ARV2_DISCOVERY_MAX_TOPUPS=3` in the discovery block with a one-line comment; remove the two retired lines.
- [ ] **Step 4: Run** — `uv run pytest tests/test_config_settings.py -q` → PASS; `grep -n "CRITERIA_GATE_KEYS\|RELAXED_AUTO" .env .env.example` → no output.
- [ ] **Step 5: Commit** — `git commit -m "Discovery settings: top-up cap in, gate-key and relaxed switches out"`

---

### Task 8: The Head of ABM's instructions and profile v70

**Files:**
- Create: `platform/agents/catalog/skills/stage0-interview/v43/SKILL.md` (copy v42, replace section 7b with spec §6.1 verbatim, bump `version`)
- Create: `platform/agents/catalog/skills/manual-discovery/v16/SKILL.md` (**founder review — text below**) and the other hand-written `manual-*` v16 copies the profile bump requires (copy v15 → v16, bump `version`, fix any `v15` self-paths)
- Modify: `platform/agents/catalog/manual/tool_notes.yaml` (spec §6.2; the pre-call pointer goes in whichever key the builder already renders before a tool — check `grep -n "afterwards\|before\|skill_section" platform/agents/clue_agents/manual/build.py`; if none renders pre-call text, put the pointer as the first sentence of `afterwards` instead and say so in the commit)
- Create: `platform/agents/catalog/profiles/head-of-abm/v70/profile.yaml` (copy v69; `version: v70`; skills `stage0-interview v43`, `manual-* v16` with new sha256s; tools: `launch_arv2_discovery` `version: '2'`, `read_discovery_run` `version: '3'`, with fresh schema digests)
- Modify: `platform/api/clue_api/agent_registry_wiring.py` (`AgentRole.HEAD_OF_ABM: "v70"` + comment), `platform/api/clue_api/chat/composer_context.py` (profile pin), generated manual chapters via `make manual`
- Test: `tests/agents/test_catalog.py`, `tests/api/test_agent_registry_wiring.py`

- [ ] **Step 1: Failing tests** — mirror what c3ce9f77c added for v69: the v70 profile loads, grants `launch_arv2_discovery@2` and not `@1`, pins `stage0-interview v43`, and the registry promotes v70.
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Write the catalog files.** `manual-discovery` v16 body (**show the founder before merging**):

```markdown
# Discovery: finding companies for this project

You run discovery with `launch_arv2_discovery`, and you write its search: what kind of company to
find, what every company must satisfy, and the checks run on every company found. Section 7b of
the stage0-interview skill says how to write them. The project's documents are your notes; nothing
reads text out of them for you.

## What one run holds

| Term | Meaning |
| --- | --- |
| `target_count` | how many companies the human asked for |
| `source` | `websets` or `search`, as you chose |
| `end_reason` | why the run ended: `filled`, `dry`, `round_cap`, `wall_clock`, `stopped` or `failed` |
| `summary` | what the run found, what it excluded and why, and what it cost — the same summary your end-of-run turn starts with |

Each time a human asks for accounts is a new run. The same ask retried is the same run, so it
buys nothing twice. Only one run is active in a project at a time.

## How a run works

1. The first search asks for `target_count` companies with your query and criteria, skipping every
   company this project already has or found before.
2. Each company found is checked: first its own website, then one question per gate.
3. A company is **excluded** when a `must` gate fails or a `must_not` gate passes. It does not join
   the project and does not count toward `target_count`. An unclear answer never excludes.
4. While the run has fewer companies than asked, it searches again with the **same** search —
   never a looser one — skipping everything seen so far, up to three more times.
5. It ends when it has enough companies, when a search finds nothing new, after the last allowed
   search, at the time limit, or when the human stops it. You then get a turn that starts with the
   summary.

## Verdicts, and the guards over them

Each gate produces one verdict: `pass`, `fail` or `unclear`. `fail` means a source contradicted the
rule; finding nothing is `unclear`. Three guards check the answer before it counts: the quoted
sentence must appear on the cited page; the page must be on the company's own domain or name the
company; and a time window is checked in code. A guard that overturns an answer makes it `unclear`.
The guard values you may see are `ok`, `quote_not_on_page`, `wrong_company`, `outside_window`,
`no_source` and `malformed`.

## Fit and dispositions

`fit` is over the `must` and `prefer` gates: a pass counts 1, an unclear counts one half.

| Disposition | Meaning |
| --- | --- |
| `pass` | every scored gate passed |
| `partial` | a `prefer` gate failed |
| `unclear` | nothing failed and not everything passed |
| `excluded` | a `must` failed or a `must_not` passed; kept on the run only |
| `duplicate_of_existing` | already one of this project's accounts |
| `found_before` | an earlier discovery of this project found it |

## The tallies

- **verified**: at least one gate verdict exists.
- **shown**: `pass`, `partial` or `unclear` — the companies added to the project.
- **excluded**: kept on the run with the gate that excluded them.
- **approved**: a human recorded the approval decision.

`approved` is the only decision the store holds; a company the human did not choose is not chosen,
never rejected.
```

- [ ] **Step 4: Regenerate and pin** — `make manual`; compute each changed skill's sha256 (`shasum -a 256 <file>`) and each tool's schema digest (`uv run python -c "from clue_toolbelt.envelope import _schema_sha256; …"` for the v2/v3 input and output models) into v70; `make manual-check`; `uv run pytest tests/agents/test_catalog.py tests/api/test_agent_registry_wiring.py -q` → PASS.
- [ ] **Step 5: Commit** — `git commit -m "Head of ABM v70: writes the discovery brief (stage0-interview v43, manual v16)"`

---

### Task 9: The ICP-synthesis comma fix

**Files:**
- Create: `platform/agents/catalog/skills/icp-synthesis/v3/SKILL.md` (copy v2; replace the front-matter format block with spec §9's block YAML, quoted values)
- Modify: the profile that pins `icp-synthesis` (find: `grep -rln "name: icp-synthesis" platform/agents/catalog/profiles | sort -V | tail -3`) → new version pinning v3, plus its registry pin
- Modify: `platform/api/clue_api/arv2/icp_authoring.py` (refusal)
- Test: `tests/arv2/test_icp_authoring_db.py`

- [ ] **Step 1: Failing test** — authoring an ICP whose `hard_gates` row carries a key with a `null` value that is not one of `key, rule, test, criterion` (the comma-split signature, e.g. the Task-0 trial's `BROKEN_ICP` gate) is refused with `icp_front_matter_invalid` naming the gate key; a block-YAML document with commas inside quoted values is accepted and round-trips its full text.
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** — in `icp_authoring.py`, after `parse_front_matter`, reject any `hard_gates`/`qualifier_fields` row with a `None`-valued key outside `{"key","rule","test","criterion","field_key","description","display","titles"}`; write the v3 skill and the profile bump.
- [ ] **Step 4: Run** — `uv run pytest tests/arv2/test_icp_authoring_db.py tests/agents/test_catalog.py -q` → PASS.
- [ ] **Step 5: Commit** — `git commit -m "ICP synthesis writes block YAML; authoring refuses comma-split gates"`

---

### Task 10: Frontend — busy thread and Stop

**Files:**
- Modify: `apps/frontend/src/features/projects/model/chat-thread.ts` (Zod `discovery`), the chat controller `apps/frontend/src/features/projects/hooks/use-project-chat-controller.ts`, its turns repository (the file behind `repositories.turns`, find with `grep -rn "stop(" apps/frontend/src/features/projects/data`), `apps/frontend/src/features/chat-shell/components/chat-surface.tsx`
- Test: the controller's and repository's existing `*.test.ts` files

**Interfaces:**
- Consumes: Task 6 `ThreadWire.discovery`, Task 5 stop route.
- Produces: controller fields `discoveryRunId: string | null`, `stopDiscovery(): Promise<void>`; repository `discoveries.stop({ projectId, runId })`.

- [ ] **Step 1: Failing tests** — the schema parses `discovery: {run_id, stoppable}` and `null`; with a discovery and no running turn the composer props are `running=true` and `onStop` calls `discoveries.stop` with the run id; after the thread reloads without `discovery`, `running` falls back to the turn state.
- [ ] **Step 2: Run** — `cd apps/frontend && npx tsx --test <the two test files>` → FAIL.
- [ ] **Step 3: Implement** — Zod `ThreadDiscoverySchema = z.object({ run_id: z.string(), stoppable: z.boolean() })`, `discovery: ThreadDiscoverySchema.nullable().optional()`; the controller keeps `discoveryRunId` from the thread read and reloads the thread when a `turn.*` frame for this thread arrives; `stopDiscovery` posts to `/api/v1/projects/{projectId}/discovery-runs/{runId}/stop` through the repository (HTTP + fixture adapters); in `chat-surface.tsx`: `running={chat.runningTurn !== null || chat.discoveryRunId !== null}` and `onStop={() => void (chat.runningTurn === null && chat.discoveryRunId ? chat.stopDiscovery() : chat.stopActiveTurn())}`. **The composer hint line from spec §7 is NOT added** until the founder/co-founder design ruling; the existing "N messages queued" line carries the queued state meanwhile.
- [ ] **Step 4: Run** — the tests pass; `cd apps/frontend && npm run design-system:build && npm run lint && npm run build` (lane stack down, port free) → green.
- [ ] **Step 5: Commit** — `git commit -m "Chat: a discovery keeps its thread busy and can be stopped"`

---

### Task 11: Live proof and records

**Files:**
- Modify: `docs/superpowers/drafts/2026-09-30-target-discovery-trial/README.md`, `_memory/` (new session note), `CLAUDE.md` backlog line (one bullet: shipped + residuals)

- [ ] **Step 1:** `uv run alembic upgrade head` on the lane DB; restart the platform API, design API and workers (design API by hand — `restart-api` does not restart it; see `_memory/2026-09-29-conduit-onboarding-watch-and-cost-fixes.md`).
- [ ] **Step 2:** In the app (Conduit hotel-operators project): ask for 10 accounts; confirm the thread shows running, a message typed meanwhile is held, the wake turn reports, then the held message runs. Grade the 10 with the trial's method.
- [ ] **Step 3:** Ask for 3 accounts three times; grade. Launch from a second thread while one runs → the agent reports the other conversation. Press Stop mid-run → `stopped`, verified companies kept, wake reports.
- [ ] **Step 4:** Force a short run (ask for 50 on a narrow brief) and record what the agent decided.
- [ ] **Step 5:** Record results, spend and any defect in `_memory/` and the trial README; commit.

---

## Self-review notes

- Spec coverage: §3 → Tasks 2–3; §4 → Task 4 (+ wake Task 5); §5 → Tasks 1, 3, 5; §6 → Task 8 (6.1, 6.2), Task 4 (6.3); §7 → Task 10; §8 → Tasks 1, 7, 8; §9 → Task 9; §10 → every task's tests + Task 11.
- Founder-review items before merge: `manual-discovery` v16 text (Task 8), the `@2` `model_description` (Task 3), the icp-synthesis v3 block (Task 9, already approved as spec §9).
