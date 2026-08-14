"""S4-C pure acceptance for trusted ``@2`` Client-KB tool authority.

These checks deliberately stop before S4-D: the implementations exist and can be composed by an
explicit caller, but the central production registry still exposes only the immutable ``@1``
compatibility versions.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ValidationError

from clue_agents import DomainObjectRef, ProjectContextArtifact
from clue_api.agent_execution_wiring import _trusted_tool_arguments
from clue_api.agent_runtime_wiring import _with_trusted_runtime
from clue_api.client_knowledge_contracts import (
    INSPECT_CLIENT_CLAIM_ADDRESS,
    LIST_CLIENT_KNOWLEDGE_ADDRESS,
    MODEL_VISIBLE_INSPECT_FIELDS,
    MODEL_VISIBLE_LIST_FIELDS,
    InspectClientClaimV2Input,
    ListClientKnowledgeV2Input,
)
from clue_api.client_knowledge_tools import (
    ListClientKnowledgeInput,
    build_client_knowledge_v2_tools,
)
from clue_api.toolbelt_wiring import build_toolbelt
from clue_gateway.agent_model import provider_compatible_tool_schema
from tests.agents.conftest import artifact, constitution

CLIENT_ID = UUID("11111111-1111-4111-8111-111111111111")
CLAIM_ID = UUID("22222222-2222-4222-8222-222222222222")


def _production_constitution(*, version: int = 7):
    return constitution(
        client_entity_id=str(CLIENT_ID),
        project_context_artifacts=(
            ProjectContextArtifact(
                name="client_knowledge",
                artifact_ref=artifact("client-knowledge.json"),
                domain_ref=DomainObjectRef(
                    workspace_id="ws-1",
                    object_type="client_knowledge",
                    object_id=str(CLIENT_ID),
                    version=version,
                ),
            ),
            ProjectContextArtifact(
                name="stage0_project_state",
                artifact_ref=artifact("stage0-project-state.json"),
                domain_ref=DomainObjectRef(
                    workspace_id="ws-1",
                    object_type="stage0_project_state",
                    object_id="project-1",
                    version=None,
                ),
            ),
        ),
    )


def _model_parameters(model: type[ListClientKnowledgeV2Input | InspectClientClaimV2Input]):
    args_schema = _with_trusted_runtime(model, name=f"{model.__name__}S4CRuntime")

    async def probe(**_kwargs: object) -> str:  # pragma: no cover - schema only
        raise AssertionError("schema probe must not execute")

    tool = StructuredTool.from_function(
        coroutine=probe,
        name="s4c_schema_probe",
        description="S4-C schema probe.",
        args_schema=args_schema,
    )
    schema = provider_compatible_tool_schema(convert_to_openai_tool(tool))
    return args_schema, schema["function"]["parameters"]


def test_v2_builds_exact_frozen_descriptors_but_is_not_production_registered() -> None:
    implementations = build_client_knowledge_v2_tools()
    assert tuple(item.descriptor.address for item in implementations) == (
        LIST_CLIENT_KNOWLEDGE_ADDRESS,
        INSPECT_CLIENT_CLAIM_ADDRESS,
    )
    assert all(item.descriptor.effect_class.value == "read" for item in implementations)
    assert all(item.descriptor.replay.policy.value == "effect_free" for item in implementations)
    assert all(item.descriptor.replay.external_boundary.value == "none" for item in implementations)

    production = build_toolbelt(storage=None)
    for name in ("list_client_knowledge", "inspect_client_claim"):
        assert production.has(name, "1") is True
        assert production.has(name, "2") is False


@pytest.mark.parametrize(
    ("model", "visible"),
    (
        (ListClientKnowledgeV2Input, set(MODEL_VISIBLE_LIST_FIELDS)),
        (InspectClientClaimV2Input, set(MODEL_VISIBLE_INSPECT_FIELDS)),
    ),
)
def test_model_schema_contains_only_the_frozen_allowlist(
    model: type[ListClientKnowledgeV2Input | InspectClientClaimV2Input],
    visible: set[str],
) -> None:
    args_schema, parameters = _model_parameters(model)
    assert set(parameters["properties"]) == visible
    assert set(args_schema.model_fields) == {*visible, "runtime"}
    assert {"workspace_id", "client_entity_id", "client_kb_version"}.isdisjoint(
        parameters["properties"]
    )

    valid: dict[str, object] = {"runtime": None}
    if model is InspectClientClaimV2Input:
        valid["claim_id"] = str(CLAIM_ID)
    for smuggled, value in (
        ("workspace_id", "ws-attacker"),
        ("client_entity_id", str(UUID("33333333-3333-4333-8333-333333333333"))),
        ("client_kb_version", 999),
        ("project_id", "project-attacker"),
        ("product_id", "product-attacker"),
    ):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            args_schema.model_validate({**valid, smuggled: value})


def test_execution_injects_client_and_exact_version_from_the_paired_artifact() -> None:
    trusted = _production_constitution(version=7)
    merged = _trusted_tool_arguments(
        arguments={"topic": "product", "limit": 3},
        input_model=ListClientKnowledgeV2Input,
        constitution=trusted,
    )
    assert merged == {
        "topic": "product",
        "limit": 3,
        "client_entity_id": str(CLIENT_ID),
        "client_kb_version": 7,
    }
    parsed = ListClientKnowledgeV2Input.model_validate(merged)
    assert parsed.client_entity_id == CLIENT_ID
    assert parsed.client_kb_version == 7

    for forged in (
        {"client_entity_id": str(CLIENT_ID)},
        {"client_kb_version": 999},
        {"workspace_id": "ws-attacker"},
    ):
        with pytest.raises(ValueError, match="trusted"):
            _trusted_tool_arguments(
                arguments=forged,
                input_model=ListClientKnowledgeV2Input,
                constitution=trusted,
            )


def test_v2_has_no_trial_focus_ref_fallback_while_frozen_v1_keeps_compatibility() -> None:
    trial = constitution(
        client_entity_id=str(CLIENT_ID),
        focus_refs=(
            DomainObjectRef(
                workspace_id="ws-1",
                object_type="client_account",
                object_id=str(CLIENT_ID),
                version=13,
            ),
        ),
    )
    v2_merged = _trusted_tool_arguments(
        arguments={"topic": "product"},
        input_model=ListClientKnowledgeV2Input,
        constitution=trial,
    )
    assert v2_merged == {"topic": "product", "client_entity_id": str(CLIENT_ID)}
    with pytest.raises(ValidationError, match="client_kb_version"):
        ListClientKnowledgeV2Input.model_validate(v2_merged)

    v1_merged = _trusted_tool_arguments(
        arguments={"topic": "product"},
        input_model=ListClientKnowledgeInput,
        constitution=trial,
    )
    assert v1_merged["client_kb_version"] == 13


def test_constitution_refuses_an_unpaired_or_mismatched_client_knowledge_artifact() -> None:
    valid = _production_constitution()
    client_artifact, stage0_artifact = valid.project_context_artifacts
    with pytest.raises(ValidationError, match="constituted together"):
        constitution(
            client_entity_id=str(CLIENT_ID),
            project_context_artifacts=(client_artifact,),
        )
    with pytest.raises(ValidationError, match="must match the constitution client"):
        constitution(
            client_entity_id=str(CLIENT_ID),
            project_context_artifacts=(
                client_artifact.model_copy(
                    update={
                        "domain_ref": client_artifact.domain_ref.model_copy(
                            update={"object_id": str(UUID(int=9))}
                        )
                    }
                ),
                stage0_artifact,
            ),
        )
