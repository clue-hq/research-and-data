from __future__ import annotations

import hashlib
import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from clue_agents.contracts import (
    AgentConstitution,
    AgentFinalizeEnvelope,
    AgentPlan,
    AgentProfile,
    AgentResourceManifest,
    AgentResourceRef,
    AgentRole,
    AgentTurnRequest,
    ContextBundleManifest,
    ContextLayer,
    ContextLayerManifest,
    DelegationRequest,
    DelegationResult,
    FinalizeStatus,
    ModelPolicy,
    PlanToolStep,
    ProjectContextArtifact,
    ResourceKind,
    SkillBundle,
    SpecialistTaskEnvelope,
    ToolPin,
    ValidatedOperation,
    ValidatedPlan,
    WorkspacePolicy,
    normalize_virtual_path,
)
from clue_core import ExecutionId, OperationId
from tests.agents.conftest import (
    EXECUTION_ID,
    NOW,
    SHA_A,
    SHA_B,
    SHA_C,
    artifact,
    constitution,
    domain_ref,
    resource,
)


def tool_pin(name: str = "read_project") -> ToolPin:
    return ToolPin(
        name=name,
        version="1",
        input_schema_sha256=SHA_A,
        output_schema_sha256=SHA_B,
    )


def workspace_policy() -> WorkspacePolicy:
    return WorkspacePolicy(
        max_total_bytes=2_000_000,
        max_file_bytes=200_000,
        max_file_count=100,
        allowed_extensions=(".json", ".md", ".txt", ".yaml"),
        readable_prefixes=(".deepagent", "inputs", "context", "work", "outputs"),
        writable_prefixes=("work", "outputs"),
        retention_class="agent-turn-standard",
    )


def profile() -> AgentProfile:
    pin = tool_pin()
    skill_ref = resource(ResourceKind.SKILL, "project-planning")
    return AgentProfile(
        name="head-of-abm",
        version="1.0.0",
        role=AgentRole.HEAD_OF_ABM,
        prompt=resource(ResourceKind.PROMPT, "head-of-abm"),
        skills=(
            SkillBundle(
                resource=skill_ref,
                summary="Plan a governed ABM project.",
                materialized_path=".deepagent/skills/project-planning/1.0.0/SKILL.md",
                required_tools=(pin,),
            ),
        ),
        tools=(pin,),
        model=ModelPolicy(
            model_id="openai/gpt-4.1",
            timeout_s=30,
            max_retries=2,
            max_output_tokens=4_096,
            temperature=0,
        ),
        workspace=workspace_policy(),
        delegation_roles=(AgentRole.RESEARCH,),
        max_delegation_depth=1,
        max_delegations=4,
        max_plan_nodes=24,
    )


def context_manifest() -> ContextBundleManifest:
    layers = tuple(
        ContextLayerManifest(
            layer=layer,
            materialized_paths=(f"context/{layer.value}.json",),
            content_sha256s=(SHA_A,),
            token_count=10,
        )
        for layer in ContextLayer
    )
    return ContextBundleManifest(
        context_bundle_id=UUID("00000000-0000-0000-0000-000000000611"),
        execution_id=EXECUTION_ID,
        schema_version="1",
        layers=layers,
        aggregate_sha256=SHA_B,
        assembled_at=NOW,
    )


@pytest.mark.parametrize(
    "path",
    (
        "/etc/passwd",
        "../secret",
        "work/../secret",
        "work//report.md",
        "work\\report.md",
        "C:/secret",
        ".",
        "work/\x00bad",
    ),
)
def test_virtual_paths_fail_closed(path: str) -> None:
    with pytest.raises(ValueError):
        normalize_virtual_path(path)


def test_workspace_policy_is_virtual_and_rejects_code_extensions() -> None:
    policy = workspace_policy()
    assert policy.virtual_mode is True
    with pytest.raises(ValidationError, match="source or executable"):
        WorkspacePolicy.model_validate(
            {**policy.model_dump(), "allowed_extensions": (".md", ".py")}
        )


def test_profile_requires_skill_tools_to_be_in_effective_allowlist() -> None:
    valid = profile()
    missing = valid.model_copy(update={"tools": ()})
    with pytest.raises(ValidationError, match="skills require tools"):
        AgentProfile.model_validate(missing.model_dump())


def test_resource_manifest_pins_exact_resource_and_tool_digests() -> None:
    value = AgentResourceManifest(
        schema_version="1",
        role=AgentRole.HEAD_OF_ABM,
        profile=resource(ResourceKind.PROFILE, "head-of-abm"),
        prompt=resource(ResourceKind.PROMPT, "head-of-abm"),
        skills=(resource(ResourceKind.SKILL, "project-planning"),),
        tools=(tool_pin(),),
        aggregate_sha256=SHA_C,
    )
    assert value.tools[0].address == "read_project@1"
    with pytest.raises(ValidationError):
        AgentResourceRef(kind=ResourceKind.SKILL, name="planning", version="latest", sha256=SHA_A)


def test_constitution_and_turn_reject_cross_workspace_refs_and_extra_fields() -> None:
    with pytest.raises(ValidationError, match="constitution artifact refs"):
        constitution(project_card_ref=artifact("project-card.json", workspace_id="ws-2"))

    with pytest.raises(ValidationError, match="turn artifact refs"):
        AgentTurnRequest(
            turn_id=UUID("00000000-0000-0000-0000-000000000612"),
            thread_id="thread-1",
            constitution=constitution(),
            user_message_artifact_ref=artifact("message.txt", workspace_id="ws-2"),
            requested_at=NOW,
        )

    with pytest.raises(ValidationError, match="Extra inputs"):
        constitution(unknown_authority="forbidden")


def _production_project_context(
    *,
    client_entity_id: str = "client-1",
    client_version: int = 7,
    project_id: str = "project-1",
) -> tuple[ProjectContextArtifact, ProjectContextArtifact]:
    return (
        ProjectContextArtifact(
            name="client_knowledge",
            artifact_ref=artifact("client-knowledge.json"),
            domain_ref=domain_ref("unused").model_copy(
                update={
                    "object_type": "client_knowledge",
                    "object_id": client_entity_id,
                    "version": client_version,
                }
            ),
        ),
        ProjectContextArtifact(
            name="stage0_project_state",
            artifact_ref=artifact("stage0-project-state.json"),
            domain_ref=domain_ref("unused").model_copy(
                update={
                    "object_type": "stage0_project_state",
                    "object_id": project_id,
                    "version": None,
                }
            ),
        ),
    )


def test_production_project_context_is_paired_and_exactly_scoped() -> None:
    bundle = _production_project_context()
    value = constitution(project_context_artifacts=bundle)
    assert value.project_context_artifacts == bundle

    with pytest.raises(ValidationError, match="constituted together"):
        constitution(project_context_artifacts=bundle[:1])
    with pytest.raises(ValidationError, match="constitution client"):
        constitution(
            project_context_artifacts=_production_project_context(client_entity_id="foreign")
        )
    with pytest.raises(ValidationError, match="constitution project"):
        constitution(project_context_artifacts=_production_project_context(project_id="project-2"))


def test_agent_plan_rejects_unknown_dependency_and_cycle() -> None:
    first = PlanToolStep(
        node_key="first",
        tool=tool_pin(),
        arguments={},
        purpose="Read the current project.",
    )
    second = PlanToolStep(
        node_key="second",
        depends_on=("missing",),
        tool=tool_pin("read_account"),
        arguments={},
        purpose="Read one account.",
    )
    with pytest.raises(ValidationError, match="unknown dependencies"):
        AgentPlan(
            plan_id=UUID("00000000-0000-0000-0000-000000000613"),
            execution_id=EXECUTION_ID,
            role=AgentRole.HEAD_OF_ABM,
            goal_ref=artifact("goal.json"),
            steps=(first, second),
            proposed_at=NOW,
        )

    cycle_a = first.model_copy(update={"depends_on": ("second",)})
    cycle_b = second.model_copy(update={"depends_on": ("first",)})
    with pytest.raises(ValidationError, match="acyclic"):
        AgentPlan(
            plan_id=UUID("00000000-0000-0000-0000-000000000614"),
            execution_id=EXECUTION_ID,
            role=AgentRole.HEAD_OF_ABM,
            goal_ref=artifact("goal.json"),
            steps=(cycle_a, cycle_b),
            proposed_at=NOW,
        )


def test_validated_plan_requires_stable_unique_operation_ids_and_budget() -> None:
    operation = ValidatedOperation(
        node_key="read",
        operation_id=OperationId(UUID("00000000-0000-0000-0000-000000000621")),
        kind="tool",
        address="read_project@1",
        depends_on=(),
        parameter_artifact_ref=artifact("plan/read-parameters.json"),
        parameter_sha256=SHA_A,
        estimated_cost_millicents=0,
        authority_sha256=SHA_B,
    )
    plan = ValidatedPlan(
        plan_id=UUID("00000000-0000-0000-0000-000000000622"),
        execution_id=EXECUTION_ID,
        validated_plan_artifact_ref=artifact("validated-plan.json"),
        proposal_sha256=SHA_A,
        resource_manifest_sha256=SHA_B,
        operations=(operation,),
        max_parallelism=1,
        estimated_cost_millicents=0,
        budget_limit_millicents=100,
        validated_at=NOW,
    )
    assert plan.operations[0].operation_id == operation.operation_id
    with pytest.raises(ValidationError, match="estimate exceeds"):
        ValidatedPlan.model_validate(
            {
                **plan.model_dump(),
                "operations": (operation.model_copy(update={"estimated_cost_millicents": 101}),),
                "estimated_cost_millicents": 101,
            }
        )


def test_delegation_contract_is_fresh_scoped_and_reference_only() -> None:
    request = DelegationRequest(
        delegation_id=UUID("00000000-0000-0000-0000-000000000631"),
        parent_execution_id=EXECUTION_ID,
        parent_role=AgentRole.HEAD_OF_ABM,
        subagent_role=AgentRole.RESEARCH,
        task_artifact_ref=artifact("delegations/task.md"),
        granted_paths=("context/focus/account.json", "delegations/research"),
        domain_refs=(domain_ref("account-1"),),
        child_budget_envelope_ref=artifact("delegations/budget.json"),
        resource_manifest_ref=artifact("delegations/resources.json"),
        resource_manifest_sha256=SHA_B,
        depth=1,
    )
    assert request.granted_paths == ("context/focus/account.json", "delegations/research")

    with pytest.raises(ValidationError, match="at least one durable reference"):
        DelegationResult(
            delegation_id=request.delegation_id,
            parent_execution_id=EXECUTION_ID,
            child_execution_id=ExecutionId(UUID("00000000-0000-0000-0000-000000000632")),
            status="completed",
            finalization_ref=artifact("delegations/finalization.json"),
            spend_millicents=0,
            completed_at=NOW,
        )


def test_specialist_task_preserves_verbatim_refs_and_output_scope() -> None:
    value = SpecialistTaskEnvelope(
        role=AgentRole.REVIEWER,
        goal="Review the canonical exemplar.",
        instructions="Do not edit or paraphrase it.",
        verbatim_context=("The human requested a strict evidence review.",),
        domain_refs=(domain_ref("account-1"),),
        required_output_path="outputs/review-verdict.md",
    )

    assert value.verbatim_context == ("The human requested a strict evidence review.",)
    with pytest.raises(ValidationError, match="below outputs"):
        SpecialistTaskEnvelope(
            role=AgentRole.REVIEWER,
            goal=value.goal,
            instructions=value.instructions,
            required_output_path="work/review.md",
        )


def test_context_manifest_requires_exact_ordered_l1_through_l7() -> None:
    valid = context_manifest()
    assert tuple(layer.layer for layer in valid.layers) == tuple(ContextLayer)
    with pytest.raises(ValidationError, match="exactly L1-L7"):
        ContextBundleManifest.model_validate({**valid.model_dump(), "layers": valid.layers[:-1]})


def test_finalize_envelope_never_treats_bare_model_stop_as_success() -> None:
    common = {
        "finalization_id": UUID("00000000-0000-0000-0000-000000000641"),
        "execution_id": EXECUTION_ID,
        "finalized_at": NOW,
    }
    with pytest.raises(ValidationError, match="durable user-message"):
        AgentFinalizeEnvelope(status=FinalizeStatus.COMPLETED, **common)
    with pytest.raises(ValidationError, match="failure code"):
        AgentFinalizeEnvelope(status=FinalizeStatus.FAILED, **common)

    completed = AgentFinalizeEnvelope(
        status=FinalizeStatus.COMPLETED,
        user_message_artifact_ref=artifact("final/message.md"),
        output_refs=(artifact("outputs/report.md"),),
        **common,
    )
    assert completed.status is FinalizeStatus.COMPLETED


_FROZEN_CONTRACT_TYPES = (
    AgentProfile,
    SkillBundle,
    AgentConstitution,
    AgentTurnRequest,
    AgentPlan,
    ValidatedPlan,
    DelegationRequest,
    DelegationResult,
    SpecialistTaskEnvelope,
    ContextBundleManifest,
    AgentFinalizeEnvelope,
)


def _schema_digest(model: type[object]) -> str:
    schema = model.model_json_schema()  # type: ignore[attr-defined]
    payload = json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def test_frozen_contract_json_schema_digests() -> None:
    """Any schema change is a reviewed contract revision, not silent pre-migration drift."""

    actual = {model.__name__: _schema_digest(model) for model in _FROZEN_CONTRACT_TYPES}
    # Contract revision P3.1 (PD-part3 §3 delta 1, ratified 2026-08-14): AgentRole gains
    # 'design' — the composite design deepagent's platform-facing role. Every digest that
    # moved embeds the role enum; the DB CHECKs widened in the same commit (549de68ae3b9).
    assert actual == {
        "AgentProfile": "bdcad179c2b9b5d5f9dbf41434e0de74801c0ce85e028aec1d515ebf77ff7653",
        "SkillBundle": "ddbffd59d074ffd70880fd0398b7bc0a9aab2163e55aa8527c930f5866b24521",
        # S3 composes the frozen snake_case Client-KB/Stage-0 artifact names. Project-context
        # identifiers therefore accept both that vocabulary and the older kebab-case directive
        # names without widening folder-backed ``ResourceName`` contracts. The part-iii merge
        # unions that S3 shape with P3.1's 'design' role, so these three digests moved again in
        # the merge commit (the in-commit contract-delta ritual).
        "AgentConstitution": ("147c1806971d9c0b187c6e51ba1999cee0dae5a8e42d138e1b31eea12e31a323"),
        "AgentTurnRequest": ("f136b8fbb6fa070aa76fe021e829855d4e8df6f38b61b2c4119f95fe4b2889d2"),
        "AgentPlan": "4323376df8c263abd7d6ff607e370f1d4786646dfcc0ff39632ce74761ca8f61",
        "ValidatedPlan": ("4708b42a3a98619f52056ed93dad842852955bd82551a974b788969274de2026"),
        "DelegationRequest": ("7ef04260a02bd382b7fcd321e4c6b15674cba452e577703568d991c140276b2f"),
        "DelegationResult": ("956ec6033fa560ba7704031a0df4b5aa3aa98ebbb0702bc137018ab3adafb36c"),
        "SpecialistTaskEnvelope": (
            "57396348bc7f3d8f7616c38bb8ea3203cd939879cf4a56af4f6b0a46be45b113"
        ),
        "ContextBundleManifest": (
            "1d2f8ce14873a9413ac525d022a48de1fc72c9061bc28130ce0c12da3344a488"
        ),
        "AgentFinalizeEnvelope": (
            "ee5a8ac990a3329fce7f1d6acd5160cfdb6eb243bcdcc4dc4f647a9188030dae"
        ),
    }
