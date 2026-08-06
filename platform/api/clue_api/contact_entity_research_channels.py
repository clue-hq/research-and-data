"""R8 semantic channel tools over the durable M8C acquisition/validation coordinator."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Literal, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text

from clue_agents.contact_entity_research import ContactChannelProjection, ContactChannelToolInput
from clue_agents.entity_research_runtime import (
    ActiveEntityResearchToolExecution,
    EntityResearchExternalWait,
)
from clue_api.contact_channel_enrichment import (
    ContactChannelEnrichmentOutcome,
    ExaContactChannelCoordinator,
)
from clue_api.contact_entity_research import (
    ContactChannelAdmission,
    ContactResearchAuthorityError,
    ContactResearchStateStore,
)
from clue_core import (
    ContactChannel,
    ContactChannelOperation,
    ContactChannelOperationId,
    ContactResearchIntent,
    ContactResearchPolicyPin,
)
from clue_db import ConnFactory, transaction

_CAUSATION_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r8:contact-channel-causation")


class GovernedContactChannelActions:
    """Expose acquisition and validation as two exact, separately journaled agent decisions."""

    def __init__(
        self,
        *,
        intent: ContactResearchIntent,
        effective_policy: ContactResearchPolicyPin,
        coordinator: ExaContactChannelCoordinator,
        state: ContactResearchStateStore,
        observation_window: str,
        conn_factory: ConnFactory = transaction,
        provider_concurrency_limit: int = 8,
    ) -> None:
        self._intent = intent
        self._policy = effective_policy
        self._coordinator = coordinator
        self._state = state
        self._window = observation_window
        self._conn_factory = conn_factory
        if provider_concurrency_limit < 1:
            raise ValueError("contact channel provider concurrency limit must be positive")
        self._provider_concurrency_limit = provider_concurrency_limit

    def admission(
        self,
        *,
        stage: Literal["acquisition", "validation"],
    ) -> ContactChannelAdmission | None:
        target = next(
            item
            for item in self._intent.selection.body.targets
            if item.contact_entity_id == self._intent.contact_entity_id
        )
        authorizations = tuple(item for item in (target.email, target.phone) if item.allowed)
        if not authorizations:
            return None
        if stage == "acquisition":
            budget = max(Decimal(item.budget_cap_cents) for item in authorizations)
            sources = sorted(
                {source for item in authorizations for source in item.provider_source_keys}
            )
        else:
            budget = max(Decimal(item.validation_budget_cap_cents) for item in authorizations)
            sources = sorted(
                {source for item in authorizations for source in item.validation_source_keys}
            )
        if budget <= 0 or not sources:
            raise ContactResearchAuthorityError(
                f"authorized channel {stage} lacks a positive R9 reservation"
            )
        family = "+".join(sources)
        return ContactChannelAdmission(
            provider_family=f"contact_channel_{stage}:{family}",
            budget_reservation_cents=budget,
            provider_rate_limit_ref=f"provider-rate:contact-channel:{stage}:{family}",
            provider_concurrency_limit=self._provider_concurrency_limit,
        )

    async def reveal(
        self,
        *,
        active: ActiveEntityResearchToolExecution,
        request: ContactChannelToolInput,
    ) -> ContactChannelProjection:
        self._assert_active(active, request)
        channel = ContactChannel(request.channel.value)
        caused = False

        async def before_dispatch(operation: ContactChannelOperation) -> None:
            nonlocal caused
            await self._record_causation(
                active=active,
                operation=operation,
                stage="acquisition",
                disposition="caused",
            )
            caused = True

        result = await self._coordinator.start(
            intent=self._intent,
            effective_policy=self._policy,
            channel=channel,
            observation_window=self._window,
            defer_validation=True,
            before_acquisition_dispatch=before_dispatch,
        )
        operation = result.operation
        if not caused:
            await self._record_causation(
                active=active,
                operation=operation,
                stage="acquisition",
                disposition=(
                    "joined"
                    if result.outcome is ContactChannelEnrichmentOutcome.JOINED_IN_FLIGHT
                    else "replayed"
                ),
            )
        if result.outcome in {
            ContactChannelEnrichmentOutcome.CREATED,
            ContactChannelEnrichmentOutcome.WAITING_EXTERNAL,
            ContactChannelEnrichmentOutcome.JOINED_IN_FLIGHT,
        }:
            digest = await self._refresh(active)
            raise EntityResearchExternalWait(
                wait_ref=f"contact-channel-acquisition:{operation.operation_id}",
                current_state_sha256=digest,
            )
        await self._fold_cost(active, operation=operation, stage="acquisition")
        await self._refresh(active)
        return await self._projection(active, channel=request.channel, stage="acquisition")

    async def validate(
        self,
        *,
        active: ActiveEntityResearchToolExecution,
        request: ContactChannelToolInput,
    ) -> ContactChannelProjection:
        self._assert_active(active, request)
        operation = await self._latest_acquisition(active, request.channel)
        caused = False

        async def before_dispatch(value: ContactChannelOperation) -> None:
            nonlocal caused
            await self._record_causation(
                active=active,
                operation=value,
                stage="validation",
                disposition="caused",
            )
            caused = True

        if operation.state.value in {"succeeded", "rejected"}:
            result_operation = operation
        else:
            result = await self._coordinator.validate_ready(
                workspace_id=self._intent.workspace_id,
                operation_id=operation.operation_id,
                effective_policy=self._policy,
                before_validation_dispatch=before_dispatch,
            )
            result_operation = result.operation
            if result.outcome is ContactChannelEnrichmentOutcome.JOINED_IN_FLIGHT:
                if not caused:
                    await self._record_causation(
                        active=active,
                        operation=result_operation,
                        stage="validation",
                        disposition="joined",
                    )
                digest = await self._refresh(active)
                raise EntityResearchExternalWait(
                    wait_ref=f"contact-channel-validation:{operation.operation_id}",
                    current_state_sha256=digest,
                )
        if not caused:
            await self._record_causation(
                active=active,
                operation=result_operation,
                stage="validation",
                disposition="replayed",
            )
        await self._fold_cost(active, operation=result_operation, stage="validation")
        await self._refresh(active)
        return await self._projection(active, channel=request.channel, stage="validation")

    def _assert_active(
        self,
        active: ActiveEntityResearchToolExecution,
        request: ContactChannelToolInput,
    ) -> None:
        authorization = active.context.authorization
        if (
            authorization.subject_entity_id != self._intent.contact_entity_id
            or authorization.parent_account_id != self._intent.account_entity_id
            or authorization.workspace_id != self._intent.workspace_id
            or request.channel.value
            not in {channel.value for channel in authorization.effective_channel_permissions}
        ):
            raise ContactResearchAuthorityError(
                "channel action differs from the exact selected contact authority"
            )
        target = next(
            value
            for value in self._intent.selection.body.targets
            if value.contact_entity_id == self._intent.contact_entity_id
        )
        channel_authority = target.email if request.channel.value == "email" else target.phone
        selected_sources = {
            *channel_authority.provider_source_keys,
            *channel_authority.validation_source_keys,
        }
        if not channel_authority.allowed or not selected_sources.issubset(
            authorization.effective_channel_source_keys
        ):
            raise ContactResearchAuthorityError("channel sources differ from selected authority")

    async def _record_causation(
        self,
        *,
        active: ActiveEntityResearchToolExecution,
        operation: ContactChannelOperation,
        stage: str,
        disposition: str,
    ) -> None:
        authorization = active.context.authorization
        event_ref = active.journal_event_ref
        if not event_ref.startswith("entity-agent-event:"):
            raise ContactResearchAuthorityError("channel tool lacks an exact journal event")
        event_id = UUID(event_ref.removeprefix("entity-agent-event:"))
        causation_id = uuid5(
            _CAUSATION_NAMESPACE,
            f"{authorization.job_id}:{operation.operation_id}:{stage}:{active.call.tool_call_id}",
        )
        values = {
            "causation_id": causation_id,
            "run_id": authorization.research_run_id,
            "job_id": authorization.job_id,
            "workspace_id": authorization.workspace_id,
            "contact_id": authorization.subject_entity_id,
            "account_id": authorization.parent_account_id,
            "turn_id": active.context.agent_turn_id,
            "execution_id": active.context.agent_execution_id,
            "event_id": event_id,
            "tool_call_id": active.call.tool_call_id,
            "tool_input_sha": active.call.tool_input_sha256,
            "operation_id": operation.operation_id,
            "channel": operation.request.channel.value,
            "stage": stage,
            "disposition": disposition,
        }
        async with self._conn_factory() as conn:
            await conn.execute(
                text(
                    "INSERT INTO entity_research_contact_channel_causation "
                    "(causation_id, research_run_id, job_id, workspace_id, contact_entity_id, "
                    "parent_account_id, agent_turn_id, agent_execution_id, tool_event_id, "
                    "tool_call_id, tool_input_sha256, channel_operation_id, channel, stage, "
                    "disposition) "
                    "VALUES (:causation_id, :run_id, :job_id, :workspace_id, :contact_id, "
                    ":account_id, :turn_id, :execution_id, :event_id, :tool_call_id, "
                    ":tool_input_sha, :operation_id, :channel, :stage, :disposition) "
                    "ON CONFLICT DO NOTHING"
                ),
                values,
            )
            stored = (
                (
                    await conn.execute(
                        text(
                            "SELECT job_id, contact_entity_id, parent_account_id, "
                            "agent_turn_id, tool_call_id, tool_input_sha256, channel::text, "
                            "stage, disposition FROM entity_research_contact_channel_causation "
                            "WHERE causation_id=:causation_id"
                        ),
                        values,
                    )
                )
                .mappings()
                .one()
            )
        expected = (
            authorization.job_id,
            authorization.subject_entity_id,
            authorization.parent_account_id,
            active.context.agent_turn_id,
            active.call.tool_call_id,
            active.call.tool_input_sha256,
            operation.request.channel.value,
            stage,
            disposition,
        )
        observed = tuple(
            stored[key]
            for key in (
                "job_id",
                "contact_entity_id",
                "parent_account_id",
                "agent_turn_id",
                "tool_call_id",
                "tool_input_sha256",
                "channel",
                "stage",
                "disposition",
            )
        )
        same_resumed_cause = (
            observed[:3] == expected[:3]
            and observed[4:-1] == expected[4:-1]
            and observed[-1] == "caused"
            and disposition in {"joined", "replayed"}
        )
        if observed != expected and not same_resumed_cause:
            raise ContactResearchAuthorityError("channel causation replay changed authority")

    async def _fold_cost(
        self,
        active: ActiveEntityResearchToolExecution,
        *,
        operation: ContactChannelOperation,
        stage: str,
    ) -> None:
        cost = (
            operation.acquisition_cost_cents_charged
            if stage == "acquisition"
            else operation.validation_cost_cents_charged
        )
        async with self._conn_factory() as conn:
            values = {
                "operation_id": operation.operation_id,
                "stage": stage,
                "run_id": active.context.authorization.research_run_id,
                "job_id": active.context.authorization.job_id,
                "cost": cost,
            }
            folded = (
                await conn.execute(
                    text(
                        "INSERT INTO entity_research_contact_channel_cost_fold "
                        "(channel_operation_id, stage, research_run_id, job_id, cost_cents) "
                        "VALUES (:operation_id, :stage, :run_id, :job_id, :cost) "
                        "ON CONFLICT DO NOTHING RETURNING channel_operation_id"
                    ),
                    values,
                )
            ).scalar_one_or_none()
            if folded is None:
                stored = (
                    (
                        await conn.execute(
                            text(
                                "SELECT cost_cents FROM "
                                "entity_research_contact_channel_cost_fold WHERE "
                                "channel_operation_id=:operation_id AND stage=:stage"
                            ),
                            values,
                        )
                    )
                    .mappings()
                    .one()
                )
                if Decimal(stored["cost_cents"]) != cost:
                    raise ContactResearchAuthorityError(
                        "channel cost fold replay changed settlement"
                    )
                return
            job_updated = (
                await conn.execute(
                    text(
                        "UPDATE entity_research_job SET spent_cents=spent_cents+:cost, "
                        "updated_at=now() WHERE job_id=:job_id AND research_run_id=:run_id "
                        "AND spent_cents+:cost<=budget_cap_cents RETURNING job_id"
                    ),
                    values,
                )
            ).scalar_one_or_none()
            if job_updated is None:
                raise ContactResearchAuthorityError(
                    "settled channel cost exceeds the exact contact-job budget"
                )
            run_updated = (
                await conn.execute(
                    text(
                        "UPDATE entity_research_run SET spent_cents=spent_cents+:cost, "
                        "updated_at=now() WHERE research_run_id=:run_id "
                        "AND spent_cents+:cost<=budget_cap_cents RETURNING research_run_id"
                    ),
                    values,
                )
            ).scalar_one_or_none()
            if run_updated is None:
                raise ContactResearchAuthorityError(
                    "settled channel cost exceeds the exact contact-run budget"
                )

    async def _latest_acquisition(
        self,
        active: ActiveEntityResearchToolExecution,
        channel: object,
    ) -> ContactChannelOperation:
        async with self._conn_factory() as conn:
            operation_id = (
                await conn.execute(
                    text(
                        "SELECT operation.id FROM entity_research_contact_channel_causation link "
                        "JOIN contact_channel_operation operation ON operation.id="
                        "link.channel_operation_id WHERE link.job_id=:job_id AND "
                        "link.stage='acquisition' AND operation.channel::text=:channel "
                        "ORDER BY link.created_at DESC LIMIT 1"
                    ),
                    {
                        "job_id": active.context.authorization.job_id,
                        "channel": getattr(channel, "value", str(channel)),
                    },
                )
            ).scalar_one_or_none()
            if operation_id is None:
                raise ContactResearchAuthorityError(
                    "channel validation requires a preceding acquisition tool decision"
                )
            from clue_research.durable import get_contact_channel_operation

            return await get_contact_channel_operation(
                conn,
                workspace_id=self._intent.workspace_id,
                operation_id=ContactChannelOperationId(operation_id),
            )

    async def _refresh(self, active: ActiveEntityResearchToolExecution) -> str:
        async with self._conn_factory() as conn:
            return await self._state.refresh_state(conn, active.context.authorization.job_id)

    async def _projection(
        self,
        active: ActiveEntityResearchToolExecution,
        *,
        channel: object,
        stage: str,
    ) -> ContactChannelProjection:
        async with self._conn_factory() as conn:
            rows = await self._state._channel_rows(conn, active.context.authorization.job_id)
        expected = getattr(channel, "value", str(channel))
        row = next(
            (
                value
                for value in rows
                if str(value["channel"]) == expected and str(value["stage"]) == stage
            ),
            None,
        )
        if row is None:
            raise ContactResearchAuthorityError("channel result is absent from exact job state")
        return self._state._channel_projection(cast(Mapping[str, object], row))


__all__ = ["GovernedContactChannelActions"]
