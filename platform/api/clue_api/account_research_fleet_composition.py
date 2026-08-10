"""M8D R6 production composition of the R2-R5 account-research unit and fleet shell.

This module is deliberately provider-neutral.  The injected action resolver owns the concrete
Exa/Sumble adapters for an exact job; this root composes their durable R4 services behind the R5
semantic tools and installs the resulting ``create_agent()`` driver in the R6 admission wrapper.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import text

from clue_agents import AgentModelProvider
from clue_agents.contracts import ModelPolicy
from clue_agents.entity_research_runtime import (
    EntityResearchAgentFactory,
    EntityResearchAgentRuntime,
    EntityResearchCheckpointerFactory,
)
from clue_api.account_entity_research import (
    AccountResearchExecutionGuard,
    AccountResearchFinalizationEngine,
    AccountResearchStateStore,
)
from clue_api.account_entity_research_composition import (
    AccountResearchDefinitionResolver,
    AccountResearchProviderActionResolver,
    StaticAccountResearchProviderActions,
)
from clue_api.account_research_fleet import (
    AccountResearchFleetService,
    AccountResearchFleetWorkHandler,
)
from clue_api.account_research_fleet_launch import AccountResearchFleetLauncher
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
    ProviderActionBinding,
)
from clue_api.entity_research_tools import (
    GovernedEntityResearchToolFactory as GovernedTools,
)
from clue_api.prose_synthesis_step import ProseSynthesisStep
from clue_api.sumble_entity_research_tools import SumbleEntityResearchLineageReader
from clue_db import ConnFactory, transaction
from clue_fleet import EntityResearchJobRow, EntityResearchJobWorkHandler
from clue_storage import StorageBackend


@dataclass(frozen=True, slots=True)
class AccountResearchFleetComposition:
    """The separately addressable launch/projection service and detached-work handler."""

    fleets: AccountResearchFleetService
    launcher: AccountResearchFleetLauncher
    handler: AccountResearchFleetWorkHandler


class AccountResearchProviderActionFactory(Protocol):
    async def __call__(
        self,
        job: EntityResearchJobRow,
        *,
        account_run_id: UUID,
    ) -> ProviderActionBinding: ...


class AccountResearchJobContextResolver(Protocol):
    async def account_run_id(self, job: EntityResearchJobRow) -> UUID: ...


class DbAccountResearchJobContextResolver:
    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def account_run_id(self, job: EntityResearchJobRow) -> UUID:
        async with self._conn_factory() as conn:
            value = (
                await conn.execute(
                    text(
                        "SELECT control.account_run_id FROM "
                        "entity_research_account_fleet_job_control control JOIN "
                        "entity_research_account_fleet fleet "
                        "ON fleet.research_run_id=control.research_run_id "
                        "WHERE control.job_id=:job_id AND "
                        "control.research_run_id=:run_id AND fleet.workspace_id=:workspace_id"
                    ),
                    {
                        "job_id": job.job_id,
                        "run_id": job.research_run_id,
                        "workspace_id": job.workspace_id,
                    },
                )
            ).scalar_one_or_none()
        if value is None:
            raise RuntimeError("account research job lacks its exact account-run binding")
        return UUID(str(value))


class RunScopedAccountResearchProviderActions(AccountResearchProviderActionResolver):
    """Construct the three exact R5 provider actions from each durable leased job.

    Unlike the R5 static test helper, this resolver cannot carry a process-local map of job ids.
    Each factory must re-read the job's pinned directive/selection/provider state, so a fresh
    worker process composes the same actions and provider replay identities.
    """

    def __init__(
        self,
        *,
        deep: AccountResearchProviderActionFactory,
        enrichment: AccountResearchProviderActionFactory,
        committee: AccountResearchProviderActionFactory,
        contexts: AccountResearchJobContextResolver | None = None,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._factories: Mapping[str, AccountResearchProviderActionFactory] = {
            "research_account_deep": deep,
            "enrich_account": enrichment,
            "discover_buying_committee": committee,
        }
        self._contexts = contexts or DbAccountResearchJobContextResolver(conn_factory=conn_factory)

    async def resolve(self, job: EntityResearchJobRow) -> Mapping[str, ProviderActionBinding]:
        account_run_id = await self._contexts.account_run_id(job)
        return {
            tool_name: await factory(job, account_run_id=account_run_id)
            for tool_name, factory in self._factories.items()
        }


def build_account_research_fleet_composition(
    *,
    storage: StorageBackend,
    models: AgentModelProvider,
    provider_actions: AccountResearchProviderActionResolver,
    model_policy: ModelPolicy,
    conn_factory: ConnFactory = transaction,
    checkpointers: EntityResearchCheckpointerFactory | None = None,
    prose_step: ProseSynthesisStep | None = None,
) -> AccountResearchFleetComposition:
    """Compose one production-capable account fleet without provider branches in the fleet.

    The same connection factory is threaded through requests, causation, lineage, agent state,
    finalization, and R2 job transitions.  A result can therefore be exposed to the model only
    after its provider-owned and provider-neutral durability surfaces agree.
    """

    if isinstance(provider_actions, StaticAccountResearchProviderActions):
        raise TypeError("production account fleet cannot use static provider action bindings")
    journal = DbEntityResearchAgentJournal(conn_factory=conn_factory)
    results = EntityResearchResultStore(
        storage=storage,
        conn_factory=conn_factory,
        lineage_readers={
            ExternalResearchResultLineageReader.provider_kind: (
                ExternalResearchResultLineageReader(conn_factory=conn_factory)
            ),
            "sumble_account": SumbleEntityResearchLineageReader(
                provider_kind="sumble_account",
                conn_factory=conn_factory,
            ),
            "sumble_committee": SumbleEntityResearchLineageReader(
                provider_kind="sumble_committee",
                conn_factory=conn_factory,
            ),
        },
    )
    tools = GovernedTools(
        requests=EntityResearchToolRequestStore(
            conn_factory=conn_factory,
            storage=storage,
        ),
        causation=EntityResearchProviderCausationStore(conn_factory=conn_factory),
        results=results,
    )
    state = AccountResearchStateStore(conn_factory=conn_factory)
    definitions = AccountResearchDefinitionResolver(
        tools=tools,
        state=state,
        provider_actions=provider_actions,
        model_policy=model_policy,
        conn_factory=conn_factory,
        require_atomic_admission=True,
    )
    batches = DbEntityResearchToolBatchCoordinator(conn_factory=conn_factory)
    runtime = EntityResearchAgentRuntime(
        factory=EntityResearchAgentFactory(
            models=models,
            journal=journal,
            guard=AccountResearchExecutionGuard(conn_factory=conn_factory),
            batches=batches,
        ),
        checkpointers=checkpointers or PostgresEntityResearchCheckpointers(),
        journal=journal,
        finalizer=AccountResearchFinalizationEngine(conn_factory=conn_factory),
    )
    inner = EntityResearchJobWorkHandler(
        store=R9EntityResearchJobStore(conn_factory=conn_factory),
        driver=CreateAgentEntityResearchDriver(
            runtime=runtime,
            definitions=definitions,
        ),
    )
    fleets = AccountResearchFleetService(conn_factory=conn_factory)
    return AccountResearchFleetComposition(
        fleets=fleets,
        launcher=AccountResearchFleetLauncher(fleets=fleets, conn_factory=conn_factory),
        handler=AccountResearchFleetWorkHandler(
            inner=inner,
            fleets=fleets,
            # Lane E E1: ``None`` (the default) composes the pre-Lane-E handler exactly.
            prose_step=prose_step,
        ),
    )


__all__ = [
    "AccountResearchFleetComposition",
    "AccountResearchJobContextResolver",
    "AccountResearchProviderActionFactory",
    "DbAccountResearchJobContextResolver",
    "RunScopedAccountResearchProviderActions",
    "build_account_research_fleet_composition",
]
