"""The project's ``status.md`` and ``decisions.md`` — compiled from rows, never from a model.

Spec: docs/superpowers/specs/2026-09-12-project-context-and-icp-authoring-design.md §4.1.
The renderers are pure so the wording is tested without a database; the loaders read only ARV2
rows and the ``project_state`` statements (ruling R8). Nothing here writes "now": every timestamp
is a row's own, so two attempts of one turn compile identical bytes.

:func:`current_project_documents` sits here too, beside the two compiled files, because the
project's folder is one set: a document this project authored for itself is both a file in the
project library at ``project/`` and a line in ``status.md``'s "Project documents" section, and
both come off the same rows. It cannot live in :mod:`clue_api.project_context_files`, which
:mod:`clue_api.brand_knowledge_context` (the reader of those rows) imports — this module imports
both and is imported only by the turn's wiring, so the dependency runs one way.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import AgentArtifactReader
from clue_api.arv2.discovery_store import SHOWN_DISPOSITIONS, VERIFIED_PREDICATE
from clue_api.arv2.icp_confirmation import ProjectIcpPin, current_project_icp_pin
from clue_api.arv2.project_documents import PLAN_PATH
from clue_api.brand_knowledge_context import (
    INPUT_PREFIX,
    KnowledgeDocumentRef,
    current_project_knowledge_refs,
    document_ref,
    version_qualified_path,
)
from clue_api.project_context_files import (
    CompiledProjectFile,
    ProjectFilesPinConflict,
    project_workspace_path,
    summary_of,
)
from clue_api.statement_evidence import resolve_statement_quotes
from clue_core import OnboardingInputKind
from clue_projections.stage0 import ResolvedQuote
from clue_research.stage0 import StatementRoute, read_statements
from clue_spine import ProjectProductSet, current_project_product_set, get_project
from clue_storage import StorageBackend, read_verified_artifact

__all__ = [
    "DecisionItem",
    "DiscoveryFacts",
    "PersonaRunFacts",
    "ProjectDocumentFacts",
    "ProjectStatusFacts",
    "ResearchJobFacts",
    "ResearchRunFacts",
    "current_project_documents",
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
    #: Why the run ended, or ``None`` while it searches and for a run from before the brief.
    end_reason: str | None
    #: Companies a gate excluded — judged (so in ``verified``), never shown, never an account.
    excluded: int


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
    #: The **name** the document is served under below ``project/`` — its row path, or
    #: the version-qualified spelling when another version of that path owns the plain name.
    path: str
    version: int
    status: str
    updated_at: datetime
    #: What the document says it is for — ``plan``, ``persona``, or whatever word the human agreed
    #: to pin it under — read off the current version's own front matter. ``None`` when it claims
    #: none, and ``None`` for every surface that lists documents without reading their bytes.
    role: str | None = None
    #: The document's own title, read off the same front matter. ``None`` for the same two reasons.
    title: str | None = None
    #: A version of this same path that is newer than the one served here, when the surface being
    #: compiled serves only **one** version per path (the project library, W3). The per-turn seeds
    #: leave both ``None`` because they carry the other version as a real, version-qualified file
    #: and list it on its own line: a surface names what it serves, in the form it serves it.
    newer_version: int | None = None
    newer_status: str | None = None


@dataclass(frozen=True, slots=True)
class PersonaRunFacts:
    """One personas-only onboarding run this project asked for.

    The agent opens these through ``request_persona_synthesis@1`` and is told "it is running"; the
    run then lives entirely on the fleet. Without a line here, a run that failed, stalled or
    finished with gaps is visible to nobody — not the agent that asked, not the human waiting for
    the document — and the agent keeps reporting work that will never land.
    """

    run_id: UUID
    status: str
    requested_at: datetime
    finished_at: datetime | None


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
    personas: tuple[PersonaRunFacts, ...]


@dataclass(frozen=True, slots=True)
class DecisionItem:
    route_key: str
    quote: str
    statement_id: UUID | None = None
    onboarding_input_id: UUID | None = None
    entity_id: UUID | None = None
    route_ref: str | None = None
    correction_of_id: UUID | None = None
    input_kind: OnboardingInputKind | None = None
    input_actor: str | None = None
    input_created_at: datetime | None = None
    input_source_ref: str | None = None
    recorded_by_actor: str | None = None
    created_at: datetime | None = None


_ACCOUNT_COUNT = text(
    "SELECT count(*) FROM project_account WHERE workspace_id = :ws AND project_id = :project"
)

# "verified" and "shown" are the words the discovery screen uses, and their arithmetic is the
# lane's, not this module's: both are bound from ``clue_api.arv2.discovery_store``'s public
# constants rather than re-typed here, so a seventh disposition cannot leave status.md quietly
# reporting a different number than the UI — and ``VERIFIED_PREDICATE`` in particular is shared
# with the chat read and the Target-accounts poll, because "verified" means *judged* (a verdict
# row), not merely "no longer pending". Every sub-select is workspace-scoped too: the candidate's
# ``workspace_id`` is not forced equal to its run's by any FK.
_LATEST_DISCOVERY = text(
    f"""
    SELECT r.run_id, r.status, r.asked, r.end_reason,
           COALESCE(r.found_strict, 0) + COALESCE(r.found_relaxed, 0) AS found,
           r.started_at, r.finished_at,
           (SELECT count(*) FROM arv2_discovery_candidate c
             WHERE c.run_id = r.run_id AND c.workspace_id = :ws
               AND {VERIFIED_PREDICATE}) AS verified,
           (SELECT count(*) FROM arv2_discovery_candidate c
             WHERE c.run_id = r.run_id AND c.workspace_id = :ws
               AND c.disposition = ANY(:shown)) AS shown,
           (SELECT count(*) FROM arv2_discovery_candidate c
             WHERE c.run_id = r.run_id AND c.workspace_id = :ws
               AND c.disposition = 'excluded') AS excluded,
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


#: The personas runs listed in status.md, newest first. Older ones are history, not status.
_PERSONA_RUNS_SHOWN = 3

# Workspace-scoped as well as project-scoped: ``onboarding_run.project_id`` is part of a composite
# FK to ``project``, but this read is a scan, and every scan in this module names the tenant.
_PERSONA_RUNS = text(
    """
    SELECT run_id, status, requested_at, finished_at
    FROM onboarding_run
    WHERE workspace_id = :ws AND kind = 'personas' AND project_id = :project
    ORDER BY requested_at DESC, run_id DESC
    LIMIT :limit
    """
)


@dataclass(frozen=True, slots=True)
class _ScopedProjectDocument:
    """One project document plus the name it materializes under. Both users read these pairs."""

    ref: KnowledgeDocumentRef
    name: str


async def _project_document_refs(
    conn: AsyncConnection, *, workspace_id: str, project_id: str
) -> tuple[_ScopedProjectDocument, ...]:
    """This project's servable documents with their workspace names, in name order.

    ``status.md`` lists them and the turn seeds them; reading the same rows through one function
    is what keeps the file from naming a document the workspace does not carry, or carrying one
    the file never mentions.

    **The pinned ICP is one of them, even when it is no longer current.** A project confirms its
    variant, then asks for a change, and the agent authors the next version at the same path: the
    project's *current* set now serves v2 while ``project_icp_pin`` still holds v1 — the version
    the human agreed to and every launch researches against. Serving only the current set would
    leave the confirmed bytes readable nowhere while the brand card still named them at that path.

    So both are compiled, by the rule ``brand_knowledge_context.workspace_paths`` already applies
    on the brand's side of the scope: the **pinned** version keeps the plain name, because that is
    what this project's ICP *is*, and the newer version is offered beside it under
    :func:`version_qualified_path`. Two real files, neither hidden, neither overwriting the other.
    """

    refs = await current_project_knowledge_refs(
        conn, workspace_id=workspace_id, project_id=project_id
    )
    pin = await current_project_icp_pin(conn, workspace_id=workspace_id, project_id=project_id)
    pinned: KnowledgeDocumentRef | None = None
    if (
        pin is not None
        # A brand-scoped pin is the brand card's and the brand seeds' business, not this folder's.
        and pin.project_id == project_id
        and all(ref.document_id != pin.document_id for ref in refs)
    ):
        candidate = await document_ref(conn, workspace_id=workspace_id, document_id=pin.document_id)
        # A pinned row with no bytes is honestly absent: there is nothing to verify or seed.
        if candidate is not None and candidate.project_id == project_id:
            pinned = candidate
    scoped = [
        _ScopedProjectDocument(
            ref=ref,
            name=(
                version_qualified_path(ref.path, ref.version)
                if pinned is not None and ref.path == pinned.path
                else ref.path
            ),
        )
        for ref in refs
    ]
    if pinned is not None:
        scoped.append(_ScopedProjectDocument(ref=pinned, name=pinned.path))
    return tuple(sorted(scoped, key=lambda item: item.name))


async def current_project_documents(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    project_id: str,
) -> list[CompiledProjectFile]:
    """This project's own documents as files, ready to be pinned beside its compiled ones.

    A project-scoped document (an ICP variant the project authored for itself, its personas, the
    plan) is not brand knowledge: ``knowledge_seed_files`` skips it deliberately, because it
    materializes under the *project's* prefix. This is where it gets there — the turn's project
    files pin persists and freezes these bytes exactly as it does ``status.md``, so a retry seeds
    the document version the first attempt read even after a newer version is authored.

    Every document's bytes are verified twice: :func:`read_verified_artifact` against its durable
    artifact row, and then the row's own ``artifact_sha256`` against what was read. The second
    refusal is :class:`ProjectFilesPinConflict` for the same reason the pinned read raises it —
    seeding a file whose bytes are not the bytes the document row names would hand the model a
    document this project never authored, under a name it trusts.

    The set is :func:`_project_document_refs`', so a project-scoped ICP the project pinned is
    compiled here under the plain name even after a newer version superseded it, and the newer
    version rides beside it version-qualified.
    """

    files: list[CompiledProjectFile] = []
    for item in await _project_document_refs(
        conn, workspace_id=workspace_id, project_id=project_id
    ):
        ref = item.ref
        record, body = await read_verified_artifact(
            conn,
            storage,
            storage_key=ref.artifact_key,
            workspace_id=workspace_id,
        )
        if record.content_sha256 != ref.artifact_sha256:
            raise ProjectFilesPinConflict(
                f"the project document {ref.path!r} no longer matches its stored digest"
            )
        files.append(
            CompiledProjectFile(
                path=item.name,
                kind=ref.kind,
                body=body,
                version=ref.version,
                status=ref.status,
                summary=summary_of(body),
            )
        )
    return files


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
    document_refs = await _project_document_refs(
        conn, workspace_id=workspace_id, project_id=project_id
    )
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
                {**params, "shown": list(SHOWN_DISPOSITIONS)},
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
            end_reason=None if row["end_reason"] is None else str(row["end_reason"]),
            excluded=int(row["excluded"]),
        )
    )
    personas = tuple(
        PersonaRunFacts(
            run_id=row["run_id"],
            status=str(row["status"]),
            requested_at=row["requested_at"],
            finished_at=row["finished_at"],
        )
        for row in (await conn.execute(_PERSONA_RUNS, {**params, "limit": _PERSONA_RUNS_SHOWN}))
        .mappings()
        .all()
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
        documents=tuple(
            ProjectDocumentFacts(
                path=item.name,
                version=item.ref.version,
                status=item.ref.status,
                updated_at=item.ref.updated_at,
            )
            for item in document_refs
        ),
        personas=personas,
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
        DecisionItem(
            route_key=row.route_key,
            quote=item.quote,
            statement_id=row.id,
            onboarding_input_id=row.onboarding_input_id,
            entity_id=row.entity_id,
            route_ref=row.route_ref,
            correction_of_id=row.correction_of_id,
            input_kind=row.input_kind,
            input_actor=row.input_actor,
            input_created_at=row.input_created_at,
            input_source_ref=row.input_source_ref,
            recorded_by_actor=row.recorded_by_actor,
            created_at=row.created_at,
        )
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
        # The pin carries its document's scope, and the two scopes materialize under two different
        # prefixes. A project-local variant named under the brand's prefix is a path nothing seeds
        # — and this file is the first thing the agent opens on a thread, so it would send it to
        # read a file that does not exist and then report its own ICP as missing.
        icp_path = (
            INPUT_PREFIX + facts.icp.path
            if facts.icp.project_id is None
            else project_workspace_path(facts.icp.path)
        )
        lines += [f"- Key: `{facts.icp.icp_key}` (version {facts.icp.version}) — `{icp_path}`"]
    lines += ["", "## Products"]
    if facts.product_set is None:
        lines += ["Not confirmed."]
    else:
        ids = ", ".join(f"`{pid}`" for pid in facts.product_set.product_ids)
        lines += [f"- Selection version {facts.product_set.selection_version}: {ids}"]
    lines += ["", "## Plan"]
    # The plan is a **pin, not a path** (founder ruling 2026-09-14): it is whichever document the
    # human agreed to pin as the plan, which the document says by carrying ``role: plan``. The old
    # path stays as the fallback — it is what the skills still suggest, and what every plan written
    # before the roles existed is called — so a project that never pinned one still has a Plan
    # section. The first in path order wins when two documents claim the role, because two plans is
    # the human's business to resolve, not a reason to report none.
    plan = next(
        (d for d in facts.documents if d.role == "plan"),
        next((d for d in facts.documents if d.path == PLAN_PATH), None),
    )
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
            f"excluded {d.excluded}, approved {d.approved}",
            f"  - started {_iso(d.started_at)}, finished {_iso(d.finished_at)}",
        ]
        if d.end_reason is not None:
            lines += [f"  - ended: {d.end_reason.replace('_', ' ')}"]
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
    lines += ["", "## Personas"]
    if not facts.personas:
        lines += ["No persona run yet."]
    for persona_run in facts.personas:
        lines += [
            f"- Run `{persona_run.run_id}`: {persona_run.status}, "
            f"requested {_iso(persona_run.requested_at)}, "
            f"finished {_iso(persona_run.finished_at)}"
        ]
    lines += ["", "## Project documents"]
    if not facts.documents:
        lines += ["None yet."]
    for doc in facts.documents:
        # A surface that serves one version per path says the other version exists *in words*,
        # because naming it as a file would send the model to a path that surface does not carry.
        newer = (
            ""
            if doc.newer_version is None
            else f" (newer version v{doc.newer_version} {doc.newer_status})"
        )
        lines += [
            f"- `{project_workspace_path(doc.path)}` — version {doc.version}, {doc.status}, "
            f"updated {_iso(doc.updated_at)}{newer}"
        ]
    return "\n".join(lines) + "\n"


def render_decisions_markdown(items: Sequence[DecisionItem]) -> str:
    if not items:
        return (
            "# Project decisions\n\nNothing recorded yet. Record preferences, boundaries and "
            "choices through `record_interview_answer` (route `project_state`).\n"
        )
    lines = [
        "# Project decisions",
        "",
        "Current recorded statements; explicit corrections supersede earlier statements. "
        "Keep each quote's named target and scope. A missing entity/reference does not establish "
        "applicability to every account or artifact. Input actor and recording actor are distinct; "
        "do not present agent-authored context as the human's own request.",
        "",
    ]
    for item in items:
        quote = item.quote.replace("\n", " ").strip()
        lines.append(f'- **{item.route_key}** — "{quote}"')
        # JSON keeps values on one line and distinguishes missing metadata from
        # a human attribution or an asserted project-wide scope. Preserve IDs so
        # record_interview_answer can actually address a prior statement to correct.
        provenance = {
            "statement_id": item.statement_id,
            "input_id": item.onboarding_input_id,
            "input_kind": item.input_kind,
            "input_actor": item.input_actor,
            "input_created_at": item.input_created_at,
            "recorded_by_actor": item.recorded_by_actor,
            "recorded_at": item.created_at,
        }
        scope = {
            "entity_id": item.entity_id,
            "route_ref": item.route_ref,
            "input_source_ref": item.input_source_ref,
            "correction_of_id": item.correction_of_id,
        }
        lines.append(f"  - Provenance: {json.dumps(provenance, default=str, ensure_ascii=False)}")
        lines.append(f"  - Scope: {json.dumps(scope, default=str, ensure_ascii=False)}")
    return "\n".join(lines) + "\n"
