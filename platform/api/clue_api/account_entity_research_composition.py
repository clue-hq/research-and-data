"""M8D R5 exact account ``create_agent()`` definition and governed tool composition."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text

from clue_agents.account_entity_research import (
    AccountCommitteePlanProjection,
    DiscoverBuyingCommitteeInput,
)
from clue_agents.contracts import ModelPolicy
from clue_agents.entity_research_contracts import (
    EntityAgentRole,
    EntityResearchAgentDefinition,
    EntityResearchResource,
    EntityResearchResourceBundle,
    EntityResearchRuntimeContext,
    EntityResearchStopPolicy,
)
from clue_api.account_entity_research import (
    AccountResearchStateStore,
    account_engine_tool_bindings,
    read_account_committee_plan,
)
from clue_api.entity_research_runtime_wiring import EntityResearchDefinitionResolver
from clue_api.entity_research_tools import (
    GovernedEntityResearchToolFactory,
    ProviderActionBinding,
)
from clue_core.entity_research import (
    EntityAgentToolSurface,
    FacetDelegationContract,
    ResearchSubjectType,
)
from clue_db import ConnFactory, transaction
from clue_fleet.entity_research import EntityResearchExecutionFence, EntityResearchJobRow

_TURN_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r5:account-agent-turn")
#: The profile is the resource a launch durably pins into `EntityResearchJobAuthorization`
#: (`agent_profile_ref` + `agent_profile_sha256`), and `resolve` refuses any job whose
#: authorization names a different one. Its body is unchanged since v2, so its pin stays v2: a ref
#: bump here would strand every already-launched job (they carry the v2 ref at rest) and is
#: warranted only when the role identity itself changes.
_ACCOUNT_PROFILE_VERSION = "v2"
_ACCOUNT_PROFILE_REF = f"agent-profile:account-research:{_ACCOUNT_PROFILE_VERSION}"
#: Steering content (prompt + skills) is *not* authorization-pinned — it is pinned for replay by
#: the R3 journal's `system_prompt_sha256`/`resource_manifest_sha256`, and the turn key carries the
#: task attempt, so a resumed job legitimately re-drives under newer steering. v3 adds the account
#: tool operations manual (the Tier-1 static failure playbook) alongside the v2 prompt/skill.
_ACCOUNT_STEERING_VERSION = "v3"
_ACCOUNT_PROMPT_REF = f"agent-prompt:account-research:{_ACCOUNT_STEERING_VERSION}"
_ACCOUNT_SKILL_REF = f"agent-skill:governed-account-research:{_ACCOUNT_STEERING_VERSION}"
_ACCOUNT_MANUAL_REF = f"agent-skill:account-tool-operations-manual:{_ACCOUNT_STEERING_VERSION}"
_ACCOUNT_TOOL_NAMES = (
    "read_account_research_state",
    "research_account_deep",
    "enrich_account",
    "inspect_account_evidence",
    "discover_buying_committee",
    "record_committee_role_inferences",
    "assess_account_coverage",
    "read_research_result",
    "read_evidence",
    "finalize_account_research",
)


class AccountResearchCompositionError(RuntimeError):
    pass


def _committee_plan_block(plan: AccountCommitteePlanProjection | None) -> str:
    """Render the confirmed committee authority the agent must scope its committee call within."""

    if plan is None:
        return ""
    lines = [
        "",
        "",
        f"The confirmed committee plan ({plan.directive_ref}) is the only committee authority; "
        "`buying_unit_scope.target_functions` must be chosen from its functions, never invented:",
        f"- functions: {', '.join(plan.functions) or '(unrestricted)'}",
        f"- levels: {', '.join(plan.levels) or '(unrestricted)'}",
        f"- teams: {', '.join(plan.teams) or '(unrestricted)'}",
        f"- personas: {', '.join(plan.personas) or '(unrestricted)'}",
        f"- candidate_cap: {plan.candidate_cap}",
    ]
    if plan.questions:
        lines.append("- confirmed committee questions:")
        lines.extend(f"  - {value}" for value in plan.questions)
    else:
        # An unrestricted plan is authority to research the committee, not a reason to refuse it.
        # Live, an agent read "(unrestricted)" plus a `questions` field it could not leave empty,
        # concluded it had no verbatim question to copy and no function it was allowed to choose,
        # and looped on the coverage refusal until the graph recursion cap killed the job. Say the
        # two admissible values out loud instead.
        lines.append(
            "- this plan confirms no committee question: leave `questions` empty (never invent "
            "one), and because every selector above is unrestricted, choose the "
            "`buying_unit_scope.target_functions` your account evidence supports."
        )
    return "\n".join(lines)


@runtime_checkable
class AccountResearchProviderActionResolver(Protocol):
    async def resolve(self, job: EntityResearchJobRow) -> Mapping[str, ProviderActionBinding]: ...


class StaticAccountResearchProviderActions(AccountResearchProviderActionResolver):
    """Run-scoped fixture/composition helper; R6 owns multi-job production construction."""

    def __init__(
        self,
        actions: Mapping[UUID, Mapping[str, ProviderActionBinding]],
    ) -> None:
        self._actions = {job_id: dict(values) for job_id, values in actions.items()}

    async def resolve(self, job: EntityResearchJobRow) -> Mapping[str, ProviderActionBinding]:
        actions = self._actions.get(job.job_id)
        if actions is None:
            raise AccountResearchCompositionError(
                "account research provider actions are absent for the exact job"
            )
        return actions


class AccountResearchDefinitionResolver(EntityResearchDefinitionResolver):
    """Construct one R5 account mind without promoting it into production cutover (R6)."""

    def __init__(
        self,
        *,
        tools: GovernedEntityResearchToolFactory,
        state: AccountResearchStateStore,
        provider_actions: AccountResearchProviderActionResolver,
        model_policy: ModelPolicy,
        conn_factory: ConnFactory = transaction,
        catalog_root: Path | None = None,
        profile_catalog_root: Path | None = None,
        require_atomic_admission: bool = False,
        enforce_budget: bool = True,
    ) -> None:
        self._tools = tools
        self._state = state
        self._provider_actions = provider_actions
        self._model_policy = model_policy
        self._conn_factory = conn_factory
        self._catalog_root = catalog_root or _account_catalog_root()
        self._profile_root = profile_catalog_root or _account_catalog_root(_ACCOUNT_PROFILE_VERSION)
        self._require_atomic_admission = require_atomic_admission
        self._enforce_budget = enforce_budget

    async def resolve(
        self,
        *,
        job: EntityResearchJobRow,
        fence: EntityResearchExecutionFence,
    ) -> EntityResearchAgentDefinition:
        if (
            job.subject_type is not ResearchSubjectType.ACCOUNT
            or job.authorization.subject_type is not ResearchSubjectType.ACCOUNT
            or job.authorization.agent_profile_ref != _ACCOUNT_PROFILE_REF
            or job.active_worker_id != fence.worker_id
            or job.lease_generation != fence.lease_generation
        ):
            raise AccountResearchCompositionError(
                "R5 definition requires one exact live account-job fence/profile"
            )
        resources = self._resources()
        if resources.profile.sha256 != job.authorization.agent_profile_sha256:
            raise AccountResearchCompositionError(
                "authorized account profile digest differs from the R5 resource body"
            )
        surface = EntityAgentToolSurface(
            subject_type=ResearchSubjectType.ACCOUNT,
            tool_names=_ACCOUNT_TOOL_NAMES,
        )
        actions = dict(await self._provider_actions.resolve(job))
        if set(actions) != {
            "research_account_deep",
            "enrich_account",
            "discover_buying_committee",
        }:
            raise AccountResearchCompositionError(
                "R5 account provider actions must be exactly deep/enrich/committee"
            )
        if self._require_atomic_admission and any(
            action.provider_family is None
            or action.provider_rate_limit_ref is None
            or action.provider_concurrency_limit is None
            or action.budget_reservation_cents <= 0
            for action in actions.values()
        ):
            raise AccountResearchCompositionError(
                "production account provider actions require complete R9 admission metadata"
            )
        committee = actions["discover_buying_committee"]
        actions["discover_buying_committee"] = committee.model_copy(
            update={"args_schema": DiscoverBuyingCommitteeInput}
        )
        engine = account_engine_tool_bindings(self._state)
        bindings = self._tools.compose(
            surface=surface,
            provider_actions=actions,
            engine_tools=engine,
        )
        async with self._conn_factory() as conn:
            remaining = (
                await conn.execute(
                    text(
                        "SELECT budget_cap_cents-spent_cents FROM entity_research_run "
                        "WHERE research_run_id=:run_id AND workspace_id=:workspace_id"
                    ),
                    {
                        "run_id": job.research_run_id,
                        "workspace_id": job.workspace_id,
                    },
                )
            ).scalar_one_or_none()
            committee_plan = await read_account_committee_plan(
                conn, authorization=job.authorization
            )
        if remaining is None:
            raise AccountResearchCompositionError("account research run is absent")
        context = EntityResearchRuntimeContext(
            agent_execution_id=job.authorization.attempt_id,
            # One drive is one turn. The attempt ordinal is load-bearing: a released lease
            # restarts at generation 1, so a crashed job resumed at the same durable state would
            # otherwise re-mint the previous drive's turn id and the R3 journal would refuse the
            # resume as a replay under different exact construction.
            agent_turn_id=uuid5(
                _TURN_NAMESPACE,
                f"{job.job_id}:{fence.lease_generation}:{fence.task_attempt}"
                f":{job.current_state_sha256}",
            ),
            role=EntityAgentRole.ACCOUNT,
            authorization=job.authorization,
            resources=resources,
            tool_surface=surface,
            stop_policy=EntityResearchStopPolicy(
                max_model_rounds=24,
                max_tool_calls=32,
                max_runtime_s=900,
                max_parallel_tools=3,
                max_consecutive_zero_yield=4,
            ),
            facet_contract=FacetDelegationContract(
                enabled=False,
                max_depth=0,
                max_children=0,
                children_may_delegate=False,
            ),
            current_state_sha256=job.current_state_sha256,
            job_budget_cap_cents=job.budget_cap_cents,
            job_spent_cents=job.spent_cents,
            run_budget_remaining_cents=max(Decimal(0), Decimal(str(remaining))),
            budget_controls_enabled=self._enforce_budget,
        )
        questions = "\n".join(
            f"- {value}" for value in job.authorization.selection.research_questions
        )
        question_instruction = (
            "The confirmed directional questions are:\n" + questions
            if questions
            else (
                "No separate directional questions were confirmed. The admitted field/source "
                "plan is the complete research boundary."
            )
        )
        return EntityResearchAgentDefinition(
            context=context,
            model_policy=self._model_policy,
            tools=bindings,
            task_instruction=(
                "Research the exact account within the confirmed scope. "
                + (
                    "Form its evidence-backed buying committee. "
                    if job.authorization.selection.committee_source_keys
                    else "Committee research is not selected; do not require or attempt it. "
                )
                + (
                    "Budget controls are disabled: budget values are record-only accounting "
                    "estimates and must never be used to skip an otherwise authorized provider "
                    "call. "
                    if not self._enforce_budget
                    else ""
                )
                + question_instruction
                + _committee_plan_block(committee_plan)
            ),
        )

    def _resources(self) -> EntityResearchResourceBundle:
        def resource(kind: str, ref: str, version: str, path: Path) -> EntityResearchResource:
            body = path.read_text(encoding="utf-8")
            return EntityResearchResource(
                kind=kind,  # type: ignore[arg-type]
                ref=ref,
                version=version,
                sha256=hashlib.sha256(body.encode()).hexdigest(),
                body=body,
            )

        def steering(kind: str, ref: str, name: str) -> EntityResearchResource:
            return resource(kind, ref, _ACCOUNT_STEERING_VERSION, self._catalog_root / name)

        return EntityResearchResourceBundle(
            profile=resource(
                "profile",
                _ACCOUNT_PROFILE_REF,
                _ACCOUNT_PROFILE_VERSION,
                self._profile_root / "profile.md",
            ),
            prompt=steering("prompt", _ACCOUNT_PROMPT_REF, "prompt.md"),
            skills=(
                steering("skill", _ACCOUNT_SKILL_REF, "skill.md"),
                steering("skill", _ACCOUNT_MANUAL_REF, "manual.md"),
            ),
        )


def _account_catalog_root(version: str = _ACCOUNT_STEERING_VERSION) -> Path:
    return (
        Path(__file__).parents[2] / "agents" / "catalog" / "entity-research" / "account" / version
    )


def account_research_profile_sha256(catalog_root: Path | None = None) -> str:
    root = catalog_root or _account_catalog_root(_ACCOUNT_PROFILE_VERSION)
    return hashlib.sha256((root / "profile.md").read_bytes()).hexdigest()


#: The one profile reference a launch may stamp into a job authorization. The launcher and this
#: resolver must never disagree about it — ``resolve`` refuses a job whose authorization names any
#: other profile — so both read this constant.
ACCOUNT_RESEARCH_PROFILE_REF = _ACCOUNT_PROFILE_REF

__all__ = [
    "ACCOUNT_RESEARCH_PROFILE_REF",
    "AccountResearchCompositionError",
    "AccountResearchDefinitionResolver",
    "AccountResearchProviderActionResolver",
    "StaticAccountResearchProviderActions",
    "account_research_profile_sha256",
]
