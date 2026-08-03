from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from clue_agents import (
    AgentTurnRequest,
    ProjectContextArtifact,
    ProjectLayerSource,
)
from tests.agents.conftest import NOW, artifact, constitution, domain_ref
from tests.agents.test_context import TURN_ID
from tests.agents.test_contracts import profile


class _Artifacts:
    async def read(self, ref: object) -> bytes:
        key = ref.artifact_key.rsplit("/", 1)[-1]  # type: ignore[attr-defined]
        return {
            "project-card.json": b'{"project":"p-1"}',
            "budget.json": b'{"limit":100}',
            "research-directive.json": b'{"directive_ref":"research-directive:1:v1"}',
        }[key]


def test_project_layer_materializes_exact_directive_path_and_typed_ref() -> None:
    directive_artifact = artifact("research-directive.json")
    directive_ref = domain_ref("directive-1").model_copy(
        update={"object_type": "research_directive"}
    )
    base = constitution()
    request = AgentTurnRequest(
        turn_id=TURN_ID,
        thread_id="fresh-account-research-thread",
        constitution=base.model_copy(
            update={
                "project_context_artifacts": (
                    ProjectContextArtifact(
                        name="research-directive",
                        artifact_ref=directive_artifact,
                        domain_ref=directive_ref,
                    ),
                )
            }
        ),
        user_message_artifact_ref=artifact("user-message.txt"),
        requested_at=NOW,
    )

    candidates = asyncio.run(
        ProjectLayerSource(artifacts=_Artifacts()).load(
            request=request,
            profile=profile(),
            history=(),
        )
    )

    directive = next(item for item in candidates if item.ref == directive_artifact)
    assert directive.materialized_path == "context/project/research-directive.json"
    assert directive.body == '{"directive_ref":"research-directive:1:v1"}'
    assert directive.required is True
    assert request.constitution.project_context_artifacts[0].domain_ref == directive_ref


def test_project_context_artifact_cannot_shadow_base_project_inputs() -> None:
    base = constitution()
    with pytest.raises(ValidationError, match="cannot shadow"):
        base.model_copy(
            update={
                "project_context_artifacts": (
                    ProjectContextArtifact(
                        name="budget",
                        artifact_ref=artifact("shadow-budget.json"),
                        domain_ref=domain_ref("directive-1"),
                    ),
                )
            }
        ).model_validate(
            {
                **base.model_dump(mode="python"),
                "project_context_artifacts": (
                    ProjectContextArtifact(
                        name="budget",
                        artifact_ref=artifact("shadow-budget.json"),
                        domain_ref=domain_ref("directive-1"),
                    ),
                ),
            }
        )
