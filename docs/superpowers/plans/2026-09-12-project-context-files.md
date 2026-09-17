# Project Context Files Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every production project-conversation turn materializes a per-project folder under `inputs/project/` — a deterministic `status.md` compiled from ARV2 rows and a `decisions.md` rendered from the project's recorded `project_state` statements — pinned once per turn so retries see the same bytes, and indexed for the model by a bounded L3 card.

**Architecture:** A new composition-root module compiles the two files from durable rows (no model call), persists their bytes as artifacts, and records them insert-once in a new `agent_turn_project_files` table keyed on the turn (the same discipline as `agent_turn_knowledge_pin`). `ProjectConversationTurnRunner.run` seeds them read-only next to the brand files and adds a second L3 artifact, `project_files_index`. No profile, skill or recipe changes in this plan (plan 2's skill v23 carries the reading instruction).

**Tech Stack:** Python 3.12, SQLAlchemy async + Alembic (hash revision ids), pydantic v2, pytest against the lane DB `clue_san-salvador` (`--ignore-glob='*_live.py' -p no:cacheprovider`).

**Spec:** `docs/superpowers/specs/2026-09-12-project-context-and-icp-authoring-design.md` §4.1 (rulings R1, R2, R8).

## Global Constraints

- Postgres is the only source of truth; the compiled files are projections of rows, never a store of their own. Timestamps in `status.md` are the rows' own; the compiler never writes "now".
- Seeds under `inputs/` are frozen and re-verified byte-for-byte on a reclaimed turn (`AgentResourceMaterializer.verify_materialized`). Compiled bytes are therefore persisted and pinned per turn; a retry reads the pin, never recompiles.
- `platform/api/clue_api/arv2/` may not import `clue_research.stage0` or any `clue_api.*` module outside itself (Global Constraint 7 of the ARV2 plans, enforced by `tests/arv2/test_import_guard.py`). The modules this plan adds live at the `clue_api` root.
- ARV2 schema is the only truth: status reads `project_icp_pin`, `project_product`, `arv2_discovery_run`, `arv2_discovery_candidate`, `arv2_research_run`, `arv2_research_job`, `project_account`. Never the old lane's tables.
- Alembic: hash revision id via `alembic revision -m "<slug>"`, `down_revision = "c90aaea30a88"`, reversible `downgrade()`, exactly one head.
- Never run `make check` or a broad pytest with real keys sourced. Offline suites run without `.env`; DB suites run on the lane DB only, with `--ignore-glob='*_live.py' -p no:cacheprovider`. Never run `*_live.py`.
- No `git push`, no PRs, no AI attribution in commits.
- The brand-knowledge index card (`BrandKnowledgeIndexCard@1`) is not modified; its digest tests must stay green.

---

## File structure

| File | Responsibility |
|---|---|
| `alembic/versions/<hash>_arv2_project_files_pin.py` | Create `agent_turn_project_files` (insert-once per turn, append-only). |
| `platform/api/clue_api/project_status.py` | Load `ProjectStatusFacts` from ARV2 rows; render `status.md`. Load current-effective `project_state` statements with resolved quotes; render `decisions.md`. Pure renderers, DB loaders separate. |
| `platform/api/clue_api/project_context_files.py` | `PROJECT_INPUT_PREFIX`, `CompiledProjectFile`, the per-turn pin (`load_or_create_project_files_pin`, `read_pinned_project_files`), `project_seed_files`, `ProjectFilesIndexCard@1` + `compile_project_files_index_card`. |
| `platform/api/clue_api/agent_turn_fleet_wiring.py` | Call the compilers and the pin after the knowledge pin; seed the files; compose the `project_files_index` L3 artifact. |
| `tests/db/test_arv2_project_files_pin_migration.py` | Migration up/down/up, CHECKs, append-only. |
| `tests/api/test_project_status.py` | Pure renderer tests. |
| `tests/api/test_project_context_files_db.py` | Loaders, pin insert-once, digest verification, seeds, index card. |
| `tests/api/test_o6_conversation_composition_db.py` | Extended: the production turn seeds `inputs/project/status.md` + `decisions.md` and composes `project_files_index`. |

---

### Task 1: Migration — `agent_turn_project_files`

**Files:**
- Create: `alembic/versions/<hash>_arv2_project_files_pin.py` (run `uv run alembic revision -m "arv2 project files pin"` to mint the id; set `down_revision = "c90aaea30a88"`)
- Test: `tests/db/test_arv2_project_files_pin_migration.py`

**Interfaces:**
- Produces: table `agent_turn_project_files (turn_id uuid PK, workspace_id text, project_id text, files jsonb, files_sha256 text, pinned_at timestamptz)`; FK `(turn_id, workspace_id) → agent_turn_submission (turn_id, workspace_id)`; FK `(project_id, workspace_id) → project (project_id, workspace_id)`; CHECK `jsonb_typeof(files) = 'array'`; CHECK `files_sha256 ~ '^[0-9a-f]{64}$'`; trigger `agent_turn_project_files_append_only BEFORE UPDATE OR DELETE … execution_reject_append_only_mutation()`; index `(workspace_id, project_id, pinned_at DESC)`.

- [ ] **Step 1: Write the failing migration test**

Copy `tests/db/test_arv2_onboarding_knowledge_pin_migration.py` to `tests/db/test_arv2_project_files_pin_migration.py` and adapt: `_PREVIOUS_REVISION = "c90aaea30a88"`, `_TABLE = "agent_turn_project_files"`. Keep the three tests in the same shape: (a) upgrade → the table, both FKs, the two CHECK constraints, the trigger and the index exist (query `pg_constraint`/`pg_trigger`/`pg_indexes` by name); (b) an insert with `files_sha256 = 'sha256:…'` (prefixed) raises `DBAPIError`; an `UPDATE` on an inserted row raises `DBAPIError` (append-only); (c) downgrade lands on `_PREVIOUS_REVISION` and the table is gone, then upgrade again succeeds.

The `project` FK columns: the anchor is `project (project_id, workspace_id)` (`project_workspace_anchor`); `project_icp_pin` uses `FOREIGN KEY (project_id, workspace_id) REFERENCES project (project_id, workspace_id)` — copy that form.

- [ ] **Step 2: Run the test to verify it fails**

Run: `set -a; source .env; set +a; uv run pytest tests/db/test_arv2_project_files_pin_migration.py -p no:cacheprovider -q`
Expected: FAIL (no such revision / table).

- [ ] **Step 3: Write the migration**

```python
"""arv2 project files pin

Revision ID: <hash>
Revises: c90aaea30a88
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "<hash>"
down_revision: str | None = "c90aaea30a88"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE agent_turn_project_files (
            turn_id       uuid PRIMARY KEY,
            workspace_id  text NOT NULL,
            project_id    text NOT NULL,
            files         jsonb NOT NULL,
            files_sha256  text NOT NULL,
            pinned_at     timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_turn_project_files_submission_fk
                FOREIGN KEY (turn_id, workspace_id)
                REFERENCES agent_turn_submission (turn_id, workspace_id),
            CONSTRAINT agent_turn_project_files_project_fk
                FOREIGN KEY (project_id, workspace_id)
                REFERENCES project (project_id, workspace_id),
            CONSTRAINT agent_turn_project_files_identity_nonempty CHECK (
                length(btrim(workspace_id)) > 0 AND length(btrim(project_id)) > 0
            ),
            CONSTRAINT agent_turn_project_files_array CHECK (jsonb_typeof(files) = 'array'),
            CONSTRAINT agent_turn_project_files_sha256 CHECK (files_sha256 ~ '^[0-9a-f]{64}$')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE agent_turn_project_files IS 'The immutable set of compiled project "
        "files (inputs/project/**) one AGENT_TURN opens with, written before composition. Every "
        "retry of the turn seeds exactly these bytes; rows that change meanwhile affect only a "
        "later turn.'"
    )
    op.execute(
        "CREATE INDEX agent_turn_project_files_project "
        "ON agent_turn_project_files (workspace_id, project_id, pinned_at DESC)"
    )
    op.execute(
        "CREATE TRIGGER agent_turn_project_files_append_only "
        "BEFORE UPDATE OR DELETE ON agent_turn_project_files "
        "FOR EACH ROW EXECUTE FUNCTION execution_reject_append_only_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS agent_turn_project_files_append_only ON agent_turn_project_files")
    op.execute("DROP TABLE agent_turn_project_files")
```

- [ ] **Step 4: Run the test to verify it passes; confirm one head**

Run: `set -a; source .env; set +a; uv run pytest tests/db/test_arv2_project_files_pin_migration.py -p no:cacheprovider -q && uv run alembic heads`
Expected: PASS; exactly one head (the new id).

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/<hash>_arv2_project_files_pin.py tests/db/test_arv2_project_files_pin_migration.py
git commit -m "feat(arv2): agent_turn_project_files — the insert-once pin of a turn's compiled project files"
```

---

### Task 2: `project_status.py` — facts, loaders, and the two renderers

**Files:**
- Create: `platform/api/clue_api/project_status.py`
- Test: `tests/api/test_project_status.py` (pure), `tests/api/test_project_context_files_db.py` (loaders; created here, extended in Task 3)

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True, slots=True)
  class ProjectStatusFacts:
      project_id: str
      icp: ProjectIcpPin | None                  # clue_api.arv2.icp_confirmation
      product_set: ProjectProductSet | None      # clue_spine
      account_count: int
      discovery: DiscoveryFacts | None
      research: tuple[ResearchRunFacts, ...]
      documents: tuple[ProjectDocumentFacts, ...]   # empty in this plan; plan 2 fills it

  @dataclass(frozen=True, slots=True)
  class DiscoveryFacts:
      run_id: UUID; status: str; asked: int | None; found: int; verified: int; shown: int
      approved: int; started_at: datetime | None; finished_at: datetime | None

  @dataclass(frozen=True, slots=True)
  class ResearchJobFacts:
      account_name: str; status: str; stage: str | None; person_jobs: int

  @dataclass(frozen=True, slots=True)
  class ResearchRunFacts:
      run_id: UUID; status: str; effort: str; created_at: datetime
      finished_at: datetime | None; jobs: tuple[ResearchJobFacts, ...]

  @dataclass(frozen=True, slots=True)
  class ProjectDocumentFacts:
      path: str; version: int; status: str; updated_at: datetime

  @dataclass(frozen=True, slots=True)
  class DecisionItem:
      route_key: str; quote: str

  async def load_project_status_facts(conn, *, workspace_id: str, project_id: str) -> ProjectStatusFacts
  async def load_project_decisions(conn, artifacts: AgentArtifactReader, *, workspace_id: str, project_id: str) -> tuple[DecisionItem, ...]
  def render_status_markdown(facts: ProjectStatusFacts) -> str
  def render_decisions_markdown(items: Sequence[DecisionItem]) -> str
  ```

- [ ] **Step 1: Write the failing pure renderer tests**

`tests/api/test_project_status.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from clue_api.arv2.icp_confirmation import ProjectIcpPin
from clue_api.project_status import (
    DecisionItem,
    DiscoveryFacts,
    ProjectStatusFacts,
    ResearchJobFacts,
    ResearchRunFacts,
    render_decisions_markdown,
    render_status_markdown,
)
from clue_spine import ProjectProductSet

_T = datetime(2026, 9, 12, 8, 30, tzinfo=UTC)


def _facts(**overrides: object) -> ProjectStatusFacts:
    base = ProjectStatusFacts(
        project_id="prj_1", icp=None, product_set=None, account_count=0,
        discovery=None, research=(), documents=(),
    )
    return ProjectStatusFacts(**{**base.__dict__, **overrides})  # type: ignore[arg-type]


def test_an_empty_project_renders_every_section_with_its_honest_absence() -> None:
    text = render_status_markdown(_facts())
    assert text.startswith("# Project status\n")
    for heading in ("## Confirmed ICP", "## Products", "## Plan", "## Accounts",
                    "## Discovery", "## Research", "## Project documents"):
        assert heading in text
    assert "Not confirmed." in text
    assert "No discovery run yet." in text
    assert "No research run yet." in text
    assert "Not written." in text
    assert "now" not in text.lower()


def test_pinned_icp_products_discovery_and_research_render_from_the_rows() -> None:
    facts = _facts(
        icp=ProjectIcpPin(
            document_id=UUID(int=1), icp_key="gi-groups", artifact_key="ws/aa",
            artifact_sha256="a" * 64, product_selection_version=2, version=3,
            path="audience/icp-gi-groups.md",
        ),
        product_set=ProjectProductSet(
            workspace_id="ws", project_id="prj_1", brand_id="brand", selection_version=2,
            product_ids=("prd_a", "prd_b"), gate_id=UUID(int=9),
            confirmed_by_user_id="usr", confirmed_at=_T,
        ),
        account_count=7,
        discovery=DiscoveryFacts(
            run_id=UUID(int=2), status="completed", asked=20, found=18, verified=18,
            shown=12, approved=7, started_at=_T, finished_at=_T,
        ),
        research=(ResearchRunFacts(
            run_id=UUID(int=3), status="in_progress", effort="full", created_at=_T,
            finished_at=None,
            jobs=(ResearchJobFacts("Goodman Campbell", "completed", "member_research", 4),
                  ResearchJobFacts("Acme Health", "in_progress", "synthesis", 0)),
        ),),
    )
    text = render_status_markdown(facts)
    assert "- Key: `gi-groups` (version 3) — `inputs/brand/knowledge/audience/icp-gi-groups.md`" in text
    assert "- Selection version 2: `prd_a`, `prd_b`" in text
    assert "- Accounts in this project: 7" in text
    assert "- Latest run `00000000-0000-0000-0000-000000000002`: completed" in text
    assert "asked 20, found 18, verified 18, shown 12, approved 7" in text
    assert "- Run `00000000-0000-0000-0000-000000000003`: in_progress, effort full, 1/2 finished" in text
    assert "  - Goodman Campbell: completed (member_research), 4 person jobs" in text
    assert "  - Acme Health: in_progress (synthesis), 0 person jobs" in text
    assert "2026-09-12T08:30:00+00:00" in text


def test_decisions_render_one_bullet_per_statement_oldest_first_or_an_honest_empty() -> None:
    assert render_decisions_markdown(()) == (
        "# Project decisions\n\nNothing recorded yet. Record preferences, boundaries and choices "
        "through `record_interview_answer` (route `project_state`).\n"
    )
    text = render_decisions_markdown((
        DecisionItem("project.outcome", "we want new logos in mid-market GI groups"),
        DecisionItem("project.icp_boundary", "exclude academic medical centres"),
    ))
    assert text == (
        "# Project decisions\n\n"
        "- **project.outcome** — \"we want new logos in mid-market GI groups\"\n"
        "- **project.icp_boundary** — \"exclude academic medical centres\"\n"
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/api/test_project_status.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: clue_api.project_status`.

- [ ] **Step 3: Write the module**

`platform/api/clue_api/project_status.py`:

```python
"""The project's ``status.md`` and ``decisions.md`` — compiled from rows, never from a model.

Spec: docs/superpowers/specs/2026-09-12-project-context-and-icp-authoring-design.md §4.1.
The renderers are pure so the wording is tested without a database; the loaders read only ARV2
rows and the ``project_state`` statements (ruling R8). Nothing here writes "now": every timestamp
is a row's own, so two attempts of one turn compile identical bytes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import AgentArtifactReader
from clue_api.arv2.icp_confirmation import ProjectIcpPin, current_project_icp_pin
from clue_api.brand_knowledge_context import INPUT_PREFIX
from clue_api.statement_evidence import resolve_statement_quotes
from clue_projections.stage0 import ResolvedQuote
from clue_research.stage0 import StatementRoute, read_statements
from clue_spine import ProjectProductSet, current_project_product_set

__all__ = [
    "DecisionItem",
    "DiscoveryFacts",
    "ProjectDocumentFacts",
    "ProjectStatusFacts",
    "ResearchJobFacts",
    "ResearchRunFacts",
    "load_project_decisions",
    "load_project_status_facts",
    "render_decisions_markdown",
    "render_status_markdown",
]

#: Research runs listed in status.md, newest first. Older runs are history, not status.
_RESEARCH_RUNS_SHOWN = 5


@dataclass(frozen=True, slots=True)
class DiscoveryFacts:
    run_id: UUID
    status: str
    asked: int | None
    found: int
    verified: int
    shown: int
    approved: int
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class ResearchJobFacts:
    account_name: str
    status: str
    stage: str | None
    person_jobs: int


@dataclass(frozen=True, slots=True)
class ResearchRunFacts:
    run_id: UUID
    status: str
    effort: str
    created_at: datetime
    finished_at: datetime | None
    jobs: tuple[ResearchJobFacts, ...]


@dataclass(frozen=True, slots=True)
class ProjectDocumentFacts:
    path: str
    version: int
    status: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ProjectStatusFacts:
    project_id: str
    icp: ProjectIcpPin | None
    product_set: ProjectProductSet | None
    account_count: int
    discovery: DiscoveryFacts | None
    research: tuple[ResearchRunFacts, ...]
    documents: tuple[ProjectDocumentFacts, ...]


@dataclass(frozen=True, slots=True)
class DecisionItem:
    route_key: str
    quote: str


_ACCOUNT_COUNT = text(
    "SELECT count(*) FROM project_account WHERE workspace_id = :ws AND project_id = :project"
)

_LATEST_DISCOVERY = text(
    """
    SELECT r.run_id, r.status, r.asked, COALESCE(r.found_strict, 0) + COALESCE(r.found_relaxed, 0)
           AS found, r.started_at, r.finished_at,
           (SELECT count(*) FROM arv2_discovery_candidate c
             WHERE c.run_id = r.run_id AND c.disposition <> 'pending') AS verified,
           (SELECT count(*) FROM arv2_discovery_candidate c
             WHERE c.run_id = r.run_id AND c.disposition IN ('pass', 'partial', 'unclear')) AS shown,
           (SELECT count(*) FROM arv2_discovery_candidate c
             WHERE c.run_id = r.run_id AND c.decision = 'approved') AS approved
    FROM arv2_discovery_run r
    WHERE r.workspace_id = :ws AND r.project_id = :project
    ORDER BY r.created_at DESC, r.run_id DESC
    LIMIT 1
    """
)

_RESEARCH_RUNS = text(
    """
    SELECT run_id, status, effort, created_at, finished_at
    FROM arv2_research_run
    WHERE workspace_id = :ws AND project_id = :project
    ORDER BY created_at DESC, run_id DESC
    LIMIT :limit
    """
)

_RESEARCH_JOBS = text(
    """
    SELECT j.run_id, j.subject_type, j.account_entity_id, a.canonical_name, j.status, j.stage
    FROM arv2_research_job j
    JOIN account_entity a ON a.id = j.account_entity_id
    WHERE j.run_id = ANY(:run_ids)
    ORDER BY j.run_id, j.subject_type, a.canonical_name, j.job_id
    """
)


async def load_project_status_facts(
    conn: AsyncConnection, *, workspace_id: str, project_id: str
) -> ProjectStatusFacts:
    icp = await current_project_icp_pin(conn, workspace_id=workspace_id, project_id=project_id)
    product_set = await current_project_product_set(
        conn, workspace_id=workspace_id, project_id=project_id
    )
    params = {"ws": workspace_id, "project": project_id}
    account_count = int(await conn.scalar(_ACCOUNT_COUNT, params) or 0)
    row = (await conn.execute(_LATEST_DISCOVERY, params)).mappings().first()
    discovery = (
        None
        if row is None
        else DiscoveryFacts(
            run_id=row["run_id"], status=str(row["status"]),
            asked=None if row["asked"] is None else int(row["asked"]),
            found=int(row["found"]), verified=int(row["verified"]), shown=int(row["shown"]),
            approved=int(row["approved"]), started_at=row["started_at"],
            finished_at=row["finished_at"],
        )
    )
    runs = (
        await conn.execute(_RESEARCH_RUNS, {**params, "limit": _RESEARCH_RUNS_SHOWN})
    ).mappings().all()
    research: list[ResearchRunFacts] = []
    if runs:
        jobs = (
            await conn.execute(_RESEARCH_JOBS, {"run_ids": [r["run_id"] for r in runs]})
        ).mappings().all()
        for run in runs:
            accounts: dict[UUID, ResearchJobFacts] = {}
            person_counts: dict[UUID, int] = {}
            for job in jobs:
                if job["run_id"] != run["run_id"]:
                    continue
                if job["subject_type"] == "person":
                    person_counts[job["account_entity_id"]] = (
                        person_counts.get(job["account_entity_id"], 0) + 1
                    )
                    continue
                accounts[job["account_entity_id"]] = ResearchJobFacts(
                    account_name=str(job["canonical_name"]), status=str(job["status"]),
                    stage=None if job["stage"] is None else str(job["stage"]), person_jobs=0,
                )
            research.append(
                ResearchRunFacts(
                    run_id=run["run_id"], status=str(run["status"]), effort=str(run["effort"]),
                    created_at=run["created_at"], finished_at=run["finished_at"],
                    jobs=tuple(
                        ResearchJobFacts(
                            account_name=job.account_name, status=job.status, stage=job.stage,
                            person_jobs=person_counts.get(account_id, 0),
                        )
                        for account_id, job in accounts.items()
                    ),
                )
            )
    return ProjectStatusFacts(
        project_id=project_id, icp=icp, product_set=product_set, account_count=account_count,
        discovery=discovery, research=tuple(research), documents=(),
    )


async def load_project_decisions(
    conn: AsyncConnection,
    artifacts: AgentArtifactReader,
    *,
    workspace_id: str,
    project_id: str,
) -> tuple[DecisionItem, ...]:
    """The current-effective ``project_state`` statements, quotes resolved, oldest first.

    ``read_statements`` already drops any statement a later row corrects; an erased or missing
    artifact yields ``ExcludedEvidence`` and the item is simply omitted (empty is honest).
    """

    rows = await read_statements(
        conn, workspace_id=workspace_id, project_id=project_id,
        route_kind=StatementRoute.PROJECT_STATE,
    )
    resolved = await resolve_statement_quotes(
        conn, artifacts, workspace_id=workspace_id, statements=rows
    )
    return tuple(
        DecisionItem(route_key=row.route_key, quote=item.quote)
        for row, item in zip(rows, resolved, strict=True)
        if isinstance(item, ResolvedQuote)
    )


def _iso(value: datetime | None) -> str:
    return "—" if value is None else value.isoformat()


def render_status_markdown(facts: ProjectStatusFacts) -> str:
    lines: list[str] = ["# Project status", ""]
    lines += ["## Confirmed ICP"]
    if facts.icp is None:
        lines += ["Not confirmed."]
    else:
        lines += [
            f"- Key: `{facts.icp.icp_key}` (version {facts.icp.version}) — "
            f"`{INPUT_PREFIX}{facts.icp.path}`"
        ]
    lines += ["", "## Products"]
    if facts.product_set is None:
        lines += ["Not confirmed."]
    else:
        ids = ", ".join(f"`{pid}`" for pid in facts.product_set.product_ids)
        lines += [f"- Selection version {facts.product_set.selection_version}: {ids}"]
    lines += ["", "## Plan"]
    plan = next((d for d in facts.documents if d.path == "project/plan.md"), None)
    if plan is None:
        lines += ["Not written."]
    else:
        lines += [f"- Version {plan.version}, updated {_iso(plan.updated_at)} — "
                  f"`inputs/project/plan.md`"]
    lines += ["", "## Accounts", f"- Accounts in this project: {facts.account_count}"]
    lines += ["", "## Discovery"]
    if facts.discovery is None:
        lines += ["No discovery run yet."]
    else:
        d = facts.discovery
        asked = "—" if d.asked is None else str(d.asked)
        lines += [
            f"- Latest run `{d.run_id}`: {d.status}",
            f"  - asked {asked}, found {d.found}, verified {d.verified}, shown {d.shown}, "
            f"approved {d.approved}",
            f"  - started {_iso(d.started_at)}, finished {_iso(d.finished_at)}",
        ]
    lines += ["", "## Research"]
    if not facts.research:
        lines += ["No research run yet."]
    for run in facts.research:
        finished = sum(1 for job in run.jobs if job.status in ("completed", "needs_review"))
        lines += [
            f"- Run `{run.run_id}`: {run.status}, effort {run.effort}, "
            f"{finished}/{len(run.jobs)} finished (created {_iso(run.created_at)})"
        ]
        for job in run.jobs:
            stage = "" if job.stage is None else f" ({job.stage})"
            lines += [f"  - {job.account_name}: {job.status}{stage}, {job.person_jobs} person jobs"]
    lines += ["", "## Project documents"]
    if not facts.documents:
        lines += ["None yet."]
    for doc in facts.documents:
        lines += [f"- `inputs/project/{doc.path}` — version {doc.version}, {doc.status}, "
                  f"updated {_iso(doc.updated_at)}"]
    return "\n".join(lines) + "\n"


def render_decisions_markdown(items: Sequence[DecisionItem]) -> str:
    if not items:
        return (
            "# Project decisions\n\nNothing recorded yet. Record preferences, boundaries and "
            "choices through `record_interview_answer` (route `project_state`).\n"
        )
    lines = ["# Project decisions", ""]
    for item in items:
        quote = item.quote.replace("\n", " ").strip()
        lines.append(f'- **{item.route_key}** — "{quote}"')
    return "\n".join(lines) + "\n"
```

Adjust the pure tests' expected strings to match exactly what the renderer emits if a wording differs; the assertions above are the contract.

- [ ] **Step 4: Run the pure tests**

Run: `uv run pytest tests/api/test_project_status.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Write the failing loader DB test**

`tests/api/test_project_context_files_db.py` (fixtures as in `tests/api/test_brand_knowledge_context_db.py`: `migrated_db`, `rollback_conn`, `seed_principal`, `seed_project`, `_MemoryStorage`, `run_async`). One test for now:

```python
def test_status_facts_read_the_pin_the_product_set_and_the_arv2_rows(require_profiling_db) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, project_id, brand_id = await _seed_workspace_project(conn)   # helper: seed_principal + seed_project + brand row
            facts = await load_project_status_facts(conn, workspace_id=ws, project_id=project_id)
            assert facts.icp is None and facts.product_set is None and facts.discovery is None
            assert facts.research == () and facts.account_count == 0
            # one account in the project, one discovery run with two candidates (one approved),
            # one research run with one account job (stage synthesis) and two person jobs
            account_id = await _seed_account(conn, ws, "Goodman Campbell")
            await conn.execute(text("INSERT INTO project_account (workspace_id, project_id, account_entity_id, added_via) VALUES (:ws, :p, :a, 'manual')"), {"ws": ws, "p": project_id, "a": account_id})
            run_id = await _seed_discovery_run(conn, ws, project_id, brand_id, asked=20, found_strict=10, found_relaxed=3)
            await _seed_candidate(conn, run_id, ws, project_id, "goodman.org", disposition="pass", decision="approved")
            await _seed_candidate(conn, run_id, ws, project_id, "acme.org", disposition="pending")
            research_run = await _seed_research_run(conn, ws, project_id, brand_id)
            await _seed_job(conn, research_run, ws, account_id, subject_type="account", status="in_progress", stage="synthesis")
            await _seed_job(conn, research_run, ws, account_id, subject_type="person", status="not_started")
            await _seed_job(conn, research_run, ws, account_id, subject_type="person", status="completed")
            facts = await load_project_status_facts(conn, workspace_id=ws, project_id=project_id)
            assert facts.account_count == 1
            assert facts.discovery is not None and (facts.discovery.found, facts.discovery.verified, facts.discovery.shown, facts.discovery.approved) == (13, 1, 1, 1)
            assert len(facts.research) == 1
            (job,) = facts.research[0].jobs
            assert (job.account_name, job.status, job.stage, job.person_jobs) == ("Goodman Campbell", "in_progress", "synthesis", 2)
    run_async(scenario())
```

Write the `_seed_*` helpers with the column lists in `tests/arv2/test_discovery_launch_db.py` and `tests/arv2/test_account_research_launch_db.py` (they already insert `arv2_discovery_run`, `arv2_discovery_candidate`, `arv2_research_run`, `arv2_research_job` rows; copy their INSERT statements). `arv2_research_run` requires a `project_run_id` FK — those tests show how to seed the `project_run` row.

- [ ] **Step 6: Run the DB test to verify it passes**

Run: `set -a; source .env; set +a; uv run pytest tests/api/test_project_context_files_db.py -q -p no:cacheprovider --ignore-glob='*_live.py'`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add platform/api/clue_api/project_status.py tests/api/test_project_status.py tests/api/test_project_context_files_db.py
git commit -m "feat(project-context): status.md and decisions.md compiled from ARV2 rows and project_state statements"
```

---

### Task 3: `project_context_files.py` — the per-turn pin, seeds, and the index card

**Files:**
- Create: `platform/api/clue_api/project_context_files.py`
- Test: `tests/api/test_project_context_files_db.py` (extend)

**Interfaces:**
- Consumes: `agent_turn_project_files` (Task 1); `render_*`/`load_*` (Task 2); `DurableAgentArtifactStore.persist_body` (`clue_api.agent_turn_wiring`); `read_verified_artifact` (`clue_storage`); `WorkspaceSeedFile` (`clue_agents.resources`).
- Produces:
  ```python
  PROJECT_INPUT_PREFIX = "inputs/project/"
  PROJECT_FILES_INDEX_CARD_MEDIA_TYPE = "application/vnd.clue.project-files-index-card+json"

  @dataclass(frozen=True, slots=True)
  class CompiledProjectFile:
      path: str          # relative, e.g. "status.md"
      kind: str          # "project-status" | "project-decisions" | a knowledge kind (plan 2)
      body: bytes
      version: int | None
      status: str        # "compiled" for status/decisions; a document status otherwise
      summary: str       # ≤ 160 chars, first paragraph of the body after the H1

  class ProjectFileRef(BaseModel): path, kind, version, status, summary, artifact_key, artifact_sha256
  class ProjectFilesPinRow(BaseModel): turn_id, workspace_id, project_id, files: tuple[ProjectFileRef, ...], files_sha256, pinned_at

  @dataclass(frozen=True, slots=True)
  class PinnedProjectFile: ref: ProjectFileRef; body: bytes

  async def load_or_create_project_files_pin(conn, artifacts, *, workspace_id, turn_id, project_id, compile: Callable[[], Awaitable[Sequence[CompiledProjectFile]]]) -> tuple[ProjectFilesPinRow, bool]
  async def read_pinned_project_files(conn, storage, *, pin: ProjectFilesPinRow) -> tuple[PinnedProjectFile, ...]
  def project_seed_files(files: Sequence[PinnedProjectFile]) -> tuple[WorkspaceSeedFile, ...]
  class ProjectFileEntry(BaseModel): path, workspace_path, kind, version, status, summary, artifact_sha256
  class ProjectFilesIndexCard(BaseModel): schema_version: Literal["1"]; card_kind: Literal["project_files_index"]; project_id; files: list[ProjectFileEntry]; canonical_bytes(); content_sha256()
  def compile_project_files_index_card(*, project_id, files: Sequence[PinnedProjectFile]) -> ProjectFilesIndexCard
  ```

- [ ] **Step 1: Write the failing tests** (append to `tests/api/test_project_context_files_db.py`)

```python
def test_the_project_files_pin_is_insert_once_and_serves_verified_bytes(require_profiling_db) -> None:
    async def scenario() -> None:
        storage = _MemoryStorage()
        async with rollback_conn() as conn:
            ws, project_id, brand_id = await _seed_workspace_project(conn)
            turn_id = await _seed_submission(conn, ws, project_id)   # insert_submission + thread, as in test_brand_knowledge_context_db
            artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=_same_conn(conn))
            calls = 0
            async def compile_v1() -> list[CompiledProjectFile]:
                nonlocal calls; calls += 1
                return [CompiledProjectFile("status.md", "project-status", b"# Project status\n\nv1\n", None, "compiled", "v1"),
                        CompiledProjectFile("decisions.md", "project-decisions", b"# Project decisions\n\nnone\n", None, "compiled", "none")]
            async def compile_v2() -> list[CompiledProjectFile]:
                raise AssertionError("a pinned turn never recompiles")
            pin, created = await load_or_create_project_files_pin(conn, artifacts, workspace_id=ws, turn_id=turn_id, project_id=project_id, compile=compile_v1)
            assert created and calls == 1 and [f.path for f in pin.files] == ["decisions.md", "status.md"]
            again, created_again = await load_or_create_project_files_pin(conn, artifacts, workspace_id=ws, turn_id=turn_id, project_id=project_id, compile=compile_v2)
            assert not created_again and again == pin
            files = await read_pinned_project_files(conn, storage, pin=pin)
            assert [f.body for f in files] == [b"# Project decisions\n\nnone\n", b"# Project status\n\nv1\n"]
            seeds = project_seed_files(files)
            assert [s.path for s in seeds] == ["inputs/project/decisions.md", "inputs/project/status.md"]
            assert all(s.media_type == "text/markdown" for s in seeds)
            card = compile_project_files_index_card(project_id=project_id, files=files)
            assert card.card_kind == "project_files_index" and card.files[1].workspace_path == "inputs/project/status.md"
            assert card.files[1].summary == "v1"
            assert card.content_sha256().startswith("sha256:")
            # a moved blob is a loud refusal, not a silently different seed
            storage.put_sync(pin.files[0].artifact_key, b"tampered")
            with pytest.raises(ProjectFilesPinConflict):
                await read_pinned_project_files(conn, storage, pin=pin)
    run_async(scenario())
```

(`_MemoryStorage` in `tests/api/test_stage0_setup_db.py` — check its write method name and use it; `_same_conn` is a tiny `asynccontextmanager` yielding the test's connection, as the brand-knowledge test does for `DurableAgentArtifactStore`.)

- [ ] **Step 2: Run to verify it fails**

Run: `set -a; source .env; set +a; uv run pytest tests/api/test_project_context_files_db.py -q -p no:cacheprovider -k pin`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write the module**

`platform/api/clue_api/project_context_files.py` — model it line-for-line on `brand_knowledge_context.py` (`_canonical_json`, `_documents_digest`, `KnowledgePinConflict`, `read_pinned_documents`, `knowledge_seed_files`, the index card's `canonical_bytes`/`content_sha256`), with these specifics:

```python
PROJECT_INPUT_PREFIX = "inputs/project/"
PROJECT_FILES_INDEX_CARD_MEDIA_TYPE = "application/vnd.clue.project-files-index-card+json"
_FILE_MEDIA_TYPE = "text/markdown"
_SUMMARY_MAX_CHARS = 160


class ProjectFilesPinConflict(ValueError):
    """A pinned file's stored bytes no longer match the pinned digest."""


async def load_or_create_project_files_pin(conn, artifacts, *, workspace_id, turn_id, project_id, compile):
    existing = await get_project_files_pin(conn, workspace_id=workspace_id, turn_id=turn_id)
    if existing is not None:
        return existing, False
    compiled = sorted(await compile(), key=lambda f: f.path)
    refs = []
    for file in compiled:
        ref = await artifacts.persist_body(
            workspace_id=workspace_id, data=file.body, media_type=_FILE_MEDIA_TYPE,
            project_bindings=((project_id, "project_context_file"),),
        )
        refs.append(ProjectFileRef(path=file.path, kind=file.kind, version=file.version,
                                   status=file.status, summary=file.summary,
                                   artifact_key=ref.artifact_key, artifact_sha256=ref.sha256))
    digest = _files_digest(refs)
    await conn.execute(text(
        "INSERT INTO agent_turn_project_files (turn_id, workspace_id, project_id, files, files_sha256) "
        "VALUES (:turn_id, :ws, :project, CAST(:files AS jsonb), :digest) ON CONFLICT (turn_id) DO NOTHING"
    ), {...})
    winner = await get_project_files_pin(conn, workspace_id=workspace_id, turn_id=turn_id)
    assert winner is not None
    return winner, winner.files_sha256 == digest
```

`persist_body` returns `ArtifactRef.sha256` — check whether it is bare hex or `sha256:`-prefixed at `agent_turn_wiring.py:214-240` and normalize to bare hex in `ProjectFileRef` (the table CHECK is bare hex, and `read_verified_artifact` compares `record.content_sha256`, bare).

`project_seed_files` builds `WorkspaceSeedFile(path=PROJECT_INPUT_PREFIX + ref.path, content=body, sha256=ref.artifact_sha256, media_type=_FILE_MEDIA_TYPE)`.

The summary: first non-empty line after the H1 that does not start with `#`, truncated to 160 chars with `…`.

- [ ] **Step 4: Run to verify it passes; lint and type-check the two new modules**

Run: `set -a; source .env; set +a; uv run pytest tests/api/test_project_context_files_db.py -q -p no:cacheprovider` then `uv run ruff check platform/api/clue_api/project_status.py platform/api/clue_api/project_context_files.py && uv run mypy platform/api/clue_api/project_status.py platform/api/clue_api/project_context_files.py`
Expected: PASS; ruff and mypy clean.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/project_context_files.py tests/api/test_project_context_files_db.py
git commit -m "feat(project-context): the per-turn project files pin, read-only seeds under inputs/project/, and ProjectFilesIndexCard@1"
```

---

### Task 4: Compose the project files into the production turn

**Files:**
- Modify: `platform/api/clue_api/agent_turn_fleet_wiring.py:536-578` (after the knowledge pin) and `:763-843` (`_compose_project_context`)
- Test: `tests/api/test_o6_conversation_composition_db.py` (extend `test_the_production_turn_pins_seeds_and_indexes_the_brand_knowledge` or add a sibling)

**Interfaces:**
- Consumes: everything Task 2 and Task 3 produce; `self._storage`, `self._engine.artifacts`, `self._conn_factory` already on the runner.
- Produces: seeds `inputs/project/status.md`, `inputs/project/decisions.md`; L3 artifact `project_files_index` at `context/project/project_files_index.json`; log event `agent_turn.project_files_composed` with `turn_id`, `project_id`, `file_count`, `pin_created`.

- [ ] **Step 1: Extend the composition test (failing)**

In `tests/api/test_o6_conversation_composition_db.py`, after the existing assertions on `context/project/brand_knowledge_index.json` and the brand seeds, add (inside the same scenario, same lease):

```python
for path in ("inputs/project/status.md", "inputs/project/decisions.md"):
    entry = lease.backend.stat_entry_sync(path)
    assert entry.read_only is True
status_body = lease.backend.read_bytes_sync("inputs/project/status.md")   # use the backend's read helper the test already uses for brand files
assert status_body.startswith(b"# Project status\n")
assert b"## Confirmed ICP" in status_body
index = json.loads(lease.backend.read_bytes_sync("context/project/project_files_index.json"))
assert index["card_kind"] == "project_files_index"
assert sorted(f["workspace_path"] for f in index["files"]) == ["inputs/project/decisions.md", "inputs/project/status.md"]
pin = (await conn.execute(text("SELECT files_sha256 FROM agent_turn_project_files WHERE turn_id = :t"), {"t": turn_id})).scalar_one()
assert re.fullmatch(r"[0-9a-f]{64}", pin)
```

Also assert the constitution's `project_context_artifacts` names now include both `brand_knowledge_index` and `project_files_index` (the test already reads the constitution; extend that assertion — the module docstring line 9 "exactly one composed project artifact" becomes "exactly two").

- [ ] **Step 2: Run to verify it fails**

Run: `set -a; source .env; set +a; uv run pytest tests/api/test_o6_conversation_composition_db.py -q -p no:cacheprovider -k production_turn`
Expected: FAIL (no `inputs/project/status.md`).

- [ ] **Step 3: Wire the runner**

In `ProjectConversationTurnRunner.run`, immediately after `input_seeds = knowledge_seed_files(...)` (line 575):

```python
project_files: tuple[PinnedProjectFile, ...] = ()
if self._storage is not None:
    async with self._conn_factory() as conn:
        async def compile_project_files() -> list[CompiledProjectFile]:
            facts = await load_project_status_facts(
                conn, workspace_id=workspace_id, project_id=scope.project_id
            )
            decisions = await load_project_decisions(
                conn, self._engine.artifacts, workspace_id=workspace_id,
                project_id=scope.project_id,
            )
            status_md = render_status_markdown(facts).encode("utf-8")
            decisions_md = render_decisions_markdown(decisions).encode("utf-8")
            return [
                CompiledProjectFile("status.md", "project-status", status_md, None, "compiled",
                                    summary_of(status_md)),
                CompiledProjectFile("decisions.md", "project-decisions", decisions_md, None,
                                    "compiled", summary_of(decisions_md)),
            ]
        project_pin, project_pin_created = await load_or_create_project_files_pin(
            conn, self._engine.artifacts, workspace_id=workspace_id, turn_id=turn_id,
            project_id=scope.project_id, compile=compile_project_files,
        )
        project_files = await read_pinned_project_files(conn, self._storage, pin=project_pin)
    log.info("agent_turn.project_files_composed", turn_id=str(turn_id),
             project_id=scope.project_id, file_count=len(project_files),
             pin_created=project_pin_created)
input_seeds = (*input_seeds, *project_seed_files(project_files))
```

`summary_of` is exported from `project_context_files.py` (the same rule the index card uses). `load_project_decisions` needs an `AgentArtifactReader`; `self._engine.artifacts` is the `DurableAgentArtifactStore` and satisfies it (verify with `mypy`).

Note `load_project_decisions` opens no connection of its own: `resolve_statement_quotes(conn, artifacts, …)` takes the connection you pass. Do not use `ArtifactStatementEvidenceReader` here (it opens its own transaction).

Then in `_compose_project_context`, add the kwarg `project_files: tuple[PinnedProjectFile, ...] = ()` and, after the brand card block:

```python
if project_files:
    project_card = compile_project_files_index_card(project_id=scope.project_id, files=project_files)
    project_ref = await self._artifact(
        submission, scope, PROJECT_FILES_INDEX_CARD_MEDIA_TYPE,
        project_card.model_dump(mode="json", exclude_none=False),
    )
    if project_ref.sha256 != project_card.content_sha256().removeprefix("sha256:"):
        raise RuntimeError("persisted project-files index differs from its compiled content hash")
    artifacts.append(ProjectContextArtifact(
        name="project_files_index", artifact_ref=project_ref,
        domain_ref=DomainObjectRef(workspace_id=submission.workspace_id,
                                   object_type="project_files_index",
                                   object_id=scope.project_id, version=None),
    ))
    observations.append(_ContextCardObservation(
        card_kind=project_card.card_kind, schema_version=project_card.schema_version,
        content_sha256=project_ref.sha256, omitted_count=0,
    ))
```

Pass `project_files=project_files` at the call site (line ~634). Check `_observe_context_card` (lines 727–744) accepts the new `card_kind` without a registry of allowed kinds; if it validates against a set, add `"project_files_index"`.

- [ ] **Step 4: Run the composition test and the neighbours**

Run: `set -a; source .env; set +a; uv run pytest tests/api/test_o6_conversation_composition_db.py tests/api/test_brand_knowledge_context_db.py tests/api/test_project_context_files_db.py tests/api/test_fleet_wiring.py -q -p no:cacheprovider --ignore-glob='*_live.py'`
Expected: PASS. Then `uv run ruff check platform/api/clue_api/agent_turn_fleet_wiring.py && uv run lint-imports` (contracts kept, 0 broken).

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/agent_turn_fleet_wiring.py tests/api/test_o6_conversation_composition_db.py
git commit -m "feat(project-context): the production turn seeds inputs/project/status.md + decisions.md and composes project_files_index into L3"
```

---

### Task 5: Live proof and close-out

**Files:**
- Modify: `_memory/2026-09-11-san-salvador-lane-stack.md` (append a close-out section), `_memory/README.md` (index row), `docs/specs/ARV2-ONBOARDING-PLAN.md` §8 (one addendum paragraph: the project folder beside the brand folder).

- [ ] **Step 1: Restart this lane's API twins and workers** (the fleet worker composes the turn): `./scripts/dev_stack_san_salvador.sh restart-api > /tmp/san-salvador_restart.log 2>&1; ./scripts/dev_stack_san_salvador.sh restart-workers >> /tmp/san-salvador_restart.log 2>&1; ./scripts/dev_stack_san_salvador.sh status`. Never pipe the wrapper's output; never touch semarang's processes.

- [ ] **Step 2: Send one turn on an existing project** with a pinned ICP and a completed research run (the founder's Insight Health project). Then on the lane DB:

```sql
SELECT files_sha256, jsonb_array_length(files) FROM agent_turn_project_files ORDER BY pinned_at DESC LIMIT 1;
```
Expected: one row, 2 files. Open the turn inspector's context tab in the frontend and confirm `context/project/project_files_index.json` lists both files; ask the agent "where does this project stand?" in a **new thread** and confirm its answer names the pinned ICP and the research state from `status.md`.

- [ ] **Step 3: Record the close-out** in `_memory/…` (what shipped, the SQL above and its result, the walk transcript summary, anything parked), add the README index row, add the §8 addendum paragraph.

- [ ] **Step 4: Commit**

```bash
git add _memory docs/specs/ARV2-ONBOARDING-PLAN.md
git commit -m "docs(project-context): close-out for the project folder — live proof and memory"
```

---

## Self-review

- Spec coverage §4.1: folder + two files (T2–T4), byte stability via the pin (T1, T3), index card (T3–T4), skill instruction deferred to plan 2 (stated in the header). ✔
- Placeholder scan: `<hash>` is the alembic-minted id, not a placeholder; `_seed_*` helpers are named with their sources. ✔
- Type consistency: `CompiledProjectFile(path, kind, body, version, status, summary)` positional order matches Task 3 and Task 4; `PinnedProjectFile.ref`/`.body` used consistently; `load_or_create_project_files_pin(conn, artifacts, *, workspace_id, turn_id, project_id, compile)` same in T3 and T4. ✔
