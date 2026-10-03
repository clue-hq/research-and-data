"""M8D R3 Postgres journal/checkpointer and R2 driver adapter.

This is composition without cutover: R4/R5 may supply the concrete definition, governed tools,
admission guard, and finalization engine to this reusable runtime.  ``fleet_main`` intentionally
does not bind the handler yet, so R1's fail-loud new-run quarantine remains in force.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol, cast, runtime_checkable

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import text

from clue_agents.entity_research_contracts import (
    EntityAgentRole,
    EntityResearchAgentDefinition,
    EntityResearchAgentSuspension,
    EntityResearchJournalEvent,
)
from clue_agents.entity_research_runtime import (
    EntityResearchAgentJournal,
    EntityResearchAgentRuntime,
    EntityResearchCheckpointerFactory,
)
from clue_api.agent_execution_wiring import ensure_checkpoint_tables
from clue_core import serialize_value_json
from clue_db import ConnFactory, database_url, transaction
from clue_fleet.entity_research import (
    EntityResearchDriverDisposition,
    EntityResearchDriverResult,
    EntityResearchExecutionFence,
    EntityResearchJobDriver,
    EntityResearchJobRow,
)


class EntityResearchJournalConflict(RuntimeError):
    pass


def _psycopg_dsn(value: str) -> str:
    return value.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://",
        "postgresql://",
    )


@asynccontextmanager
async def postgres_entity_research_checkpointer(
    _thread_id: str,
) -> AsyncIterator[BaseCheckpointSaver[str]]:
    """Open the production LangGraph Postgres saver (its tables come from the migrations)."""

    async with AsyncPostgresSaver.from_conn_string(_psycopg_dsn(database_url())) as saver:
        await ensure_checkpoint_tables(saver)
        yield saver


class PostgresEntityResearchCheckpointers(EntityResearchCheckpointerFactory):
    def open(self, thread_id: str) -> AbstractAsyncContextManager[BaseCheckpointSaver[str], None]:
        return cast(
            AbstractAsyncContextManager[BaseCheckpointSaver[str], None],
            postgres_entity_research_checkpointer(thread_id),
        )


class DbEntityResearchAgentJournal(EntityResearchAgentJournal):
    """Append-only exact construction, model-history, and tool-causation journal."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def start(
        self,
        *,
        definition: EntityResearchAgentDefinition,
        context_sha256: str,
        resource_manifest_sha256: str,
        tool_manifest_sha256: str,
        system_prompt_sha256: str,
    ) -> None:
        context = definition.context
        authorization = context.authorization
        facet = context.facet_scope
        context_json = definition.exact_model_context()
        resource_manifest = context.resources.manifest()
        tool_manifest = definition.tool_manifest()
        values = {
            "agent_turn_id": context.agent_turn_id,
            "agent_execution_id": context.agent_execution_id,
            "job_id": authorization.job_id,
            "research_run_id": authorization.research_run_id,
            "role": context.role.value,
            "subject_type": authorization.subject_type.value,
            "target_entity_id": authorization.subject_entity_id,
            "parent_account_id": authorization.parent_account_id,
            "workspace_id": authorization.workspace_id,
            "project_id": authorization.project_id,
            "product_id": authorization.product_id,
            "project_run_id": authorization.project_run_id,
            "checkpoint_thread_id": context.effective_checkpoint_thread_id,
            "parent_agent_execution_id": (
                facet.parent_agent_execution_id if facet is not None else None
            ),
            "parent_agent_turn_id": facet.parent_agent_turn_id if facet is not None else None,
            "facet_key": facet.facet_key if facet is not None else None,
            "facet_depth": facet.depth if facet is not None else None,
            "context_json": serialize_value_json(context_json),
            "context_sha256": context_sha256,
            "resource_manifest_json": serialize_value_json(resource_manifest),
            "resource_manifest_sha256": resource_manifest_sha256,
            "tool_manifest_json": serialize_value_json(tool_manifest),
            "tool_manifest_sha256": tool_manifest_sha256,
            "system_prompt_sha256": system_prompt_sha256,
        }
        async with self._conn_factory() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_agent_turn
                        (agent_turn_id, agent_execution_id, job_id, research_run_id, role,
                         subject_type, target_entity_id, parent_account_id, workspace_id,
                         project_id, product_id, project_run_id, checkpoint_thread_id,
                         parent_agent_execution_id, parent_agent_turn_id, facet_key, facet_depth,
                         context_json, context_sha256, resource_manifest_json,
                         resource_manifest_sha256, tool_manifest_json, tool_manifest_sha256,
                         system_prompt_sha256)
                    VALUES
                        (:agent_turn_id, :agent_execution_id, :job_id, :research_run_id, :role,
                         :subject_type, :target_entity_id, :parent_account_id, :workspace_id,
                         :project_id, :product_id, :project_run_id, :checkpoint_thread_id,
                         :parent_agent_execution_id, :parent_agent_turn_id, :facet_key,
                         :facet_depth, CAST(:context_json AS jsonb), :context_sha256,
                         CAST(:resource_manifest_json AS jsonb), :resource_manifest_sha256,
                         CAST(:tool_manifest_json AS jsonb), :tool_manifest_sha256,
                         :system_prompt_sha256)
                    ON CONFLICT (agent_turn_id) DO NOTHING
                    """
                ),
                values,
            )
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT agent_execution_id, job_id, context_sha256,
                                   resource_manifest_sha256, tool_manifest_sha256,
                                   system_prompt_sha256
                            FROM entity_research_agent_turn
                            WHERE agent_turn_id=:agent_turn_id
                            """
                        ),
                        {"agent_turn_id": context.agent_turn_id},
                    )
                )
                .mappings()
                .one()
            )
        observed = (
            row["agent_execution_id"],
            row["job_id"],
            row["context_sha256"],
            row["resource_manifest_sha256"],
            row["tool_manifest_sha256"],
            row["system_prompt_sha256"],
        )
        expected = (
            context.agent_execution_id,
            authorization.job_id,
            context_sha256,
            resource_manifest_sha256,
            tool_manifest_sha256,
            system_prompt_sha256,
        )
        if observed != expected:
            raise EntityResearchJournalConflict(
                "agent turn id was replayed with different exact construction authority"
            )

    async def append(self, event: EntityResearchJournalEvent) -> str:
        async with self._conn_factory() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_agent_event
                        (event_id, agent_turn_id, agent_execution_id, event_kind, tool_call_id,
                         tool_name, tool_version, tool_input_sha256, payload_json)
                    VALUES
                        (:event_id, :agent_turn_id, :agent_execution_id, :event_kind,
                         :tool_call_id, :tool_name, :tool_version, :tool_input_sha256,
                         CAST(:payload_json AS jsonb))
                    """
                ),
                {
                    "event_id": event.event_id,
                    "agent_turn_id": event.agent_turn_id,
                    "agent_execution_id": event.agent_execution_id,
                    "event_kind": event.kind.value,
                    "tool_call_id": event.tool_call_id,
                    "tool_name": event.tool_name,
                    "tool_version": event.tool_version,
                    "tool_input_sha256": event.tool_input_sha256,
                    "payload_json": serialize_value_json(event.payload),
                },
            )
        return f"entity-agent-event:{event.event_id}"


@runtime_checkable
class EntityResearchDefinitionResolver(Protocol):
    """R4/R5 composition seam for one exact leased job's role/tools/context."""

    async def resolve(
        self,
        *,
        job: EntityResearchJobRow,
        fence: EntityResearchExecutionFence,
    ) -> EntityResearchAgentDefinition: ...


class CreateAgentEntityResearchDriver(EntityResearchJobDriver):
    """Adapt the shared R3 runtime to the R2 subject-neutral job handler."""

    def __init__(
        self,
        *,
        runtime: EntityResearchAgentRuntime,
        definitions: EntityResearchDefinitionResolver,
    ) -> None:
        self._runtime = runtime
        self._definitions = definitions

    async def run(
        self,
        job: EntityResearchJobRow,
        *,
        fence: EntityResearchExecutionFence,
        stop_requested: asyncio.Event,
        lease_lost: asyncio.Event,
    ) -> EntityResearchDriverResult:
        definition = await self._definitions.resolve(job=job, fence=fence)
        context = definition.context
        if (
            context.role is EntityAgentRole.FACET
            or context.authorization != job.authorization
            or context.current_state_sha256 != job.current_state_sha256
            or context.job_budget_cap_cents != job.budget_cap_cents
            or context.job_spent_cents != job.spent_cents
        ):
            raise EntityResearchJournalConflict(
                "resolved entity agent definition differs from the exact leased job"
            )
        outcome = await self._runtime.run(
            definition=definition,
            stop_requested=stop_requested,
            lease_lost=lease_lost,
        )
        if isinstance(outcome, EntityResearchAgentSuspension):
            return EntityResearchDriverResult(
                disposition=EntityResearchDriverDisposition.WAITING_EXTERNAL,
                wait_ref=outcome.wait_ref,
                checkpoint_ref=outcome.checkpoint_ref,
                checkpoint_sha256=outcome.checkpoint_sha256,
                current_state_sha256=outcome.current_state_sha256,
            )
        receipt = outcome.finalization_receipt
        if receipt is None:
            raise EntityResearchJournalConflict(
                "entity research driver received no accepted finalization authority"
            )
        return EntityResearchDriverResult(
            disposition=EntityResearchDriverDisposition.FINALIZED,
            finalization_receipt=receipt,
        )


__all__ = [
    "CreateAgentEntityResearchDriver",
    "DbEntityResearchAgentJournal",
    "EntityResearchDefinitionResolver",
    "EntityResearchJournalConflict",
    "PostgresEntityResearchCheckpointers",
    "postgres_entity_research_checkpointer",
]
