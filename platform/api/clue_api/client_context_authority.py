"""Trusted production Client-KB version binding for governed tool inputs.

The workspace/client/project identities already come from :class:`AgentConstitution`. The exact
Client-KB version is different: S3 pins it on the immutable ``client_knowledge`` L3 artifact. S4
tools declare a ``client_kb_version`` input so recipes and direct invocations remain fully typed,
but mark that field here so the model-facing schema removes it and the execution seam restores it
only from that artifact pin.

Keeping this marker per input model avoids changing older Stage-0 trial tools whose
``client_kb_version`` arguments predate production L3 composition. Only a tool that explicitly
opts into this production binding receives the value.
"""

from __future__ import annotations

from pydantic import BaseModel

from clue_agents import AgentConstitution

__all__ = [
    "PRODUCTION_CLIENT_KB_AUTHORITY_POLICY",
    "TRUSTED_CLIENT_KB_VERSION_FIELD",
    "client_kb_version_for_input_model",
    "client_kb_version_from_constitution",
    "production_client_kb_version_from_constitution",
    "trusted_client_kb_version_fields",
]

TRUSTED_CLIENT_KB_VERSION_FIELD = "clue_trusted_client_kb_version_field"
PRODUCTION_CLIENT_KB_AUTHORITY_POLICY = "paired_client_knowledge_artifact"


def trusted_client_kb_version_fields(model: type[BaseModel]) -> tuple[str, ...]:
    """Return fields explicitly served from the production Client-KB artifact pin."""

    return tuple(
        name
        for name, field in model.model_fields.items()
        if isinstance(field.json_schema_extra, dict)
        and field.json_schema_extra.get(TRUSTED_CLIENT_KB_VERSION_FIELD) is True
    )


def production_client_kb_version_from_constitution(
    constitution: AgentConstitution,
) -> int | None:
    """Resolve only the validated production ``client_knowledge`` artifact pin.

    :class:`AgentConstitution` has already proved that the artifact is paired with the active
    project's Stage-0 artifact and that its workspace, client id, and positive version match the
    constitution. S4-C's final ``@2`` tools deliberately have no trial/focus-ref fallback: if the
    paired production artifact is absent, no Client-KB version is injected and validation fails
    closed before the tool can run.
    """

    artifact = next(
        (
            item
            for item in constitution.project_context_artifacts
            if item.name == "client_knowledge"
        ),
        None,
    )
    if artifact is None:
        return None
    # AgentConstitution already proves type, client, workspace, and a positive exact version.
    assert artifact.domain_ref.object_type == "client_knowledge"
    assert artifact.domain_ref.object_id == constitution.client_entity_id
    assert artifact.domain_ref.version is not None
    return artifact.domain_ref.version


def client_kb_version_from_constitution(constitution: AgentConstitution) -> int | None:
    """Resolve the production pin, with the frozen ``@1`` trial compatibility fallback."""

    production_version = production_client_kb_version_from_constitution(constitution)
    if production_version is not None:
        return production_version

    # The development Stage-0 trial predates the split S3 artifacts but still pins the same
    # client/version pair as a trusted focus ref. Keeping this compatibility source lets the
    # immutable ``@1`` surface survive without letting the model author the version.
    focus = next(
        (
            item
            for item in constitution.focus_refs
            if item.object_type == "client_account"
            and item.object_id == constitution.client_entity_id
            and item.version is not None
        ),
        None,
    )
    return focus.version if focus is not None else None


def client_kb_version_for_input_model(
    constitution: AgentConstitution,
    model: type[BaseModel],
) -> int | None:
    """Apply the authority policy opted into by one immutable tool-input contract."""

    policy = getattr(model, "client_kb_authority_policy", None)
    if policy == PRODUCTION_CLIENT_KB_AUTHORITY_POLICY:
        return production_client_kb_version_from_constitution(constitution)
    return client_kb_version_from_constitution(constitution)
