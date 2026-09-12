"""The Head of ABM reads this project's own ARV2 rows, instead of remembering them.

An agent that only knows what its own thread launched is wrong the moment a human imports a list,
approves a discovery candidate in the app, or opens a second thread. These tools close that gap:
they are effect-free reads over the rows that already exist — the project's accounts and the state
of each account's research here — so "how many accounts do we have, and how many are researched?"
is answered from the database rather than from the transcript.

Three properties are deliberate, and each one is a test:

* **Effect-free, and classified as such.** ``READ`` + ``EFFECT_FREE``: a read never launches
  anything, buys anything or approves anything, so replaying a turn that contained one is free.
* **Absence is a typed refusal, never an empty success.** A project this workspace cannot see
  comes back as ``project_not_found``, because an empty account list is a *statement* — "this
  project has no accounts" — and it would be a lie about a project that is simply not ours.
* **Scope is ambient.** The workspace comes from :class:`~clue_toolbelt.ToolContext`, never from
  the model; the project id is an untrusted input, checked against that workspace before any row
  is read.

Tasks 2 and 3 of this plan add ``read_account_research@1`` and ``read_discovery_run@1`` to this
module, behind the same :class:`Arv2ReadService` seam: one protocol the toolbelt tools call, one
:class:`DbArv2ReadService` that opens one transaction per call.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.errors import Arv2Error
from clue_db import ConnFactory, transaction
from clue_spine import get_project
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailed,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolInput,
    ToolOutput,
    ToolResult,
)

__all__ = [
    "MAX_ACCOUNTS",
    "Arv2ReadRefused",
    "Arv2ReadService",
    "DbArv2ReadService",
    "ProjectAccountView",
    "ProjectAccountsPage",
    "ReadProjectAccountsInput",
    "ReadProjectAccountsOutput",
    "ReadProjectAccountsTool",
    "list_project_accounts",
]

#: The hard ceiling on one read. A tool result is context the model pays for on every later turn,
#: so the page is bounded by construction rather than by the caller's good manners.
MAX_ACCOUNTS = 200


class Arv2ReadRefused(Arv2Error):
    """A read cannot be served, and the caller is told exactly which prerequisite is missing.

    ``code`` is stable and machine-readable; the toolbelt tools turn it straight into a
    :class:`~clue_toolbelt.PreconditionFailure`. Codes: ``project_not_found``.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# =================================================================================================
# read 1: the project's accounts
# =================================================================================================


class ProjectAccountView(BaseModel, frozen=True):
    """One account in a project: who it is, where its research stands, and how it got here."""

    account_entity_id: str
    name: str
    domain: str | None
    #: ``arv2_research_job.status`` verbatim — ``not_started`` / ``in_progress`` / ``needs_review``
    #: / ``completed`` / ``suspended``. An account with no job at all reads ``not_started``.
    research_status: str
    #: The account has been researched before **and** is being researched again right now.
    refreshing: bool
    added_via: str
    added_at: str


@dataclass(frozen=True, slots=True)
class ProjectAccountsPage:
    """One bounded page of a project's accounts, plus how many there are in total."""

    project_id: str
    total: int
    accounts: tuple[ProjectAccountView, ...]


#: The project's accounts with each one's research state, in one statement.
#:
#: ``merged_into IS NULL`` drops merge losers: a merged account is the same company under another
#: id, and listing it twice would make a project look bigger than it is. The lateral join takes the
#: account's newest ARV2 **account** job — person jobs share this table and the account column, and
#: a contact still being researched is not the account being re-researched. ``refreshing`` is the
#: narrow claim it sounds like: the latest run is live *and* an earlier one completed, so the
#: account already has research on it and is getting more.
_LIST_PROJECT_ACCOUNTS = text(
    """
    SELECT a.id, a.canonical_name, a.primary_domain, pa.added_via, pa.added_at,
           j.status AS research_status,
           EXISTS (SELECT 1 FROM arv2_research_job j2
                   WHERE j2.workspace_id = :ws AND j2.account_entity_id = a.id
                     AND j2.subject_type = 'account'
                     AND j2.status IN ('not_started', 'in_progress')
                     AND EXISTS (SELECT 1 FROM arv2_research_job j3
                                 WHERE j3.workspace_id = :ws AND j3.account_entity_id = a.id
                                   AND j3.subject_type = 'account' AND j3.status = 'completed'
                                   AND j3.created_at < j2.created_at)) AS refreshing
    FROM project_account pa
    JOIN account_entity a ON a.id = pa.account_entity_id AND a.merged_into IS NULL
    LEFT JOIN LATERAL (
      SELECT status FROM arv2_research_job j
      WHERE j.workspace_id = :ws AND j.account_entity_id = a.id AND j.subject_type = 'account'
      ORDER BY j.created_at DESC, j.job_id DESC LIMIT 1
    ) j ON TRUE
    WHERE pa.workspace_id = :ws AND pa.project_id = :project
    ORDER BY a.canonical_name, a.id
    LIMIT :limit
    """
)

#: The total counts memberships, not the page — including any merge loser still on the roster, so
#: the number matches the project's own membership rows rather than a filtered view of them.
_COUNT_PROJECT_ACCOUNTS = text(
    "SELECT count(*) FROM project_account WHERE workspace_id = :ws AND project_id = :project"
)


async def list_project_accounts(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    limit: int,
) -> ProjectAccountsPage:
    """The project's accounts with their research status. Raises when the project is not ours."""

    project = await get_project(conn, project_id)
    if project is None or project.workspace_id != workspace_id:
        # Fail-closed and indistinguishable: another workspace's project is not "empty", it is
        # absent — the same answer a project id that never existed gets.
        raise Arv2ReadRefused("project_not_found", f"no project {project_id} in this workspace")
    params = {"ws": workspace_id, "project": project_id, "limit": limit}
    rows = (await conn.execute(_LIST_PROJECT_ACCOUNTS, params)).mappings().all()
    total = int((await conn.execute(_COUNT_PROJECT_ACCOUNTS, params)).scalar_one())
    accounts = tuple(
        ProjectAccountView(
            account_entity_id=str(row["id"]),
            name=str(row["canonical_name"]),
            domain=str(row["primary_domain"]) if row["primary_domain"] is not None else None,
            # No job is "never researched", which is what a born job would say too.
            research_status=str(row["research_status"] or "not_started"),
            refreshing=bool(row["refreshing"]),
            added_via=str(row["added_via"]),
            added_at=row["added_at"].isoformat(),
        )
        for row in rows
    )
    return ProjectAccountsPage(project_id=project_id, total=total, accounts=accounts)


# =================================================================================================
# the service seam + its production implementation
# =================================================================================================


class Arv2ReadService(Protocol):
    """What the read tools call. One transaction per call is the implementation's business."""

    async def list_project_accounts(
        self, *, workspace_id: str, project_id: str, limit: int
    ) -> ProjectAccountsPage: ...


class DbArv2ReadService:
    """The production service: one transaction per read, and nothing else — reads need no storage,
    no queue and no settings, so this composes on every deployment that has a database."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def list_project_accounts(
        self, *, workspace_id: str, project_id: str, limit: int
    ) -> ProjectAccountsPage:
        async with self._conn_factory() as conn:
            return await list_project_accounts(
                conn, workspace_id=workspace_id, project_id=project_id, limit=limit
            )


def _not_composed() -> tuple[PreconditionFailure, ...]:
    return (
        PreconditionFailure(
            reason_code="arv2_reads_not_composed",
            message="the ARV2 read surface is not composed on this deployment",
        ),
    )


# =================================================================================================
# the tools
# =================================================================================================


class ReadProjectAccountsInput(ToolInput):
    project_id: str
    limit: int = Field(default=100, ge=1, le=MAX_ACCOUNTS)


class ReadProjectAccountsOutput(ToolOutput):
    project_id: str
    total: int
    #: ``ProjectAccountView`` rows. ``total`` is the whole membership; ``len(accounts)`` is the
    #: page, so the model can say "showing 100 of 240" rather than guessing at the rest.
    accounts: tuple[dict[str, Any], ...]


class ReadProjectAccountsTool(Tool):
    """List one project's accounts with each account's research status."""

    name = "read_project_accounts"
    version = "1"
    model_description = (
        "List the accounts in one project with each account's research status (not_started, "
        "in_progress, needs_review, completed, suspended) and how it joined the project. Read "
        "this before saying how many accounts there are, which are researched, or before "
        "proposing more discovery. Effect-free."
    )
    input_model: ClassVar[type[ToolInput]] = ReadProjectAccountsInput
    output_model: ClassVar[type[ToolOutput]] = ReadProjectAccountsOutput
    effect_class = ToolEffectClass.READ
    replay = ReplaySafety(
        policy=ReplayPolicy.EFFECT_FREE,
        durable_identity="current project_account rows + each account's latest ARV2 account job",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("project_id", "limit"))
    #: ``project`` is the spine row the execution is bound to — a replay identity, not a Stage-0
    #: pin (standing rule item 5).
    pin_requirements = ("project",)

    def __init__(self, service: Arv2ReadService | None) -> None:
        self._service = service

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        del inputs, ctx
        return _not_composed() if self._service is None else ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ReadProjectAccountsInput)
        assert self._service is not None
        try:
            page = await self._service.list_project_accounts(
                # The tenant is AMBIENT authority, never model-authored.
                workspace_id=ctx.workspace_id,
                project_id=inputs.project_id,
                limit=inputs.limit,
            )
        except Arv2ReadRefused as refused:
            raise PreconditionFailed([PreconditionFailure(refused.code, str(refused))]) from refused
        output = ReadProjectAccountsOutput(
            project_id=page.project_id,
            total=page.total,
            accounts=tuple(account.model_dump() for account in page.accounts),
        )
        return ToolResult(tool=self.name, version=self.version, references=output.model_dump())
