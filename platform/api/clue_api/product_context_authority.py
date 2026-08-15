"""Trusted selected-product and Product-KB version injection for S5 tools."""

from __future__ import annotations

from pydantic import BaseModel

from clue_agents import AgentConstitution

TRUSTED_PRODUCT_ID_FIELD = "clue_trusted_product_id_field"
TRUSTED_PRODUCT_KB_VERSION_FIELD = "clue_trusted_product_kb_version_field"
PRODUCTION_PRODUCT_KB_AUTHORITY_POLICY = "paired_product_knowledge_artifact"


def trusted_product_scope_fields(model: type[BaseModel]) -> tuple[str, ...]:
    return tuple(
        name
        for name, field in model.model_fields.items()
        if isinstance(field.json_schema_extra, dict)
        and (
            field.json_schema_extra.get(TRUSTED_PRODUCT_ID_FIELD) is True
            or field.json_schema_extra.get(TRUSTED_PRODUCT_KB_VERSION_FIELD) is True
        )
    )


def product_scope_from_constitution(
    constitution: AgentConstitution,
) -> tuple[str, int] | None:
    """Resolve the exact selected-product artifact pair; no focus/model fallback exists."""

    artifact = next(
        (
            item
            for item in constitution.project_context_artifacts
            if item.name == "product_knowledge"
        ),
        None,
    )
    if artifact is None or constitution.product_id is None:
        return None
    if (
        artifact.domain_ref.object_type != "product_knowledge"
        or artifact.domain_ref.object_id != constitution.product_id
        or artifact.domain_ref.workspace_id != constitution.workspace_id
        or artifact.domain_ref.version is None
        or artifact.domain_ref.version < 1
    ):
        return None
    return constitution.product_id, artifact.domain_ref.version


def product_scope_for_input_model(
    constitution: AgentConstitution,
    model: type[BaseModel],
) -> tuple[str, int] | None:
    if (
        getattr(model, "product_kb_authority_policy", None)
        != PRODUCTION_PRODUCT_KB_AUTHORITY_POLICY
    ):
        return None
    return product_scope_from_constitution(constitution)


__all__ = [
    "PRODUCTION_PRODUCT_KB_AUTHORITY_POLICY",
    "TRUSTED_PRODUCT_ID_FIELD",
    "TRUSTED_PRODUCT_KB_VERSION_FIELD",
    "product_scope_for_input_model",
    "product_scope_from_constitution",
    "trusted_product_scope_fields",
]
