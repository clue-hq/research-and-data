"""M8D R9 atomic parallel admission, partial durability, and cold-resume acceptance."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from sqlalchemy import text

from clue_agents.entity_research_contracts import (
    EntityAgentRole,
    EntityResearchAgentDefinition,
    EntityResearchAgentResult,
    EntityResearchAgentSuspension,
    EntityResearchResource,
    EntityResearchResourceBundle,
    EntityResearchRuntimeContext,
    EntityResearchToolBinding,
)
from clue_agents.entity_research_runtime import (
    EntityResearchAgentFactory,
    EntityResearchAgentRuntime,
    EntityResearchExternalWait,
)
from clue_agents.entity_research_tools import EntityResearchSemanticToolInput
from clue_agents.model import ScriptedAgentChatModel
from clue_api.account_entity_research import (
    AccountResearchAuthorityError,
    AccountResearchExecutionGuard,
)
from clue_api.contact_entity_research import (
    ContactResearchAuthorityError,
    ContactResearchExecutionGuard,
)
from clue_api.entity_research_parallel import (
    DbEntityResearchToolBatchCoordinator,
    EntityResearchBatchWakeService,
    EntityResearchParallelAdmissionError,
    R9EntityResearchJobStore,
)
from clue_api.entity_research_runtime_wiring import (
    DbEntityResearchAgentJournal,
    PostgresEntityResearchCheckpointers,
)
from clue_core import EntityId, ProjectRunId
from clue_core.entity_research import ResearchJobState, ResearchRunKind, ResearchSubjectType
from clue_db import db_lifespan, transaction
from clue_fleet import (
    DbEntityResearchJobStore,
    EntityResearchExecutionFence,
    FleetTaskKind,
    LeaseGeneration,
    WorkId,
    acquire_work_lease,
    claim_next_task,
    release_work_lease,
)
from tests.agents.test_entity_research_runtime_r3 import (
    Finalizer,
    Guard,
    Models,
    _context,
    _proposal,
)
from tests.db.conftest import _db_available, run_async
from tests.fleet.entity_research_r2_helpers import run_envelope

_TTL = timedelta(seconds=60)


class _MemoryCheckpointers:
    """One process-local saver is sufficient for an admission rejection before tool dispatch."""

    def __init__(self) -> None:
        from langgraph.checkpoint.memory import InMemorySaver

        self._saver = InMemorySaver()

    def open(self, _thread_id: str) -> Any:
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def opened() -> Any:
            yield self._saver

        return opened()


async def _claim(
    job_id: UUID,
    *,
    worker_id: str,
) -> EntityResearchExecutionFence:
    async with transaction() as conn:
        task = await claim_next_task(
            conn,
            kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
            worker_id=worker_id,
            project_run_id=ProjectRunId(job_id),
        )
        assert task is not None
        lease = await acquire_work_lease(
            conn,
            work_id=WorkId(job_id),
            worker_id=worker_id,
            ttl=_TTL,
        )
        assert lease is not None
        return EntityResearchExecutionFence(
            task_id=task.task_id,
            worker_id=worker_id,
            lease_generation=lease.generation,
            task_attempt=1,
        )


async def _release(job_id: UUID, fence: EntityResearchExecutionFence) -> None:
    async with transaction() as conn:
        await release_work_lease(
            conn,
            work_id=WorkId(job_id),
            worker_id=fence.worker_id,
            generation=LeaseGeneration(fence.lease_generation),
        )


def _profile_authorized_envelope() -> tuple[Any, str, str]:
    envelope = run_envelope(ResearchRunKind.ACCOUNT_RESEARCH)
    original = envelope.jobs[0]
    profile_body = "role: account-research\nframework: langchain-create-agent\n"
    profile_sha = hashlib.sha256(profile_body.encode()).hexdigest()
    authorization = original.authorization.model_copy(update={"agent_profile_sha256": profile_sha})
    return (
        envelope.model_copy(
            update={"jobs": (original.model_copy(update={"authorization": authorization}),)}
        ),
        profile_body,
        profile_sha,
    )


def _runtime_context(
    *,
    job: Any,
    profile_body: str,
    profile_sha: str,
) -> EntityResearchRuntimeContext:
    base = _context(ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT)
    profile = EntityResearchResource(
        kind="profile",
        ref=job.authorization.agent_profile_ref,
        version="v1",
        sha256=profile_sha,
        body=profile_body,
    )
    return EntityResearchRuntimeContext(
        agent_execution_id=job.authorization.attempt_id,
        agent_turn_id=uuid4(),
        role=EntityAgentRole.ACCOUNT,
        authorization=job.authorization,
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


def _semantic_tool(
    name: str,
    callback: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
) -> StructuredTool:
    async def invoke(**values: Any) -> dict[str, Any]:
        return await callback(values)

    return StructuredTool.from_function(
        coroutine=invoke,
        name=name,
        description=f"R9 governed provider boundary for {name}",
        args_schema=EntityResearchSemanticToolInput,
    )


def _r9_definition(
    context: EntityResearchRuntimeContext,
    *,
    exa: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    sumble: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    reservation_cents: Decimal = Decimal("1"),
) -> EntityResearchAgentDefinition:
    async def unused(_values: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("the scripted R9 agent selected an unexpected tool")

    callbacks = {
        "research_account_deep": exa,
        "enrich_account": sumble,
    }
    tools: list[EntityResearchToolBinding] = []
    for name in context.tool_surface.tool_names:
        callback = callbacks.get(name, unused)
        metadata: dict[str, Any] = {}
        if name in callbacks:
            family = "exa" if name == "research_account_deep" else "sumble"
            metadata = {
                "provider_family": family,
                "budget_reservation_cents": reservation_cents,
                "provider_rate_limit_ref": f"provider-rate:{family}:r9-test",
                "provider_concurrency_limit": 2,
            }
        tools.append(
            EntityResearchToolBinding(
                tool=_semantic_tool(name, callback),
                version=1,
                **metadata,
            )
        )
    return EntityResearchAgentDefinition(
        context=context,
        model_policy=_account_model_policy(),
        tools=tuple(tools),
        task_instruction="Run only the exact independent research calls and finalize honestly.",
    )


def _account_model_policy() -> Any:
    from clue_agents.contracts import ModelPolicy

    return ModelPolicy(
        model_id="r9-scripted-model",
        timeout_s=5,
        max_retries=0,
        max_output_tokens=4096,
        temperature=0,
    )


def _provider_result(*, result_ref: str, cost_cents: str) -> dict[str, Any]:
    return {
        "tool_request_ref": f"tool-request:{result_ref}",
        "results": [{"result_ref": result_ref, "cost_cents": cost_cents}],
        "current_state_sha256": "e" * 64,
        "yield_count": 1,
    }


def _parallel_calls() -> list[dict[str, Any]]:
    return [
        {
            "name": "research_account_deep",
            "args": {
                "field_keys": ["account.operational_pain"],
                "source_keys": ["exa_deep"],
                "questions": ["What creates administrative friction?"],
            },
            "id": "r9-exa",
        },
        {
            "name": "enrich_account",
            "args": {
                "field_keys": ["account.hiring_velocity_eng"],
                "source_keys": ["sumble_jobs"],
                "questions": ["Which operational roles are being hired?"],
            },
            "id": "r9-sumble",
        },
    ]


def test_parallel_batch_is_rejected_atomically_before_any_handler_when_budget_is_insufficient() -> (
    None
):
    if not _db_available():
        pytest.skip("CLUE_DATABASE_URL unset or database unreachable")

    async def scenario() -> None:
        envelope, profile_body, profile_sha = _profile_authorized_envelope()
        calls = 0

        async def forbidden(_values: dict[str, Any]) -> dict[str, Any]:
            nonlocal calls
            calls += 1
            raise AssertionError("atomic rejection must happen before handler dispatch")

        async with db_lifespan():
            store = R9EntityResearchJobStore()
            await store.launch(envelope)
            job_id = envelope.jobs[0].authorization.job_id
            fence = await _claim(job_id, worker_id="r9-budget-worker")
            begun = await store.begin(job_id, fence=fence)
            assert begun.admitted
            job = begun.job
            context = _runtime_context(job=job, profile_body=profile_body, profile_sha=profile_sha)
            definition = _r9_definition(
                context,
                exa=forbidden,
                sumble=forbidden,
                reservation_cents=Decimal("2.50"),
            )
            model = ScriptedAgentChatModel(
                responses=(AIMessage(content="", tool_calls=_parallel_calls()),)
            )
            journal = DbEntityResearchAgentJournal()
            runtime = EntityResearchAgentRuntime(
                factory=EntityResearchAgentFactory(
                    models=Models(model),
                    journal=journal,
                    guard=Guard(),
                    batches=DbEntityResearchToolBatchCoordinator(),
                ),
                checkpointers=_MemoryCheckpointers(),
                journal=journal,
                finalizer=Finalizer(),
            )
            with pytest.raises(
                EntityResearchParallelAdmissionError,
                match="atomic tool batch exceeds the exact job budget",
            ):
                await runtime.run(definition=definition)
            assert calls == 0
            async with transaction() as conn:
                counts = (
                    (
                        await conn.execute(
                            text(
                                "SELECT "
                                "(SELECT count(*) FROM entity_research_tool_batch "
                                " WHERE agent_turn_id=:turn_id) AS batches, "
                                "(SELECT count(*) FROM entity_research_budget_reservation "
                                " WHERE job_id=:job_id) AS reservations"
                            ),
                            {"turn_id": context.agent_turn_id, "job_id": job.job_id},
                        )
                    )
                    .mappings()
                    .one()
                )
            assert counts == {"batches": 0, "reservations": 0}
            await _release(job_id, fence)

    run_async(scenario())


def test_exa_and_sumble_run_concurrently_then_wait_resume_joins_partial_results_exactly_once() -> (
    None
):
    if not _db_available():
        pytest.skip("CLUE_DATABASE_URL unset or database unreachable")

    async def scenario() -> None:
        envelope, profile_body, profile_sha = _profile_authorized_envelope()
        job_id = envelope.jobs[0].authorization.job_id
        starts: list[str] = []
        both_started = asyncio.Event()
        sumble_ready = False
        exa_dispatches = 0
        sumble_submits = 0
        sumble_polls = 0

        async def meet(name: str) -> None:
            starts.append(name)
            if len(starts) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=2)

        async def exa(_values: dict[str, Any]) -> dict[str, Any]:
            nonlocal exa_dispatches
            exa_dispatches += 1
            await meet("exa")
            return _provider_result(result_ref="exa-result:one", cost_cents="1")

        async def sumble(_values: dict[str, Any]) -> dict[str, Any]:
            nonlocal sumble_submits, sumble_polls
            if not sumble_ready:
                sumble_submits += 1
                await meet("sumble")
                raise EntityResearchExternalWait(
                    wait_ref="provider-operation:sumble:r9-one",
                    current_state_sha256="e" * 64,
                )
            sumble_polls += 1
            return _provider_result(result_ref="sumble-result:one", cost_cents="1")

        async with db_lifespan():
            store = R9EntityResearchJobStore()
            await store.launch(envelope)
            first_fence = await _claim(job_id, worker_id="r9-worker-a")
            first_begin = await store.begin(job_id, fence=first_fence)
            assert first_begin.admitted
            first_context = _runtime_context(
                job=first_begin.job,
                profile_body=profile_body,
                profile_sha=profile_sha,
            )
            first_proposal = _proposal(first_context)
            model = ScriptedAgentChatModel(
                responses=(
                    AIMessage(content="", tool_calls=_parallel_calls()),
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "ResearchFinalizationProposal",
                                "args": first_proposal.model_dump(mode="json"),
                                "id": "r9-final",
                            }
                        ],
                    ),
                )
            )
            journal = DbEntityResearchAgentJournal()
            first_runtime = EntityResearchAgentRuntime(
                factory=EntityResearchAgentFactory(
                    models=Models(model),
                    journal=journal,
                    guard=Guard(),
                    batches=DbEntityResearchToolBatchCoordinator(),
                ),
                checkpointers=PostgresEntityResearchCheckpointers(),
                journal=journal,
                finalizer=Finalizer(),
            )
            first = await first_runtime.run(
                definition=_r9_definition(first_context, exa=exa, sumble=sumble)
            )
            assert isinstance(first, EntityResearchAgentSuspension)
            assert first.wait_ref.startswith("entity-research-batch-wait:")
            assert starts == ["exa", "sumble"] or starts == ["sumble", "exa"]
            assert (exa_dispatches, sumble_submits, sumble_polls) == (1, 1, 0)

            sumble_ready = True
            wake = EntityResearchBatchWakeService()
            # A provider callback can win the short race before the R2 job wait is committed.
            # Its member readiness remains durable; the R9 job-store composition reconciles it
            # immediately after persisting the composite wait.
            assert (
                await wake.notify_member_ready(
                    "provider-operation:sumble:r9-one",
                    actor="provider-callback:sumble",
                )
                == 0
            )
            waiting = await store.wait_external(
                job_id,
                fence=first_fence,
                wait_ref=first.wait_ref,
                checkpoint_ref=first.checkpoint_ref,
                checkpoint_sha256=first.checkpoint_sha256,
                current_state_sha256=first.current_state_sha256,
            )
            assert waiting.state is ResearchJobState.QUEUED
            await _release(job_id, first_fence)

            # Duplicate provider notifications cannot offer another worker task.
            assert (
                await wake.notify_member_ready(
                    "provider-operation:sumble:r9-one",
                    actor="provider-callback:sumble",
                )
                == 0
            )
            woken = await store.get_job(job_id)
            assert woken is not None and woken.state is ResearchJobState.QUEUED

            second_fence = await _claim(job_id, worker_id="r9-worker-b")
            second_begin = await store.begin(job_id, fence=second_fence)
            assert second_begin.admitted
            second_context = _runtime_context(
                job=second_begin.job,
                profile_body=profile_body,
                profile_sha=profile_sha,
            )
            assert second_context.agent_turn_id != first_context.agent_turn_id

            # New runtime, checkpointer connection, coordinator, and middleware: the saved graph
            # resumes at its tool node. Exa is joined from its durable settled result while the
            # Sumble operation reuses the retained wait reservation and is only polled.
            second_finalizer = Finalizer()
            second_runtime = EntityResearchAgentRuntime(
                factory=EntityResearchAgentFactory(
                    models=Models(model),
                    journal=journal,
                    guard=Guard(),
                    batches=DbEntityResearchToolBatchCoordinator(),
                ),
                checkpointers=PostgresEntityResearchCheckpointers(),
                journal=journal,
                finalizer=second_finalizer,
            )
            second = await second_runtime.run(
                definition=_r9_definition(second_context, exa=exa, sumble=sumble)
            )
            assert isinstance(second, EntityResearchAgentResult)
            assert second.finalization_receipt is not None
            assert (exa_dispatches, sumble_submits, sumble_polls) == (1, 1, 1)
            terminal = await store.finalize(
                job_id,
                fence=second_fence,
                receipt=second.finalization_receipt,
            )
            assert terminal.state is ResearchJobState.TERMINAL
            await _release(job_id, second_fence)

            async with transaction() as conn:
                ledger = (
                    (
                        await conn.execute(
                            text(
                                """
                                SELECT
                                  (SELECT count(*) FROM entity_research_tool_batch
                                   WHERE job_id=:job_id) AS batches,
                                  (SELECT count(*) FROM entity_research_tool_batch_member member
                                   JOIN entity_research_tool_batch batch USING (batch_id)
                                   WHERE batch.job_id=:job_id) AS members,
                                  (SELECT count(*) FROM entity_research_budget_reservation
                                   WHERE job_id=:job_id) AS reservations,
                                  (SELECT count(*) FROM entity_research_provider_permit
                                   WHERE job_id=:job_id) AS permits,
                                  (SELECT count(*) FROM entity_research_tool_batch_event event
                                   JOIN entity_research_tool_batch batch USING (batch_id)
                                   WHERE batch.job_id=:job_id AND event.event_kind='completed')
                                      AS completed_events,
                                  (SELECT count(*) FROM entity_research_tool_batch_event event
                                   JOIN entity_research_tool_batch batch USING (batch_id)
                                   WHERE batch.job_id=:job_id AND
                                         event.event_kind='waiting_external') AS wait_events,
                                  (SELECT count(*) FROM entity_research_budget_reservation_release
                                   release JOIN entity_research_budget_reservation reservation
                                     USING (reservation_id)
                                   WHERE reservation.job_id=:job_id) AS reservation_releases,
                                  (SELECT COALESCE(sum(release.settled_cost_cents), 0)
                                   FROM entity_research_budget_reservation_release release
                                   JOIN entity_research_budget_reservation reservation
                                     USING (reservation_id)
                                   WHERE reservation.job_id=:job_id) AS settled_cost
                                """
                            ),
                            {"job_id": job_id},
                        )
                    )
                    .mappings()
                    .one()
                )
                dispositions = tuple(
                    (
                        await conn.execute(
                            text(
                                "SELECT event.disposition FROM entity_research_tool_batch_event "
                                "event JOIN entity_research_tool_batch batch USING (batch_id) "
                                "WHERE batch.job_id=:job_id AND event.event_kind='completed' "
                                "ORDER BY event.event_seq"
                            ),
                            {"job_id": job_id},
                        )
                    )
                    .scalars()
                    .all()
                )
            assert ledger == {
                "batches": 2,
                "members": 4,
                "reservations": 2,
                "permits": 3,
                "completed_events": 3,
                "wait_events": 1,
                "reservation_releases": 2,
                "settled_cost": Decimal("2.000000"),
            }
            assert dispositions == ("settled", "joined_settled_result", "settled")

    run_async(scenario())


def test_crash_reuses_admission_without_stale_internal_read_replay() -> None:
    if not _db_available():
        pytest.skip("CLUE_DATABASE_URL unset or database unreachable")

    from clue_agents.entity_research_contracts import EntityResearchToolCall, canonical_sha256

    async def scenario() -> None:
        envelope, profile_body, profile_sha = _profile_authorized_envelope()
        async with db_lifespan():
            store = DbEntityResearchJobStore()
            await store.launch(envelope)
            job_id = envelope.jobs[0].authorization.job_id
            fence = await _claim(job_id, worker_id="r9-crash-worker")
            begun = await store.begin(job_id, fence=fence)
            assert begun.admitted
            job = begun.job
            journal = DbEntityResearchAgentJournal()

            async def unused(_values: dict[str, Any]) -> dict[str, Any]:
                raise AssertionError("direct coordinator proof does not invoke handlers")

            async def start_turn(context: EntityResearchRuntimeContext) -> None:
                definition = _r9_definition(context, exa=unused, sumble=unused)
                await journal.start(
                    definition=definition,
                    context_sha256=canonical_sha256(definition.exact_model_context()),
                    resource_manifest_sha256=canonical_sha256(context.resources.manifest()),
                    tool_manifest_sha256=canonical_sha256(definition.tool_manifest()),
                    system_prompt_sha256="f" * 64,
                )

            def external(call_id: str) -> EntityResearchToolCall:
                arguments: dict[str, Any] = {
                    "field_keys": ["account.operational_pain"],
                    "source_keys": ["exa_deep"],
                    "questions": ["What creates administrative friction?"],
                }
                return EntityResearchToolCall(
                    tool_call_id=call_id,
                    tool_name="research_account_deep",
                    tool_version=1,
                    tool_input_sha256=canonical_sha256(arguments),
                    arguments=arguments,
                    provider_family="exa",
                    budget_reservation_cents=Decimal("1"),
                    provider_rate_limit_ref="provider-rate:exa:r9-crash",
                    provider_concurrency_limit=1,
                )

            first_context = _runtime_context(
                job=job,
                profile_body=profile_body,
                profile_sha=profile_sha,
            )
            await start_turn(first_context)
            first_call = external("crashed-call")
            await DbEntityResearchToolBatchCoordinator().admit(
                context=first_context,
                calls=(first_call,),
            )

            blocked_context = first_context.model_copy(update={"agent_turn_id": uuid4()})
            await start_turn(blocked_context)
            blocked_arguments = {
                **first_call.arguments,
                "questions": ["A different independent request must wait for provider capacity."],
            }
            blocked_call = first_call.model_copy(
                update={
                    "tool_call_id": "rate-limited-call",
                    "tool_input_sha256": canonical_sha256(blocked_arguments),
                    "arguments": blocked_arguments,
                }
            )
            with pytest.raises(
                EntityResearchParallelAdmissionError,
                match="provider concurrency limit is exhausted",
            ):
                await DbEntityResearchToolBatchCoordinator().admit(
                    context=blocked_context,
                    calls=(blocked_call,),
                )

            # Provider settlement can fold actual spend before the coordinator durably records
            # its terminal tool event. At a tight cap, the exact recovery must not count that
            # already-admitted operation as new exposure and strand the job.
            async with transaction() as conn:
                await conn.execute(
                    text("UPDATE entity_research_job SET spent_cents=3.50 WHERE job_id=:job_id"),
                    {"job_id": job.job_id},
                )
                await conn.execute(
                    text(
                        "UPDATE entity_research_run SET spent_cents=9.50 "
                        "WHERE research_run_id=:run_id"
                    ),
                    {"run_id": job.authorization.research_run_id},
                )

            # Simulate a process disappearing after admission but before a handler event. A fresh
            # turn reuses the exact outstanding reservation and permit instead of double-admitting.
            second_context = first_context.model_copy(update={"agent_turn_id": uuid4()})
            await start_turn(second_context)
            second_call = external("resumed-call")
            fresh = DbEntityResearchToolBatchCoordinator()
            await fresh.admit(context=second_context, calls=(second_call,))
            duplicated_contact_id = uuid4()
            settled_result = _provider_result(
                result_ref="exa-result:crash-resume",
                cost_cents="1",
            )
            settled_result["results"][0]["discovered_subjects"] = [
                {
                    "subject_type": "contact",
                    "target_entity_id": str(duplicated_contact_id),
                }
            ]
            await fresh.completed(
                context=second_context,
                call=second_call,
                result=settled_result,
            )

            # Engine-state reads are intentionally not joined across turns: identical arguments
            # can observe a different current claim/coverage state after provider materialization.
            internal_arguments: dict[str, Any] = {}
            first_read = EntityResearchToolCall(
                tool_call_id="read-before",
                tool_name="read_account_research_state",
                tool_version=1,
                tool_input_sha256=canonical_sha256(internal_arguments),
                arguments=internal_arguments,
            )
            third_context = first_context.model_copy(update={"agent_turn_id": uuid4()})
            await start_turn(third_context)
            await fresh.admit(context=third_context, calls=(first_read,))
            await fresh.failed(
                context=third_context,
                call=first_read,
                error=ValueError("first retained failure"),
            )
            # A checkpoint retry of the same admitted member may observe a different failure
            # before a code/config repair lets it complete. The first immutable failure marker
            # must not mask that retry as a parallel-ledger replay violation.
            await fresh.failed(
                context=third_context,
                call=first_read,
                error=RuntimeError("different retry failure"),
            )
            await fresh.completed(
                context=third_context,
                call=first_read,
                result={"state": "before"},
            )
            assert (await fresh.replay(context=third_context, call=first_read)).result == {
                "state": "before"
            }
            fourth_context = first_context.model_copy(update={"agent_turn_id": uuid4()})
            await start_turn(fourth_context)
            second_read = first_read.model_copy(update={"tool_call_id": "read-after"})
            await fresh.admit(context=fourth_context, calls=(second_read,))
            assert not (await fresh.replay(context=fourth_context, call=second_read)).found

            async with transaction() as conn:
                from clue_research.compliance.dsar import (
                    _erase_entity_research_runtime_payloads,
                )

                subject_count = int(
                    (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM "
                                "entity_research_tool_batch_result_subject WHERE "
                                "workspace_id=:workspace_id AND subject_type='contact' AND "
                                "target_entity_id=:contact_id"
                            ),
                            {
                                "workspace_id": job.workspace_id,
                                "contact_id": duplicated_contact_id,
                            },
                        )
                    ).scalar_one()
                )
                assert subject_count == 1
                await _erase_entity_research_runtime_payloads(
                    conn,
                    contact_entity_id=EntityId(duplicated_contact_id),
                    workspace_id=job.workspace_id,
                )
                erased = (
                    (
                        await conn.execute(
                            text(
                                "SELECT event.result_json, event.result_erased_at FROM "
                                "entity_research_tool_batch_event event JOIN "
                                "entity_research_tool_batch_result_subject subject "
                                "USING (event_id) WHERE subject.workspace_id=:workspace_id AND "
                                "subject.subject_type='contact' AND "
                                "subject.target_entity_id=:contact_id"
                            ),
                            {
                                "workspace_id": job.workspace_id,
                                "contact_id": duplicated_contact_id,
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
                assert erased["result_json"] == {"erased": True}
                assert erased["result_erased_at"] is not None
                ledger = (
                    (
                        await conn.execute(
                            text(
                                """
                                SELECT
                                  (SELECT count(*) FROM entity_research_budget_reservation
                                   WHERE job_id=:job_id) AS reservations,
                                  (SELECT count(*) FROM entity_research_provider_permit
                                   WHERE job_id=:job_id) AS permits,
                                  (SELECT count(*) FROM entity_research_budget_reservation_release
                                   release JOIN entity_research_budget_reservation reservation
                                     USING (reservation_id)
                                   WHERE reservation.job_id=:job_id) AS reservation_releases,
                                  (SELECT count(*) FROM entity_research_provider_permit_release
                                   release JOIN entity_research_provider_permit permit
                                     USING (permit_id)
                                   WHERE permit.job_id=:job_id) AS permit_releases
                                """
                            ),
                            {"job_id": job.job_id},
                        )
                    )
                    .mappings()
                    .one()
                )
            assert ledger == {
                "reservations": 1,
                "permits": 1,
                "reservation_releases": 1,
                "permit_releases": 1,
            }
            await _release(job_id, fence)

    run_async(scenario())


def test_dependent_follow_up_and_overlapping_field_work_cannot_enter_one_parallel_batch() -> None:
    context = _context(ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT)
    coordinator = DbEntityResearchToolBatchCoordinator()

    from clue_agents.entity_research_contracts import EntityResearchToolCall, canonical_sha256

    def call(call_id: str, *, parent: str | None = None) -> EntityResearchToolCall:
        arguments: dict[str, Any] = {
            "field_keys": ["account.operational_pain"],
            "source_keys": ["exa_deep"],
            "questions": ["What creates friction?"],
        }
        if parent is not None:
            arguments["parent_operation_ref"] = parent
        return EntityResearchToolCall(
            tool_call_id=call_id,
            tool_name="research_account_deep",
            tool_version=1,
            tool_input_sha256=canonical_sha256(arguments),
            arguments=arguments,
            provider_family="exa",
            budget_reservation_cents=Decimal("1"),
            provider_rate_limit_ref="provider-rate:exa:r9-test",
            provider_concurrency_limit=2,
        )

    async def dependency() -> None:
        with pytest.raises(
            EntityResearchParallelAdmissionError,
            match="additive follow-up is dependent",
        ):
            await coordinator.admit(
                context=context,
                calls=(call("initial"), call("follow-up", parent="operation:initial")),
            )

    async def overlap() -> None:
        with pytest.raises(
            EntityResearchParallelAdmissionError,
            match="parallel field overlap",
        ):
            await coordinator.admit(
                context=context,
                calls=(call("source-a"), call("source-b")),
            )

    run_async(dependency())
    run_async(overlap())


def test_contact_parallel_guard_allows_only_distinct_depth_one_facets() -> None:
    from clue_agents.entity_research_contracts import EntityResearchToolCall, canonical_sha256

    context = _context(ResearchSubjectType.CONTACT, EntityAgentRole.CONTACT)
    guard = ContactResearchExecutionGuard(conn_factory=None)  # type: ignore[arg-type]

    def facet(call_id: str, facet_key: str) -> EntityResearchToolCall:
        arguments: dict[str, Any] = {"facet_key": facet_key}
        return EntityResearchToolCall(
            tool_call_id=call_id,
            tool_name="delegate_contact_facet",
            tool_version=1,
            tool_input_sha256=canonical_sha256(arguments),
            arguments=arguments,
        )

    async def scenario() -> None:
        await guard.authorize_parallel(
            context=context,
            calls=(facet("publications", "publications"), facet("events", "public_appearances")),
        )
        with pytest.raises(ContactResearchAuthorityError, match="distinct selected facets"):
            await guard.authorize_parallel(
                context=context,
                calls=(facet("duplicate-a", "publications"), facet("duplicate-b", "publications")),
            )

    run_async(scenario())


def test_account_parallel_guard_allows_disjoint_structured_sources() -> None:
    from clue_agents.entity_research_contracts import EntityResearchToolCall, canonical_sha256

    context = _context(ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT)
    guard = AccountResearchExecutionGuard(conn_factory=None)  # type: ignore[arg-type]

    def enrich(call_id: str, source_key: str, field_key: str) -> EntityResearchToolCall:
        arguments: dict[str, Any] = {
            "field_keys": [field_key],
            "source_keys": [source_key],
            "questions": [],
        }
        return EntityResearchToolCall(
            tool_call_id=call_id,
            tool_name="enrich_account",
            tool_version=1,
            tool_input_sha256=canonical_sha256(arguments),
            arguments=arguments,
        )

    async def scenario() -> None:
        disjoint = (
            enrich("tech", "sumble_tech_stack", "core.primary_tech_stack"),
            enrich("jobs", "sumble_jobs", "account.hiring_velocity_eng"),
        )
        await guard.authorize_parallel(context=context, calls=disjoint)
        DbEntityResearchToolBatchCoordinator._validate_batch(context, disjoint)
        with pytest.raises(
            AccountResearchAuthorityError,
            match="disjoint structured sources",
        ):
            await guard.authorize_parallel(
                context=context,
                calls=(
                    enrich("jobs-a", "sumble_jobs", "account.hiring_velocity_eng"),
                    enrich("jobs-b", "sumble_jobs", "core.employee_count"),
                ),
            )
        with pytest.raises(
            EntityResearchParallelAdmissionError,
            match="not independently partitioned",
        ):
            DbEntityResearchToolBatchCoordinator._validate_batch(
                context,
                (
                    enrich("jobs-a", "sumble_jobs", "account.hiring_velocity_eng"),
                    enrich("jobs-b", "sumble_jobs", "core.employee_count"),
                ),
            )

    run_async(scenario())


def test_two_read_only_calls_in_one_round_are_not_duplicate_provider_work() -> None:
    """Live regression: a round holding two persisted-result reads suspended the whole job.

    Both guards refused it — the account guard as "duplicate account provider work", and R9's own
    batch validation as work "not independently partitioned", because a read tool carries no source
    keys to partition. A read buys nothing, reserves nothing and dispatches nothing, so a repeated
    one is reading, never duplicated provider work.
    """

    from clue_agents.entity_research_contracts import EntityResearchToolCall, canonical_sha256

    def read(call_id: str, ref: str, *, tool_name: str = "read_research_result") -> Any:
        arguments: dict[str, Any] = {"result_ref": ref}
        return EntityResearchToolCall(
            tool_call_id=call_id,
            tool_name=tool_name,
            tool_version=1,
            tool_input_sha256=canonical_sha256(arguments),
            arguments=arguments,
        )

    async def scenario() -> None:
        account_context = _context(ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT)
        account_calls = (read("read-a", "research-result:a"), read("read-b", "research-result:b"))
        await AccountResearchExecutionGuard(conn_factory=None).authorize_parallel(  # type: ignore[arg-type]
            context=account_context, calls=account_calls
        )
        DbEntityResearchToolBatchCoordinator._validate_batch(account_context, account_calls)

        contact_context = _context(ResearchSubjectType.CONTACT, EntityAgentRole.CONTACT)
        contact_calls = (
            read("c-read-a", "research-result:a"),
            read("c-read-b", "research-result:b", tool_name="read_evidence"),
            read("c-read-c", "research-result:c", tool_name="read_evidence"),
        )
        await ContactResearchExecutionGuard(conn_factory=None).authorize_parallel(  # type: ignore[arg-type]
            context=contact_context, calls=contact_calls
        )

    run_async(scenario())
