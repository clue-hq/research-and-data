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
from clue_api.arv2.discovery_store import PENDING_DISPOSITION, SHOWN_DISPOSITIONS
from clue_api.arv2.icp_confirmation import ProjectIcpPin, current_project_icp_pin
from clue_api.brand_knowledge_context import INPUT_PREFIX
from clue_api.project_context_files import project_workspace_path
from clue_api.statement_evidence import resolve_statement_quotes
from clue_projections.stage0 import ResolvedQuote
from clue_research.stage0 import StatementRoute, read_statements
from clue_spine import ProjectProductSet, current_project_product_set, get_project

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

#: A job that will not move again on its own. The run header counts these as "finished" — the
#: seam-1 vocabulary has no separate "failed": a job that could not finish lands in needs_review.
_TERMINAL_JOB_STATUSES = ("completed", "needs_review")


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
    project_name: str
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

# "verified" and "shown" are the words the discovery screen uses, and their arithmetic is the
# lane's, not this module's: both dispositions are bound from ``clue_api.arv2.discovery_store``'s
# public constants rather than re-typed here, so a seventh disposition cannot leave status.md
# quietly reporting a different number than the UI. Every sub-select is workspace-scoped too: the
# candidate's ``workspace_id`` is not forced equal to its run's by any FK.
_LATEST_DISCOVERY = text(
    """
    SELECT r.run_id, r.status, r.asked,
           COALESCE(r.found_strict, 0) + COALESCE(r.found_relaxed, 0) AS found,
           r.started_at, r.finished_at,
           (SELECT count(*) FROM arv2_discovery_candidate c
             WHERE c.run_id = r.run_id AND c.workspace_id = :ws
               AND c.disposition <> :pending) AS verified,
           (SELECT count(*) FROM arv2_discovery_candidate c
             WHERE c.run_id = r.run_id AND c.workspace_id = :ws
               AND c.disposition = ANY(:shown)) AS shown,
           (SELECT count(*) FROM arv2_discovery_candidate c
             WHERE c.run_id = r.run_id AND c.workspace_id = :ws
               AND c.decision = 'approved') AS approved
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

# ``arv2_research_job.run_id`` is a single-column FK, so nothing in the schema forces a job's
# workspace to equal its run's: the job and the account it names are scoped here explicitly rather
# than trusted to be scoped by something that is scoped.
_RESEARCH_JOBS = text(
    """
    SELECT j.run_id, j.subject_type, j.account_entity_id, a.canonical_name, j.status, j.stage
    FROM arv2_research_job j
    JOIN account_entity a ON a.id = j.account_entity_id
    WHERE j.run_id = ANY(:run_ids) AND j.workspace_id = :ws AND a.workspace_id = :ws
    ORDER BY j.run_id, j.subject_type, a.canonical_name, j.job_id
    """
)


async def load_project_status_facts(
    conn: AsyncConnection, *, workspace_id: str, project_id: str
) -> ProjectStatusFacts:
    """Everything status.md says about one project, read from its own rows.

    Only the latest discovery run and the newest :data:`_RESEARCH_RUNS_SHOWN` research runs are
    read: older runs are history, and the file is context, not an archive.

    Raises ``ValueError`` when the project is not this workspace's: a status file compiled for a
    project the caller cannot see is never the right answer.
    """

    project = await get_project(conn, project_id)
    if project is None or project.workspace_id != workspace_id:
        raise ValueError("this project does not exist in this workspace")
    icp = await current_project_icp_pin(conn, workspace_id=workspace_id, project_id=project_id)
    product_set = await current_project_product_set(
        conn, workspace_id=workspace_id, project_id=project_id
    )
    params: dict[str, object] = {"ws": workspace_id, "project": project_id}
    account_count = int(await conn.scalar(_ACCOUNT_COUNT, params) or 0)
    row = (
        (
            await conn.execute(
                _LATEST_DISCOVERY,
                {
                    **params,
                    "shown": list(SHOWN_DISPOSITIONS),
                    "pending": PENDING_DISPOSITION,
                },
            )
        )
        .mappings()
        .first()
    )
    discovery = (
        None
        if row is None
        else DiscoveryFacts(
            run_id=row["run_id"],
            status=str(row["status"]),
            asked=None if row["asked"] is None else int(row["asked"]),
            found=int(row["found"]),
            verified=int(row["verified"]),
            shown=int(row["shown"]),
            approved=int(row["approved"]),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )
    )
    runs = (
        (await conn.execute(_RESEARCH_RUNS, {**params, "limit": _RESEARCH_RUNS_SHOWN}))
        .mappings()
        .all()
    )
    research: list[ResearchRunFacts] = []
    if runs:
        jobs = (
            (
                await conn.execute(
                    _RESEARCH_JOBS,
                    {"run_ids": [r["run_id"] for r in runs], "ws": workspace_id},
                )
            )
            .mappings()
            .all()
        )
        for run in runs:
            # One line per account; a run's person jobs are counted onto the account they belong
            # to (``account_entity_id`` is the account for both subject kinds) rather than listed,
            # because a committee of twelve would otherwise bury the account it belongs to.
            accounts: dict[UUID, ResearchJobFacts] = {}
            person_counts: dict[UUID, int] = {}
            for job in jobs:
                if job["run_id"] != run["run_id"]:
                    continue
                if job["subject_type"] == "person":
                    person_counts[job["account_entity_id"]] = (
                        person_counts.get(job["account_entity_id"], 0) + 1
                    )
                    # An account whose own job ran in an *earlier* run still has committee work
                    # here. Standing in for it with what this run does know beats dropping it:
                    # a silently missing account reads as "not researched", and its person jobs
                    # would vanish from the run's own denominator too.
                    accounts.setdefault(
                        job["account_entity_id"],
                        ResearchJobFacts(
                            account_name=str(job["canonical_name"]),
                            status="person research only",
                            stage=None,
                            person_jobs=0,
                        ),
                    )
                    continue
                accounts[job["account_entity_id"]] = ResearchJobFacts(
                    account_name=str(job["canonical_name"]),
                    status=str(job["status"]),
                    stage=None if job["stage"] is None else str(job["stage"]),
                    person_jobs=0,
                )
            research.append(
                ResearchRunFacts(
                    run_id=run["run_id"],
                    status=str(run["status"]),
                    effort=str(run["effort"]),
                    created_at=run["created_at"],
                    finished_at=run["finished_at"],
                    jobs=tuple(
                        ResearchJobFacts(
                            account_name=job.account_name,
                            status=job.status,
                            stage=job.stage,
                            person_jobs=person_counts.get(account_id, 0),
                        )
                        for account_id, job in accounts.items()
                    ),
                )
            )
    return ProjectStatusFacts(
        project_id=project_id,
        project_name=project.name,
        icp=icp,
        product_set=product_set,
        account_count=account_count,
        discovery=discovery,
        research=tuple(research),
        documents=(),
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
        conn,
        workspace_id=workspace_id,
        project_id=project_id,
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
    """Every section, always — an empty one says so rather than disappearing.

    The title names the project. The model should never have to infer *which* project it is
    reading about, and it also makes the file's content address project-specific: two fresh
    projects in one workspace would otherwise compile byte-identical status files and share one
    artifact, so erasing the first project's artifacts would refuse the second project's turns.
    """

    lines: list[str] = [f"# Project status — {facts.project_name} (`{facts.project_id}`)", ""]
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
        lines += [
            f"- Version {plan.version}, updated {_iso(plan.updated_at)} — "
            f"`{project_workspace_path(plan.path)}`"
        ]
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
        finished = sum(1 for job in run.jobs if job.status in _TERMINAL_JOB_STATUSES)
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
        lines += [
            f"- `{project_workspace_path(doc.path)}` — version {doc.version}, {doc.status}, "
            f"updated {_iso(doc.updated_at)}"
        ]
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
