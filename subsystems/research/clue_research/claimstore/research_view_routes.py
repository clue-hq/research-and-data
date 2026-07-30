"""Registered field-to-section projection metadata for C7 research views.

Routes are presentation-neutral policy data: they state which semantic research section owns a
registered field. They do not store a claim value, prose, or rendered dossier body.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import EntityType, ResearchSectionKind

ResearchRoutePurpose = Literal["display", "personalization_candidate"]
ResearchRouteContext = Literal["subject_current", "project_run_pinned"]
ResearchRouteProductMode = Literal["neutral_or_exact", "exact_required", "neutral_only"]

_ACCOUNT_SECTIONS = frozenset(
    {
        ResearchSectionKind.SUMMARY,
        ResearchSectionKind.ABOUT,
        ResearchSectionKind.INSIGHTS,
        ResearchSectionKind.EVIDENCE,
        ResearchSectionKind.VALUE_NARRATIVE,
    }
)
_CONTACT_SECTIONS = frozenset(
    {
        ResearchSectionKind.SUMMARY,
        ResearchSectionKind.PROFESSIONAL_SIGNALS,
        ResearchSectionKind.EVIDENCE,
        ResearchSectionKind.QUOTES,
        ResearchSectionKind.BACKGROUND,
        ResearchSectionKind.CAREER,
        ResearchSectionKind.EDUCATION,
        ResearchSectionKind.PUBLICATIONS,
        ResearchSectionKind.AWARDS,
        ResearchSectionKind.PERSONALIZATION,
    }
)


class ResearchViewRouteRedefinitionError(ValueError):
    """An active field route already exists with different immutable projection policy."""


class ResearchViewFieldRoute(BaseModel):
    """One immutable/versioned semantic placement for a registered field."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: str = Field(min_length=1)
    entity_type: EntityType
    section_kind: ResearchSectionKind
    purpose: ResearchRoutePurpose = "display"
    context_scope: ResearchRouteContext = "subject_current"
    product_mode: ResearchRouteProductMode = "neutral_or_exact"
    ordinal: int = Field(default=0, ge=0)
    route_version: int = Field(default=1, ge=1)
    view_schema_version: Literal["1.0"] = "1.0"

    @model_validator(mode="after")
    def _legal_section(self) -> ResearchViewFieldRoute:
        allowed = (
            _ACCOUNT_SECTIONS
            if self.entity_type is EntityType.ACCOUNT
            else _CONTACT_SECTIONS
        )
        if self.section_kind not in allowed:
            raise ValueError(
                f"{self.section_kind.value} is not a legal {self.entity_type.value} claim section"
            )
        personalization = self.purpose == "personalization_candidate"
        if personalization != (self.section_kind is ResearchSectionKind.PERSONALIZATION):
            raise ValueError(
                "personalization_candidate purpose and personalization section must agree"
            )
        if personalization and not self.field_key.startswith("contact.personalization."):
            raise ValueError(
                "personalization routes require an explicit contact.personalization.* "
                "derived field"
            )
        return self


async def register_research_view_route(
    conn: AsyncConnection, route: ResearchViewFieldRoute
) -> None:
    """Register one active route idempotently; conflicting redefinition is loud."""

    row = (
        await conn.execute(
            text(
                """
                SELECT section_kind, purpose, context_scope, product_mode, ordinal, route_version
                FROM research_view_field_route
                WHERE field_key = :field_key
                  AND entity_type = CAST(:entity_type AS entity_type)
                  AND view_schema_version = :view_schema_version
                  AND purpose = :purpose
                  AND active
                """
            ),
            {
                "field_key": route.field_key,
                "entity_type": route.entity_type.value,
                "view_schema_version": route.view_schema_version,
                "purpose": route.purpose,
            },
        )
    ).first()
    incoming = (
        route.section_kind.value,
        route.purpose,
        route.context_scope,
        route.product_mode,
        route.ordinal,
        route.route_version,
    )
    if row is not None:
        if tuple(row) == incoming:
            return
        raise ResearchViewRouteRedefinitionError(
            f"active research-view route for {route.field_key!r} differs; "
            "deactivate/version it instead of redefining it"
        )
    await conn.execute(
        text(
            """
            INSERT INTO research_view_field_route (
                field_key, entity_type, view_schema_version, section_kind, purpose,
                context_scope, product_mode, ordinal, route_version
            ) VALUES (
                :field_key, CAST(:entity_type AS entity_type), :view_schema_version,
                :section_kind, :purpose, :context_scope, :product_mode, :ordinal, :route_version
            )
            """
        ),
        {
            "field_key": route.field_key,
            "entity_type": route.entity_type.value,
            "view_schema_version": route.view_schema_version,
            "section_kind": route.section_kind.value,
            "purpose": route.purpose,
            "context_scope": route.context_scope,
            "product_mode": route.product_mode,
            "ordinal": route.ordinal,
            "route_version": route.route_version,
        },
    )


async def list_research_view_routes(
    conn: AsyncConnection,
    *,
    entity_type: EntityType,
    view_schema_version: str = "1.0",
) -> tuple[ResearchViewFieldRoute, ...]:
    """Return active routes for one subject type/schema in deterministic display order."""

    rows = (
        await conn.execute(
            text(
                """
                SELECT field_key, entity_type, section_kind, purpose, context_scope,
                       product_mode, ordinal, route_version, view_schema_version
                FROM research_view_field_route
                WHERE entity_type = CAST(:entity_type AS entity_type)
                  AND view_schema_version = :view_schema_version
                  AND active
                ORDER BY ordinal, field_key, purpose
                """
            ),
            {
                "entity_type": entity_type.value,
                "view_schema_version": view_schema_version,
            },
        )
    ).mappings()
    return tuple(ResearchViewFieldRoute.model_validate(dict(row)) for row in rows)


__all__ = [
    "ResearchRouteContext",
    "ResearchRouteProductMode",
    "ResearchRoutePurpose",
    "ResearchViewFieldRoute",
    "ResearchViewRouteRedefinitionError",
    "list_research_view_routes",
    "register_research_view_route",
]
