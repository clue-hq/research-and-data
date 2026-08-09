"""M8D R10 subject-neutral production composition for account and contact research.

The detached worker owns one ``entity_research_job`` task kind.  Account and contact research
remain separately selected, launched, budgeted, projected, and finalized, but their work is
drained through one provider-neutral router and the same queue/lease substrate.  The router makes
no provider decision; it reads the immutable job subject and delegates to the corresponding
role-configured ``create_agent()`` handler.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import text

from clue_agents import AgentModelProvider
from clue_agents.contracts import ModelPolicy
from clue_api.account_entity_research_composition import AccountResearchProviderActionResolver
from clue_api.account_research_fleet_composition import (
    AccountResearchFleetComposition,
    build_account_research_fleet_composition,
)
from clue_api.contact_entity_research_composition import (
    ContactResearchChannelActionResolver,
    ContactResearchProviderActionResolver,
)
from clue_api.contact_research_fleet_composition import (
    ContactResearchFleetComposition,
    build_contact_research_fleet_composition,
)
from clue_api.prose_synthesis_step import ProseSynthesisStep
from clue_core.entity_research import ResearchSubjectType
from clue_db import ConnFactory, transaction
from clue_fleet import EntityResearchJobError
from clue_fleet.enums import FleetTaskKind
from clue_fleet.work_worker import WorkContext, WorkHandler, WorkResult
from clue_storage import StorageBackend


class EntityResearchSubjectResolver(Protocol):
    async def subject_for_job(self, job_id: UUID) -> ResearchSubjectType: ...


class DbEntityResearchSubjectResolver:
    """Resolve a job only when its subject-specific launch authority is complete."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def subject_for_job(self, job_id: UUID) -> ResearchSubjectType:
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT job.subject_type::text AS subject_type, "
                            "EXISTS (SELECT 1 FROM entity_research_account_fleet_job_control "
                            "account_control WHERE account_control.job_id=job.job_id AND "
                            "account_control.research_run_id=job.research_run_id) "
                            "AS account_bound, "
                            "EXISTS (SELECT 1 FROM entity_research_contact_job_authority "
                            "contact_control WHERE contact_control.job_id=job.job_id AND "
                            "contact_control.research_run_id=job.research_run_id AND "
                            "contact_control.workspace_id=job.workspace_id) AS contact_bound "
                            "FROM entity_research_job job WHERE job.job_id=:job_id"
                        ),
                        {"job_id": job_id},
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            raise EntityResearchJobError("entity research job is absent")
        subject = ResearchSubjectType(str(row["subject_type"]))
        correctly_bound = (
            bool(row["account_bound"])
            if subject is ResearchSubjectType.ACCOUNT
            else bool(row["contact_bound"])
        )
        other_bound = (
            bool(row["contact_bound"])
            if subject is ResearchSubjectType.ACCOUNT
            else bool(row["account_bound"])
        )
        if not correctly_bound or other_bound:
            raise EntityResearchJobError(
                "entity research job lacks one exact subject-specific launch authority"
            )
        return subject


class SubjectNeutralEntityResearchWorkHandler:
    """Own the single task kind and route solely by immutable account/contact subject type."""

    kind = FleetTaskKind.ENTITY_RESEARCH_JOB

    def __init__(
        self,
        *,
        accounts: WorkHandler,
        contacts: WorkHandler,
        subjects: EntityResearchSubjectResolver | None = None,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        if accounts.kind is not self.kind or contacts.kind is not self.kind:
            raise ValueError("both entity research delegates must own entity_research_job")
        self._handlers = {
            ResearchSubjectType.ACCOUNT: accounts,
            ResearchSubjectType.CONTACT: contacts,
        }
        self._subjects = subjects or DbEntityResearchSubjectResolver(conn_factory=conn_factory)

    async def handle(self, context: WorkContext) -> WorkResult:
        raw_job_id = context.payload.get("job_id")
        if not isinstance(raw_job_id, str):
            raise EntityResearchJobError("entity research work payload has no job_id")
        try:
            job_id = UUID(raw_job_id)
        except ValueError as exc:
            raise EntityResearchJobError(
                "entity research work payload has an invalid job_id"
            ) from exc
        if job_id != UUID(str(context.work_id)):
            raise EntityResearchJobError("entity research work payload widens the leased work id")
        subject = await self._subjects.subject_for_job(job_id)
        return await self._handlers[subject].handle(context)


@dataclass(frozen=True, slots=True)
class EntityResearchFleetComposition:
    """Separate launch/read surfaces and one shared worker-owned task handler."""

    accounts: AccountResearchFleetComposition
    contacts: ContactResearchFleetComposition
    handler: SubjectNeutralEntityResearchWorkHandler


def build_entity_research_fleet_composition(
    *,
    storage: StorageBackend,
    models: AgentModelProvider,
    account_provider_actions: AccountResearchProviderActionResolver,
    contact_provider_actions: ContactResearchProviderActionResolver,
    contact_channel_actions: ContactResearchChannelActionResolver,
    model_policy: ModelPolicy,
    conn_factory: ConnFactory = transaction,
    prose_step: ProseSynthesisStep | None = None,
) -> EntityResearchFleetComposition:
    """Promote the R6/R8 units behind the one R2/R9 production work-kind seam."""

    accounts = build_account_research_fleet_composition(
        storage=storage,
        models=models,
        provider_actions=account_provider_actions,
        model_policy=model_policy,
        conn_factory=conn_factory,
        # Lane E: ONE step instance serves both lanes. The step authorizes nothing and holds no
        # per-lane state — its operation id is already field-parameterized (`{job}:{field_key}`),
        # so a second instance would disambiguate nothing and merely double the binds to remember.
        prose_step=prose_step,
    )
    contacts = build_contact_research_fleet_composition(
        storage=storage,
        models=models,
        provider_actions=contact_provider_actions,
        channel_actions=contact_channel_actions,
        model_policy=model_policy,
        conn_factory=conn_factory,
        prose_step=prose_step,
    )
    return EntityResearchFleetComposition(
        accounts=accounts,
        contacts=contacts,
        handler=SubjectNeutralEntityResearchWorkHandler(
            accounts=accounts.handler,
            contacts=contacts.handler,
            conn_factory=conn_factory,
        ),
    )


__all__ = [
    "DbEntityResearchSubjectResolver",
    "EntityResearchFleetComposition",
    "EntityResearchSubjectResolver",
    "SubjectNeutralEntityResearchWorkHandler",
    "build_entity_research_fleet_composition",
]
