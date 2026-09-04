"""M8D R3 live-Postgres journal, checkpoint, and cold-replay acceptance."""

from __future__ import annotations

import asyncio
import hashlib
from decimal import Decimal
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from clue_agents.entity_research_contracts import (
    EntityAgentRole,
    EntityResearchAgentDefinition,
    EntityResearchAgentResult,
    EntityResearchResource,
    EntityResearchResourceBundle,
    EntityResearchRuntimeContext,
)
from clue_agents.entity_research_runtime import (
    EntityResearchAgentFactory,
    EntityResearchAgentRuntime,
)
from clue_agents.model import ScriptedAgentChatModel
from clue_api.entity_research_runtime_wiring import (
    CreateAgentEntityResearchDriver,
    DbEntityResearchAgentJournal,
    EntityResearchJournalConflict,
    PostgresEntityResearchCheckpointers,
)
from clue_core.entity_research import ResearchRunKind, ResearchSubjectType
from clue_db import db_lifespan, transaction
from clue_fleet import (
    DbEntityResearchJobStore,
    EntityResearchDriverDisposition,
    EntityResearchExecutionFence,
    EntityResearchJobRow,
)
from tests.agents.test_entity_research_runtime_r3 import (
    Finalizer,
    Guard,
    Models,
    _context,
    _definition,
    _proposal,
)
from tests.db.conftest import _db_available, run_async
from tests.fleet.entity_research_r2_helpers import run_envelope


class DefinitionResolver:
    def __init__(self, definition: EntityResearchAgentDefinition) -> None:
        self.definition = definition

    async def resolve(
        self,
        *,
        job: EntityResearchJobRow,
        fence: EntityResearchExecutionFence,
    ) -> EntityResearchAgentDefinition:
        del job, fence
        return self.definition


def test_postgres_journal_checkpoint_and_fresh_runtime_replay() -> None:
    if not _db_available():
        pytest.skip("CLUE_DATABASE_URL unset or database unreachable")

    async def run() -> None:
        envelope = run_envelope(ResearchRunKind.ACCOUNT_RESEARCH)
        original_job = envelope.jobs[0]
        profile_body = "role: account-research\nframework: langchain-create-agent\n"
        profile_sha256 = hashlib.sha256(profile_body.encode()).hexdigest()
        authorization = original_job.authorization.model_copy(
            update={"agent_profile_sha256": profile_sha256}
        )
        envelope = envelope.model_copy(
            update={"jobs": (original_job.model_copy(update={"authorization": authorization}),)}
        )

        async with db_lifespan():
            store = DbEntityResearchJobStore()
            await store.launch(envelope)
            job = await store.get_job(authorization.job_id)
            assert job is not None

            base = _context(ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT)
            profile = EntityResearchResource(
                kind="profile",
                ref=authorization.agent_profile_ref,
                version="v1",
                sha256=profile_sha256,
                body=profile_body,
            )
            context = EntityResearchRuntimeContext(
                agent_execution_id=authorization.attempt_id,
                agent_turn_id=base.agent_turn_id,
                role=EntityAgentRole.ACCOUNT,
                authorization=authorization,
                resources=EntityResearchResourceBundle(
                    profile=profile,
                    prompt=base.resources.prompt,
                    skills=base.resources.skills,
                ),
                tool_surface=base.tool_surface,
                stop_policy=base.stop_policy,
                facet_contract=base.facet_contract,
                current_state_sha256=job.current_state_sha256,
                job_budget_cap_cents=job.budget_cap_cents,
                job_spent_cents=job.spent_cents,
                run_budget_remaining_cents=Decimal("10"),
            )
            proposal = _proposal(context)
            model = ScriptedAgentChatModel(
                responses=(
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "ResearchFinalizationProposal",
                                "args": proposal.model_dump(mode="json"),
                                "id": "typed-final-db",
                            }
                        ],
                    ),
                )
            )
            journal = DbEntityResearchAgentJournal()
            guard = Guard()
            finalizer = Finalizer()
            runtime = EntityResearchAgentRuntime(
                factory=EntityResearchAgentFactory(
                    models=Models(model),
                    journal=journal,
                    guard=guard,
                ),
                checkpointers=PostgresEntityResearchCheckpointers(),
                journal=journal,
                finalizer=finalizer,
            )
            definition = _definition(context)
            first = await runtime.run(definition=definition)
            assert isinstance(first, EntityResearchAgentResult)
            assert first.finalization_receipt is not None

            # A fresh runtime and saver rehydrate the terminal structured response from Postgres.
            # Driving that runtime through the R2 adapter proves the shared fleet seam too. The
            # scripted model has no second response, so any replayed model call would fail.
            replay = EntityResearchAgentRuntime(
                factory=EntityResearchAgentFactory(
                    models=Models(model),
                    journal=journal,
                    guard=guard,
                ),
                checkpointers=PostgresEntityResearchCheckpointers(),
                journal=journal,
                finalizer=finalizer,
            )
            driver = CreateAgentEntityResearchDriver(
                runtime=replay,
                definitions=DefinitionResolver(definition),
            )
            second = await driver.run(
                job,
                fence=EntityResearchExecutionFence(
                    task_id=uuid4(),
                    worker_id="r3-db-test",
                    lease_generation=1,
                    task_attempt=1,
                ),
                stop_requested=asyncio.Event(),
                lease_lost=asyncio.Event(),
            )
            assert second.disposition is EntityResearchDriverDisposition.FINALIZED
            assert second.finalization_receipt is not None
            assert second.finalization_receipt.proposal == first.proposal

            # The same turn cannot be reinterpreted under a different task even when its
            # resource/tool pins are unchanged. Exact construction conflict happens before the
            # exhausted scripted model could be called again.
            with pytest.raises(EntityResearchJournalConflict, match="different exact"):
                await replay.run(
                    definition=definition.model_copy(
                        update={"task_instruction": "Research a widened task instead."}
                    )
                )

            async with transaction() as conn:
                turn = (
                    (
                        await conn.execute(
                            text(
                                """
                                SELECT role, subject_type, target_entity_id, context_sha256,
                                       resource_manifest_sha256, tool_manifest_sha256,
                                       system_prompt_sha256
                                FROM entity_research_agent_turn
                                WHERE agent_turn_id=:turn_id
                                """
                            ),
                            {"turn_id": context.agent_turn_id},
                        )
                    )
                    .mappings()
                    .one()
                )
                events = (
                    (
                        await conn.execute(
                            text(
                                """
                                SELECT event_kind FROM entity_research_agent_event
                                WHERE agent_turn_id=:turn_id ORDER BY event_seq
                                """
                            ),
                            {"turn_id": context.agent_turn_id},
                        )
                    )
                    .scalars()
                    .all()
                )
                checkpoint_count = int(
                    (
                        await conn.execute(
                            text(
                                """
                                SELECT count(*) FROM checkpoints
                                WHERE thread_id=:thread_id
                                """
                            ),
                            {"thread_id": context.effective_checkpoint_thread_id},
                        )
                    ).scalar_one()
                )
            assert turn["role"] == "account"
            assert turn["subject_type"] == "account"
            assert turn["target_entity_id"] == authorization.subject_entity_id
            assert all(len(str(turn[key])) == 64 for key in turn if key.endswith("sha256"))
            assert events.count("model_started") == 1
            assert events.count("model_completed") == 1
            assert events.count("finalization_accepted") == 2
            assert checkpoint_count >= 1

            with pytest.raises(DBAPIError, match="append-only"):
                async with transaction() as conn:
                    await conn.execute(
                        text(
                            """
                            UPDATE entity_research_agent_turn SET role='contact'
                            WHERE agent_turn_id=:turn_id
                            """
                        ),
                        {"turn_id": context.agent_turn_id},
                    )

    run_async(run())
