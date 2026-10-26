# Display pages written at settle, pending placeholders, shared blocks — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move ARV2 display-page synthesis off the HTTP request onto the fleet (account overview at
research settle, contact pages on the first open of their account), serve not-yet-written sections
as `pending` with the sentence "Synthesis in progress, please wait a few seconds." and a 5 s
client poll, and let the insights page share blocks with the overview and contact pages where it
asks the same question.

**Architecture:** A new fleet task kind `arv2_display_page` carries `{workspace_id, subject_kind,
subject_id, page}`; its handler calls the existing `ensure_page(..., regenerate_stale=True)` on the
worker. The web read seam (`DisplayPages`) stops writing inline when it has a work queue: it serves
stored blocks, computes which missing sections WOULD be written (the gather step, no model call),
marks those `pending`, and enqueues the page's task; without a queue the inline write survives as
the fallback. Shared blocks are a recipe field `shared_from=(page, section_key)`: a shared recipe
owns no block and composes the owner's stored body under its own heading.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy async / Alembic / pytest (DB suites on the
lane's throwaway DB only); Next.js App Router + Zod + `node:test` for the frontend.

**Spec:** `docs/superpowers/specs/archive/2026-09-12-display-prewrite-and-shared-blocks-design.md`
(rulings of 2026-09-12; the pending-placeholder ruling of 2026-09-21 replaces the "simply blank"
ruling). Read it first; this plan argues from it.

## Global Constraints

- Alembic: `uv run alembic revision -m "<slug>"` assigns the id; `down_revision` = the output of
  `uv run alembic heads` at execution time (one head, always). Every `upgrade()` has a matching
  `downgrade()`. New `fleet_task_kind` labels are APPENDED with `ALTER TYPE … ADD VALUE IF NOT
  EXISTS` and mirrored at the END of `clue_fleet.enums.FleetTaskKind` (the parity tests compare in
  order).
- The placeholder sentence is exactly `Synthesis in progress, please wait a few seconds.` — one
  constant, `PENDING_MESSAGE`, in `platform/api/clue_api/frontend_read/display_pages.py`; the
  frontend renders `emptyMessage` verbatim and never hardcodes it.
- `pending` is served ONLY for a missing section whose recipe would produce a section (the gather
  step returns a non-empty input). Never for a section that matches nothing.
- No new env key. The fleet handler composes behind the existing `CLUE_ARV2_DISPLAY_GENERATE_ON_READ`
  + `CLUE_OPENROUTER_API_KEY` conditions (spec §2).
- The web read never spends when it has a queue: no `ensure_page` call on the request path.
- Every DB test runs against the lane's throwaway DB (`CLUE_DATABASE_URL` pointed at it), never the
  lane DB; the design-API and fleet workers must be DOWN for fleet-queue DB suites.
- Frontend gate: `cd apps/frontend && npm run design-system:build && npm run lint && npm run build`
  and `npm test`. Contract parity: `uv run pytest tests/api/contract_v1 -q` (regenerate
  `zod-fields.json` per `tests/api/contract_v1/README.md` when a Zod model changes).
- Commit after every task with a message that says what changed and why. No AI attribution.
  Never push.
- Run `ruff check` + `ruff format` on touched Python; `mypy` on touched packages
  (`uv run mypy platform/api platform/fleet`).

## File structure

| File | Responsibility |
| --- | --- |
| `platform/fleet/clue_fleet/enums.py` | `FleetTaskKind.ARV2_DISPLAY_PAGE` (append) |
| `alembic/versions/<id>_arv2_display_page_fleet_kind.py` | `ADD VALUE 'arv2_display_page'`, downgrade recreates the enum (R4 pattern) |
| `platform/api/clue_api/arv2/fleet_task.py` | `ARV2_DISPLAY_DEDUP_PREFIX`, `ARV2_DISPLAY_TASK_PRIORITY`, `arv2_display_work_id` |
| `platform/api/clue_api/arv2/display/page.py` | `ensure_page(..., job_id=)` stamps the research job on the page's spend; `people_of` made public |
| `platform/api/clue_api/arv2/display/fleet_handler.py` | NEW: `Arv2DisplayPageWorkHandler`, `build_arv2_display_page_handler`, `display_page_payload` |
| `platform/api/clue_api/fleet_wiring.py` | `build_multi_work_worker(arv2_display_page_handler=)` kind-guarded |
| `platform/api/clue_api/fleet_main.py` | composes the handler beside the research handlers |
| `platform/api/clue_api/arv2/account_research_driver.py` | `_offer_display_page` after `_offer_committee` |
| `platform/api/clue_api/frontend_read/contract_v1.py` | `ResearchSection.pending` |
| `apps/frontend/src/features/accounts/model/research-display.ts` | `pending` on the Zod section |
| `tests/api/contract_v1/zod-fields.json` | regenerated |
| `apps/frontend/docs/api-contracts/accounts.md` | `pending` row + the pending sentence |
| `platform/api/clue_api/frontend_read/display_pages.py` | queue path: pending sections, page offers, contact offers on open; `PENDING_MESSAGE` |
| `platform/api/clue_api/frontend_read/app.py`, `projections_app.py` | thread a `DbWorkQueue` into `DisplayPages` |
| `platform/api/clue_api/frontend_read/contacts.py` | the contacts tab offers the members' pages |
| `apps/frontend/src/features/accounts/hooks/use-pending-sections-refresh.ts` | NEW: `router.refresh()` every 5 s while any section is pending |
| `apps/frontend/src/features/accounts/components/research-content.tsx` | the three section renderers mount the hook |
| `platform/api/clue_api/arv2/display/recipes.py` | `SectionRecipe.shared_from`; two sharing recipes; SQL carries the columns |
| `alembic/versions/<id>_display_recipe_shared_from.py` | two nullable columns on `display_section_recipe`; retires the two sections' own live blocks |
| `platform/api/clue_api/arv2/display/blocks.py` | `shared_blocks`, `compose_display_block(..., shared=)`, `cited_claim_ids` |
| `_memory/2026-09-21-display-prewrite-execution.md` | execution record |

---

### Task 1: The `arv2_display_page` fleet kind and its work identity

**Files:**
- Modify: `platform/fleet/clue_fleet/enums.py` (append after `ARV2_DISCOVERY`)
- Create: `alembic/versions/<id>_arv2_display_page_fleet_kind.py`
- Modify: `platform/api/clue_api/arv2/fleet_task.py`
- Test: `tests/db/test_arv2_display_page_kind_migration.py`, `tests/arv2/test_fleet_task.py`

**Interfaces:**
- Produces: `FleetTaskKind.ARV2_DISPLAY_PAGE = "arv2_display_page"`;
  `ARV2_DISPLAY_DEDUP_PREFIX = "arv2-display-page:"`; `ARV2_DISPLAY_TASK_PRIORITY = -80`;
  `arv2_display_work_id(subject_kind: str, subject_id: str, page: str) -> WorkId`.

- [ ] **Step 1: Write the failing pure test**

`tests/arv2/test_fleet_task.py` (create if absent; otherwise append):

```python
from __future__ import annotations

from uuid import UUID

from clue_api.arv2.fleet_task import (
    ARV2_ACCOUNT_TASK_PRIORITY,
    ARV2_DISCOVERY_TASK_PRIORITY,
    ARV2_DISPLAY_DEDUP_PREFIX,
    ARV2_DISPLAY_TASK_PRIORITY,
    arv2_display_work_id,
)


def test_a_display_page_work_id_is_one_id_per_subject_and_page() -> None:
    subject = "5c1a5a7e-2a5c-4f8a-9d5f-6f0e6b3c1a11"
    overview = arv2_display_work_id("account", subject, "overview")
    assert isinstance(overview, UUID)
    assert overview == arv2_display_work_id("account", subject, "overview")
    assert overview != arv2_display_work_id("account", subject, "insights")
    assert overview != arv2_display_work_id("contact", subject, "contact")


def test_display_pages_yield_to_research_and_discovery() -> None:
    # The fleet orders by ASCENDING priority: research (-100) and discovery (-90) go first.
    assert ARV2_ACCOUNT_TASK_PRIORITY < ARV2_DISCOVERY_TASK_PRIORITY < ARV2_DISPLAY_TASK_PRIORITY < 0
    assert ARV2_DISPLAY_DEDUP_PREFIX == "arv2-display-page:"
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/arv2/test_fleet_task.py -q`
Expected: FAIL with `ImportError` on `ARV2_DISPLAY_DEDUP_PREFIX`.

- [ ] **Step 3: Append the enum member**

In `platform/fleet/clue_fleet/enums.py`, after the `ARV2_DISCOVERY` member:

```python
    # ARV2 display (spec 2026-09-12): one task per (subject, page) — the fleet writes the page's
    # missing and stale sections so no HTTP request ever waits on a model. Appended, never inserted.
    ARV2_DISPLAY_PAGE = "arv2_display_page"
```

Add one docstring bullet beside the `ARV2_DISCOVERY` bullet:

```
    * ``ARV2_DISPLAY_PAGE`` — one ARV2 display page (spec 2026-09-12): the account overview at
      settle, a contact page on the first open of its account, and any page a read found stale.
```

- [ ] **Step 4: Add the work identity**

Append to `platform/api/clue_api/arv2/fleet_task.py` (and extend `__all__` with the three names):

```python
import uuid

#: The display page's prefix, so a page task's dedup key cannot collide with a research job's.
ARV2_DISPLAY_DEDUP_PREFIX = "arv2-display-page:"
#: A page write yields to research (-100) and discovery (-90): both produce the claims a page is
#: written from, so a page waiting behind them is written from more, not less. It still outranks
#: ordinary work (0) because a person is looking at the blank section it fills.
ARV2_DISPLAY_TASK_PRIORITY = -80


def arv2_display_work_id(subject_kind: str, subject_id: str, page: str) -> WorkId:
    """One work id per (subject, page): the same page offered twice is one task, whoever offers it."""
    return WorkId(uuid.uuid5(uuid.NAMESPACE_URL, f"clue:arv2-display-page:{subject_kind}:{subject_id}:{page}"))
```

- [ ] **Step 5: Run the pure test**

Run: `uv run pytest tests/arv2/test_fleet_task.py -q`
Expected: PASS.

- [ ] **Step 6: Write the failing migration test**

`tests/db/test_arv2_display_page_kind_migration.py`:

```python
"""The arv2_display_page fleet kind (spec 2026-09-12, plan 2026-09-21 Task 1)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_db import db_lifespan
from clue_fleet import FleetTaskKind

from .conftest import run_async


@pytest.mark.usefixtures("require_db")
def test_the_fleet_kind_enum_has_arv2_display_page_last_and_matches_the_db() -> None:
    async def scenario() -> list[str]:
        async with db_lifespan() as engine, engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = 'fleet_task_kind' ORDER BY e.enumsortorder"
                )
            )
            return [str(r.enumlabel) for r in rows]

    labels = run_async(scenario())
    assert labels[-1] == "arv2_display_page"
    assert labels == [k.value for k in FleetTaskKind]
```

- [ ] **Step 7: Run it to see it fail**

Run (throwaway DB, migrated to the current head first):
`set -a; source .env; set +a; CLUE_DATABASE_URL=<throwaway-dsn> uv run pytest tests/db/test_arv2_display_page_kind_migration.py -q`
Expected: FAIL — the DB has no `arv2_display_page` label.

- [ ] **Step 8: Create the migration**

Run: `uv run alembic revision -m "arv2 display page fleet kind"` and edit the generated file so it
reads (keep the generated `revision`; set `down_revision` to the current head from
`uv run alembic heads`):

```python
"""arv2 display page fleet kind

The fleet_task_kind enum gains ``arv2_display_page`` (spec 2026-09-12 §2): the account overview is
written when the account job settles, contact pages on the first open of their account, stale
pages whenever a read finds them. ADD VALUE appends, which is what the in-order parity test wants.
"""

from __future__ import annotations

from alembic import op

revision = "<generated>"
down_revision = "<current head>"
branch_labels = None
depends_on = None

_KINDS_BEFORE = (
    "drive_run",
    "account_job",
    "execute_graph",
    "entity_research_job",
    "agent_turn",
    "stage0_recon",
    "official_site_crawl",
    "design_job",
    "onboarding_run",
    "arv2_account_research",
    "arv2_discovery",
)


def upgrade() -> None:
    # ADD VALUE is safe inside alembic's transaction because nothing here USES the label (the
    # 2cd622be2da0 precedent).
    op.execute("ALTER TYPE fleet_task_kind ADD VALUE IF NOT EXISTS 'arv2_display_page'")


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM fleet_task WHERE kind::text = 'arv2_display_page') THEN
                RAISE EXCEPTION 'cannot downgrade while arv2_display_page fleet tasks exist';
            END IF;
        END $$
        """
    )
    labels = ", ".join(f"'{k}'" for k in _KINDS_BEFORE)
    op.execute("ALTER TYPE fleet_task_kind RENAME TO fleet_task_kind_display")
    op.execute(f"CREATE TYPE fleet_task_kind AS ENUM ({labels})")
    op.execute(
        "ALTER TABLE fleet_task ALTER COLUMN kind TYPE fleet_task_kind "
        "USING kind::text::fleet_task_kind"
    )
    op.execute("DROP TYPE fleet_task_kind_display")
```

- [ ] **Step 9: Migrate the throwaway DB and run the DB test**

Run: `CLUE_DATABASE_URL=<throwaway-dsn> uv run alembic upgrade head` then the test from Step 7.
Expected: PASS. Then `uv run alembic heads` prints exactly one head.

- [ ] **Step 10: Run the neighbouring parity tests + the smoke**

Run: `CLUE_DATABASE_URL=<throwaway-dsn> uv run pytest tests/db/test_arv2_r2_migration.py tests/db/test_arv2_onboarding_kind_migration.py -q` and `CLUE_DATABASE_URL=<throwaway-dsn> make db-smoke`.
Expected: PASS (the two older tests compare the whole enum in order and now see the new label).

- [ ] **Step 11: Commit**

```bash
git add platform/fleet/clue_fleet/enums.py platform/api/clue_api/arv2/fleet_task.py alembic/versions/*arv2_display_page_fleet_kind.py tests/arv2/test_fleet_task.py tests/db/test_arv2_display_page_kind_migration.py
git commit -m "feat(fleet): arv2_display_page task kind — one task per (subject, page), yields to research"
```

---

### Task 2: The fleet handler that writes a page

**Files:**
- Modify: `platform/api/clue_api/arv2/display/page.py` (`ensure_page` gains `job_id`; `_people_of` → public `people_of`)
- Create: `platform/api/clue_api/arv2/display/fleet_handler.py`
- Modify: `platform/api/clue_api/fleet_wiring.py:365-500` (`build_multi_work_worker`)
- Modify: `platform/api/clue_api/fleet_main.py:1318-1350`
- Test: `tests/arv2/display/test_fleet_handler_db.py`, `tests/api/test_fleet_wiring.py`

**Interfaces:**
- Consumes: Task 1's `FleetTaskKind.ARV2_DISPLAY_PAGE`, `arv2_display_work_id`.
- Produces:
  - `ensure_page(..., job_id: UUID | None = None)` — stamps `LedgerStamp(workspace_id=…, job_id=job_id)` on the page's provider rows.
  - `people_of(subject, members) -> tuple[list[SubjectRef], list[str]]` (the old `_people_of`, exported).
  - `display_page_payload(*, workspace_id: str, subject_kind: str, subject_id: str, page: str, job_id: UUID | None = None) -> dict[str, JsonValue]`.
  - `class Arv2DisplayPageWorkHandler` with `kind = FleetTaskKind.ARV2_DISPLAY_PAGE`, `__init__(*, settings, conn_factory, runner_factory, artifacts)`, `async handle(context) -> WorkResult`.
  - `build_arv2_display_page_handler(settings, secrets, *, storage) -> Arv2DisplayPageWorkHandler | None`.
  - `build_multi_work_worker(..., arv2_display_page_handler: WorkHandler | None = None)`.

- [ ] **Step 1: Write the failing handler DB test**

`tests/arv2/display/test_fleet_handler_db.py`:

```python
"""The arv2_display_page handler: writes a page once, a redelivery writes nothing (plan Task 2)."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.display.fleet_handler import (
    Arv2DisplayPageWorkHandler,
    display_page_payload,
)
from clue_api.arv2.fleet_task import arv2_display_work_id
from clue_fleet import FleetTaskKind, LeaseGeneration, WorkContext
from tests.arv2.display._seed import seed_display_fixture
from tests.arv2.display.test_page_db import RoutingTransport, _block_counts, _factory
from tests.arv2.test_provider_ledger_db import FakeArtifacts
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

WORKSPACE = "ws_display_fleet"
SETTINGS: Any = __import__("clue_config").Settings(_env_file=None, arv2_display_generate_on_read=True)


def _context(payload: dict[str, Any]) -> WorkContext:
    return WorkContext(
        task_id=uuid4(),
        work_id=arv2_display_work_id(
            str(payload.get("subject_kind")), str(payload.get("subject_id")), str(payload.get("page"))
        ),
        worker_id="w1",
        lease_generation=LeaseGeneration(1),
        payload=payload,
        stop_requested=asyncio.Event(),
        lease_lost=asyncio.Event(),
    )


def test_the_handler_owns_the_display_kind() -> None:
    assert Arv2DisplayPageWorkHandler.kind is FleetTaskKind.ARV2_DISPLAY_PAGE


def test_a_page_task_writes_the_page_once_and_a_redelivery_writes_nothing() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            transport = RoutingTransport()
            handler = Arv2DisplayPageWorkHandler(
                settings=SETTINGS,
                conn_factory=conn_session_factory(conn),
                runner_factory=_factory(transport),
                artifacts=FakeArtifacts(),
            )
            job_id = uuid4()
            payload = display_page_payload(
                workspace_id=seeded.workspace_id,
                subject_kind="contact",
                subject_id=str(seeded.nick),
                page="contact",
                job_id=job_id,
            )

            first = await handler.handle(_context(payload))
            assert first.outcome == "completed"
            assert first.requeue is False
            assert sorted(first.references["generated"]) == sorted(transport.sections)
            assert len(transport.sections) == 5
            assert await _block_counts(conn, seeded.workspace_id) == (5, 0)
            # The page's spend is stamped with the research job that produced its claims.
            stamped = (
                await conn.execute(
                    text("SELECT count(*) FROM provider_call_ledger WHERE job_id = :job_id"),
                    {"job_id": job_id},
                )
            ).scalar_one()
            assert stamped == 5

            second = await handler.handle(_context(payload))
            assert second.outcome == "completed"
            assert second.references["generated"] == []
            assert len(transport.sections) == 5, "a redelivery costs nothing it already paid for"

    run_async(_run())


def test_a_payload_naming_no_subject_fails_without_requeue() -> None:
    handler = Arv2DisplayPageWorkHandler(
        settings=SETTINGS, conn_factory=None, runner_factory=None, artifacts=FakeArtifacts()  # type: ignore[arg-type]
    )
    result = asyncio.run(handler.handle(_context({"workspace_id": WORKSPACE})))
    assert result.outcome == "failed"
    assert result.requeue is False


def test_an_unknown_subject_fails_without_requeue() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            handler = Arv2DisplayPageWorkHandler(
                settings=SETTINGS,
                conn_factory=conn_session_factory(conn),
                runner_factory=_factory(RoutingTransport(allowed=False)),
                artifacts=FakeArtifacts(),
            )
            payload = display_page_payload(
                workspace_id=seeded.workspace_id,
                subject_kind="account",
                subject_id=str(UUID(int=7)),
                page="overview",
            )
            result = await handler.handle(_context(payload))
            assert result.outcome == "failed"
            assert result.requeue is False
            assert result.references["reason"] == "SubjectNotFound"

    run_async(_run())
```

Note for the implementer: `provider_call_ledger.job_id` is the column `LedgerStamp.job_id` writes
(slice 1b); confirm the column name with `grep -n job_id libs/clue-spend/clue_spend/ledger.py`
before relying on the count assertion, and adjust the SQL to the real column if it differs.

- [ ] **Step 2: Run it to see it fail**

Run: `CLUE_DATABASE_URL=<throwaway-dsn> uv run pytest tests/arv2/display/test_fleet_handler_db.py -q`
Expected: FAIL with `ModuleNotFoundError: clue_api.arv2.display.fleet_handler`.

- [ ] **Step 3: Thread `job_id` through `ensure_page` and export `people_of`**

In `platform/api/clue_api/arv2/display/page.py`:

1. Rename `_people_of` to `people_of` (update its two call sites in this file) and add `"people_of"`
   to `__all__` if the module has one.
2. Add the keyword `job_id: UUID | None = None` to `ensure_page` after `regenerate_stale`, and
   change the drain stamp to `LedgerStamp(workspace_id=workspace_id, job_id=job_id)`.
   Add to the docstring: "``job_id`` is the research job whose claims this page is written from,
   when the caller knows it (the settle-time task does; a read does not): the page's spend then
   shows where the research spend shows."

- [ ] **Step 4: Write the handler**

`platform/api/clue_api/arv2/display/fleet_handler.py`:

```python
"""The arv2_display_page fleet handler (spec 2026-09-12 §2): one task writes one page.

The handler is thin on purpose. Everything about *what* a page is — which sections are missing,
which went stale, the gather, the floor, the spend rows — already lives in
:func:`~clue_api.arv2.display.page.ensure_page`; the handler only decides what a task's ending
means to the fleet. Idempotent by construction: ``display_block_live`` keeps one live row per
section and ``ensure_page`` writes only what is missing or stale, so a redelivered task pays for
nothing it already paid for.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import cast
from uuid import UUID

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.display.gather import SubjectKind, SubjectNotFound
from clue_api.arv2.display.page import (
    PageSubjectMismatch,
    RunnerFactory,
    default_runner_factory,
    ensure_page,
)
from clue_api.arv2.display.recipes import PAGES, Page
from clue_api.arv2.errors import Arv2Error, ProviderHalted, ProviderTransportError
from clue_api.arv2.provider_ledger import ArtifactSink
from clue_api.storage import StorageBackend
from clue_config import Secrets, Settings
from clue_core.json import JsonValue
from clue_db import ConnFactory, transaction
from clue_fleet import FleetTaskKind, WorkContext, WorkResult
from clue_obs import get_logger

__all__ = [
    "Arv2DisplayPageWorkHandler",
    "build_arv2_display_page_handler",
    "display_page_payload",
]

log = get_logger(__name__)


def display_page_payload(
    *,
    workspace_id: str,
    subject_kind: str,
    subject_id: str,
    page: str,
    job_id: UUID | None = None,
) -> dict[str, JsonValue]:
    """The one payload shape both enqueuers (the settle, the read) offer and the handler parses."""
    payload: dict[str, JsonValue] = {
        "workspace_id": workspace_id,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "page": page,
    }
    if job_id is not None:
        payload["job_id"] = str(job_id)
    return payload


@dataclass(frozen=True)
class _PageScope:
    workspace_id: str
    subject_kind: SubjectKind
    subject_id: str
    page: Page
    job_id: UUID | None


def _scope(payload: Mapping[str, JsonValue]) -> _PageScope | None:
    workspace_id = payload.get("workspace_id")
    subject_kind = payload.get("subject_kind")
    subject_id = payload.get("subject_id")
    page = payload.get("page")
    if not (
        isinstance(workspace_id, str)
        and subject_kind in ("account", "contact")
        and isinstance(subject_id, str)
        and page in PAGES
    ):
        return None
    try:
        UUID(subject_id)
    except ValueError:
        return None
    raw_job = payload.get("job_id")
    job_id: UUID | None = None
    if isinstance(raw_job, str):
        try:
            job_id = UUID(raw_job)
        except ValueError:
            job_id = None
    return _PageScope(
        workspace_id=workspace_id,
        subject_kind=cast(SubjectKind, subject_kind),
        subject_id=subject_id,
        page=cast(Page, page),
        job_id=job_id,
    )


class Arv2DisplayPageWorkHandler:
    """One display page, as one fleet work handler."""

    kind = FleetTaskKind.ARV2_DISPLAY_PAGE

    def __init__(
        self,
        *,
        settings: Settings,
        conn_factory: ConnFactory,
        runner_factory: RunnerFactory,
        artifacts: ArtifactSink,
    ) -> None:
        self._settings = settings
        self._conn_factory = conn_factory
        self._runner_factory = runner_factory
        self._artifacts = artifacts

    async def handle(self, context: WorkContext) -> WorkResult:
        """Write the page. Never raises: every ending is a :class:`WorkResult`."""
        scope = _scope(context.payload)
        if scope is None:
            log.error("arv2.display_page_invalid_payload", payload=sorted(context.payload))
            return WorkResult(outcome="failed", references={}, requeue=False)
        try:
            async with self._conn_factory() as conn:
                result = await ensure_page(
                    conn,
                    workspace_id=scope.workspace_id,
                    subject_kind=scope.subject_kind,
                    subject_id=scope.subject_id,
                    page=scope.page,
                    settings=self._settings,
                    runner_factory=self._runner_factory,
                    artifacts=self._artifacts,
                    spend_conn_factory=self._conn_factory,
                    regenerate_stale=True,
                    job_id=scope.job_id,
                )
        except (SubjectNotFound, PageSubjectMismatch) as exc:
            # The row this task names does not exist (or the page cannot be about it). Nothing to
            # retry; the next read of a real subject offers a real task.
            log.warning(
                "arv2.display_page_refused",
                reason=type(exc).__name__,
                workspace_id=scope.workspace_id,
                subject_kind=scope.subject_kind,
                subject_id=scope.subject_id,
                page=scope.page,
            )
            return WorkResult(
                outcome="failed", references={"reason": type(exc).__name__}, requeue=False
            )
        except (ProviderHalted, ProviderTransportError, Arv2Error, OSError, ValueError) as exc:
            # The provider (or our own sink) failed; the sections stay unwritten and the next read
            # of the page re-offers this task (reopen_terminal). A requeue here would hammer a
            # provider that just refused us.
            log.warning(
                "arv2.display_page_failed",
                reason=type(exc).__name__,
                error=str(exc),
                workspace_id=scope.workspace_id,
                subject_kind=scope.subject_kind,
                subject_id=scope.subject_id,
                page=scope.page,
            )
            return WorkResult(
                outcome="failed", references={"reason": type(exc).__name__}, requeue=False
            )
        log.info(
            "arv2.display_page_written",
            workspace_id=scope.workspace_id,
            subject_kind=scope.subject_kind,
            subject_id=scope.subject_id,
            page=scope.page,
            generated=list(result.generated),
            regenerated=list(result.regenerated),
            failed=list(result.failed),
            cost_usd=str(result.cost_usd),
        )
        return WorkResult(
            outcome="completed",
            references={
                "generated": list(result.generated),
                "regenerated": list(result.regenerated),
                "skipped_empty": list(result.skipped_empty),
                "failed": list(result.failed),
                "cost_usd": str(result.cost_usd),
                "finished_at": datetime.now(UTC).isoformat(),
            },
            requeue=False,
        )


def build_arv2_display_page_handler(
    settings: Settings, secrets: Secrets, *, storage: StorageBackend
) -> Arv2DisplayPageWorkHandler | None:
    """Compose the handler on this worker, or refuse loudly and compose nothing.

    The same two conditions the web seam's ``_production_runner_factory`` checks (spec §2): the
    display flag, and a model key. Without either the tasks stay queued for a worker that has both,
    which is the honest outcome — a keyless handler would fail every task at its first call.
    """
    if not settings.arv2_display_generate_on_read:
        log.info("arv2.display_page_handler_not_composed", reason="CLUE_ARV2_DISPLAY_GENERATE_ON_READ is off")
        return None
    key = secrets.openrouter_api_key
    if key is None or not key.get_secret_value().strip():
        log.warning(
            "arv2.display_page_handler_not_composed",
            reason="CLUE_OPENROUTER_API_KEY is not configured",
            detail="display page tasks stay queued until a worker with the key drains them",
        )
        return None
    return Arv2DisplayPageWorkHandler(
        settings=settings,
        conn_factory=transaction,
        runner_factory=default_runner_factory(settings, secrets),
        artifacts=DurableAgentArtifactStore(storage=storage, conn_factory=transaction),
    )
```

Import notes for the implementer: `JsonValue` lives where `clue_fleet.queue` imports it from
(`grep -n "JsonValue" platform/fleet/clue_fleet/queue.py`); `StorageBackend` is imported in
`fleet_main.py` — copy that import path. `PAGES` is `("overview", "insights", "contact")` in
`recipes.py`.

- [ ] **Step 5: Run the handler tests**

Run: `CLUE_DATABASE_URL=<throwaway-dsn> uv run pytest tests/arv2/display/test_fleet_handler_db.py tests/arv2/display/test_page_db.py -q`
Expected: PASS (the page suite still passes with the new keyword defaulting to `None`).

- [ ] **Step 6: Write the failing wiring test**

Append to `tests/api/test_fleet_wiring.py`, next to the discovery guard test:

```python
def test_arv2_display_page_handler_is_composed_when_given_and_kind_guarded() -> None:
    graph = _CompositionHandler(FleetTaskKind.EXECUTE_GRAPH)
    handler = _CompositionHandler(FleetTaskKind.ARV2_DISPLAY_PAGE)
    worker = build_multi_work_worker(
        _settings(),
        driver=build_fleet_run_driver(),
        graph_handler=graph,
        arv2_display_page_handler=handler,
        worker_id="shared-worker",
    )
    assert worker._handlers[FleetTaskKind.ARV2_DISPLAY_PAGE] is handler

    with pytest.raises(ValueError, match="arv2_display_page_handler must own"):
        build_multi_work_worker(
            _settings(),
            driver=build_fleet_run_driver(),
            graph_handler=graph,
            arv2_display_page_handler=_CompositionHandler(FleetTaskKind.ARV2_DISCOVERY),
        )
```

- [ ] **Step 7: Run it to see it fail**

Run: `uv run pytest tests/api/test_fleet_wiring.py -q -k display_page`
Expected: FAIL with `TypeError: unexpected keyword argument 'arv2_display_page_handler'`.

- [ ] **Step 8: Wire the worker and the boot**

In `platform/api/clue_api/fleet_wiring.py::build_multi_work_worker`: add the keyword
`arv2_display_page_handler: WorkHandler | None = None` after `arv2_discovery_handler`; add the
guard and the append in the same style as the discovery ones:

```python
    if (
        arv2_display_page_handler is not None
        and arv2_display_page_handler.kind is not FleetTaskKind.ARV2_DISPLAY_PAGE
    ):
        raise ValueError("arv2_display_page_handler must own arv2_display_page tasks")
    ...
    if arv2_display_page_handler is not None:
        handlers.append(arv2_display_page_handler)
```

And one docstring paragraph: "``arv2_display_page_handler`` (spec 2026-09-12) is the same shape
again: optional because a deployment with the display flag off or no model key composes none, and
kind-guarded here."

In `platform/api/clue_api/fleet_main.py`, beside the R4 line:

```python
        from clue_api.arv2.display.fleet_handler import build_arv2_display_page_handler

        # Spec 2026-09-12: the page writer. No model provider object — the runner reads the key
        # itself, the way the web seam's production factory does.
        arv2_display_page_handler = build_arv2_display_page_handler(
            settings, secrets, storage=storage
        )
```

and pass `arv2_display_page_handler=arv2_display_page_handler,` to `build_multi_work_worker`
(put the import at the top of the module with the other `clue_api.arv2` imports).

- [ ] **Step 9: Run the wiring test + the fleet suites + type check**

Run: `uv run pytest tests/api/test_fleet_wiring.py -q` and
`uv run ruff check platform/api/clue_api/arv2/display/fleet_handler.py platform/api/clue_api/fleet_wiring.py platform/api/clue_api/fleet_main.py platform/api/clue_api/arv2/display/page.py && uv run ruff format --check <same files> && uv run mypy platform/api/clue_api/arv2/display platform/api/clue_api/fleet_wiring.py platform/api/clue_api/fleet_main.py`
Expected: all green.

- [ ] **Step 10: Commit**

```bash
git add platform/api/clue_api/arv2/display/fleet_handler.py platform/api/clue_api/arv2/display/page.py platform/api/clue_api/fleet_wiring.py platform/api/clue_api/fleet_main.py tests/arv2/display/test_fleet_handler_db.py tests/api/test_fleet_wiring.py
git commit -m "feat(display): arv2_display_page fleet handler — ensure_page on the worker, spend stamped with the research job"
```

---

### Task 3: The account overview is offered when the account job settles

**Files:**
- Modify: `platform/api/clue_api/arv2/account_research_driver.py:940-1035`
- Test: `tests/arv2/test_account_research_driver.py`

**Interfaces:**
- Consumes: Task 1's `ARV2_DISPLAY_DEDUP_PREFIX`, `ARV2_DISPLAY_TASK_PRIORITY`, `arv2_display_work_id`; Task 2's `display_page_payload`.
- Produces: `Arv2AccountResearchWorkHandler._offer_display_page(composition) -> None` (private; called after `_offer_committee`).

- [ ] **Step 1: Write the failing test**

Append to `tests/arv2/test_account_research_driver.py`, after the committee-offer tests (reuse
`_run_row`, `_job_row`, `FakeStore`, `_patch_reads`, `_patch_committee_step`, `_handler`,
`_finalizes_with_a_committee`, `_RecordingQueue`, `_context` exactly as the test at line ~1149 does):

```python
def test_an_account_job_offers_its_overview_page_after_the_committee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec 2026-09-12 §2: the overview is written at settle — offered after the commit, after
    the committee's person jobs, stamped with the account job as the page's spend."""
    run = _run_row()
    job = _job_row(run)
    store = FakeStore(run, job)
    _patch_reads(
        monkeypatch, account=SimpleNamespace(canonical_name="Probook", primary_domain="probook.ai")
    )
    _patch_committee_step(monkeypatch, store, run)
    handler, _conn_factory, _writer, _models = _handler(
        store, model=_finalizes_with_a_committee(), queue=_RecordingQueue(store)
    )

    result = asyncio.run(handler.handle(_context(job)))

    assert result.outcome == "completed"
    offers = [payload for name, payload in store.events if name == "enqueue"]
    kinds = [offer["kind"] for offer in offers]
    assert kinds[-1] == FleetTaskKind.ARV2_DISPLAY_PAGE
    assert FleetTaskKind.ARV2_ACCOUNT_RESEARCH in kinds[:-1]
    page = offers[-1]
    assert page["work_id"] == arv2_display_work_id("account", str(job.account_entity_id), "overview")
    assert page["dedup_key"] == f"{ARV2_DISPLAY_DEDUP_PREFIX}account:{job.account_entity_id}:overview"
    assert page["priority"] == ARV2_DISPLAY_TASK_PRIORITY
    assert page["reopen_terminal"] is True
    assert page["payload"] == {
        "workspace_id": job.workspace_id,
        "subject_kind": "account",
        "subject_id": str(job.account_entity_id),
        "page": "overview",
        "job_id": str(job.job_id),
    }


def test_a_worker_with_no_queue_says_it_offered_no_overview_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    job = _job_row(run)
    store = FakeStore(run, job)
    _patch_reads(
        monkeypatch, account=SimpleNamespace(canonical_name="Probook", primary_domain="probook.ai")
    )
    _patch_committee_step(monkeypatch, store, run)
    handler, _conn_factory, _writer, _models = _handler(
        store, model=_finalizes_with_a_committee(), queue=None
    )
    result = asyncio.run(handler.handle(_context(job)))
    assert result.outcome == "completed"
    assert not store.named("enqueue")
```

Add the imports the test needs at the top of the file:
`from clue_api.arv2.fleet_task import ARV2_DISPLAY_DEDUP_PREFIX, ARV2_DISPLAY_TASK_PRIORITY, arv2_display_work_id`
and `from clue_fleet import FleetTaskKind` if not already imported.

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/arv2/test_account_research_driver.py -q -k overview_page`
Expected: FAIL — the last offer's kind is `ARV2_ACCOUNT_RESEARCH` (no page offer exists).

- [ ] **Step 3: Add the offer**

In `platform/api/clue_api/arv2/account_research_driver.py`, right after
`await self._offer_committee(composition, committee)` in `_settle`:

```python
        await self._offer_display_page(composition)
```

and the method after `_offer_committee`:

```python
    async def _offer_display_page(self, composition: _Composition) -> None:
        """Offer the account's overview page — **after** the settle committed. Never raises.

        Spec 2026-09-12 §2: the overview is written when the account job settles, so the first
        person to open the account reads a page instead of paying for one. Only the account job
        offers (a person job settling enqueues nothing: contact pages are paid for on accounts a
        user opens). The offer rides the committee offer's rules: rows first, offer second; a
        failed offer is logged, never raised — the next read of the page re-offers it.
        """
        if composition.job.subject_type != "account":
            return
        if self._queue is None:
            log.warning(
                "arv2.display_page_not_enqueued",
                job_id=str(composition.job.job_id),
                account_entity_id=str(composition.job.account_entity_id),
                detail=(
                    "this worker composed the ARV2 research handler without a work queue, so the "
                    "account's overview page will be written on its first open instead"
                ),
            )
            return
        subject_id = str(composition.job.account_entity_id)
        try:
            await self._queue.enqueue(
                kind=FleetTaskKind.ARV2_DISPLAY_PAGE,
                work_id=arv2_display_work_id("account", subject_id, "overview"),
                dedup_key=f"{ARV2_DISPLAY_DEDUP_PREFIX}account:{subject_id}:overview",
                priority=ARV2_DISPLAY_TASK_PRIORITY,
                payload=display_page_payload(
                    workspace_id=composition.job.workspace_id,
                    subject_kind="account",
                    subject_id=subject_id,
                    page="overview",
                    job_id=composition.job.job_id,
                ),
                # A re-settle re-offers the page: a terminal (done or failed) task is re-opened,
                # a queued or claimed one is left alone.
                reopen_terminal=True,
            )
        except Exception:  # noqa: BLE001 — the job's terminal row must survive a queue outage
            log.exception("arv2.display_page_enqueue_failed", job_id=str(composition.job.job_id))
```

Imports at the top of the driver: `ARV2_DISPLAY_DEDUP_PREFIX`, `ARV2_DISPLAY_TASK_PRIORITY`,
`arv2_display_work_id` from `clue_api.arv2.fleet_task` (the module already imports from it), and
`from clue_api.arv2.display.fleet_handler import display_page_payload`. Check
`uv run lint-imports` afterwards: `clue_api.arv2` importing `clue_api.arv2.display` is inside the
lane and allowed; if the import contract objects, move `display_page_payload` into
`clue_api/arv2/fleet_task.py` (it is pure) and import it from there in both places.

- [ ] **Step 4: Run the driver suite**

Run: `uv run pytest tests/arv2/test_account_research_driver.py -q && uv run lint-imports`
Expected: PASS; import contracts kept.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/account_research_driver.py tests/arv2/test_account_research_driver.py
git commit -m "feat(arv2): the account job offers its overview page after the committee — written at settle"
```

---

### Task 4: `pending` on the section contract

**Files:**
- Modify: `platform/api/clue_api/frontend_read/contract_v1.py:290-309`
- Modify: `apps/frontend/src/features/accounts/model/research-display.ts:78-87`
- Modify: `tests/api/contract_v1/zod-fields.json` (regenerated)
- Modify: `apps/frontend/docs/api-contracts/accounts.md` (Section shape + field table)
- Test: `tests/api/contract_v1/test_contract_v1.py` (existing parity tests), `apps/frontend/src/features/accounts/model/research-display.test.ts`

**Interfaces:**
- Produces: `ResearchSection.pending: bool = False` (wire key `pending`); Zod
  `pending: z.boolean().default(false)`.

- [ ] **Step 1: Write the failing frontend model test**

`apps/frontend/src/features/accounts/model/research-display.test.ts` (create; `node:test` like its
neighbours — check how sibling `*.test.ts` files under `model/` import the schema and follow them):

```ts
import assert from "node:assert/strict";
import test from "node:test";

import { ResearchSectionSchema } from "./research-display";

test("a section is not pending unless the server says so", () => {
  const section = ResearchSectionSchema.parse({
    key: "why-now",
    h1: "Why now",
    empty: true,
    items: [],
  });
  assert.equal(section.pending, false);
});

test("a pending section keeps its served placeholder sentence", () => {
  const section = ResearchSectionSchema.parse({
    key: "why-now",
    h1: "Why now",
    empty: true,
    items: [],
    pending: true,
    emptyMessage: "Synthesis in progress, please wait a few seconds.",
  });
  assert.equal(section.pending, true);
  assert.equal(section.emptyMessage, "Synthesis in progress, please wait a few seconds.");
});
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd apps/frontend && npm test -- src/features/accounts/model/research-display.test.ts`
(if `npm test` takes no path, run the whole suite and find the two new failures).
Expected: FAIL — `section.pending` is `undefined`.

- [ ] **Step 3: Add the field on both sides**

Zod, in `ResearchSectionSchema` after `defaultOpen`:

```ts
  // Plan 2026-09-21: true while the fleet is writing this section; the client polls while any
  // section on the page is pending and renders `emptyMessage` verbatim meanwhile.
  pending: z.boolean().default(false),
```

Pydantic, in `ResearchSection` after `default_open`:

```python
    # Plan 2026-09-21: the section is missing AND a fleet task is writing it. Served with the one
    # ``empty_message`` sentence; the client polls the page while any section is pending.
    pending: bool = False
```

and extend the docstring: "``pending`` is true only when the section will be written (its recipe
matched claims and its page task is offered); a section that matches nothing is never pending."

- [ ] **Step 4: Regenerate the committed Zod shapes and update the doc**

From the monorepo root:

```bash
NODE_ROOT="$PWD/apps/frontend"
NODE_PATH="$NODE_ROOT/node_modules" npx --prefix "$NODE_ROOT" tsx "$PWD/tests/api/contract_v1/validate.ts" --shapes > tests/api/contract_v1/zod-fields.json
```

In `apps/frontend/docs/api-contracts/accounts.md`: change the Section line of the shape block to

```
  Section  { key, h1, empty, items[], intro[]?, restricted=false, defaultOpen=false, emptyMessage?, pending=false }
```

and add a field-table row directly under the `ResearchSection.empty` / `emptyMessage` row:

```
| `ResearchSection.pending` | `true` while a fleet task is writing the section (plan 2026-09-21): the section is `empty`, its `emptyMessage` is the served sentence `Synthesis in progress, please wait a few seconds.`, and the client re-reads the page every 5 s while any section is pending. Never `true` for a section whose recipe matched nothing. |
```

- [ ] **Step 5: Run both parity suites**

Run: `cd apps/frontend && npm test` and, from the root, `uv run pytest tests/api/contract_v1 -q`.
Expected: PASS (fields carried on both sides; the committed shapes match; the doc table lists the
new field).

- [ ] **Step 6: Commit**

```bash
git add platform/api/clue_api/frontend_read/contract_v1.py apps/frontend/src/features/accounts/model/research-display.ts apps/frontend/src/features/accounts/model/research-display.test.ts tests/api/contract_v1/zod-fields.json apps/frontend/docs/api-contracts/accounts.md
git commit -m "feat(contract): ResearchSection.pending — a section the fleet is writing, with its placeholder sentence"
```

---

### Task 5: The read seam serves pending sections and offers tasks instead of writing inline

**Files:**
- Modify: `platform/api/clue_api/frontend_read/display_pages.py` (class `DisplayPages`, `PageRead`)
- Modify: `platform/api/clue_api/frontend_read/app.py:212-260` (`build_frontend_read_router`, `install_frontend_read_surface`)
- Modify: `platform/api/clue_api/projections_app.py:947-956`
- Modify: `platform/api/clue_api/frontend_read/contacts.py:729-742`
- Test: `tests/api/test_frontend_read_display_pages_db.py`, `tests/api/test_frontend_read_contacts.py`

**Interfaces:**
- Consumes: Task 1's ids, Task 2's `display_page_payload`, `people_of`; Task 4's `pending`.
- Produces:
  - `PENDING_MESSAGE = "Synthesis in progress, please wait a few seconds."`
  - `DisplayPages(..., queue: WorkQueue | None = None)`; property `schedules -> bool`
    (`queue is not None and settings.arv2_display_generate_on_read`).
  - `PageRead.pending: tuple[str, ...]` (section keys served pending).
  - `DisplayPages.offer_contact_pages(conn, *, workspace_id: str, account_id: str) -> int`
    (how many contact-page tasks were newly offered).
  - `build_frontend_read_router(..., work_queue: WorkQueue | None = None)` and
    `install_frontend_read_surface(..., work_queue: WorkQueue | None = None)`.

**Behaviour to implement (from spec §2 "on open" and §4, with the 2026-09-21 ruling):**

When `generate` is true and `self.schedules`:
1. Read live blocks and stale sections as today.
2. `missing = [recipe for recipe in recipes if recipe.section_key not in blocks]`. If any: resolve
   the subject, its members (account pages), `people_of`, then
   `gather_section_inputs(conn, workspace_id=…, subject=…, recipes=missing, people=…, settings=…)`;
   `pending = tuple(item.recipe.section_key for item in inputs if not item.empty)`.
3. If `pending` or `stale`: offer the page task (`reopen_terminal=True`). A queue failure is logged
   (`frontend_read.display.offer_failed`) and the sections are served NOT pending (the sentence is a
   promise; an offer that did not land cannot make it).
4. Compose the page; for every key in `pending` set `section["pending"] = True` and
   `section["emptyMessage"] = PENDING_MESSAGE`; then apply the existing outage sentence, which wins
   over the placeholder on the empty sections it names (an open incident is the more honest word).
5. Account pages additionally call `offer_contact_pages` (below), throttled per
   `(workspace_id, account_id)` by an in-process cooldown of 60 s.
6. No `ensure_page` call, no in-process regeneration task.

When there is no queue: today's behaviour, unchanged (inline write on miss, in-process background
regeneration on stale). `generate=False` stays a pure projection: no offers of any kind.

`offer_contact_pages`: members = `committee_members(...)`; candidates = members who have a settled
person job (`arv2_research_job.subject_type='person' AND subject_entity_id=<member> AND status IN
('completed','needs_review')`) and no live `display_block` on page `contact`; one offer per
candidate (`("contact", member_id, "contact")`, `reopen_terminal=True`, payload from
`display_page_payload` with `job_id` = that person job's id). Returns the count of `True` offers.

- [ ] **Step 1: Write the failing seam tests**

Append to `tests/api/test_frontend_read_display_pages_db.py` (reuse `_pages`, `_sections`,
`_retired_blocks`, `RoutingTransport`, `_factory`, `seed_display_fixture`, `rollback_conn`,
`run_async`, `WORKSPACE`; `SETTINGS` in that file has `arv2_display_generate_on_read=True` — check
`grep -n "SETTINGS =" tests/api/test_frontend_read_display_pages_db.py` and keep using it):

```python
from clue_api.arv2.account_research_store import create_job, finish_job
from clue_api.arv2.fleet_task import ARV2_DISPLAY_DEDUP_PREFIX, arv2_display_work_id
from clue_api.frontend_read.display_pages import PENDING_MESSAGE
from clue_fleet import FleetTaskKind


class _RecordingQueue:
    def __init__(self, *, accept: bool = True) -> None:
        self.offers: list[dict[str, Any]] = []
        self._accept = accept

    async def enqueue(self, **kwargs: Any) -> bool:
        self.offers.append(kwargs)
        return self._accept


class _BrokenQueue:
    async def enqueue(self, **kwargs: Any) -> bool:
        raise RuntimeError("queue down")


def test_with_a_queue_a_missing_page_is_served_pending_and_offered_never_written_inline() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            transport = RoutingTransport(allowed=False)
            queue = _RecordingQueue()
            pages = _pages(conn, runner_factory=_factory(transport), queue=queue)
            assert pages.schedules is True

            read = await pages.page(
                conn,
                workspace_id=seeded.workspace_id,
                subject_kind="contact",
                subject_id=str(seeded.nick),
                page="contact",
            )

            assert transport.sections == [], "a read with a queue never calls the model"
            assert read.generated == ()
            assert read.pending == CONTACT_SECTIONS
            for section in _sections(read):
                assert section["empty"] is True
                assert section["pending"] is True
                assert section["emptyMessage"] == PENDING_MESSAGE
            assert len(queue.offers) == 1
            offer = queue.offers[0]
            assert offer["kind"] is FleetTaskKind.ARV2_DISPLAY_PAGE
            assert offer["work_id"] == arv2_display_work_id("contact", str(seeded.nick), "contact")
            assert offer["dedup_key"] == f"{ARV2_DISPLAY_DEDUP_PREFIX}contact:{seeded.nick}:contact"
            assert offer["reopen_terminal"] is True
            assert offer["payload"]["page"] == "contact"
            assert pages._regenerating == {}
            assert await _retired_blocks(conn, seeded.workspace_id) == 0

    run_async(_run())


def test_a_section_that_matches_nothing_is_never_pending() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            queue = _RecordingQueue()
            pages = _pages(conn, runner_factory=_factory(RoutingTransport(allowed=False)), queue=queue)

            # ``silent`` holds no claims: no section can ever be written for them.
            read = await pages.page(
                conn,
                workspace_id=seeded.workspace_id,
                subject_kind="contact",
                subject_id=str(seeded.silent),
                page="contact",
            )

            assert read.pending == ()
            assert all(not section["pending"] for section in _sections(read))
            assert all("emptyMessage" not in section for section in _sections(read))
            assert queue.offers == [], "nothing to write, nothing offered"

    run_async(_run())


def test_an_offer_that_fails_serves_the_sections_honestly_empty() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            pages = _pages(
                conn, runner_factory=_factory(RoutingTransport(allowed=False)), queue=_BrokenQueue()
            )
            read = await pages.page(
                conn,
                workspace_id=seeded.workspace_id,
                subject_kind="contact",
                subject_id=str(seeded.nick),
                page="contact",
            )
            assert read.pending == ()
            assert all(not section["pending"] for section in _sections(read))

    run_async(_run())


def test_a_stored_page_with_a_stale_section_is_served_as_stored_and_the_page_is_offered() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            transport = RoutingTransport()
            # Write the page the old way first (no queue), so every section is stored.
            written = await _pages(conn, runner_factory=_factory(transport)).page(
                conn,
                workspace_id=seeded.workspace_id,
                subject_kind="contact",
                subject_id=str(seeded.nick),
                page="contact",
            )
            assert written.generated == CONTACT_SECTIONS
            calls_before = len(transport.sections)
            # A new claim under one recipe makes one section stale.
            await write_claim(conn, seeded, "nick_new_title", seeded.nick, "contact.current_title", "CMO")

            queue = _RecordingQueue()
            pages = _pages(conn, runner_factory=_factory(transport), queue=queue)
            read = await pages.page(
                conn,
                workspace_id=seeded.workspace_id,
                subject_kind="contact",
                subject_id=str(seeded.nick),
                page="contact",
            )

            assert len(transport.sections) == calls_before, "served as stored, no rewrite inline"
            assert read.stale != ()
            assert read.pending == ()
            assert all(not section["empty"] for section in _sections(read))
            assert len(queue.offers) == 1 and queue.offers[0]["payload"]["page"] == "contact"
            assert pages._regenerating == {}

    run_async(_run())


def test_opening_an_account_offers_the_contact_pages_of_settled_members_once() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            # Nick has a settled person job; Vari has none.
            run_id, account_job, nick_job = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            await _seed_run(conn, seeded, run_id)  # see the note below
            await create_job(conn, job_id=account_job, run_id=run_id, workspace_id=seeded.workspace_id, account_entity_id=uuid.UUID(str(seeded.account)))
            await create_job(conn, job_id=nick_job, run_id=run_id, workspace_id=seeded.workspace_id, account_entity_id=uuid.UUID(str(seeded.account)), subject_type="person", subject_entity_id=uuid.UUID(str(seeded.nick)))
            await _settle_job(conn, nick_job)  # finish_job(..., status="completed", ...)

            queue = _RecordingQueue()
            pages = _pages(conn, runner_factory=_factory(RoutingTransport(allowed=False)), queue=queue)
            await pages.page(
                conn,
                workspace_id=seeded.workspace_id,
                subject_kind="account",
                subject_id=str(seeded.account),
                page="overview",
            )
            contact_offers = [o for o in queue.offers if o["payload"]["subject_kind"] == "contact"]
            assert [o["payload"]["subject_id"] for o in contact_offers] == [str(seeded.nick)]
            assert contact_offers[0]["payload"]["job_id"] == str(nick_job)

            # A second open inside the cooldown offers no contact page again.
            await pages.page(
                conn,
                workspace_id=seeded.workspace_id,
                subject_kind="account",
                subject_id=str(seeded.account),
                page="insights",
            )
            assert len([o for o in queue.offers if o["payload"]["subject_kind"] == "contact"]) == 1

            # A member whose page exists is skipped: write Nick's page, clear the cooldown, reopen.
            await _pages(conn, runner_factory=_factory(RoutingTransport())).page(
                conn,
                workspace_id=seeded.workspace_id,
                subject_kind="contact",
                subject_id=str(seeded.nick),
                page="contact",
            )
            pages._contact_offers.clear()
            await pages.page(
                conn,
                workspace_id=seeded.workspace_id,
                subject_kind="account",
                subject_id=str(seeded.account),
                page="overview",
            )
            assert len([o for o in queue.offers if o["payload"]["subject_kind"] == "contact"]) == 1

    run_async(_run())
```

Notes for the implementer: `_seed_run` must insert the `arv2_research_run` row `create_job`'s FK
needs — copy the run insert from `tests/arv2/test_account_research_driver_db.py` (grep
`arv2_research_run` there) into a small helper in this test file; `_settle_job` calls
`finish_job(conn, job_id, status="completed", finalization={}, model_rounds=0, tool_calls=0,
cost_usd=Decimal(0), credits=Decimal(0), media_seconds=0)` — check `finish_job`'s full keyword list
in `account_research_store.py:321` and pass every required one. Extend `_pages` to forward a
`queue=` keyword: `queue=kwargs.pop("queue", None)`. `write_claim` is imported from
`tests.arv2.display._seed`; match its real signature (`grep -n "def write_claim" tests/arv2/display/_seed.py`).

- [ ] **Step 2: Run them to see them fail**

Run: `CLUE_DATABASE_URL=<throwaway-dsn> uv run pytest tests/api/test_frontend_read_display_pages_db.py -q -k "queue or pending or offer"`
Expected: FAIL with `TypeError: unexpected keyword argument 'queue'`.

- [ ] **Step 3: Implement the queue path in the seam**

In `platform/api/clue_api/frontend_read/display_pages.py`:

1. Constants and imports:

```python
from time import monotonic

from sqlalchemy import text

from clue_api.arv2.display.fleet_handler import display_page_payload
from clue_api.arv2.display.gather import gather_section_inputs
from clue_api.arv2.display.page import people_of
from clue_api.arv2.fleet_task import (
    ARV2_DISPLAY_DEDUP_PREFIX,
    ARV2_DISPLAY_TASK_PRIORITY,
    arv2_display_work_id,
)
from clue_fleet import FleetTaskKind, WorkQueue

#: The one sentence a section carries while the fleet is writing it (founder ruling 2026-09-21).
PENDING_MESSAGE = "Synthesis in progress, please wait a few seconds."
#: How long one web process waits before re-offering an account's contact pages on open.
_CONTACT_OFFER_COOLDOWN_S = 60.0

_SETTLED_MEMBER_JOBS = text(
    """
    SELECT DISTINCT ON (subject_entity_id) subject_entity_id, job_id
    FROM arv2_research_job
    WHERE workspace_id = :workspace_id
      AND subject_type = 'person'
      AND subject_entity_id = ANY(CAST(:member_ids AS uuid[]))
      AND status IN ('completed', 'needs_review')
    ORDER BY subject_entity_id, finished_at DESC NULLS LAST
    """
)
_MEMBERS_WITH_A_PAGE = text(
    """
    SELECT DISTINCT subject_id FROM display_block
    WHERE workspace_id = :workspace_id AND subject_kind = 'contact' AND page = 'contact'
      AND subject_id = ANY(CAST(:member_ids AS uuid[])) AND superseded_at IS NULL
    """
)
```

2. `PageRead` gains `pending: tuple[str, ...] = ()`.

3. `DisplayPages.__init__` gains `queue: WorkQueue | None = None`, stores `self._queue = queue`
   and `self._contact_offers: dict[tuple[str, str], float] = {}`. Add:

```python
    @property
    def schedules(self) -> bool:
        """Whether a read hands page writes to the fleet instead of writing inline."""
        return self._queue is not None and self._settings.arv2_display_generate_on_read
```

4. In `page()`, replace the `if generate and self.generates:` inline block with:

```python
        pending: tuple[str, ...] = ()
        if generate and self.schedules:
            pending = await self._offer_missing_and_stale(
                conn,
                workspace_id=workspace_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                page=page,
                recipes=recipes,
                expansion=expansion,
            )
            if subject_kind == "account":
                await self._offer_members_on_open(
                    conn, workspace_id=workspace_id, account_id=subject_id
                )
        elif generate and self.generates:
            ... (the existing inline block, unchanged)
```

   and, further down, keep the existing `if stale_keys and generate:` in-process scheduling ONLY
   for the no-queue path: `if stale_keys and generate and not self.schedules:`.

   After `display_block = compose_display_block(page, recipes, blocks)` and BEFORE the outage
   sentence loop:

```python
        for section in display_block["sections"]:
            if section["key"] in pending:
                section["pending"] = True
                section["emptyMessage"] = PENDING_MESSAGE
```

   and include `pending=pending` in the returned `PageRead`.

5. The two new methods:

```python
    async def _offer_missing_and_stale(
        self,
        conn: AsyncConnection,
        *,
        workspace_id: str,
        subject_kind: SubjectKind,
        subject_id: str,
        page: Page,
        recipes: Sequence[SectionRecipe],
        expansion: Sequence[str],
    ) -> tuple[str, ...]:
        """Offer this page's task when anything on it needs writing; return the keys that will be.

        A missing section is *pending* only when the gather step (no model call) says its recipe
        matched claims: the placeholder sentence is a promise, and a section that matches nothing
        keeps the ordinary empty state. A stale section is served as stored and re-offered; it is
        never pending, because it is not empty.
        """
        blocks = await live_blocks(
            conn, workspace_id=workspace_id, subject_kind=subject_kind, subject_id=subject_id, page=page
        )
        stale = await stale_sections(
            conn, workspace_id=workspace_id, subject_ids=expansion, recipes=recipes, blocks=blocks
        )
        missing = [recipe for recipe in recipes if recipe.section_key not in blocks]
        would_write: tuple[str, ...] = ()
        if missing:
            subject = await resolve_subject(
                conn, workspace_id=workspace_id, kind=subject_kind, subject_id=subject_id
            )
            members = (
                await committee_members(conn, workspace_id=workspace_id, account_id=subject.account_id)
                if subject.kind == "account"
                else []
            )
            people, _ = people_of(subject, members)
            inputs = await gather_section_inputs(
                conn,
                workspace_id=workspace_id,
                subject=subject,
                recipes=missing,
                people=people,
                settings=self._settings,
            )
            would_write = tuple(item.recipe.section_key for item in inputs if not item.empty)
        if not would_write and not stale:
            return ()
        offered = await self._offer_page(
            workspace_id=workspace_id, subject_kind=subject_kind, subject_id=subject_id, page=page
        )
        return would_write if offered else ()

    async def _offer_page(
        self,
        *,
        workspace_id: str,
        subject_kind: SubjectKind,
        subject_id: str,
        page: Page,
        job_id: uuid.UUID | None = None,
    ) -> bool:
        """One page task on the fleet; ``True`` when the offer landed (new or re-opened, or already
        queued — every one of those means the page will be written). ``False`` only when the queue
        itself failed, which is logged and never raised into a read."""
        assert self._queue is not None
        try:
            await self._queue.enqueue(
                kind=FleetTaskKind.ARV2_DISPLAY_PAGE,
                work_id=arv2_display_work_id(subject_kind, subject_id, page),
                dedup_key=f"{ARV2_DISPLAY_DEDUP_PREFIX}{subject_kind}:{subject_id}:{page}",
                priority=ARV2_DISPLAY_TASK_PRIORITY,
                payload=display_page_payload(
                    workspace_id=workspace_id,
                    subject_kind=subject_kind,
                    subject_id=subject_id,
                    page=page,
                    job_id=job_id,
                ),
                reopen_terminal=True,
            )
        except Exception as exc:  # noqa: BLE001 — a queue outage must not fail a read
            log.warning(
                "frontend_read.display.offer_failed",
                workspace_id=workspace_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                page=page,
                error=str(exc),
            )
            return False
        return True

    async def _offer_members_on_open(
        self, conn: AsyncConnection, *, workspace_id: str, account_id: str
    ) -> None:
        key = (workspace_id, account_id)
        last = self._contact_offers.get(key)
        now = monotonic()
        if last is not None and now - last < _CONTACT_OFFER_COOLDOWN_S:
            return
        self._contact_offers[key] = now
        await self.offer_contact_pages(conn, workspace_id=workspace_id, account_id=account_id)

    async def offer_contact_pages(
        self, conn: AsyncConnection, *, workspace_id: str, account_id: str
    ) -> int:
        """Spec 2026-09-12 §2 "on open": offer the contact page of every committee member with a
        settled person job and no live page. Idempotent on the fleet by work id; returns how many
        offers landed. A seam with no queue offers nothing."""
        if not self.schedules:
            return 0
        members = await committee_members(conn, workspace_id=workspace_id, account_id=account_id)
        if not members:
            return 0
        member_ids = [member.id for member in members]
        settled = {
            str(row["subject_entity_id"]): row["job_id"]
            for row in (
                await conn.execute(
                    _SETTLED_MEMBER_JOBS, {"workspace_id": workspace_id, "member_ids": member_ids}
                )
            ).mappings()
        }
        written = {
            str(row["subject_id"])
            for row in (
                await conn.execute(
                    _MEMBERS_WITH_A_PAGE, {"workspace_id": workspace_id, "member_ids": member_ids}
                )
            ).mappings()
        }
        offered = 0
        for member in members:
            if member.id not in settled or member.id in written:
                continue
            if await self._offer_page(
                workspace_id=workspace_id,
                subject_kind="contact",
                subject_id=member.id,
                page="contact",
                job_id=settled[member.id],
            ):
                offered += 1
        return offered
```

   Check `SubjectRef.id` is a `str` (it is used as `str` in `_expansion`); if the SQL's
   `uuid[]` cast rejects the strings, wrap with `[uuid.UUID(m) for m in member_ids]`.

6. Update the class docstring: one paragraph saying that with a queue the seam is a *scheduler*
   (serves stored blocks, offers tasks, marks pending) and without one it is the D3 inline writer.

- [ ] **Step 4: Thread the queue from the composition root**

`build_frontend_read_router(..., work_queue: WorkQueue | None = None)` passes
`queue=work_queue` into `DisplayPages(...)`; `install_frontend_read_surface` takes and forwards
the same keyword. In `platform/api/clue_api/projections_app.py` at the install call add
`work_queue=DbWorkQueue(),` (import `from clue_fleet import DbWorkQueue`; it is the same default
queue the onboarding enqueuer and the persona request service already use in this process).
Docstring line in `build_frontend_read_router`: "``work_queue`` reaches exactly one place, the
display seam: with it a read schedules page writes on the fleet; without it the seam writes
inline (tests, a queue-less deployment)."

- [ ] **Step 5: The contacts tab offers the members' pages**

In `platform/api/clue_api/frontend_read/contacts.py::register_contact_routes`, inside
`list_account_contacts` after `read_account_contacts(...)` returns (bind the response to a name
first), add:

```python
                # Spec 2026-09-12 §2 "on open": the contacts tab is one of the three opens that
                # start the members' pages. Idempotent on the fleet; a seam without a queue is a
                # no-op here.
                await display.offer_contact_pages(
                    conn, workspace_id=workspace_id, account_id=str(account_id)
                )
```

`display` is already a parameter of `register_contact_routes`. The account id must be the
canonical (survivor) id the read resolved — reuse whatever `read_account_contacts` resolved if it
exposes it; otherwise resolve with the same helper it uses (grep `surviving_id` in that file) and
pass that. Add a test to `tests/api/test_frontend_read_contacts.py` asserting a `_RecordingQueue`
seam records offers when the tab is read for an account with a settled member (mirror the seam
test's job seeding; if that suite builds its `DisplayPages` without a queue, extend its fixture the
way `_pages` was extended).

- [ ] **Step 6: Run the seam and contacts suites, lint, types**

Run: `CLUE_DATABASE_URL=<throwaway-dsn> uv run pytest tests/api/test_frontend_read_display_pages_db.py tests/api/test_frontend_read_contacts.py tests/api/test_frontend_read_account_detail.py tests/api/test_frontend_read_account_workspace.py tests/api/test_frontend_read_app.py -q`
then `uv run ruff check platform/api/clue_api/frontend_read && uv run ruff format --check platform/api/clue_api/frontend_read && uv run mypy platform/api/clue_api/frontend_read && uv run lint-imports`.
Expected: green. The pre-existing inline-path tests still pass because no queue is given there.

- [ ] **Step 7: Commit**

```bash
git add platform/api/clue_api/frontend_read/display_pages.py platform/api/clue_api/frontend_read/app.py platform/api/clue_api/frontend_read/contacts.py platform/api/clue_api/projections_app.py tests/api/test_frontend_read_display_pages_db.py tests/api/test_frontend_read_contacts.py
git commit -m "feat(display): the read serves pending sections and offers page tasks — no inline write when a queue is composed"
```

---

### Task 6: The page polls while any section is pending

**Files:**
- Create: `apps/frontend/src/features/accounts/hooks/use-pending-sections-refresh.ts`
- Modify: `apps/frontend/src/features/accounts/components/research-content.tsx` (`ResearchDocument`, `ResearchStack`, `ResearchOverview`)
- Test: `apps/frontend/src/features/accounts/hooks/use-pending-sections-refresh.test.ts`, `apps/frontend/src/features/accounts/components/research-pending-poll.test.ts`

**Interfaces:**
- Consumes: Task 4's `pending` on `ResearchSection`.
- Produces: `anySectionPending(sections: ReadonlyArray<{ pending?: boolean }>): boolean`;
  `usePendingSectionsRefresh(pending: boolean, pollMs?: number): void`.

- [ ] **Step 1: Write the failing tests**

`apps/frontend/src/features/accounts/hooks/use-pending-sections-refresh.test.ts`:

```ts
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { anySectionPending } from "./use-pending-sections-refresh";

test("a page is pending when any section is", () => {
  assert.equal(anySectionPending([]), false);
  assert.equal(anySectionPending([{ pending: false }, {}]), false);
  assert.equal(anySectionPending([{ pending: false }, { pending: true }]), true);
});

test("the hook refreshes the server page on an interval only while pending", () => {
  const source = readFileSync(new URL("./use-pending-sections-refresh.ts", import.meta.url), "utf8");
  assert.match(source, /"use client"/);
  assert.match(source, /useRouter\(\)/);
  assert.match(source, /if \(!pending\) return;/);
  assert.match(source, /window\.setInterval\(\(\) => router\.refresh\(\), pollMs\)/);
  assert.match(source, /window\.clearInterval\(interval\)/);
  assert.match(source, /pollMs = 5000/);
});
```

`apps/frontend/src/features/accounts/components/research-pending-poll.test.ts`:

```ts
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const renderer = readFileSync(new URL("./research-content.tsx", import.meta.url), "utf8");

function body(name: string): string {
  const start = renderer.indexOf(`export function ${name}(`);
  assert.notEqual(start, -1, `${name} exists`);
  const next = renderer.indexOf("\nexport function ", start + 1);
  return renderer.slice(start, next === -1 ? undefined : next);
}

test("every section renderer polls while a section is pending", () => {
  for (const name of ["ResearchDocument", "ResearchStack", "ResearchOverview"]) {
    assert.match(body(name), /usePendingSectionsRefresh\(anySectionPending\(sections\)\)/, name);
  }
});

test("the placeholder sentence is served, never hardcoded on the client", () => {
  assert.doesNotMatch(renderer, /Synthesis in progress/);
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/frontend && npm test`
Expected: the two new files FAIL (module not found; hook not called).

- [ ] **Step 3: Write the hook**

`apps/frontend/src/features/accounts/hooks/use-pending-sections-refresh.ts`:

```ts
"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/** Whether any section of a page is still being written by the fleet. */
export function anySectionPending(sections: ReadonlyArray<{ pending?: boolean }>): boolean {
  return sections.some((section) => section.pending === true);
}

/**
 * Re-read the page every `pollMs` while a section is pending (spec 2026-09-12 §4, ruling
 * 2026-09-21). The account pages are server components that fetch once, so the poll is a
 * `router.refresh()`: the server re-reads, the pending sections arrive written, and the
 * placeholder sentence they carried is replaced by their items. Stops as soon as nothing is
 * pending; never runs on a fully written page.
 */
export function usePendingSectionsRefresh(pending: boolean, pollMs = 5000): void {
  const router = useRouter();
  useEffect(() => {
    if (!pending) return;
    const interval = window.setInterval(() => router.refresh(), pollMs);
    return () => window.clearInterval(interval);
  }, [pending, pollMs, router]);
}
```

- [ ] **Step 4: Mount it in the three renderers**

In `research-content.tsx` add the import
`import { anySectionPending, usePendingSectionsRefresh } from "../hooks/use-pending-sections-refresh";`
and, as the first hook line inside `ResearchDocument`, `ResearchStack` and `ResearchOverview`
(after their destructured props, before any early return):

```ts
  usePendingSectionsRefresh(anySectionPending(sections));
```

`ResearchStack` and `ResearchOverview` may compute a derived section list (`displaySections`);
pass the raw `sections` prop, which carries the served `pending` flags.

- [ ] **Step 5: Run the frontend gate**

Run: `cd apps/frontend && npm test && npm run design-system:build && npm run lint && npm run build`
Expected: all green (stop the lane stack before `npm run build` if the runbook note for this lane
says so).

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/features/accounts/hooks/use-pending-sections-refresh.ts apps/frontend/src/features/accounts/hooks/use-pending-sections-refresh.test.ts apps/frontend/src/features/accounts/components/research-content.tsx apps/frontend/src/features/accounts/components/research-pending-poll.test.ts
git commit -m "feat(frontend): account pages re-read every 5 s while a section is pending"
```

---

### Task 7: Shared blocks — the insights page reuses the overview's and the contacts' answers

**Files:**
- Modify: `platform/api/clue_api/arv2/display/recipes.py` (`SectionRecipe.shared_from`; two recipes; `_UPSERT`, `_SELECT`, `load_display_recipes`, `read_recipes`)
- Create: `alembic/versions/<id>_display_recipe_shared_from.py`
- Modify: `platform/api/clue_api/arv2/display/blocks.py` (`shared_blocks`, `compose_display_block(..., shared=)`, `cited_claim_ids`, `stale_sections` skips shared recipes)
- Modify: `platform/api/clue_api/arv2/display/page.py` (`ensure_page` never writes a shared recipe; composes with shared blocks)
- Modify: `platform/api/clue_api/frontend_read/display_pages.py` (composes with shared blocks; a stale owner is re-offered)
- Test: `tests/arv2/display/test_recipes.py`, `tests/arv2/display/test_blocks_db.py`, `tests/arv2/display/test_page_db.py`, `tests/api/test_frontend_read_display_pages_db.py`, `tests/db/test_display_recipe_shared_from_migration.py`

**Interfaces:**
- Produces:
  - `SectionRecipe.shared_from: tuple[Page, str] | None = None`.
  - `shared_blocks(conn, *, workspace_id, page, recipes, subject_id, member_ids) -> dict[str, list[LiveBlock]]`
    — for every recipe with `shared_from`, the owner's live blocks: the same subject when the owner
    page is about the same subject kind, else one per committee member in committee order.
  - `compose_display_block(page, recipes, blocks, shared: Mapping[str, Sequence[LiveBlock]] = {})`.
  - `cited_claim_ids(recipes, blocks, shared) -> tuple[str, ...]` (recipe order, deduped;
    replaces the two private `_cited` helpers in `page.py` and `display_pages.py`).

- [ ] **Step 1: Write the failing recipe tests**

Append to `tests/arv2/display/test_recipes.py`:

```python
def test_the_sharing_set_leaves_the_insights_page_four_generated_recipes() -> None:
    insights = recipes_for("insights")
    shared = {r.section_key: r.shared_from for r in insights if r.shared_from is not None}
    assert shared == {
        "context-only": ("overview", "watch-outs"),
        "contact-insights": ("contact", "why-this-person"),
    }
    assert [r.section_key for r in insights if r.shared_from is None] == [
        "buying-signals",
        "money-and-momentum",
        "tools-they-already-use",
        "how-they-sell",
    ]
    # The owner and the sharer ask the same question: identical keys for the same-subject pair.
    by_key = {(r.page, r.section_key): r for r in SYSTEM_RECIPES}
    assert by_key[("insights", "context-only")].allowed_field_keys == by_key[("overview", "watch-outs")].allowed_field_keys
    # A sharer never owns a block, so it is never restricted differently from its owner.
    assert by_key[("insights", "context-only")].restricted is by_key[("overview", "watch-outs")].restricted


@pytest.mark.usefixtures("require_claimstore_db")
def test_shared_from_round_trips_through_the_recipe_table() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await load_display_recipes(conn)
            rows = await read_recipes(conn, "insights", workspace_id="ws_any")
            assert {r.section_key: r.shared_from for r in rows if r.shared_from} == {
                "context-only": ("overview", "watch-outs"),
                "contact-insights": ("contact", "why-this-person"),
            }

    run_async(_run())
```

- [ ] **Step 2: Run to see them fail**

Run: `CLUE_DATABASE_URL=<throwaway-dsn> uv run pytest tests/arv2/display/test_recipes.py -q`
Expected: FAIL — `SectionRecipe` has no `shared_from`.

- [ ] **Step 3: The recipe field, the two recipes, the SQL**

In `recipes.py`:

```python
@dataclass(frozen=True)
class SectionRecipe:
    ...
    workspace_id: str = ""
    #: Spec 2026-09-12 §3: ``(page, section_key)`` of the recipe whose stored block this section
    #: renders under its own ``h1``/``position``/``default_open``. A recipe with ``shared_from``
    #: owns no block, is never gathered, never written and never scanned for staleness of its own;
    #: it is stale when its owner is. ``allowed_field_keys`` are documentary (the owner's).
    shared_from: tuple[Page, str] | None = None
```

Change the two recipes:

```python
    SectionRecipe(
        "insights",
        "contact-insights",
        "Contact insights",
        4,
        (...the same seven keys...),
        shared_from=("contact", "why-this-person"),
    ),
    SectionRecipe(
        "insights", "context-only", "Context only", 5, _UNSAFE_CONTEXT, restricted=True,
        shared_from=("overview", "watch-outs"),
    ),
```

`_UPSERT`: add `shared_from_page, shared_from_section_key` to the column list, `:shared_from_page,
:shared_from_section_key` to VALUES, and both to the `DO UPDATE SET`. `_SELECT`: add both columns.
`load_display_recipes`: pass `"shared_from_page": recipe.shared_from[0] if recipe.shared_from else None`
and the key likewise. `read_recipes`: build
`shared_from=(cast(Page, row["shared_from_page"]), row["shared_from_section_key"]) if row["shared_from_page"] else None`.

- [ ] **Step 4: The migration**

Run `uv run alembic revision -m "display recipe shared_from"` (down_revision = current head, which
is Task 1's revision) and write:

```python
"""display recipe shared_from

Spec 2026-09-12 §3. Two nullable columns name the owner of a shared section. The two sections that
become shared (insights context-only ← overview watch-outs; insights contact-insights ← the contact
page's why-this-person) stop owning blocks, so their own live blocks are retired here — the
composed page reads the owner's block from now on, and a retired block is audit, never served.
"""

from __future__ import annotations

from alembic import op

revision = "<generated>"
down_revision = "<Task 1 revision>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE display_section_recipe ADD COLUMN shared_from_page text")
    op.execute("ALTER TABLE display_section_recipe ADD COLUMN shared_from_section_key text")
    op.execute(
        """
        ALTER TABLE display_section_recipe ADD CONSTRAINT display_section_recipe_shared_from_pair
        CHECK ((shared_from_page IS NULL) = (shared_from_section_key IS NULL))
        """
    )
    op.execute(
        """
        UPDATE display_block SET superseded_at = now()
        WHERE page = 'insights' AND section_key IN ('context-only', 'contact-insights')
          AND superseded_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE display_section_recipe DROP CONSTRAINT display_section_recipe_shared_from_pair")
    op.execute("ALTER TABLE display_section_recipe DROP COLUMN shared_from_section_key")
    op.execute("ALTER TABLE display_section_recipe DROP COLUMN shared_from_page")
    # The retired blocks stay retired: the next read of an insights page writes the two sections
    # afresh under the pre-share recipes.
```

`tests/db/test_display_recipe_shared_from_migration.py`: one DB test asserting the two columns
exist and the CHECK constraint name is present (`pg_constraint` query as in
`test_arv2_onboarding_kind_migration.py`). Migrate the throwaway DB and run it plus `make db-smoke`.

- [ ] **Step 5: Write the failing compose + page tests**

Append to `tests/arv2/display/test_blocks_db.py` (pure part can live there too):

```python
def test_a_shared_section_composes_the_owner_body_under_its_own_chrome() -> None:
    owner = LiveBlock(display_block_id=uuid.uuid4(), section_key="watch-outs", body={"items": [{"id": "i1", "h2": "x", "body": []}], "intro": []}, cited_claim_ids=("c1",), model="m", prompt_version="display-v1+v1", recipe_version=1, generated_at=datetime.now(UTC))
    recipes = recipes_for("insights")
    composed = compose_display_block("insights", recipes, {}, shared={"context-only": [owner]})
    section = next(s for s in composed["sections"] if s["key"] == "context-only")
    assert section["h1"] == "Context only" and section["restricted"] is True
    assert section["items"] == owner.body["items"] and section["empty"] is False
    assert cited_claim_ids(recipes, {}, {"context-only": [owner]}) == ("c1",)


def test_a_shared_section_whose_owner_is_unwritten_is_empty_and_never_pending_here() -> None:
    composed = compose_display_block("insights", recipes_for("insights"), {}, shared={})
    section = next(s for s in composed["sections"] if s["key"] == "contact-insights")
    assert section["empty"] is True and section["items"] == []
```

(Construct `LiveBlock` with the real field names from `blocks.py:65-77`.)

Append to `tests/arv2/display/test_page_db.py`:

```python
def test_the_insights_page_writes_four_sections_and_shares_the_other_two() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            transport = RoutingTransport()
            # Owners first: Nick's contact page and the account overview.
            await _contact_page(conn, seeded, transport)
            await _overview_page(conn, seeded, transport)   # add this helper beside _contact_page
            written_before = len(transport.sections)

            result = await _insights_page(conn, seeded, transport)  # add beside the others

            assert sorted(result.generated) == sorted(
                ["buying-signals", "money-and-momentum", "tools-they-already-use", "how-they-sell"]
            )
            assert "context-only" not in transport.sections[written_before:]
            assert "contact-insights" not in transport.sections[written_before:]
            block = result.display_block
            context = next(s for s in block["sections"] if s["key"] == "context-only")
            watch = _cited_in(await _stored_overview(conn, seeded), "watch-outs")
            assert _cited_in(block, "context-only") == watch and not context["empty"]
            insights = next(s for s in block["sections"] if s["key"] == "contact-insights")
            assert not insights["empty"]
            assert _cited_in(block, "contact-insights") <= set(result.cited_claim_ids)

    run_async(_run())
```

The helpers `_overview_page`, `_insights_page` mirror `_contact_page` with the account subject and
the respective page; `_stored_overview` composes the stored overview via `live_blocks` +
`compose_display_block`. If the seeded account's watch-outs recipe matches no claims in the
fixture (check `seed_display_fixture` for `account.reputation_risk` / `account.resonance.attrition_signal`),
write one such claim in the test with `write_claim` before writing the overview so the owner block
exists.

- [ ] **Step 6: Run to see them fail**

Run: `CLUE_DATABASE_URL=<throwaway-dsn> uv run pytest tests/arv2/display/test_blocks_db.py tests/arv2/display/test_page_db.py -q -k "shared or insights"`
Expected: FAIL — `compose_display_block` takes no `shared`.

- [ ] **Step 7: Implement in `blocks.py`**

```python
async def shared_blocks(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    page: str,
    recipes: Sequence[SectionRecipe],
    subject_id: str,
    member_ids: Sequence[str],
) -> dict[str, list[LiveBlock]]:
    """For every recipe of ``page`` with ``shared_from``, the owner's live blocks, in the order
    the sharer renders them: the same subject when the owner page is about the sharer's subject
    kind, else one per committee member (committee order). A member with no owner block
    contributes nothing."""
    out: dict[str, list[LiveBlock]] = {}
    for recipe in recipes:
        if recipe.shared_from is None:
            continue
        owner_page, owner_key = recipe.shared_from
        owner_kind = PAGE_SUBJECT_KIND[owner_page]
        subjects = [subject_id] if owner_kind == PAGE_SUBJECT_KIND[page] else list(member_ids)
        found: list[LiveBlock] = []
        for owner_subject in subjects:
            blocks = await live_blocks(
                conn, workspace_id=workspace_id, subject_kind=owner_kind, subject_id=owner_subject, page=owner_page
            )
            block = blocks.get(owner_key)
            if block is not None:
                found.append(block)
        out[recipe.section_key] = found
    return out
```

(`PAGE_SUBJECT_KIND` lives in `page.py` today; move it into `recipes.py` — pure data — and import
it from there in both `page.py` and `blocks.py`, so `blocks` does not import `page`.)

`compose_display_block(page, recipes, blocks, shared=...)`: for a recipe with `shared_from`,
`items = [item for block in shared.get(key, []) for item in _stored_list(block, "items")]`,
`intro = _stored_list(shared[key][0], "intro")` when exactly one owner block and the recipe is
narrative, else `[]`; `empty` when no items and no intro. Everything else unchanged.

`cited_claim_ids(recipes, blocks, shared)`: recipe order; a shared recipe contributes every owner
block's `cited_claim_ids`; dedupe with `dict.fromkeys`.

`stale_sections`: skip recipes with `shared_from` (they have no block of their own).

- [ ] **Step 8: Implement in `page.py` and the seam**

`ensure_page`: `recipes_owned = [r for r in recipes if r.shared_from is None]`; use
`recipes_owned` for `missing`, the stale scan and the gather; after writing, compute
`shared = await shared_blocks(conn, workspace_id=…, page=page, recipes=recipes, subject_id=subject.id, member_ids=[m.id for m in members])`
and compose with `shared=shared`; `cited = cited_claim_ids(recipes, blocks, shared)`; delete the
private `_cited` duplicate.

`display_pages.py::page`: same composition (`shared_blocks` → `compose_display_block(..., shared=)`
→ `cited_claim_ids`), delete its private `_cited`. In `_offer_missing_and_stale`, exclude shared
recipes from `missing`, and add: for each shared recipe whose owner is the same subject, run
`stale_sections` over the owner page's recipe/blocks for that subject and, if stale, `_offer_page`
the OWNER page (`owner_page`, same subject); for member-owned sharers, do the same per member
(`("contact", member_id, "contact")`). The sharer is never pending: its owner's page carries the
pending state on its own screen.

- [ ] **Step 9: Run the display suites end to end**

Run: `CLUE_DATABASE_URL=<throwaway-dsn> uv run pytest tests/arv2/display tests/api/test_frontend_read_display_pages_db.py tests/api/test_frontend_read_account_workspace.py tests/api/test_frontend_read_v1_live_zafran_db.py -q` then ruff, mypy, `lint-imports`.
Expected: green. If `test_frontend_read_v1_live_zafran_db.py` pins the insights section count or
the generated set, update its expectation to the four generated + two shared sections and say why
in the assertion message.

- [ ] **Step 10: Commit**

```bash
git add platform/api/clue_api/arv2/display/recipes.py platform/api/clue_api/arv2/display/blocks.py platform/api/clue_api/arv2/display/page.py platform/api/clue_api/frontend_read/display_pages.py alembic/versions/*display_recipe_shared_from.py tests/arv2/display tests/api/test_frontend_read_display_pages_db.py tests/db/test_display_recipe_shared_from_migration.py
git commit -m "feat(display): shared blocks — insights context-only and contact-insights render their owners' stored bodies"
```

---

### Task 8: Records, docs, and the live proofs list

**Files:**
- Modify: `docs/specs/ARV2-MASTER-PLAN.md` §7 "Generation policy" paragraph
- Modify: `apps/frontend/docs/api-contracts/accounts.md` (already touched in Task 4; add the shared-section note)
- Modify: `docs/superpowers/specs/archive/2026-09-12-display-prewrite-and-shared-blocks-design.md` status line
- Create: `_memory/2026-09-21-display-prewrite-execution.md`; add one line to `_memory/README.md`
- Modify: `CLAUDE.md` backlog — replace the display-generation sentence in the `[chat×…]`-style
  bullets with a new `[display×prewrite]` bullet (what shipped, residuals, owed proofs)

- [ ] **Step 1: Master plan §7**

Replace the "Generation policy" bullet with: a section is written by the fleet — the account
overview at settle (offered by the account job), the contact pages of an account on its first open,
every other page on first open; a read never writes, it serves stored blocks, marks the sections a
task will write `pending` with the sentence `Synthesis in progress, please wait a few seconds.`,
and offers the page's task; stale sections are served as stored and re-offered; the insights page
composes `context-only` and `contact-insights` from the overview's and the contacts' blocks. Keep
the invalidation sentence as is.

- [ ] **Step 2: Contract doc**

Under the Section shape note, add: "**Shared sections (2026-09-21).** `context-only` on the
insights page is the overview's `watch-outs` block; `contact-insights` is the committee's
`why-this-person` blocks in committee order. Same items, same claim ids, the insights page's own
`h1`/`defaultOpen`. They are never `pending` on the insights page — their owner page carries that."

- [ ] **Step 3: Memory record**

`_memory/2026-09-21-display-prewrite-execution.md`: commits per task, rulings taken during
execution, gates run (with counts), and the owed live proofs below. Add the README line.

- [ ] **Step 4: CLAUDE.md backlog bullet**

`**[display×prewrite] Display pages written on the fleet since 2026-09-21** (spec …, plan …): the
`arv2_display_page` kind, the settle-time overview offer, contact pages offered on the first open
of their account, the read as scheduler (`pending` + the placeholder sentence + a 5 s
`router.refresh()` poll), shared blocks. **Residuals:** the contact-offer cooldown and the
regeneration table are per web process (a second twin may offer once more — a DB no-op by dedup);
a pending section on a page whose provider is refusing shows the outage sentence and keeps
polling; the inline write survives only as the queue-less fallback and the CLI. **Owed
(founder-triggered, spends money):** the live proofs below.`

- [ ] **Step 5: Owed live proofs (list them in the memory note; do not run them)**

1. Launch account research on one account; when the account job settles, `fleet_task` holds one
   `arv2_display_page` row for its overview; opening the account shows written sections with no
   wait and `provider_call_ledger` rows for the page carry the account job's `job_id`.
2. Open a researched account whose contact pages do not exist: the contacts tab and the overview
   each offer the members' pages once; opening a contact within seconds shows every section as
   `Synthesis in progress, please wait a few seconds.`; the page fills in on its own within two
   polls; no request took longer than the read itself.
3. Open a contact with no claims: no placeholder, the ordinary "No … information found" text, no
   task offered.
4. Add a claim under a written section's recipe; open the page: served as stored, one
   `arv2_display_page` task queued, and the section is replaced on a later open.
5. The insights page shows `Context only` equal to the overview's `Watch-outs` items and
   `Contact insights` equal to the committee's `Why this person` items, with no `display-insights-
   context-only` / `display-insights-contact-insights` labels on the ledger after the migration.

- [ ] **Step 6: Commit**

```bash
git add docs/specs/ARV2-MASTER-PLAN.md apps/frontend/docs/api-contracts/accounts.md docs/superpowers/specs/archive/2026-09-12-display-prewrite-and-shared-blocks-design.md _memory/2026-09-21-display-prewrite-execution.md _memory/README.md CLAUDE.md
git commit -m "docs: display pages written on the fleet — master plan §7, contract notes, execution record, backlog"
```

---

## Self-review

- **Spec coverage.** §2 written at settle → Tasks 1, 2, 3 (kind, handler, settle offer) and the
  on-open contact offers → Task 5 (`offer_contact_pages`, contacts tab). Spend stamped with the
  research job → Task 2 (`job_id`). §3 shared blocks → Task 7 (recipe field, migration, compose,
  staleness through the owner, `cited_claim_ids` sees shared cites). §4 progressive read + the
  2026-09-21 placeholder ruling → Tasks 4, 5, 6 (`pending`, the sentence, the poll). §5 tests →
  each task carries the named case (handler writes once / redelivery writes nothing; offer after
  commit and never raises; first open offers once per settled member and skips a written member;
  shared section composes/absent/stale-with-owner; four generated recipes). §6 out of scope →
  no insights prose rewrite, no settle-time insights write, research untouched.
- **Placeholders.** None: every step carries its code or its exact command; the two places an
  implementer must confirm a name (`provider_call_ledger.job_id`, `SubjectRef.id` casting,
  `finish_job` keywords, `write_claim` signature, `_seed_run`) say which grep settles it.
- **Type consistency.** `arv2_display_work_id(subject_kind, subject_id, page)` (Task 1) is what
  Tasks 3 and 5 call; `display_page_payload(...)` (Task 2) is what Tasks 3 and 5 build payloads
  with; `people_of` (Task 2) is what Task 5 imports; `PENDING_MESSAGE` (Task 5) is what Task 4's
  frontend test quotes verbatim and Task 6 refuses to hardcode; `shared_blocks` /
  `compose_display_block(..., shared=)` / `cited_claim_ids` (Task 7) replace the two `_cited`
  helpers in `page.py` and `display_pages.py`.
