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
    "TRUSTED_CLIENT_KB_VERSION_FIELD",
    "client_kb_version_from_constitution",
    "trusted_client_kb_version_fields",
]

TRUSTED_CLIENT_KB_VERSION_FIELD = "clue_trusted_client_kb_version_field"


def trusted_client_kb_version_fields(model: type[BaseModel]) -> tuple[str, ...]:
    """Return fields explicitly served from the production Client-KB artifact pin."""

    return tuple(
        name
        for name, field in model.model_fields.items()
        if isinstance(field.json_schema_extra, dict)
        and field.json_schema_extra.get(TRUSTED_CLIENT_KB_VERSION_FIELD) is True
    )


def client_kb_version_from_constitution(constitution: AgentConstitution) -> int | None:
    """Resolve the exact S3 Client-KB domain pin, or ``None`` when this is not that surface."""

    artifact = next(
        (
            item
            for item in constitution.project_context_artifacts
            if item.name == "client_knowledge"
        ),
        None,
    )
    if artifact is None:
        # The development Stage-0 trial predates the split S3 artifacts but still pins the same
        # client/version pair as a trusted focus ref. Keeping this compatibility source lets the
        # shared Stage-0 skill survive that narrowed surface without letting the model author the
        # version. Production always takes the artifact branch above.
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
    # AgentConstitution already proves type, client, workspace, and a positive exact version.
    assert artifact.domain_ref.object_type == "client_knowledge"
    assert artifact.domain_ref.version is not None
    return artifact.domain_ref.version
