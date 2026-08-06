"""R8 bounded depth-one contact facet agents on the shared create_agent runtime."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import text

from clue_agents.contact_entity_research import ContactFacetProjection, DelegateContactFacetInput
from clue_agents.contracts import ModelPolicy
from clue_agents.entity_research_contracts import (
    EntityAgentRole,
    EntityFacetScope,
    EntityResearchAgentDefinition,
    EntityResearchAgentSuspension,
    EntityResearchRuntimeContext,
    EntityResearchStopPolicy,
    canonical_sha256,
)
from clue_agents.entity_research_runtime import (
    ActiveEntityResearchToolExecution,
    EntityResearchAgentRuntime,
    EntityResearchExternalWait,
)
from clue_api.contact_entity_research import (
    ContactResearchAuthorityError,
    ContactResearchStateStore,
)
from clue_api.entity_research_tools import (
    GovernedEntityResearchToolFactory,
    ProviderActionBinding,
)
from clue_core import serialize_value_json
from clue_core.entity_research import (
    FacetDelegationContract,
    ResearchSubjectType,
)
from clue_db import ConnFactory, transaction

_TURN_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r8:contact-facet-turn")


class CreateAgentContactFacetDelegate:
    """Construct one or two non-recursive facet children through the shared R3 runtime."""

    def __init__(
        self,
        *,
        runtime: EntityResearchAgentRuntime,
        tools: GovernedEntityResearchToolFactory,
        provider_actions: Mapping[str, ProviderActionBinding],
        state: ContactResearchStateStore,
        model_policy: ModelPolicy,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        if set(provider_actions) != {"research_contact_deep"}:
            raise ValueError("contact facet children require exactly target-locked deep research")
        self._runtime = runtime
        self._tools = tools
        self._provider_actions = dict(provider_actions)
        self._state = state
        self._model_policy = model_policy
        self._conn_factory = conn_factory

    async def delegate(
        self,
        *,
        active: ActiveEntityResearchToolExecution,
        request: DelegateContactFacetInput,
    ) -> ContactFacetProjection:
        context = active.context
        authorization = context.authorization
        if (
            context.role is not EntityAgentRole.CONTACT
            or authorization.subject_type is not ResearchSubjectType.CONTACT
            or request.facet_key not in authorization.effective_facet_keys
            or request.question not in authorization.effective_research_questions
        ):
            raise ContactResearchAuthorityError(
                "facet request differs from exact parent contact authority"
            )
        current = await self._state.state(active)
        existing = next(
            (
                item
                for item in current.facet_projections
                if item.facet_key == request.facet_key and item.state == "completed"
            ),
            None,
        )
        if existing is not None:
            return existing
        ordinal, child_turn_id = await self._reserve(active, request)
        bindings = self._tools.compose_facet(
            subject_type=ResearchSubjectType.CONTACT,
            provider_action=self._provider_actions["research_contact_deep"],
        )
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT job.current_state_sha256, job.spent_cents, "
                            "job.budget_cap_cents, run.budget_cap_cents-run.spent_cents AS "
                            "run_remaining FROM entity_research_job job JOIN "
                            "entity_research_run run USING (research_run_id) "
                            "WHERE job.job_id=:job_id"
                        ),
                        {"job_id": authorization.job_id},
                    )
                )
                .mappings()
                .one()
            )
        child_context = EntityResearchRuntimeContext(
            agent_execution_id=authorization.attempt_id,
            agent_turn_id=child_turn_id,
            role=EntityAgentRole.FACET,
            authorization=authorization,
            resources=context.resources,
            tool_surface=context.tool_surface,
            stop_policy=EntityResearchStopPolicy(
                max_model_rounds=8,
                max_tool_calls=8,
                max_runtime_s=300,
                max_parallel_tools=1,
                max_consecutive_zero_yield=2,
            ),
            facet_contract=FacetDelegationContract(
                enabled=True,
                max_depth=1,
                max_children=min(2, len(authorization.effective_facet_keys)),
                children_may_delegate=False,
                shares_parent_budget=True,
            ),
            facet_scope=EntityFacetScope(
                parent_agent_execution_id=context.agent_execution_id,
                parent_agent_turn_id=context.agent_turn_id,
                facet_key=request.facet_key,
                depth=1,
                child_ordinal=ordinal,
                parent_budget_envelope_ref=authorization.effective_budget_envelope_ref,
                children_may_delegate=False,
            ),
            current_state_sha256=str(row["current_state_sha256"]),
            job_budget_cap_cents=Decimal(row["budget_cap_cents"]),
            job_spent_cents=Decimal(row["spent_cents"]),
            run_budget_remaining_cents=Decimal(row["run_remaining"]),
        )
        definition = EntityResearchAgentDefinition(
            context=child_context,
            model_policy=self._model_policy,
            tools=bindings,
            task_instruction=(
                f"Research only the admitted facet {request.facet_key!r} for the exact selected "
                f"contact. Answer only this confirmed question: {request.question}. Use "
                "target-locked deep research, observe its complete persisted result, and return "
                "a typed facet conclusion. Do not reveal channels, delegate, or finalize the "
                "parent contact job."
            ),
        )
        try:
            outcome = await self._runtime.run(definition=definition)
        except Exception as exc:
            raise ContactResearchAuthorityError(
                f"contact facet child execution failed ({type(exc).__name__}): {exc}"
            ) from exc
        if isinstance(outcome, EntityResearchAgentSuspension):
            projection = ContactFacetProjection(
                facet_key=request.facet_key,
                child_ordinal=ordinal,
                state="waiting_external",
                child_turn_id=child_turn_id,
                wait_ref=outcome.wait_ref,
            )
            await self._event(active, projection)
            raise EntityResearchExternalWait(
                wait_ref=outcome.wait_ref,
                current_state_sha256=outcome.current_state_sha256,
            )
        proposal = outcome.proposal
        if set(proposal.completed_field_keys + proposal.unresolved_field_keys) != {
            request.facet_key
        }:
            raise ContactResearchAuthorityError("facet child widened its exact selected facet")
        result_refs, claim_refs, evidence_refs = await self._child_lineage(
            authorization.job_id,
            child_turn_id,
            request.facet_key,
        )
        if (
            set(proposal.result_refs) != set(result_refs)
            or set(proposal.claim_refs) != set(claim_refs)
            or set(proposal.evidence_refs) != set(evidence_refs)
        ):
            raise ContactResearchAuthorityError(
                "facet child finalization differs from its exact persisted child-turn lineage"
            )
        projection = ContactFacetProjection(
            facet_key=request.facet_key,
            child_ordinal=ordinal,
            state="completed",
            child_turn_id=child_turn_id,
            result_refs=proposal.result_refs,
            claim_refs=proposal.claim_refs,
            evidence_refs=proposal.evidence_refs,
        )
        await self._event(active, projection)
        async with self._conn_factory() as conn:
            await self._state.refresh_state(conn, authorization.job_id)
        return projection

    async def _child_lineage(
        self,
        job_id: UUID,
        child_turn_id: UUID,
        facet_key: str,
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        async with self._conn_factory() as conn:
            result_rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT result.result_id FROM entity_research_result result JOIN "
                            "entity_research_tool_request request_row ON "
                            "request_row.tool_request_id="
                            "result.tool_request_id WHERE request_row.job_id=:job_id AND "
                            "request_row.agent_turn_id=:turn_id AND "
                            "cardinality(request_row.field_keys)=1 AND "
                            ":facet_key=ANY(request_row.field_keys) ORDER BY "
                            "result.created_at, result.result_id"
                        ),
                        {
                            "job_id": job_id,
                            "turn_id": child_turn_id,
                            "facet_key": facet_key,
                        },
                    )
                )
                .scalars()
                .all()
            )
            if not result_rows:
                raise ContactResearchAuthorityError(
                    "facet child finalized without an exact persisted child-turn result"
                )
            claim_rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT DISTINCT unnest(field.claim_refs) FROM "
                            "entity_research_result_field field WHERE field.result_id=ANY(:ids) "
                            "ORDER BY 1"
                        ),
                        {"ids": list(result_rows)},
                    )
                )
                .scalars()
                .all()
            )
            evidence_rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT DISTINCT evidence_id FROM entity_research_result_evidence "
                            "WHERE result_id=ANY(:ids) ORDER BY 1"
                        ),
                        {"ids": list(result_rows)},
                    )
                )
                .scalars()
                .all()
            )
            return (
                tuple(f"research-result:{value}" for value in result_rows),
                tuple(f"claim:{value}" for value in claim_rows),
                tuple(f"research-evidence:{value}" for value in evidence_rows),
            )

    async def _reserve(
        self,
        active: ActiveEntityResearchToolExecution,
        request: DelegateContactFacetInput,
    ) -> tuple[int, UUID]:
        authorization = active.context.authorization
        async with self._conn_factory() as conn:
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                {"scope": f"contact-facet:{authorization.job_id}"},
            )
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT DISTINCT ON (facet_key) facet_key, child_ordinal, "
                            "child_turn_id FROM entity_research_contact_facet_event "
                            "WHERE job_id=:job_id ORDER BY facet_key, event_seq DESC"
                        ),
                        {"job_id": authorization.job_id},
                    )
                )
                .mappings()
                .all()
            )
            existing = next(
                (row for row in rows if str(row["facet_key"]) == request.facet_key),
                None,
            )
            if existing is not None:
                return int(existing["child_ordinal"]), UUID(str(existing["child_turn_id"]))
            cap = min(2, len(authorization.effective_facet_keys))
            if len(rows) >= cap:
                raise ContactResearchAuthorityError("contact facet child cap is exhausted")
            ordinal = len(rows) + 1
            child_turn_id = uuid5(
                _TURN_NAMESPACE,
                f"{authorization.job_id}:{request.facet_key}:{ordinal}:{active.context.agent_turn_id}",
            )
            payload = {
                "facet_key": request.facet_key,
                "question": request.question,
                "child_ordinal": ordinal,
                "child_turn_id": str(child_turn_id),
            }
            await conn.execute(
                text(
                    "INSERT INTO entity_research_contact_facet_event "
                    "(event_id, research_run_id, job_id, workspace_id, contact_entity_id, "
                    "facet_key, child_ordinal, parent_turn_id, child_turn_id, state, "
                    "payload_json, payload_sha256) VALUES (:event_id, :run_id, :job_id, "
                    ":workspace_id, :contact_id, :facet_key, :ordinal, :parent_turn_id, "
                    ":child_turn_id, 'started', CAST(:payload AS jsonb), :digest)"
                ),
                {
                    "event_id": uuid4(),
                    "run_id": authorization.research_run_id,
                    "job_id": authorization.job_id,
                    "workspace_id": authorization.workspace_id,
                    "contact_id": authorization.subject_entity_id,
                    "facet_key": request.facet_key,
                    "ordinal": ordinal,
                    "parent_turn_id": active.context.agent_turn_id,
                    "child_turn_id": child_turn_id,
                    "payload": serialize_value_json(payload),
                    "digest": canonical_sha256(payload),
                },
            )
        return ordinal, child_turn_id

    async def _event(
        self,
        active: ActiveEntityResearchToolExecution,
        projection: ContactFacetProjection,
    ) -> None:
        authorization = active.context.authorization
        payload = projection.model_dump(mode="json")
        async with self._conn_factory() as conn:
            await conn.execute(
                text(
                    "INSERT INTO entity_research_contact_facet_event "
                    "(event_id, research_run_id, job_id, workspace_id, contact_entity_id, "
                    "facet_key, child_ordinal, parent_turn_id, child_turn_id, state, "
                    "result_refs, claim_refs, evidence_refs, wait_ref, payload_json, "
                    "payload_sha256) VALUES (:event_id, :run_id, :job_id, :workspace_id, "
                    ":contact_id, :facet_key, :ordinal, :parent_turn_id, :child_turn_id, "
                    ":state, :result_refs, :claim_refs, :evidence_refs, :wait_ref, "
                    "CAST(:payload AS jsonb), :digest) ON CONFLICT DO NOTHING"
                ),
                {
                    "event_id": uuid4(),
                    "run_id": authorization.research_run_id,
                    "job_id": authorization.job_id,
                    "workspace_id": authorization.workspace_id,
                    "contact_id": authorization.subject_entity_id,
                    "facet_key": projection.facet_key,
                    "ordinal": projection.child_ordinal,
                    "parent_turn_id": active.context.agent_turn_id,
                    "child_turn_id": projection.child_turn_id,
                    "state": projection.state,
                    "result_refs": list(projection.result_refs),
                    "claim_refs": list(projection.claim_refs),
                    "evidence_refs": list(projection.evidence_refs),
                    "wait_ref": projection.wait_ref,
                    "payload": serialize_value_json(payload),
                    "digest": canonical_sha256(payload),
                },
            )


__all__ = ["CreateAgentContactFacetDelegate"]
