# Research Progress Card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One pinned card above the project chat's composer that shows, live, how far every account research run in the project has got, with a rotating one-line status of what each running agent is doing.

**Architecture:** The account-research driver stamps a `stage` on the job row at four points (claim, finalize, committee step, member launch). A workspace-scoped read folds every live run of a project into one document: counts, a percentage from four equal stage quarters per account with member research fractional, a pill state, and the list of running agents with their stage. The chat surface polls that read every 5 s while it returns a card, renders the founder's mockup pixel-for-pixel inside the composer dock, and rotates the status line round-robin every 4 s.

**Tech Stack:** Python 3.13 / SQLAlchemy async / Alembic / FastAPI (backend), pytest (offline + lane-DB), Next.js / TypeScript / Zod / node:test (frontend).

**Spec:** `docs/superpowers/specs/2026-09-12-research-progress-card-design.md`

## Global Constraints

- Pinned above the composer, not a transcript part; one card per project summing every live run; the mockup is the only state — **no chevron, no dismiss control, no per-account detail** (founder rulings 2026-09-12).
- Stage order is the driver's real order: `deep_research → synthesis → committee → member_research → done`.
- Four equal quarters per requested account; member research fractional by person jobs finished ÷ created; 100 only when every job is terminal.
- Completed lingers 60 s then disappears; "Needs attention" on any `needs_review`/`suspended` job or suspended run, and stays until that clears.
- Status-line wording exactly: "<Account> agent doing deep research" / "Synthesising our findings for <Account>" / "Finding the buying committee for <Account>" / "Diving deeper into each committee member of <Account>" / "Research complete for N accounts" / "<Account>: <reason>".
- ARV2 tables are the only source (ruling 2026-09-09). Migrations use a hash revision id chained off the current head (`2cd622be2da0`) with a reversible `downgrade()`.
- Offline suites without `.env`; DB suites only against the lane DB with `set -a; source .env; set +a` and `-p no:cacheprovider`. No AI attribution in commits. Never push.
- Frontend gates: `npm test`, `npm run lint`, `npx tsc --noEmit -p .` (50-error baseline), `npm run build` at the end.

---

## File map

| File | Responsibility |
|---|---|
| `alembic/versions/<hash>_arv2_research_job_stage.py` | `arv2_research_job.stage` column + CHECK |
| `tests/db/test_arv2_job_stage_migration.py` | migration up/down proof |
| `platform/api/clue_api/arv2/account_research_store.py` | `JobRow.stage`, `set_job_stage`, `_job` mapper |
| `tests/arv2/test_account_research_launch_db.py` | DB test for `set_job_stage` |
| `platform/api/clue_api/arv2/account_research_driver.py` | the four stamps |
| `platform/api/clue_api/arv2/account_research_tools.py` | the `synthesis` stamp inside both finalize tools |
| `tests/arv2/test_account_research_driver.py` | stamps recorded on the fake store |
| `platform/api/clue_api/arv2/research_progress.py` | pure fold: rows → card document (math, pill, agents) |
| `tests/arv2/test_research_progress.py` | pure tests |
| `platform/api/clue_api/frontend_read/contract_v1.py` | `ResearchProgressV1` models |
| `platform/api/clue_api/frontend_read/research_progress.py` | `GET /frontend/v1/projects/{id}/research/progress` |
| `platform/api/clue_api/frontend_read/app.py` | registration |
| `tests/api/test_frontend_read_research_progress.py` | DB test |
| `apps/frontend/src/features/projects/model/research-progress.ts` | Zod schema |
| `apps/frontend/src/features/projects/model/research-progress-line.ts` | the rotating sentence (pure) |
| `apps/frontend/src/features/projects/model/research-progress-line.test.ts` | its tests |
| `apps/frontend/src/features/accounts/data/research-progress.repository.ts` | `getResearchProgress(projectId)` over `fetchRead` |
| `apps/frontend/src/app/api/projects/[projectId]/research-progress/route.ts` | BFF |
| `apps/frontend/src/app/api/projects/research-progress-route.test.ts` | BFF test |
| `apps/frontend/src/features/projects/hooks/use-research-progress-controller.ts` | polling + rotation |
| `apps/frontend/src/features/projects/components/research-progress-card.tsx` | the card |
| `apps/frontend/src/features/projects/components/research-progress-card.module.css` | its styles |
| `apps/frontend/src/features/chat-shell/components/chat-surface.tsx` | mounts the card in the composer dock |
| `apps/frontend/src/features/projects/model/research-progress-contract.test.ts` | source-contract test |
| `apps/frontend/docs/api-contracts/projects.md` | contract note |

---

### Task 1: The `stage` column

**Files:**
- Create: `alembic/versions/<hash>_arv2_research_job_stage.py` (mint the hash with `alembic revision -m "arv2 research job stage"`; do not hand-pick)
- Test: `tests/db/test_arv2_job_stage_migration.py`

**Interfaces:**
- Produces: column `arv2_research_job.stage text NULL` with `CONSTRAINT arv2_research_job_stage CHECK (stage IS NULL OR stage IN ('deep_research','synthesis','committee','member_research'))`.

- [ ] **Step 1: Write the failing test**

```python
"""``arv2_research_job.stage`` (research progress card, spec 2026-09-12): up, constrained, down."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.claimstore.conftest import migrated_db, require_claimstore_db, rollback_conn  # noqa: F401
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_stage_column_exists_and_is_constrained() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            column = (
                await conn.execute(
                    text(
                        "SELECT is_nullable FROM information_schema.columns "
                        "WHERE table_name = 'arv2_research_job' AND column_name = 'stage'"
                    )
                )
            ).scalar_one_or_none()
            assert column == "YES"
            check = (
                await conn.execute(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conname = 'arv2_research_job_stage'"
                    )
                )
            ).scalar_one()
            for stage in ("deep_research", "synthesis", "committee", "member_research"):
                assert f"'{stage}'" in check

    run_async(scenario())
```

- [ ] **Step 2: Run to verify it fails**

Run: `set -a; source .env; set +a; .venv/bin/pytest tests/db/test_arv2_job_stage_migration.py -q -p no:cacheprovider`
Expected: FAIL — `column is None` (no such column).

- [ ] **Step 3: Write the migration**

Run `.venv/bin/alembic revision -m "arv2 research job stage"` (with `.env` sourced so the DSN resolves, or pass `-x` per `alembic.ini`), then replace the generated body with:

```python
"""arv2: research job stage — where a job is, for the research progress card

Revision ID: <generated>
Revises: 2cd622be2da0
Create Date: <generated>

Spec 2026-09-12 (research progress card) §1. The account driver stamps ``stage`` at four points:
``deep_research`` when the job is claimed, ``synthesis`` when the agent's finalize tool lands,
``committee`` when the committee step starts, ``member_research`` when the person jobs are
offered. A person job stamps ``deep_research`` and ``synthesis``. Terminal rows keep their last
stage. Nullable: every row that predates this migration, and a job nothing has claimed yet.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "<generated>"
down_revision: str | None = "2cd622be2da0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STAGES = "('deep_research', 'synthesis', 'committee', 'member_research')"


def upgrade() -> None:
    op.execute("ALTER TABLE arv2_research_job ADD COLUMN stage text")
    op.execute(
        "ALTER TABLE arv2_research_job ADD CONSTRAINT arv2_research_job_stage "
        f"CHECK (stage IS NULL OR stage IN {_STAGES})"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE arv2_research_job DROP CONSTRAINT arv2_research_job_stage")
    op.execute("ALTER TABLE arv2_research_job DROP COLUMN stage")
```

Keep the `revision`/`down_revision` values Alembic generated (only `down_revision` must equal `2cd622be2da0`; confirm with `.venv/bin/alembic heads` printing exactly one head afterwards).

- [ ] **Step 4: Upgrade the lane DB and run the test**

Run: `set -a; source .env; set +a; .venv/bin/alembic upgrade head && .venv/bin/alembic heads && .venv/bin/pytest tests/db/test_arv2_job_stage_migration.py -q -p no:cacheprovider`
Expected: one head; PASS.

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/*_arv2_research_job_stage.py tests/db/test_arv2_job_stage_migration.py
git commit -m "feat(arv2): arv2_research_job.stage — where a job is, for the research progress card"
```

---

### Task 2: `JobRow.stage` and `set_job_stage`

**Files:**
- Modify: `platform/api/clue_api/arv2/account_research_store.py` — `JobRow` (~line 148), `_job` (~line 808), new `set_job_stage` after `suspend_job` (~line 368)
- Test: `tests/arv2/test_account_research_launch_db.py`

**Interfaces:**
- Produces: `JobStage = Literal["deep_research", "synthesis", "committee", "member_research"]`; `JobRow.stage: JobStage | None`; `async def set_job_stage(conn, *, job_id: UUID, stage: JobStage) -> None` (also bumps `updated_at`).

- [ ] **Step 1: Write the failing test**

Append to `tests/arv2/test_account_research_launch_db.py` (reuse that file's own helpers for creating a run and a job — search `create_run(` and `create_job(` in it and copy the exact calls; import `set_job_stage` and `read_job`):

```python
def test_set_job_stage_moves_the_stage_and_updated_at_only() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            run, job_id = await _seed_run_with_one_account_job(conn)  # the file's helper; see above
            before = await read_job(conn, job_id=job_id)
            assert before is not None and before.stage is None
            await set_job_stage(conn, job_id=job_id, stage="deep_research")
            after = await read_job(conn, job_id=job_id)
            assert after is not None
            assert after.stage == "deep_research"
            assert after.status == before.status
            assert after.updated_at >= before.updated_at
            await set_job_stage(conn, job_id=job_id, stage="member_research")
            assert (await read_job(conn, job_id=job_id)).stage == "member_research"
    run_async(scenario())
```

If `JobRow` carries no `updated_at`, read it with `SELECT updated_at FROM arv2_research_job WHERE job_id = :id` before and after instead.

- [ ] **Step 2: Run to verify it fails**

Run: `set -a; source .env; set +a; .venv/bin/pytest tests/arv2/test_account_research_launch_db.py -q -p no:cacheprovider -k set_job_stage`
Expected: FAIL — `ImportError` on `set_job_stage`.

- [ ] **Step 3: Implement**

Near the other `Literal` aliases at the top of the store (search `JobStatus = Literal`):

```python
JobStage = Literal["deep_research", "synthesis", "committee", "member_research"]
```

In `JobRow` add after `media_seconds: int`:

```python
    #: Where the job is (spec 2026-09-12 §1); ``None`` before its first claim or on rows that
    #: predate the column. Stamped by the driver, read by the research progress card.
    stage: JobStage | None = None
```

In `_job`, add `stage=row["stage"],` to the constructor call.

After `suspend_job`:

```python
async def set_job_stage(conn: AsyncConnection, *, job_id: UUID, stage: JobStage) -> None:
    """Stamp where the job is (spec 2026-09-12 §1). Never touches status or the receipt."""
    await conn.execute(
        text(
            "UPDATE arv2_research_job SET stage = :stage, updated_at = now() "
            "WHERE job_id = :job_id"
        ),
        {"stage": stage, "job_id": job_id},
    )
```

Export `set_job_stage` and `JobStage` from `clue_api.arv2.__init__` if that module re-exports the store's functions (check with `grep -n "begin_job" platform/api/clue_api/arv2/__init__.py`; mirror whatever it does for `begin_job`).

- [ ] **Step 4: Run; ruff; mypy**

Run: `set -a; source .env; set +a; .venv/bin/pytest tests/arv2/test_account_research_launch_db.py -q -p no:cacheprovider && .venv/bin/ruff check platform/api/clue_api/arv2/account_research_store.py && .venv/bin/mypy platform/api/clue_api/arv2/account_research_store.py`
Expected: PASS, clean.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/account_research_store.py platform/api/clue_api/arv2/__init__.py tests/arv2/test_account_research_launch_db.py
git commit -m "feat(arv2): JobRow.stage and set_job_stage — the driver's four progress stamps have a home"
```

---

### Task 3: The four stamps

**Files:**
- Modify: `platform/api/clue_api/arv2/account_research_driver.py` — `_run` (~line 602, after `begin_job`), `_settle` (~line 870, around `_fan_out_committee`)
- Modify: `platform/api/clue_api/arv2/account_research_tools.py` — `_finalize_research` (~line 2044) and `_finalize_person_research` (~line 2081)
- Test: `tests/arv2/test_account_research_driver.py`

**Interfaces:**
- Consumes: `set_job_stage` (Task 2); the driver's `self._store` (the store module or its double); the tool runtime's `runtime.scope.job_id` and `runtime._conn_factory`.
- Produces: stamps in this order on an account job: `deep_research` (claim), `synthesis` (finalize tool), `committee` (before `run_committee_step`), `member_research` (after the fan-out returned ≥1 job). Person job: `deep_research`, `synthesis`.

- [ ] **Step 1: Write the failing tests**

In `tests/arv2/test_account_research_driver.py`, add to `FakeStore`:

```python
    async def set_job_stage(self, conn: Any, *, job_id: UUID, stage: str) -> None:
        del conn
        self.events.append(("set_job_stage", {"job_id": job_id, "stage": stage}))
```

Find the existing test that drives one account job through `_settle` with a finalization that names committee candidates (search the file for `committee_candidates` and `finish_job`) and add, after its existing assertions:

```python
    stamps = [payload["stage"] for event, payload in store.events if event == "set_job_stage"]
    # Claim → (finalize stamps synthesis inside the tool; see the tools test) → committee →
    # member_research once the person jobs exist. The order is the driver's real order.
    assert stamps == ["deep_research", "committee", "member_research"]
```

and to the test that drives a job whose finalization names **no** candidates (search `committee_jobs=0` or a run with an empty committee):

```python
    stamps = [payload["stage"] for event, payload in store.events if event == "set_job_stage"]
    assert stamps == ["deep_research", "committee"]
```

In the tools test module (`tests/arv2/test_account_research_tools.py` — search for the existing `_finalize_research` test that constructs a `ToolRuntime` with a fake `conn_factory`), add:

```python
def test_finalize_stamps_the_synthesis_stage_before_writing(monkeypatch: pytest.MonkeyPatch) -> None:
    stamped: list[tuple[UUID, str]] = []

    async def fake_set_job_stage(conn: Any, *, job_id: UUID, stage: str) -> None:
        del conn
        stamped.append((job_id, stage))

    monkeypatch.setattr(tools_module, "set_job_stage", fake_set_job_stage)
    runtime = _runtime_for_finalize_test()  # the module's existing builder; copy its name
    asyncio.run(tools_module._finalize_research(runtime, _minimal_finalize_args()))
    assert stamped == [(runtime.scope.job_id, "synthesis")]
```

Use the existing runtime/args builders in that test module by their real names (search `_finalize_research(` in `tests/arv2/`); do not invent them.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/arv2/test_account_research_driver.py tests/arv2/test_account_research_tools.py -q -p no:cacheprovider -k "stamp or committee"`
Expected: the new assertions FAIL (no `set_job_stage` events).

- [ ] **Step 3: Implement the driver stamps**

In `_run`, right after `composition = await self._compose(conn, job)` inside the same `async with self._connection() as conn:` block:

```python
            await self._store.set_job_stage(conn, job_id=job.job_id, stage="deep_research")
```

In `_settle`, replace

```python
            if composition.job.subject_type == "account":
                committee = await self._fan_out_committee(conn, composition, runtime)
```

with

```python
            if composition.job.subject_type == "account":
                await self._store.set_job_stage(
                    conn, job_id=composition.job.job_id, stage="committee"
                )
                committee = await self._fan_out_committee(conn, composition, runtime)
                if committee.jobs:
                    await self._store.set_job_stage(
                        conn, job_id=composition.job.job_id, stage="member_research"
                    )
```

Both stamps ride the settle transaction, so a job row never shows `member_research` without its person rows.

- [ ] **Step 4: Implement the tool stamps**

In `account_research_tools.py`, import `set_job_stage` from `clue_api.arv2.account_research_store` (the module already imports from it — extend that import). In `_finalize_research`, right after the `finalization_already_proposed` refusal:

```python
    # Spec 2026-09-12 §1: the agent's last act is the synthesis of its findings.
    async with runtime._conn_factory() as conn:  # noqa: SLF001 - the runtime's own seam
        await set_job_stage(conn, job_id=runtime.scope.job_id, stage="synthesis")
```

If `ToolRuntime` exposes a public accessor for its connection factory (search `def conn` / `conn_factory` property near line 337), use that instead of the private attribute and drop the `noqa`. Add the identical block to `_finalize_person_research` after its refusal.

- [ ] **Step 5: Run the two suites; ruff; mypy**

Run: `.venv/bin/pytest tests/arv2/test_account_research_driver.py tests/arv2/test_account_research_tools.py -q -p no:cacheprovider && .venv/bin/ruff check platform/api/clue_api/arv2 && .venv/bin/mypy platform/api/clue_api/arv2/account_research_driver.py platform/api/clue_api/arv2/account_research_tools.py`
Expected: PASS, clean. Other tests in the driver suite that assert the exact `store.events` sequence must have `("set_job_stage", …)` entries inserted at the right places (claim, committee, member) — update them and say so in the test's comment.

- [ ] **Step 6: Commit**

```bash
git add platform/api/clue_api/arv2/account_research_driver.py platform/api/clue_api/arv2/account_research_tools.py tests/arv2/test_account_research_driver.py tests/arv2/test_account_research_tools.py
git commit -m "feat(arv2): the driver stamps deep_research, synthesis, committee and member_research on the job row"
```

---

### Task 4: The pure fold — rows to card

**Files:**
- Create: `platform/api/clue_api/arv2/research_progress.py`
- Test: `tests/arv2/test_research_progress.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class ProgressJob:
    run_id: UUID; job_id: UUID; account_entity_id: UUID; account_name: str
    subject_type: Literal["account", "person"]; status: str; stage: str | None
    started_at: datetime | None; finished_at: datetime | None; failure_message: str | None

@dataclass(frozen=True)
class ProgressAgent: account_name: str; stage: str; subject: Literal["account", "person"]
@dataclass(frozen=True)
class ProgressAttention: account_name: str; reason: str
@dataclass(frozen=True)
class ProgressCard:
    requested_accounts: int; queued: int; running: int; finished: int
    progress_pct: int; pill: Literal["running", "completed", "needs_attention"]
    last_finished_at: datetime | None; agents: tuple[ProgressAgent, ...]
    attention: tuple[ProgressAttention, ...]

def account_score(account_job: ProgressJob, person_jobs: Sequence[ProgressJob]) -> float  # 0..1
def fold_progress(jobs: Sequence[ProgressJob], *, run_statuses: Mapping[UUID, str], now: datetime, linger_s: int = 60) -> ProgressCard | None
```

- [ ] **Step 1: Write the failing tests**

```python
"""The research progress card's math and pill, as pure functions over job rows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from clue_api.arv2.research_progress import ProgressJob, account_score, fold_progress

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
RUN = uuid4()


def job(
    name: str,
    *,
    subject: str = "account",
    status: str = "in_progress",
    stage: str | None = "deep_research",
    finished_at: datetime | None = None,
    failure: str | None = None,
    account_id=None,  # noqa: ANN001
) -> ProgressJob:
    return ProgressJob(
        run_id=RUN,
        job_id=uuid4(),
        account_entity_id=account_id or uuid4(),
        account_name=name,
        subject_type=subject,  # type: ignore[arg-type]
        status=status,
        stage=stage,
        started_at=NOW - timedelta(minutes=5) if status != "not_started" else None,
        finished_at=finished_at,
        failure_message=failure,
    )


def test_account_score_walks_the_four_quarters() -> None:
    acc = uuid4()
    assert account_score(job("A", status="not_started", stage=None, account_id=acc), []) == 0
    assert account_score(job("A", stage="deep_research", account_id=acc), []) == 0
    assert account_score(job("A", stage="synthesis", account_id=acc), []) == 0.25
    assert account_score(job("A", stage="committee", account_id=acc), []) == 0.5
    members = [job("A", subject="person", status="completed", stage="synthesis", account_id=acc, finished_at=NOW)]
    members += [job("A", subject="person", status="in_progress", account_id=acc) for _ in range(4)]
    # member_research: 1 of 5 people done → 0.75 + 0.25 * (1/5)
    assert account_score(job("A", stage="member_research", status="completed", account_id=acc, finished_at=NOW), members) == 0.8


def test_no_committee_completes_at_the_committee_quarter() -> None:
    acc = uuid4()
    done = job("A", stage="committee", status="completed", account_id=acc, finished_at=NOW)
    assert account_score(done, []) == 1.0


def test_fold_sums_every_live_run_and_lists_running_agents_in_start_order() -> None:
    a, b = uuid4(), uuid4()
    other_run = uuid4()
    jobs = [
        job("Alpha", stage="synthesis", account_id=a),
        job("Beta", status="not_started", stage=None, account_id=b),
        ProgressJob(**{**job("Gamma", stage="committee").__dict__, "run_id": other_run}),
    ]
    card = fold_progress(jobs, run_statuses={RUN: "in_progress", other_run: "in_progress"}, now=NOW)
    assert card is not None
    assert (card.requested_accounts, card.queued, card.running, card.finished) == (3, 1, 2, 0)
    assert card.progress_pct == round(100 * (0.25 + 0 + 0.5) / 3)
    assert card.pill == "running"
    assert [(agent.account_name, agent.stage) for agent in card.agents] == [("Alpha", "synthesis"), ("Gamma", "committee")]


def test_completed_lingers_then_disappears() -> None:
    acc = uuid4()
    done = job("A", stage="committee", status="completed", account_id=acc, finished_at=NOW - timedelta(seconds=30))
    card = fold_progress([done], run_statuses={RUN: "completed"}, now=NOW)
    assert card is not None and card.pill == "completed" and card.progress_pct == 100
    assert fold_progress([done], run_statuses={RUN: "completed"}, now=NOW + timedelta(seconds=61)) is None


def test_needs_attention_names_the_account_and_never_lingers_away() -> None:
    acc = uuid4()
    bad = job("A", stage="synthesis", status="needs_review", account_id=acc, finished_at=NOW - timedelta(hours=2), failure="model_error")
    card = fold_progress([bad], run_statuses={RUN: "needs_review"}, now=NOW)
    assert card is not None
    assert card.pill == "needs_attention"
    assert card.attention[0].account_name == "A" and "model_error" in card.attention[0].reason


def test_nothing_live_and_nothing_recent_is_no_card() -> None:
    assert fold_progress([], run_statuses={}, now=NOW) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/arv2/test_research_progress.py -q -p no:cacheprovider`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
"""The research progress card's arithmetic (spec 2026-09-12 §2–§3, §6): pure, over job rows.

Nothing here reads a table. The read (``frontend_read/research_progress.py``) loads every job of
the project's runs that are not all terminal — plus runs whose last job finished inside the
linger window — and hands the rows here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

__all__ = [
    "ProgressAgent",
    "ProgressAttention",
    "ProgressCard",
    "ProgressJob",
    "account_score",
    "fold_progress",
]

TERMINAL = frozenset({"completed", "needs_review", "suspended"})
ATTENTION = frozenset({"needs_review", "suspended"})

#: Four equal quarters, in the driver's real order. A stage's quarter is earned when the job has
#: MOVED PAST it (the next stamp landed), except ``member_research``, which fills fractionally.
_STAGE_INDEX = {"deep_research": 0, "synthesis": 1, "committee": 2, "member_research": 3}


@dataclass(frozen=True)
class ProgressJob:
    run_id: UUID
    job_id: UUID
    account_entity_id: UUID
    account_name: str
    subject_type: Literal["account", "person"]
    status: str
    stage: str | None
    started_at: datetime | None
    finished_at: datetime | None
    failure_message: str | None


@dataclass(frozen=True)
class ProgressAgent:
    account_name: str
    stage: str
    subject: Literal["account", "person"]


@dataclass(frozen=True)
class ProgressAttention:
    account_name: str
    reason: str


@dataclass(frozen=True)
class ProgressCard:
    requested_accounts: int
    queued: int
    running: int
    finished: int
    progress_pct: int
    pill: Literal["running", "completed", "needs_attention"]
    last_finished_at: datetime | None
    agents: tuple[ProgressAgent, ...]
    attention: tuple[ProgressAttention, ...]


def account_score(account_job: ProgressJob, person_jobs: Sequence[ProgressJob]) -> float:
    """One account's share of done, 0..1 (spec §3).

    * not yet claimed, or still in ``deep_research`` → 0
    * ``synthesis`` reached → 0.25; ``committee`` reached → 0.5
    * ``member_research`` reached → 0.75 + 0.25 × (person jobs terminal ÷ person jobs)
    * a terminal account job that never reached ``member_research`` (no committee) → 1.0
    """
    if account_job.stage is None:
        return 0.0
    index = _STAGE_INDEX.get(account_job.stage, 0)
    if index < 3:
        if account_job.status in TERMINAL:
            return 1.0
        return 0.25 * index
    if not person_jobs:
        return 1.0 if account_job.status in TERMINAL else 0.75
    done = sum(1 for p in person_jobs if p.status in TERMINAL)
    return 0.75 + 0.25 * (done / len(person_jobs))


def _reason(job: ProgressJob) -> str:
    if job.status == "suspended":
        return "paused, waiting for a worker"
    return job.failure_message or "needs review"


def fold_progress(
    jobs: Sequence[ProgressJob],
    *,
    run_statuses: Mapping[UUID, str],
    now: datetime,
    linger_s: int = 60,
) -> ProgressCard | None:
    """Every job of the project's qualifying runs → one card, or ``None`` (spec §2, §6)."""
    if not jobs:
        return None
    accounts = [j for j in jobs if j.subject_type == "account"]
    people_by_account: dict[UUID, list[ProgressJob]] = {}
    for j in jobs:
        if j.subject_type == "person":
            people_by_account.setdefault(j.account_entity_id, []).append(j)

    all_terminal = all(j.status in TERMINAL for j in jobs)
    last_finished = max((j.finished_at for j in jobs if j.finished_at), default=None)
    attention = tuple(
        ProgressAttention(account_name=j.account_name, reason=_reason(j))
        for j in jobs
        if j.status in ATTENTION
    ) + tuple(
        ProgressAttention(account_name=j.account_name, reason="run suspended")
        for j in accounts
        if run_statuses.get(j.run_id) == "suspended" and j.status not in ATTENTION
    )
    if all_terminal and not attention:
        if last_finished is None or now - last_finished > timedelta(seconds=linger_s):
            return None

    scores = [account_score(a, people_by_account.get(a.account_entity_id, ())) for a in accounts]
    pct = round(100 * sum(scores) / len(scores)) if scores else 0
    running_jobs = sorted(
        (j for j in jobs if j.status == "in_progress"),
        key=lambda j: (j.started_at or now, str(j.job_id)),
    )
    pill: Literal["running", "completed", "needs_attention"]
    if attention:
        pill = "needs_attention"
    elif all_terminal:
        pill = "completed"
    else:
        pill = "running"
    return ProgressCard(
        requested_accounts=len(accounts),
        queued=sum(1 for a in accounts if a.status == "not_started"),
        running=len(running_jobs),
        finished=sum(1 for a in accounts if a.status in TERMINAL),
        progress_pct=100 if all_terminal and not attention else min(pct, 99),
        pill=pill,
        last_finished_at=last_finished,
        agents=tuple(
            ProgressAgent(
                account_name=j.account_name,
                stage=j.stage or "deep_research",
                subject=j.subject_type,
            )
            for j in running_jobs
        ),
        attention=attention,
    )
```

Note `progress_pct` is capped at 99 until every job is terminal (spec: 100 only then). Adjust `test_fold_sums_every_live_run…` expectations only if the cap bites (it does not there).

- [ ] **Step 4: Run; ruff; mypy**

Run: `.venv/bin/pytest tests/arv2/test_research_progress.py -q -p no:cacheprovider && .venv/bin/ruff check platform/api/clue_api/arv2/research_progress.py tests/arv2/test_research_progress.py && .venv/bin/mypy platform/api/clue_api/arv2/research_progress.py`
Expected: PASS, clean.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/research_progress.py tests/arv2/test_research_progress.py
git commit -m "feat(arv2): research progress fold — four stage quarters per account, member research fractional, pill and agents"
```

---

### Task 5: The read

**Files:**
- Modify: `platform/api/clue_api/frontend_read/contract_v1.py` (append)
- Create: `platform/api/clue_api/frontend_read/research_progress.py`
- Modify: `platform/api/clue_api/frontend_read/app.py` (import + registration after `register_account_logo_route`)
- Test: `tests/api/test_frontend_read_research_progress.py`

**Interfaces:**
- Consumes: `fold_progress`, `ProgressJob` (Task 4).
- Produces: `GET /frontend/v1/projects/{project_id}/research/progress` → `{"data": ResearchProgressV1 | null}` where `ResearchProgressV1 = { requested_accounts, queued, running, finished, progress_pct, pill, last_finished_at, agents: [{account_name, stage, subject}], attention: [{account_name, reason}] }`.

- [ ] **Step 1: Write the failing test**

```python
"""``GET /frontend/v1/projects/{id}/research/progress`` — the pinned card's document."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.account_research_store import (
    begin_job,
    create_job,
    create_run,
    set_job_stage,
)
from clue_api.frontend_read.app import FRONTEND_READ_PREFIX
from tests.claimstore.conftest import migrated_db, require_claimstore_db, rollback_conn  # noqa: F401
from tests.db.conftest import run_async

from .test_frontend_read_accounts_list import _app, _client

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_null_then_a_running_card_then_needs_attention() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            # Reuse the launch DB test's seeding: a workspace, a project, two accounts, one run.
            from tests.arv2.test_account_research_launch_db import _seed_workspace_project_accounts  # copy the real helper name

            ws, project_id, (alpha, beta), run_row = await _seed_workspace_project_accounts(conn)
            path = f"{FRONTEND_READ_PREFIX}/projects/{project_id}/research/progress"
            headers = {"X-Workspace-Id": ws}
            async with _client(_app(conn)) as client:
                assert (await client.get(path, headers=headers)).json()["data"] is None

            assert await create_run(conn, run_row) is True
            a_job, b_job = uuid4(), uuid4()
            await create_job(conn, job_id=a_job, run_id=run_row.run_id, workspace_id=ws, account_entity_id=alpha)
            await create_job(conn, job_id=b_job, run_id=run_row.run_id, workspace_id=ws, account_entity_id=beta)
            assert await begin_job(conn, job_id=a_job) is not None
            await set_job_stage(conn, job_id=a_job, stage="synthesis")
            async with _client(_app(conn)) as client:
                body = (await client.get(path, headers=headers)).json()["data"]
            assert (body["requested_accounts"], body["queued"], body["running"], body["finished"]) == (2, 1, 1, 0)
            assert body["progress_pct"] == 13  # (0.25 + 0) / 2
            assert body["pill"] == "running"
            assert body["agents"] == [{"account_name": "Alpha", "stage": "synthesis", "subject": "account"}]

            await conn.execute(
                text("UPDATE arv2_research_job SET status = 'needs_review', failure_code = 'model_error', "
                     "failure_message = 'the model errored', finished_at = now() WHERE job_id = :id"),
                {"id": a_job},
            )
            async with _client(_app(conn)) as client:
                body = (await client.get(path, headers=headers)).json()["data"]
            assert body["pill"] == "needs_attention"
            assert body["attention"] == [{"account_name": "Alpha", "reason": "the model errored"}]
    run_async(scenario())
```

The seeding helper: read `tests/arv2/test_account_research_launch_db.py` for how it builds a workspace, project, accounts named "Alpha"/"Beta" (or rename in the assertions to whatever it names them) and a `RunRow`; if there is no single helper, inline the same calls (`seed_project`, `insert_account_entity`, `ensure_project_run`, `RunRow(...)`) exactly as that file does.

- [ ] **Step 2: Run to verify it fails**

Run: `set -a; source .env; set +a; .venv/bin/pytest tests/api/test_frontend_read_research_progress.py -q -p no:cacheprovider`
Expected: FAIL — 404.

- [ ] **Step 3: Implement**

Append to `contract_v1.py`:

```python
class ResearchProgressAgentV1(BaseModel):
    account_name: str
    stage: str
    subject: Literal["account", "person"]


class ResearchProgressAttentionV1(BaseModel):
    account_name: str
    reason: str


class ResearchProgressV1(BaseModel):
    """The pinned research progress card (spec 2026-09-12 §2)."""

    requested_accounts: int
    queued: int
    running: int
    finished: int
    progress_pct: int
    pill: Literal["running", "completed", "needs_attention"]
    last_finished_at: str | None
    agents: list[ResearchProgressAgentV1]
    attention: list[ResearchProgressAttentionV1]


class ResearchProgressResponseV1(BaseModel):
    data: ResearchProgressV1 | None
```

Create `research_progress.py`:

```python
"""``GET /frontend/v1/projects/{project_id}/research/progress`` — the pinned card (spec 2026-09-12).

Loads every job of the project's runs that are not all terminal, plus runs whose last job
finished within the linger window, and folds them with ``arv2.research_progress.fold_progress``.
ARV2 tables only (ruling 2026-09-09).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import text

from clue_api.arv2.research_progress import LINGER_S, ProgressJob, fold_progress
from clue_api.frontend_read.app import WorkspaceDep
from clue_api.frontend_read.contract_v1 import (
    ResearchProgressAgentV1,
    ResearchProgressAttentionV1,
    ResearchProgressResponseV1,
    ResearchProgressV1,
)
from clue_api.frontend_read.v1_shared import iso_utc
from clue_db import ConnFactory

__all__ = ["register_research_progress_route"]

_JOBS = text(
    """
    WITH runs AS (
        SELECT r.run_id, r.status
        FROM arv2_research_run r
        WHERE r.workspace_id = :workspace_id AND r.project_id = :project_id
          AND (
            EXISTS (SELECT 1 FROM arv2_research_job j WHERE j.run_id = r.run_id
                     AND j.status NOT IN ('completed', 'needs_review', 'suspended'))
            OR EXISTS (SELECT 1 FROM arv2_research_job j WHERE j.run_id = r.run_id
                     AND j.status IN ('needs_review', 'suspended'))
            OR r.status = 'suspended'
            OR (SELECT max(j.finished_at) FROM arv2_research_job j WHERE j.run_id = r.run_id)
               > now() - make_interval(secs => :linger_s)
          )
    )
    SELECT j.run_id, runs.status AS run_status, j.job_id, j.account_entity_id,
           a.canonical_name, j.subject_type, j.status, j.stage, j.started_at, j.finished_at,
           j.failure_message
    FROM arv2_research_job j
    JOIN runs ON runs.run_id = j.run_id
    JOIN account_entity a ON a.id = j.account_entity_id
    ORDER BY j.started_at NULLS LAST, j.job_id
    """
)


def register_research_progress_route(router: APIRouter, *, conn_factory: ConnFactory) -> None:
    @router.get(
        "/projects/{project_id}/research/progress", response_model=ResearchProgressResponseV1
    )
    async def get_research_progress(
        project_id: str, workspace_id: WorkspaceDep
    ) -> ResearchProgressResponseV1:
        async with conn_factory() as conn:
            rows = (
                await conn.execute(
                    _JOBS,
                    {"workspace_id": workspace_id, "project_id": project_id, "linger_s": LINGER_S},
                )
            ).mappings().all()
        jobs = [
            ProgressJob(
                run_id=row["run_id"],
                job_id=row["job_id"],
                account_entity_id=row["account_entity_id"],
                account_name=str(row["canonical_name"]),
                subject_type=row["subject_type"],
                status=str(row["status"]),
                stage=row["stage"],
                started_at=row["started_at"],
                finished_at=row["finished_at"],
                failure_message=row["failure_message"],
            )
            for row in rows
        ]
        run_statuses = {row["run_id"]: str(row["run_status"]) for row in rows}
        card = fold_progress(jobs, run_statuses=run_statuses, now=datetime.now(UTC), linger_s=LINGER_S)
        if card is None:
            return ResearchProgressResponseV1(data=None)
        return ResearchProgressResponseV1(
            data=ResearchProgressV1(
                requested_accounts=card.requested_accounts,
                queued=card.queued,
                running=card.running,
                finished=card.finished,
                progress_pct=card.progress_pct,
                pill=card.pill,
                last_finished_at=iso_utc(card.last_finished_at) if card.last_finished_at else None,
                agents=[ResearchProgressAgentV1(**a.__dict__) for a in card.agents],
                attention=[ResearchProgressAttentionV1(**a.__dict__) for a in card.attention],
            )
        )
```

Add `LINGER_S = 60` to `research_progress.py` (Task 4's module) and export it. In `app.py` import `register_research_progress_route` beside the discovery-status import and register it after `register_account_logo_route(...)`:

```python
    # The pinned research progress card's document (spec 2026-09-12).
    register_research_progress_route(router, conn_factory=conn_factory)
```

- [ ] **Step 4: Run; ruff; mypy**

Run: `set -a; source .env; set +a; .venv/bin/pytest tests/api/test_frontend_read_research_progress.py -q -p no:cacheprovider && .venv/bin/ruff check platform/api/clue_api/frontend_read && .venv/bin/mypy platform/api/clue_api/frontend_read/research_progress.py`
Expected: PASS, clean.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/research_progress.py platform/api/clue_api/frontend_read/contract_v1.py platform/api/clue_api/frontend_read/research_progress.py platform/api/clue_api/frontend_read/app.py tests/api/test_frontend_read_research_progress.py
git commit -m "feat(frontend-read): GET /projects/{id}/research/progress — the pinned research card's document"
```

---

### Task 6: Frontend model, the rotating line, repository, BFF

**Files:**
- Create: `apps/frontend/src/features/projects/model/research-progress.ts`
- Create: `apps/frontend/src/features/projects/model/research-progress-line.ts`
- Create: `apps/frontend/src/features/projects/model/research-progress-line.test.ts`
- Create: `apps/frontend/src/features/accounts/data/research-progress.repository.ts`
- Create: `apps/frontend/src/app/api/projects/[projectId]/research-progress/route.ts`
- Create: `apps/frontend/src/app/api/projects/research-progress-route.test.ts`

**Interfaces:**
- Produces: `ResearchProgressSchema`, `ResearchProgressResponseSchema`, `type ResearchProgress`; `researchProgressLine(card, tick): string`; `researchProgressHeadline(card): string` ("N account research agents running, M accounts queued"); `getResearchProgress(projectId)`; BFF `GET /api/projects/:projectId/research-progress`.

- [ ] **Step 1: Write the failing line tests**

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { researchProgressHeadline, researchProgressLine } from "./research-progress-line";
import type { ResearchProgress } from "./research-progress";

const base: ResearchProgress = {
  requested_accounts: 10, queued: 3, running: 7, finished: 0, progress_pct: 40, pill: "running",
  last_finished_at: null, attention: [],
  agents: [
    { account_name: "OpenAI", stage: "deep_research", subject: "account" },
    { account_name: "Anthropic", stage: "committee", subject: "account" },
    { account_name: "Anthropic", stage: "deep_research", subject: "person" },
    { account_name: "OpenAI", stage: "synthesis", subject: "account" },
  ],
};

test("the headline counts agents and queued accounts", () => {
  assert.equal(researchProgressHeadline(base), "7 account research agents running, 3 accounts queued");
  assert.equal(researchProgressHeadline({ ...base, running: 1, queued: 1 }), "1 account research agent running, 1 account queued");
});

test("the line rotates round-robin over the running agents, worded by stage", () => {
  assert.equal(researchProgressLine(base, 0), "OpenAI agent doing deep research");
  assert.equal(researchProgressLine(base, 1), "Finding the buying committee for Anthropic");
  assert.equal(researchProgressLine(base, 2), "Diving deeper into each committee member of Anthropic");
  assert.equal(researchProgressLine(base, 3), "Synthesising our findings for OpenAI");
  assert.equal(researchProgressLine(base, 4), "OpenAI agent doing deep research");
});

test("completed and needs-attention have their own lines", () => {
  assert.equal(researchProgressLine({ ...base, pill: "completed", agents: [], finished: 10 }, 5), "Research complete for 10 accounts");
  assert.equal(
    researchProgressLine({ ...base, pill: "needs_attention", attention: [{ account_name: "Cove", reason: "the model errored" }] }, 0),
    "Cove: the model errored",
  );
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/frontend && npx tsx --test src/features/projects/model/research-progress-line.test.ts`
Expected: FAIL — modules not found.

- [ ] **Step 3: Implement the model and the line**

`research-progress.ts`:

```ts
import { z } from "zod";

/** The pinned research card's document (`/frontend/v1/projects/:id/research/progress`). */
export const ResearchProgressSchema = z.object({
  requested_accounts: z.number().int().nonnegative(),
  queued: z.number().int().nonnegative(),
  running: z.number().int().nonnegative(),
  finished: z.number().int().nonnegative(),
  progress_pct: z.number().int().min(0).max(100),
  pill: z.enum(["running", "completed", "needs_attention"]).catch("running"),
  last_finished_at: z.string().nullable(),
  agents: z.array(
    z.object({
      account_name: z.string(),
      stage: z.enum(["deep_research", "synthesis", "committee", "member_research"]).catch("deep_research"),
      subject: z.enum(["account", "person"]).catch("account"),
    }),
  ),
  attention: z.array(z.object({ account_name: z.string(), reason: z.string() })),
});

export type ResearchProgress = z.infer<typeof ResearchProgressSchema>;

export const ResearchProgressResponseSchema = z.object({ data: ResearchProgressSchema.nullable() });
```

`research-progress-line.ts`:

```ts
import type { ResearchProgress } from "./research-progress";

/** "7 account research agents running, 3 accounts queued" — the mockup's second line. */
export function researchProgressHeadline(card: ResearchProgress): string {
  const agents = `${card.running} account research ${card.running === 1 ? "agent" : "agents"} running`;
  const queued = `${card.queued} ${card.queued === 1 ? "account" : "accounts"} queued`;
  return `${agents}, ${queued}`;
}

/**
 * The bottom line of the card (spec §5): one sentence at a time, round-robin over the running
 * agents by `tick`, worded by stage. A person job reads as the member line for its account.
 */
export function researchProgressLine(card: ResearchProgress, tick: number): string {
  if (card.pill === "needs_attention" && card.attention.length) {
    const item = card.attention[tick % card.attention.length];
    return `${item.account_name}: ${item.reason}`;
  }
  if (card.pill === "completed" || card.agents.length === 0) {
    return `Research complete for ${card.finished} ${card.finished === 1 ? "account" : "accounts"}`;
  }
  const agent = card.agents[tick % card.agents.length];
  if (agent.subject === "person" || agent.stage === "member_research") {
    return `Diving deeper into each committee member of ${agent.account_name}`;
  }
  switch (agent.stage) {
    case "synthesis":
      return `Synthesising our findings for ${agent.account_name}`;
    case "committee":
      return `Finding the buying committee for ${agent.account_name}`;
    default:
      return `${agent.account_name} agent doing deep research`;
  }
}
```

- [ ] **Step 4: Run the line tests**

Run: `cd apps/frontend && npx tsx --test src/features/projects/model/research-progress-line.test.ts`
Expected: PASS.

- [ ] **Step 5: Repository and BFF**

`research-progress.repository.ts` (in `features/accounts/data`, beside the discovery one, because `fetchRead` lives there):

```ts
import { fetchRead } from "./frontend-api";
import { ResearchProgressResponseSchema, type ResearchProgress } from "@/features/projects/model/research-progress";

export async function getResearchProgress(
  projectId: string,
  read: typeof fetchRead = fetchRead,
): Promise<ResearchProgress | null> {
  const body = await read(`/projects/${encodeURIComponent(projectId)}/research/progress`);
  return ResearchProgressResponseSchema.parse(body).data;
}
```

`app/api/projects/[projectId]/research-progress/route.ts`:

```ts
import { getResearchProgress } from "@/features/accounts/data/research-progress.repository";

/** The pinned research card's poll (spec 2026-09-12 §4). Never cached. */
export async function GET(_request: Request, { params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  try {
    const data = await getResearchProgress(projectId);
    return Response.json({ data }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json(
      { error: "Unable to read research progress. Please try again." },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
}
```

`app/api/projects/research-progress-route.test.ts`:

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { GET } from "./[projectId]/research-progress/route";

// One segment above the bracketed route on purpose (the `[segment]` glob pitfall).
test("a failed read is retryable, uncached, and carries no upstream detail", async (t) => {
  t.mock.method(globalThis, "fetch", async () => {
    throw new Error("private upstream connection details");
  });
  const response = await GET(new Request("http://localhost/api/projects/prj_1/research-progress"), {
    params: Promise.resolve({ projectId: "prj_1" }),
  });
  assert.equal(response.status, 502);
  assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.deepEqual(await response.json(), { error: "Unable to read research progress. Please try again." });
});
```

- [ ] **Step 6: Run tests, lint, tsc**

Run: `cd apps/frontend && npm test 2>&1 | grep -E "^ℹ (tests|pass|fail)" && npm run lint && npx tsc --noEmit -p . 2>&1 | grep -c "error TS"`
Expected: pass; lint 0 errors; tsc at baseline.

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/features/projects/model/research-progress.ts apps/frontend/src/features/projects/model/research-progress-line.ts apps/frontend/src/features/projects/model/research-progress-line.test.ts apps/frontend/src/features/accounts/data/research-progress.repository.ts "apps/frontend/src/app/api/projects/[projectId]/research-progress/route.ts" apps/frontend/src/app/api/projects/research-progress-route.test.ts
git commit -m "feat(frontend): research progress model, the rotating status line, repository and BFF route"
```

---

### Task 7: The controller and the card

**Files:**
- Create: `apps/frontend/src/features/projects/hooks/use-research-progress-controller.ts`
- Create: `apps/frontend/src/features/projects/components/research-progress-card.tsx`
- Create: `apps/frontend/src/features/projects/components/research-progress-card.module.css`
- Modify: `apps/frontend/src/features/chat-shell/components/chat-surface.tsx` (import; hook after `addToOpenChat`; render inside `styles.composerFrame` before the edit-targets bar)
- Create: `apps/frontend/src/features/projects/model/research-progress-contract.test.ts`

**Interfaces:**
- Consumes: `getResearchProgress` via the BFF route (Task 6), `researchProgressLine`/`researchProgressHeadline`, `ProjectIcon` (check `ProjectIconName` for a telescope; if none exists, add `"telescope"` to `project-icon.tsx` with the mockup's telescope path — a 16 px outline; keep the existing icon map's style), `styles.rotatingLoader` is not needed.
- Produces: `useResearchProgressController(projectId, { pollMs = 5000, rotateMs = 4000, prime }) → { card, line, headline }`; `<ResearchProgressCard card line headline />`.

- [ ] **Step 1: Write the source-contract test**

`research-progress-contract.test.ts`:

```ts
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

function source(path: string) {
  return readFileSync(new URL(path, import.meta.url), "utf8");
}
const surface = source("../../chat-shell/components/chat-surface.tsx");
const card = source("../components/research-progress-card.tsx");
const hook = source("../hooks/use-research-progress-controller.ts");

test("the card is pinned in the composer dock, one per project, polled while it exists", () => {
  assert.match(surface, /useResearchProgressController\(projectId/);
  assert.match(surface, /<ResearchProgressCard/);
  // Inside the composer frame, above the edit-targets bar and the composer.
  assert.ok(surface.indexOf("<ResearchProgressCard") < surface.indexOf("<ProjectComposer"));
  assert.match(hook, /pollMs = 5000/);
  assert.match(hook, /rotateMs = 4000/);
});

test("the card is the mockup and nothing more: no chevron, no dismiss, one state", () => {
  assert.match(card, /Account research/);
  assert.match(card, /Queued/);
  assert.match(card, /role="progressbar"/);
  assert.doesNotMatch(card, /chevron|Dismiss|expanded|details/i);
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/frontend && npx tsx --test src/features/projects/model/research-progress-contract.test.ts`
Expected: FAIL.

- [ ] **Step 3: The controller**

```ts
"use client";

import { useEffect, useState } from "react";
import { ResearchProgressResponseSchema, type ResearchProgress } from "../model/research-progress";
import { researchProgressHeadline, researchProgressLine } from "../model/research-progress-line";

/**
 * The pinned research card's state (spec 2026-09-12 §4–§5): reads on mount, re-reads every
 * `pollMs` while the read returns a card, rotates the status line every `rotateMs`, and stops
 * when the read returns `null` (the backend's own linger window decides that). `prime` bumps
 * once from outside (a completed launch tool part) so the card appears within a tick.
 */
export function useResearchProgressController(
  projectId: string,
  { pollMs = 5000, rotateMs = 4000, prime = 0 }: { pollMs?: number; rotateMs?: number; prime?: number } = {},
): { card: ResearchProgress | null; line: string; headline: string } {
  const [card, setCard] = useState<ResearchProgress | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let live = true;
    async function read() {
      try {
        const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/research-progress`, { cache: "no-store" });
        if (!response.ok) return;
        const next = ResearchProgressResponseSchema.parse(await response.json()).data;
        if (cancelled) return;
        live = next !== null;
        setCard(next);
      } catch {
        // Keep the last card; the next tick tries again.
      }
    }
    void read();
    const poll = window.setInterval(() => { if (live) void read(); }, pollMs);
    return () => { cancelled = true; window.clearInterval(poll); };
  }, [pollMs, prime, projectId]);

  useEffect(() => {
    if (card === null) return;
    const rotate = window.setInterval(() => setTick((current) => current + 1), rotateMs);
    return () => window.clearInterval(rotate);
  }, [card === null, rotateMs]);

  return {
    card,
    line: card ? researchProgressLine(card, tick) : "",
    headline: card ? researchProgressHeadline(card) : "",
  };
}
```

Note: when the read returns `null` the interval keeps ticking but `live` is false, so nothing is fetched until `prime` or `projectId` changes and the effect re-runs. That is the "stops when null" rule with the launch signal as the restart.

- [ ] **Step 4: The card**

`research-progress-card.tsx` — the mockup, no chevron:

```tsx
"use client";

import type { ResearchProgress } from "../model/research-progress";
import { ProjectIcon } from "./project-icon";
import styles from "./research-progress-card.module.css";

const PILL_LABEL = { running: "Running", completed: "Completed", needs_attention: "Needs attention" } as const;

export function ResearchProgressCard({ card, headline, line }: { card: ResearchProgress; headline: string; line: string }) {
  return (
    <section aria-label="Account research progress" aria-live="polite" className={styles.card}>
      <header className={styles.header}>
        <ProjectIcon className={styles.glyph} name="telescope" size={24} />
        <div className={styles.titles}>
          <h2 className={styles.title}>Account research</h2>
          <p className={styles.subtitle}>{headline}</p>
        </div>
        <span className={styles.pill} data-pill={card.pill}>{PILL_LABEL[card.pill]}</span>
      </header>
      <div className={styles.queuedRow}>
        <span aria-hidden="true" className={styles.queuedDot} />
        <span className={styles.queuedCount}>{card.queued} {card.queued === 1 ? "Account" : "Accounts"}</span>
        <span className={styles.queuedLabel}>Queued</span>
      </div>
      <div aria-valuemax={100} aria-valuemin={0} aria-valuenow={card.progress_pct} className={styles.bar} role="progressbar">
        <span className={styles.barFill} style={{ width: `${card.progress_pct}%` }} />
      </div>
      <p className={styles.line}>{line}</p>
    </section>
  );
}
```

`research-progress-card.module.css` — dimensions from the mockup (420 × hug, 24 px padding, 8 px radius, 6 px bar), tokens from the design system:

```css
.card {
  display: flex;
  flex-direction: column;
  gap: 16px;
  width: 100%;
  padding: 20px 24px;
  border: 1px solid var(--clue-ds-color-border-neutral);
  border-radius: 12px;
  background: var(--clue-ds-color-bg-neutral);
  font-family: "Satoshi", Arial, sans-serif;
}
.header { display: flex; align-items: flex-start; gap: 16px; }
.glyph { flex: none; margin-top: 4px; color: var(--clue-ds-color-content-neutral); }
.titles { flex: 1; min-width: 0; }
.title { margin: 0; font: 500 18px/24px "Satoshi", Arial, sans-serif; color: var(--clue-ds-color-content-neutral); }
.subtitle { margin: 4px 0 0; font: 400 14px/20px "Satoshi", Arial, sans-serif; color: var(--clue-ds-color-content-subtle); }
.pill { flex: none; padding: 4px 12px; border-radius: 999px; background: var(--clue-ds-color-bg-neutral-hover); font: 400 14px/20px "Satoshi", Arial, sans-serif; color: var(--clue-ds-color-content-neutral); }
.pill[data-pill="needs_attention"] { background: var(--clue-ds-color-primitives-warning-alpha-100); color: var(--clue-ds-color-content-utility-warning); }
.queuedRow { display: flex; align-items: center; gap: 12px; font: 400 16px/22px "Satoshi", Arial, sans-serif; color: var(--clue-ds-color-content-subtle); }
.queuedDot { width: 12px; height: 12px; border-radius: 50%; border: 1.5px solid var(--clue-ds-color-border-neutral); }
.queuedCount { flex: 1; color: var(--clue-ds-color-content-neutral); }
.bar { height: 6px; border-radius: 3px; background: var(--clue-ds-color-bg-neutral-hover); overflow: hidden; }
.barFill { display: block; height: 100%; border-radius: 3px; background: var(--clue-ds-color-content-neutral); transition: width 400ms ease-out; }
.line { margin: 0; font: 400 14px/20px "Satoshi", Arial, sans-serif; color: var(--clue-ds-color-content-subtle); }
```

Check every `--clue-ds-*` token exists (`grep -rn "clue-ds-color-primitives-warning-alpha-100" apps/frontend/src --include=*.css | head -1`; substitute the nearest existing warning tokens if the names differ — they are used by `brand-context.module.css`'s `approvalChipDraft`).

If `ProjectIconName` has no `"telescope"`, add one to `project-icon.tsx` following the map's existing entries (a 24-viewBox outline path), and say so in the commit.

- [ ] **Step 5: Mount in the chat surface**

In `chat-surface.tsx` add imports:

```ts
import { ResearchProgressCard } from "@/features/projects/components/research-progress-card";
import { useResearchProgressController } from "@/features/projects/hooks/use-research-progress-controller";
```

After the `addToOpenChat` hook (and after the discovery hooks from the streaming plan, if present):

```ts
  // The pinned research card (spec 2026-09-12): one per project, above the composer, alive
  // while the read returns a card. A completed launch_account_research part primes the read.
  const [researchPrime, setResearchPrime] = useState(0);
  const research = useResearchProgressController(projectId, { prime: researchPrime });
  const knownResearchLaunchIds = useRef<Set<string> | null>(null);
  useEffect(() => {
    const known = knownResearchLaunchIds.current;
    const ids = chat.transcript.flatMap((m) =>
      m.parts.flatMap((p) =>
        p.kind === "tool" && p.toolName === "launch_account_research" && p.state === "output-available"
          ? [p.toolCallId]
          : [],
      ),
    );
    if (known === null) {
      knownResearchLaunchIds.current = new Set(ids);
      return;
    }
    const fresh = ids.filter((id) => !known.has(id));
    for (const id of ids) known.add(id);
    if (fresh.length) setResearchPrime((current) => current + 1);
  }, [chat.transcript]);
```

Inside `<div className={styles.composerFrame}>`, as its first child (before the edit-targets bar):

```tsx
            {research.card ? (
              <ResearchProgressCard card={research.card} headline={research.headline} line={research.line} />
            ) : null}
```

Confirm the tool name: `grep -n '"launch_account_research"' platform/api/clue_api/arv2/account_research_launch.py platform/api/clue_api/toolbelt_wiring.py` and use the exact registered name.

- [ ] **Step 6: Run everything**

Run: `cd apps/frontend && npm test 2>&1 | grep -E "^ℹ (tests|pass|fail)" && npm run lint && npx tsc --noEmit -p . 2>&1 | grep -c "error TS" && npm run build 2>&1 | tail -3`
Expected: pass; lint 0 errors; tsc baseline; build green.

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/features/projects/hooks/use-research-progress-controller.ts apps/frontend/src/features/projects/components/research-progress-card.tsx apps/frontend/src/features/projects/components/research-progress-card.module.css apps/frontend/src/features/projects/components/project-icon.tsx apps/frontend/src/features/chat-shell/components/chat-surface.tsx apps/frontend/src/features/projects/model/research-progress-contract.test.ts
git commit -m "feat(frontend): the pinned research progress card — polled every 5 s, status line rotating every 4 s, the mockup and nothing more"
```

---

### Task 8: Contract note and memory

**Files:**
- Modify: `apps/frontend/docs/api-contracts/projects.md` (append a section)
- Modify: `_memory/2026-09-11-san-salvador-lane-stack.md` (append)

- [ ] **Step 1: Append to `projects.md`**

```markdown
### Research progress card (2026-09-12)

Spec `docs/superpowers/specs/2026-09-12-research-progress-card-design.md`. One pinned card per
project above the composer, rendered from `GET /frontend/v1/projects/:projectId/research/progress`
(BFF `GET /api/projects/:projectId/research-progress`): `{ requested_accounts, queued, running,
finished, progress_pct, pill, last_finished_at, agents[{account_name, stage, subject}],
attention[{account_name, reason}] } | null`. Backend: the account driver stamps
`arv2_research_job.stage` (deep_research → synthesis → committee → member_research); the fold is
`clue_api.arv2.research_progress` (four quarters per account, member research fractional; 100
only when every job is terminal; Completed lingers 60 s). Frontend polls every 5 s while a card
is served and rotates the status line every 4 s (`model/research-progress-line.ts`). No chevron,
no dismiss, no per-account detail (founder rulings 2026-09-12).
```

- [ ] **Step 2: Append to the memory note**

```markdown

## Research progress card landed (plan 2026-09-12-research-progress-card)

`arv2_research_job.stage` (migration off `2cd622be2da0`), `set_job_stage`, four driver stamps
(claim / finalize tool / committee / member launch), pure fold `arv2/research_progress.py`, read
`/frontend/v1/projects/{id}/research/progress`, card pinned in the composer dock. Owed: the
founder's walk (launch research → card appears within 5 s → bar and line move → Completed for
60 s → gone).
```

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/docs/api-contracts/projects.md _memory/2026-09-11-san-salvador-lane-stack.md
git commit -m "docs: research progress card — contract note and lane memory"
```

---

## Self-review

- **Spec coverage.** §1 stamps: Tasks 1–3. §2 read: Task 5. §3 math: Task 4 (`account_score`, cap at 99, no-committee case, zero-person case). §4 card + polling + prime on launch: Tasks 6–7. §5 wording: Task 6's `researchProgressLine` and its tests use the exact sentences. §6 lifecycle: linger in the fold + the read's SQL window; needs-attention never lingers away; failed read keeps the last card. §7 tests: each task. §8 out of scope respected (no capacity, no detail, no dismiss).
- **Placeholder scan.** Task 2/3/5 tell the implementer to reuse existing test helpers *by searching named call sites* rather than inventing them; each names the search string. No "TBD".
- **Type consistency.** `set_job_stage(conn, *, job_id, stage)` matches across Tasks 2, 3 and the fake store; `ProgressJob`/`fold_progress(jobs, run_statuses=, now=, linger_s=)` match Tasks 4–5; the wire keys (`requested_accounts`, `queued`, `running`, `finished`, `progress_pct`, `pill`, `last_finished_at`, `agents`, `attention`) are identical in the Python contract, the Zod schema and the tests.
