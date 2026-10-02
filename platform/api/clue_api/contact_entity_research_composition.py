"""M8D R8 exact contact create_agent definition and governed tool composition."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text

from clue_agents.contracts import ModelPolicy
from clue_agents.entity_research_contracts import (
    EntityAgentRole,
    EntityResearchAgentDefinition,
    EntityResearchResource,
    EntityResearchResourceBundle,
    EntityResearchRuntimeContext,
    EntityResearchStopPolicy,
)
from clue_agents.entity_research_runtime import EntityResearchAgentRuntime
from clue_api.contact_entity_research import (
    ContactChannelActions,
    ContactResearchStateStore,
    contact_engine_tool_bindings,
)
from clue_api.contact_entity_research_facets import CreateAgentContactFacetDelegate
from clue_api.entity_research_runtime_wiring import EntityResearchDefinitionResolver
from clue_api.entity_research_tools import (
    GovernedEntityResearchToolFactory,
    ProviderActionBinding,
)
from clue_core.contact_research import ContactResearchIntent, ContactResearchPolicyPin
from clue_core.entity_research import (
    EntityAgentToolSurface,
    FacetDelegationContract,
    ResearchSubjectType,
)
from clue_db import ConnFactory, transaction
from clue_fleet.entity_research import EntityResearchExecutionFence, EntityResearchJobRow

_TURN_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r8:contact-agent-turn")
_CONTACT_PROFILE_REF = "agent-profile:contact-research:v1"
_CONTACT_PROMPT_REF = "agent-prompt:contact-research:v1"
_CONTACT_SKILL_REF = "agent-skill:governed-contact-research:v1"
_CONTACT_TOOL_NAMES = (
    "read_contact_research_state",
    "research_contact_deep",
    "enrich_contact",
    "inspect_contact_evidence",
    "reveal_contact_channel",
    "validate_contact_channel",
    "assess_contact_coverage",
    "read_research_result",
    "read_evidence",
    "delegate_contact_facet",
    "finalize_contact_research",
)


class ContactResearchCompositionError(RuntimeError):
    pass


@runtime_checkable
class ContactResearchProviderActionResolver(Protocol):
    async def resolve(self, job: EntityResearchJobRow) -> Mapping[str, ProviderActionBinding]: ...


@runtime_checkable
class ContactResearchChannelActionResolver(Protocol):
    async def resolve(
        self,
        job: EntityResearchJobRow,
        *,
        intent: ContactResearchIntent,
        policy: ContactResearchPolicyPin,
        state: ContactResearchStateStore,
    ) -> ContactChannelActions: ...


class StaticContactResearchProviderActions(ContactResearchProviderActionResolver):
    def __init__(self, actions: Mapping[UUID, Mapping[str, ProviderActionBinding]]) -> None:
        self._actions = {job_id: dict(values) for job_id, values in actions.items()}

    async def resolve(self, job: EntityResearchJobRow) -> Mapping[str, ProviderActionBinding]:
        actions = self._actions.get(job.job_id)
        if actions is None:
            raise ContactResearchCompositionError(
                "contact research provider actions are absent for the exact job"
            )
        return actions


class StaticContactResearchChannelActions(ContactResearchChannelActionResolver):
    def __init__(self, actions: Mapping[UUID, ContactChannelActions]) -> None:
        self._actions = dict(actions)

    async def resolve(
        self,
        job: EntityResearchJobRow,
        *,
        intent: ContactResearchIntent,
        policy: ContactResearchPolicyPin,
        state: ContactResearchStateStore,
    ) -> ContactChannelActions:
        del intent, policy, state
        try:
            return self._actions[job.job_id]
        except KeyError as exc:
            raise ContactResearchCompositionError(
                "contact channel actions are absent for the exact job"
            ) from exc


class ContactResearchDefinitionResolver(EntityResearchDefinitionResolver):
    def __init__(
        self,
        *,
        tools: GovernedEntityResearchToolFactory,
        state: ContactResearchStateStore,
        provider_actions: ContactResearchProviderActionResolver,
        channel_actions: ContactResearchChannelActionResolver,
        facet_runtime: EntityResearchAgentRuntime,
        model_policy: ModelPolicy,
        conn_factory: ConnFactory = transaction,
        catalog_root: Path | None = None,
        require_atomic_admission: bool = False,
        enforce_budget: bool = True,
    ) -> None:
        self._tools = tools
        self._state = state
        self._provider_actions = provider_actions
        self._channel_actions = channel_actions
        self._facet_runtime = facet_runtime
        self._model_policy = model_policy
        self._conn_factory = conn_factory
        self._catalog_root = catalog_root or (
            Path(__file__).parents[2] / "agents" / "catalog" / "entity-research" / "contact" / "v1"
        )
        self._require_atomic_admission = require_atomic_admission
        self._enforce_budget = enforce_budget

    async def resolve(
        self,
        *,
        job: EntityResearchJobRow,
        fence: EntityResearchExecutionFence,
    ) -> EntityResearchAgentDefinition:
        if (
            job.subject_type is not ResearchSubjectType.CONTACT
            or job.authorization.subject_type is not ResearchSubjectType.CONTACT
            or job.authorization.agent_profile_ref != _CONTACT_PROFILE_REF
            or job.active_worker_id != fence.worker_id
            or job.lease_generation != fence.lease_generation
        ):
            raise ContactResearchCompositionError(
                "R8 definition requires one exact live contact-job fence/profile"
            )
        resources = self._resources()
        if resources.profile.sha256 != job.authorization.agent_profile_sha256:
            raise ContactResearchCompositionError(
                "authorized contact profile digest differs from the R8 resource body"
            )
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT authority.contact_intent_json, "
                            "authority.contact_intent_sha256, "
                            "run.budget_cap_cents-run.spent_cents AS remaining FROM "
                            "entity_research_contact_job_authority authority JOIN "
                            "entity_research_run run USING (research_run_id) WHERE "
                            "authority.job_id=:job_id AND authority.research_run_id=:run_id AND "
                            "authority.workspace_id=:workspace_id"
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
            raise ContactResearchCompositionError("contact job lacks R7 exact authority")
        intent = ContactResearchIntent.model_validate(row["contact_intent_json"])
        if intent.sha256() != str(row["contact_intent_sha256"]):
            raise ContactResearchCompositionError("persisted contact intent digest changed")
        actions = dict(await self._provider_actions.resolve(job))
        if set(actions) != {"research_contact_deep", "enrich_contact"}:
            raise ContactResearchCompositionError(
                "R8 provider actions must be exactly contact deep and structured enrichment"
            )
        if self._require_atomic_admission and any(
            action.provider_family is None
            or action.provider_rate_limit_ref is None
            or action.provider_concurrency_limit is None
            or action.budget_reservation_cents <= 0
            for action in actions.values()
        ):
            raise ContactResearchCompositionError(
                "production contact provider actions require complete R9 admission metadata"
            )
        channel_actions = await self._channel_actions.resolve(
            job,
            intent=intent,
            policy=intent.selection.body.policy,
            state=self._state,
        )
        facet = CreateAgentContactFacetDelegate(
            runtime=self._facet_runtime,
            tools=self._tools,
            provider_actions={"research_contact_deep": actions["research_contact_deep"]},
            state=self._state,
            model_policy=self._model_policy,
            conn_factory=self._conn_factory,
        )
        engine = dict(
            contact_engine_tool_bindings(
                self._state,
                facets=facet,
                channels=channel_actions,
            )
        )
        channel_bindings = {
            name: engine.pop(name)
            for name in ("reveal_contact_channel", "validate_contact_channel")
        }
        channel_admission = {
            "reveal_contact_channel": channel_actions.admission(stage="acquisition"),
            "validate_contact_channel": channel_actions.admission(stage="validation"),
        }
        for name, admission in channel_admission.items():
            if admission is None:
                continue
            channel_bindings[name] = channel_bindings[name].model_copy(
                update={
                    "provider_family": admission.provider_family,
                    "budget_reservation_cents": admission.budget_reservation_cents,
                    "provider_rate_limit_ref": admission.provider_rate_limit_ref,
                    "provider_concurrency_limit": admission.provider_concurrency_limit,
                }
            )
        base_names = tuple(
            name
            for name in _CONTACT_TOOL_NAMES
            if name not in {"reveal_contact_channel", "validate_contact_channel"}
        )
        base_surface = EntityAgentToolSurface(
            subject_type=ResearchSubjectType.CONTACT,
            tool_names=base_names,
        )
        base = self._tools.compose(
            surface=base_surface,
            provider_actions=actions,
            engine_tools=engine,
        )
        by_name = {binding.name: binding for binding in (*base, *channel_bindings.values())}
        surface = EntityAgentToolSurface(
            subject_type=ResearchSubjectType.CONTACT,
            tool_names=_CONTACT_TOOL_NAMES,
        )
        context = EntityResearchRuntimeContext(
            agent_execution_id=job.authorization.attempt_id,
            # One drive is one turn; see the account resolver's note. The attempt ordinal keeps a
            # resumed job from re-minting its crashed drive's turn id (a released lease restarts
            # at generation 1).
            agent_turn_id=uuid5(
                _TURN_NAMESPACE,
                f"{job.job_id}:{fence.lease_generation}:{fence.task_attempt}"
                f":{job.current_state_sha256}",
            ),
            role=EntityAgentRole.CONTACT,
            authorization=job.authorization,
            resources=resources,
            tool_surface=surface,
            stop_policy=EntityResearchStopPolicy(
                max_model_rounds=24,
                max_tool_calls=32,
                max_runtime_s=900,
                max_parallel_tools=2,
                max_consecutive_zero_yield=4,
            ),
            facet_contract=(
                FacetDelegationContract(
                    enabled=True,
                    max_depth=1,
                    max_children=min(2, len(job.authorization.effective_facet_keys)),
                    children_may_delegate=False,
                    shares_parent_budget=True,
                )
                if job.authorization.effective_facet_keys
                else FacetDelegationContract(
                    enabled=False,
                    max_depth=0,
                    max_children=0,
                    children_may_delegate=False,
                    shares_parent_budget=True,
                )
            ),
            current_state_sha256=job.current_state_sha256,
            job_budget_cap_cents=job.budget_cap_cents,
            job_spent_cents=job.spent_cents,
            run_budget_remaining_cents=max(Decimal(0), Decimal(str(row["remaining"]))),
            budget_controls_enabled=self._enforce_budget,
        )
        await self._state.lock_identity(context)
        questions = "\n".join(
            f"- {value}" for value in job.authorization.effective_research_questions
        )
        return EntityResearchAgentDefinition(
            context=context,
            model_policy=self._model_policy,
            tools=tuple(by_name[name] for name in _CONTACT_TOOL_NAMES),
            task_instruction=(
                "Research only the exact selected contact under the exact locked employer. "
                + (
                    "Budget controls are disabled: budget values are record-only accounting "
                    "estimates and must never be used to skip an otherwise authorized provider "
                    "call. "
                    if not self._enforce_budget
                    else ""
                )
                + "The confirmed directional questions are:\n"
                f"{questions}"
            ),
        )

    def _resources(self) -> EntityResearchResourceBundle:
        def resource(kind: str, ref: str, name: str) -> EntityResearchResource:
            body = (self._catalog_root / name).read_text(encoding="utf-8")
            return EntityResearchResource(
                kind=kind,  # type: ignore[arg-type]
                ref=ref,
                version="v1",
                sha256=hashlib.sha256(body.encode()).hexdigest(),
                body=body,
            )

        return EntityResearchResourceBundle(
            profile=resource("profile", _CONTACT_PROFILE_REF, "profile.md"),
            prompt=resource("prompt", _CONTACT_PROMPT_REF, "prompt.md"),
            skills=(resource("skill", _CONTACT_SKILL_REF, "skill.md"),),
        )


__all__ = [
    "ContactResearchChannelActionResolver",
    "ContactResearchCompositionError",
    "ContactResearchDefinitionResolver",
    "ContactResearchProviderActionResolver",
    "StaticContactResearchChannelActions",
    "StaticContactResearchProviderActions",
]
