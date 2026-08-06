"""M8D R8 production composition on the shared R2-R4 entity-research machinery."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from clue_agents import AgentModelProvider
from clue_agents.contracts import ModelPolicy
from clue_agents.entity_research_runtime import (
    EntityResearchAgentFactory,
    EntityResearchAgentRuntime,
    EntityResearchCheckpointerFactory,
)
from clue_api.contact_entity_research import (
    ContactChannelActions,
    ContactResearchExecutionGuard,
    ContactResearchFinalizationEngine,
    ContactResearchStateStore,
)
from clue_api.contact_entity_research_composition import (
    ContactResearchChannelActionResolver,
    ContactResearchDefinitionResolver,
    ContactResearchProviderActionResolver,
    StaticContactResearchChannelActions,
    StaticContactResearchProviderActions,
)
from clue_api.contact_research_fleet import (
    ContactResearchFleetService,
    ContactResearchFleetWorkHandler,
)
from clue_api.contact_research_fleet_launch import ContactResearchFleetLauncher
from clue_api.entity_research_parallel import (
    DbEntityResearchToolBatchCoordinator,
    R9EntityResearchJobStore,
)
from clue_api.entity_research_runtime_wiring import (
    CreateAgentEntityResearchDriver,
    DbEntityResearchAgentJournal,
    PostgresEntityResearchCheckpointers,
)
from clue_api.entity_research_tools import (
    EntityResearchProviderCausationStore,
    EntityResearchResultStore,
    EntityResearchToolRequestStore,
    ExternalResearchResultLineageReader,
    GovernedEntityResearchToolFactory,
    ProviderActionBinding,
)
from clue_api.sumble_entity_research_tools import SumbleEntityResearchLineageReader
from clue_core.contact_research import ContactResearchIntent, ContactResearchPolicyPin
from clue_db import ConnFactory, transaction
from clue_fleet import EntityResearchJobRow, EntityResearchJobWorkHandler
from clue_storage import StorageBackend


@dataclass(frozen=True, slots=True)
class ContactResearchFleetComposition:
    launcher: ContactResearchFleetLauncher
    fleets: ContactResearchFleetService
    handler: ContactResearchFleetWorkHandler


class ContactResearchProviderActionFactory(Protocol):
    async def __call__(
        self,
        job: EntityResearchJobRow,
        *,
        intent: ContactResearchIntent,
    ) -> ProviderActionBinding: ...


class ContactResearchChannelActionFactory(Protocol):
    async def __call__(
        self,
        job: EntityResearchJobRow,
        *,
        intent: ContactResearchIntent,
        policy: ContactResearchPolicyPin,
        state: ContactResearchStateStore,
    ) -> ContactChannelActions: ...


class RunScopedContactResearchProviderActions(ContactResearchProviderActionResolver):
    """Rebuild contact provider actions from each job's immutable R7 intent."""

    def __init__(
        self,
        *,
        deep: ContactResearchProviderActionFactory,
        enrichment: ContactResearchProviderActionFactory,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._deep = deep
        self._enrichment = enrichment
        self._conn_factory = conn_factory

    async def resolve(self, job: EntityResearchJobRow) -> Mapping[str, ProviderActionBinding]:
        intent = await _contact_intent(job, conn_factory=self._conn_factory)
        return {
            "research_contact_deep": await self._deep(job, intent=intent),
            "enrich_contact": await self._enrichment(job, intent=intent),
        }


class RunScopedContactResearchChannelActions(ContactResearchChannelActionResolver):
    def __init__(self, *, factory: ContactResearchChannelActionFactory) -> None:
        self._factory = factory

    async def resolve(
        self,
        job: EntityResearchJobRow,
        *,
        intent: ContactResearchIntent,
        policy: ContactResearchPolicyPin,
        state: ContactResearchStateStore,
    ) -> ContactChannelActions:
        return await self._factory(job, intent=intent, policy=policy, state=state)


async def _contact_intent(
    job: EntityResearchJobRow,
    *,
    conn_factory: ConnFactory,
) -> ContactResearchIntent:
    from sqlalchemy import text

    async with conn_factory() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT contact_intent_json, contact_intent_sha256 FROM "
                        "entity_research_contact_job_authority WHERE job_id=:job_id AND "
                        "research_run_id=:run_id AND workspace_id=:workspace_id"
                    ),
                    {
                        "job_id": job.job_id,
                        "run_id": job.research_run_id,
                        "workspace_id": job.workspace_id,
                    },
                )
            )
            .mappings()
            .first()
        )
    if row is None:
        raise RuntimeError("contact job lacks its exact durable intent")
    intent = ContactResearchIntent.model_validate(row["contact_intent_json"])
    if intent.sha256() != str(row["contact_intent_sha256"]):
        raise RuntimeError("contact job intent digest changed")
    return intent


def build_contact_research_fleet_composition(
    *,
    storage: StorageBackend,
    models: AgentModelProvider,
    provider_actions: ContactResearchProviderActionResolver,
    channel_actions: ContactResearchChannelActionResolver,
    model_policy: ModelPolicy,
    conn_factory: ConnFactory = transaction,
    checkpointers: EntityResearchCheckpointerFactory | None = None,
) -> ContactResearchFleetComposition:
    if isinstance(provider_actions, StaticContactResearchProviderActions) or isinstance(
        channel_actions, StaticContactResearchChannelActions
    ):
        raise TypeError("production contact fleet cannot use static action bindings")
    journal = DbEntityResearchAgentJournal(conn_factory=conn_factory)
    results = EntityResearchResultStore(
        storage=storage,
        conn_factory=conn_factory,
        lineage_readers={
            ExternalResearchResultLineageReader.provider_kind: (
                ExternalResearchResultLineageReader(conn_factory=conn_factory)
            ),
            "sumble_contact": SumbleEntityResearchLineageReader(
                provider_kind="sumble_contact",
                conn_factory=conn_factory,
            ),
        },
    )
    tools = GovernedEntityResearchToolFactory(
        requests=EntityResearchToolRequestStore(
            conn_factory=conn_factory,
            storage=storage,
        ),
        causation=EntityResearchProviderCausationStore(conn_factory=conn_factory),
        results=results,
    )
    state = ContactResearchStateStore(conn_factory=conn_factory)
    checkpointer_factory = checkpointers or PostgresEntityResearchCheckpointers()
    runtime = EntityResearchAgentRuntime(
        factory=EntityResearchAgentFactory(
            models=models,
            journal=journal,
            guard=ContactResearchExecutionGuard(conn_factory=conn_factory),
            batches=DbEntityResearchToolBatchCoordinator(conn_factory=conn_factory),
        ),
        checkpointers=checkpointer_factory,
        journal=journal,
        finalizer=ContactResearchFinalizationEngine(conn_factory=conn_factory),
    )
    definitions = ContactResearchDefinitionResolver(
        tools=tools,
        state=state,
        provider_actions=provider_actions,
        channel_actions=channel_actions,
        facet_runtime=runtime,
        model_policy=model_policy,
        conn_factory=conn_factory,
        require_atomic_admission=True,
    )
    inner = EntityResearchJobWorkHandler(
        store=R9EntityResearchJobStore(conn_factory=conn_factory),
        driver=CreateAgentEntityResearchDriver(runtime=runtime, definitions=definitions),
    )
    fleets = ContactResearchFleetService(conn_factory=conn_factory)
    return ContactResearchFleetComposition(
        launcher=ContactResearchFleetLauncher(conn_factory=conn_factory),
        fleets=fleets,
        handler=ContactResearchFleetWorkHandler(inner=inner, fleets=fleets),
    )


__all__ = [
    "ContactResearchChannelActionFactory",
    "ContactResearchFleetComposition",
    "ContactResearchProviderActionFactory",
    "RunScopedContactResearchChannelActions",
    "RunScopedContactResearchProviderActions",
    "build_contact_research_fleet_composition",
]
